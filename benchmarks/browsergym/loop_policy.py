"""An inline agent loop: model -> ops -> results -> model, with no agent CLI.

The benchmark's other policy spawns a whole agent CLI per episode, which is
faithful to how the toolkit is used in production and useless for an unattended
sweep: it needs a logged-in CLI on the machine, it costs 30-60s of process
startup per episode, and it re-reads `abt --help` every single time -- about 5k
tokens of the 43k an episode spends. Across 375 episodes that is 1.9M tokens of
re-reading the same document.

This is the other end of the trade. One API key, one loop, no subprocess. The
ops reference is sent once per episode as a cached system prefix, so after the
first episode it costs a tenth of that.

**One tool, taking a list.** Not one tool per op: the tool signature IS
`POST /commands`, so sending three ops in a call is the ordinary shape rather
than a thing the model has to remember to prefer. Watching agents drive the CLI,
the single most common waste was a fixed pair -- type a command, press Enter --
paid as two round trips. A tool that only accepts a list cannot express that
mistake.

Two providers, kept as separate functions rather than one with branches:
they differ in tool schema shape, in how a tool result is handed back, and in
what usage is called, and a single function pretending otherwise is where
provider bugs hide.

    --provider anthropic   ANTHROPIC_API_KEY or `ant auth login`; pip install anthropic
    --provider openrouter  OPENROUTER_API_KEY; pip install openai

OpenRouter speaks the OpenAI wire format, so that path uses the OpenAI SDK
against OpenRouter's base URL -- it is not a shim in front of Claude, it is a
different provider reached the way that provider expects.
"""

from __future__ import annotations

import json
import re
import os
import sys
import urllib.request

# Haiku 4.5 by decision -- one model across a sweep, chosen for cost. Override
# with --model. Note it is a pre-4.6 model: no `effort`, and thinking would
# need the old budget_tokens shape rather than adaptive.
DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM = """You are driving a real web browser to complete one task.

You have a single tool. It takes a LIST of operations and runs them in order
against the page, returning what each one did. Send every operation you already
know you need in one call -- typing into a field and pressing Enter is one call,
not two; filling a form of four fields and submitting is one call, not five. The
list stops at the first failure and tells you which operation failed, so a long
list is never a blind leap.

Read what you are given. Every operation that changes the page returns a
`dom_diff`: `text.added` is what appeared on screen, and `actionable.added`
lists the controls that appeared with a `ref` for each. Act on those refs
directly. Running a search to find something you were just handed is the most
expensive habit available to you.

Finding things:
- `get_text` tells you what a page says. It is how you learn a page you have
  not seen. Reach for it before guessing selectors.
- `find` is for when you already know what you are looking for. It returns a
  `ref` for each match.
- A `count` of 0 means the element is not there -- do not retry with a wider
  selector. An invalid selector is reported as an error instead, so the two
  are never confused.

Traps worth knowing:
- If typing into a field makes suggestions appear in the diff, the field is a
  chooser: you must click one. Many such fields silently reject anything you
  merely typed.
- A readonly field cannot be typed into. Click it and use the widget that opens.
- Refs die on navigation. Take a fresh one from your last diff.

Every failure carries a `hint` saying what to do about it. Read it before
retrying.

When the task is done, stop and say DONE. Do not navigate away or reload -- that
would reset the task.
"""

# A turn with no tool calls is how an agent says "finished", and that is how it
# is treated -- except when it has not actually answered. Episodes stop mid
# thought: "This strongly suggests..." with no ops, no ANSWER line, and turns
# still on the clock. The loop took that as done, and the answer parser then
# submitted the trailing reasoning as the answer, so a stopped-early episode
# was recorded as a rambling wrong one.
#
# 17 of 187 shopping episodes ended this way; 14 of them scored zero.
#
# So: ask once, and only when asking is free -- no answer given, turns
# remaining, and not already asked. If the agent still declines to answer, it
# is finished and the episode ends as before.
_ANSWER_MARK = re.compile(r"^\s*ANSWER:", re.MULTILINE)

_NUDGE = (
    "You stopped without giving an answer, and you still have turns left. If "
    "you already have the answer, give it now, ending with the ANSWER: line "
    "in the required form. If you do not have it yet, carry on working and "
    "answer once you do. If you have established that it cannot be "
    "determined, answer N/A."
)


def _playbook_section() -> str:
    """The shipped playbook discipline, read from the guideline it ships in.

    Deliberately not restated here. The benchmark should measure what the
    toolkit actually tells its agents, so if that guidance changes, this
    changes with it and the run stays honest.

    The two CLI lines are swapped for the op form, because this agent drives
    ops rather than a shell. Nothing else is altered.
    """
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "guidelines" / "toolkit-workflow.md"
    try:
        raw = doc.read_text(encoding="utf-8")
    except OSError:
        return ""
    # The whole document, not a section of it. An earlier version fed only
    # the playbook part to save tokens; that dropped fifteen of sixteen
    # sections, including every operational rule the agent actually needs.
    # It is ~6.7k tokens, sent once as a cached prefix, so it is re-read for
    # roughly nothing after the first turn.
    section = (
        "The toolkit workflow follows. It is the same guidance every agent "
        "driving this toolkit is given. Its examples are written as `abt` "
        "shell commands; you are not in a shell -- send the same operations "
        "through your run_ops tool, using the op names and fields shown.\n\n"
    ) + raw
    for old, new in (
        ("abt guidelines search <domain>       # nothing back means no playbook exists",
         '{"op": "guidelines_search", "query": "<domain>"}    # nothing back means none'),
        ("abt guidelines show <name>           # read it before your first op",
         '{"op": "guidelines_read", "name": "<name>"}         # read before your first op'),
        ("```bash", "```json"),
    ):
        section = section.replace(old, new)
    return section


_PLAYBOOK = _playbook_section()
if _PLAYBOOK:
    SYSTEM = SYSTEM + "\n\n" + _PLAYBOOK + (
        "DO EXACTLY WHAT WAS ASKED AND NOTHING MORE. Do not explore past the "
        "question, gather detail nobody wanted, tidy anything you were not "
        "asked about, or keep verifying an answer you already have.\n"
    )


TOOL = {
    "name": "run_ops",
    "description": (
        "Run one or more browser operations, in order, against the page. "
        "Returns what each did, including a dom_diff of what changed. Prefer "
        "sending every operation you already know you need in one call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ops": {
                "type": "array",
                "description": (
                    'Operations, each an object like {"op":"click","css":"#x"}. '
                    "The exact parameters for every op are in the system prompt."
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "continue_on_error": {
                "type": "boolean",
                "description": "Keep going past a failed operation. Default false.",
            },
        },
        "required": ["ops"],
        "additionalProperties": False,
    },
}


def _post(server: str, path: str, payload) -> dict:
    request = urllib.request.Request(
        server.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def ops_reference(server: str) -> str:
    """The op vocabulary AND its parameters, from the server that will run it.

    Fetched rather than written down, so it cannot drift from the server the
    episode is actually talking to. This used to return bare names while the
    prompt introduced it as "with their exact parameters" -- so the model was
    told the answer was there when it was not, and invented `js` for `script`
    and `selector` for `css`. Five such failures in the first five episodes of
    a sweep.
    """
    with urllib.request.urlopen(server.rstrip("/") + "/ops", timeout=30) as response:
        return json.dumps(json.load(response), separators=(",", ":"))



PAGE = """<!doctype html><meta charset="utf-8"><title>abt loop</title>
<style>
 :root{color-scheme:dark light}
 body{background:#0d1117;color:#c9d1d9;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;margin:0;padding:14px 18px}
 h1{font-size:13px;font-weight:600;color:#8b949e;margin:0 0 10px;letter-spacing:.08em;text-transform:uppercase}
 #log{white-space:pre-wrap;word-break:break-word}
 .turn{color:#58a6ff;font-weight:600;margin-top:10px}
 .think{color:#8b949e}
 .says{color:#d2a8ff}
 .ops{color:#7ee787}
 .back{color:#79c0ff}
 .fail{color:#ff7b72;font-weight:600}
 .done{color:#f0b72f;font-weight:600;margin-top:10px}
 #status{position:fixed;top:10px;right:16px;font-size:11px;color:#6e7681}
</style>
<h1>abt &mdash; agent loop</h1><div id=status>connecting</div><div id=log></div>
<script>
let seen = 0;
const log = document.getElementById('log'), status = document.getElementById('status');
function cls(line){
  if (line.startsWith('--- turn')) return 'turn';
  if (line.includes('[think]')) return 'think';
  if (line.includes('[says')) return 'says';
  if (line.includes('[ops')) return 'ops';
  if (line.includes('FAILED')) return 'fail';
  if (line.includes('[back')) return 'back';
  if (line.startsWith('=== done')) return 'done';
  return '';
}
async function poll(){
  try{
    const r = await fetch('/since?n=' + seen);
    const d = await r.json();
    seen = d.total;
    for (const line of d.lines){
      const el = document.createElement('div');
      el.className = cls(line);
      el.textContent = line;
      log.appendChild(el);
    }
    if (d.lines.length) window.scrollTo(0, document.body.scrollHeight);
    status.textContent = d.running ? 'live \\u00b7 ' + d.total + ' lines'
                                   : 'finished \\u00b7 ' + d.total + ' lines';
  } catch(e){ status.textContent = 'disconnected'; }
  setTimeout(poll, 600);
}
poll();
</script>
"""


class LogServer:
    """Serves the trace over HTTP so a run can be watched in a browser.

    Polling rather than SSE: an agent loop can sit silent for a minute while
    the model thinks, and a silent SSE stream is indistinguishable from a
    dropped one to every proxy in between. A poll that returns nothing is
    unambiguous, and the client shows whether the run is still going.
    """

    def __init__(self, trace, port: int) -> None:
        import http.server
        import threading

        self.trace = trace
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # its own access log would drown the trace

            def _send(self, body: bytes, kind: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/since"):
                    from urllib.parse import parse_qs, urlparse

                    seen = int(
                        (parse_qs(urlparse(self.path).query).get("n") or ["0"])[0]
                    )
                    lines = outer.trace.lines
                    payload = {
                        "lines": lines[seen:],
                        "total": len(lines),
                        "running": outer.trace.running,
                    }
                    self._send(json.dumps(payload).encode(), "application/json")
                elif self.path == "/raw":
                    self._send(
                        "\n".join(outer.trace.lines).encode(), "text/plain; charset=utf-8"
                    )
                else:
                    self._send(PAGE.encode(), "text/html; charset=utf-8")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


class Trace:
    """Prints what the loop is doing, turn by turn.

    Without this the loop is a black box that emits one summary at the end,
    which is unwatchable on a task taking minutes: there is no way to tell
    "thinking hard" from "stuck retrying" from "hung". Everything goes to
    stderr, so piping the JSON result stays clean.
    """

    RULE = "-" * 52

    def __init__(self, enabled: bool = True, port: int | None = None,
                 path: str | None = None) -> None:
        self.enabled = enabled
        self.lines: list[str] = []
        self.running = True
        # Line-buffered on purpose: a task that hangs or is killed still
        # leaves on disk everything it had said up to that point.
        self.file = None
        if path:
            try:
                parent = os.path.dirname(path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                self.file = open(path, "a", encoding="utf-8", buffering=1)
            except Exception:
                self.file = None
        self.server = LogServer(self, port) if port else None
        if port:
            print(f"[trace] watch it at http://127.0.0.1:{port}",
                  file=sys.stderr, flush=True)

    def say(self, text: str = "") -> None:
        self.lines.append(text)
        if self.enabled:
            print(text, file=sys.stderr, flush=True)
        if self.file is not None:
            self.file.write(text + "\n")

    def __getattribute__(self, name):
        """Never let watching break the thing being watched.

        A tracer bug took down a live episode: `_gained` called .get() on a
        result that happened to be a bare string, and an exception from code
        whose only job is to print ended a run that was going fine. Reporting
        is not worth a single lost episode, so every public method here
        swallows its own failures and says so instead.
        """
        attribute = object.__getattribute__(self, name)
        if name.startswith("_") or not callable(attribute):
            return attribute

        def guarded(*args, **kwargs):
            try:
                return attribute(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - deliberate
                try:
                    print(f"  [trace failed: {type(exc).__name__}: {exc}]",
                          file=sys.stderr, flush=True)
                except Exception:
                    pass

        return guarded

    @staticmethod
    def _flat(body: str, limit: int) -> str:
        one = " ".join(body.split())
        return one[:limit] + ("..." if len(one) > limit else "")

    def turn(self, n: int, thinking: str | None, text: str | None) -> None:
        self.say("")
        self.say(f"--- turn {n} {self.RULE}")
        if thinking and thinking.strip():
            self.say(f"  [think] {self._flat(thinking, 400)}")
        if text and text.strip():
            self.say(f"  [says ] {self._flat(text, 400)}")

    def ops(self, ops: list) -> None:
        self.say(f"  [ops  ] sending {len(ops)}:")
        for op in ops[:12]:
            detail = {
                k: (str(v)[:40] + "..." if len(str(v)) > 40 else v)
                for k, v in op.items()
                if k != "op"
            }
            self.say(f"          {str(op.get('op')).ljust(12)} {detail}")
        if len(ops) > 12:
            self.say(f"          ... and {len(ops) - 12} more")

    def result(self, count: int, failures: int, gained: list | None) -> None:
        mark = "ok" if not failures else f"{failures} FAILED"
        self.say(f"  [back ] {count} ops, {mark}")
        if gained:
            joined = " | ".join(str(g) for g in gained[:6])
            self.say(f"          page gained: {joined[:200]}")

    def done(self, turns: int, ops: int, usage: dict) -> None:
        self.say("")
        self.say(
            f"=== done: {turns} turns, {ops} ops, "
            f"{usage['input'] + usage['output']:,} tokens "
            f"({usage['cache_read']:,} cached) ==="
        )


def _gained(payload: str) -> list:
    """The text the page gained, pulled out of a batch reply for the trace."""
    try:
        answer = json.loads(payload)
    except ValueError:
        return []
    results = answer.get("results") or ([answer] if isinstance(answer, dict) else [])
    gained: list = []
    for item in results:
        if not isinstance(item, dict):
            continue
        # `result` is not always an object: get_text answers with a bare
        # string, and calling .get() on that took down a whole episode from
        # inside the *tracer* -- code whose only job is to watch.
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        diff = result.get("dom_diff")
        if not isinstance(diff, dict):
            continue
        text = diff.get("text")
        if isinstance(text, dict):
            gained += text.get("added") or []
    return gained


class Cost:
    """Token accounting that means the same thing on both providers."""

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.cache_read = 0
        self.cache_write = 0

    def as_dict(self) -> dict:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "billable_input": self.input + self.cache_write,
        }


def _execute(server: str, ops: list, continue_on_error: bool) -> tuple[str, bool, int]:
    """Run a list of ops. Returns (text for the model, is_error, failures)."""
    try:
        answer = _post(
            server,
            "/command-list",
            {"commands": ops, "continue_on_error": bool(continue_on_error)},
        )
    except Exception as exc:
        # The loop must survive a dead server: an episode that reports what
        # went wrong is worth more than one that raises out of the sweep.
        return f"could not reach the toolkit at {server}: {exc}", True, len(ops)
    failures = sum(
        1 for item in (answer.get("results") or []) if not item.get("ok")
    )
    return (
        json.dumps(answer, separators=(",", ":"))[:60000],
        not answer.get("ok", True),
        failures,
    )


def _turn_budget(turns: int, max_turns: int) -> str:
    """Tell the agent how much rope is left, appended to every tool result.

    An episode that runs out of turns scores zero even when it was one step
    from the answer, and the agent could not see it coming: nothing in the
    conversation says a ceiling exists. Roughly one episode in eight died this
    way, most of them still making progress rather than looping.

    Escalates rather than repeating, because a constant note becomes wallpaper.
    The last band deliberately asks for a defensible answer instead of a
    perfect one -- a wrong answer and no answer both score zero, so a guess
    from evidence strictly dominates silence.
    """
    left = max_turns - turns
    if left <= 0:
        return ""
    line = "\n\n[turn %d of %d -- %d left]" % (turns, max_turns, left)
    if left <= 3:
        return line + (
            " ANSWER NOW. Send your final message this turn, ending with the "
            "ANSWER: line. Running "
            "out of turns scores zero; your best answer from what you already "
            "have may score. If you truly could not determine it, answer N/A."
        )
    if left <= 8:
        return line + (
            " Start converging. Settle for the answer you can defend rather "
            "than the one you can perfect, and stop re-verifying anything you "
            "have already confirmed once."
        )
    return line


def _run_anthropic(goal, server, model, max_turns, reference, client,
                   max_tokens=8000, trace=None):
    """The native Anthropic path: content blocks, tool_use, prefix caching."""
    import anthropic

    client = client or anthropic.Anthropic()
    system = [
        {"type": "text", "text": SYSTEM},
        {
            "type": "text",
            "text": "The operations available, with their exact parameters:\n" + reference,
            # Identical for every episode against this server, so it is worth
            # caching: on a long sweep it is the largest repeated cost, and a
            # cache read is about a tenth the price of sending it again.
            "cache_control": {"type": "ephemeral"},
        },
    ]
    messages: list = [{"role": "user", "content": goal}]
    cost, turns, ops_sent, op_failures = Cost(), 0, 0, 0
    response = None

    while turns < max_turns:
        turns += 1
        response = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            tools=[TOOL], messages=messages,
        )
        cost.input += response.usage.input_tokens
        cost.output += response.usage.output_tokens
        cost.cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cost.cache_write += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        messages.append({"role": "assistant", "content": response.content})
        if trace:
            trace.turn(
                turns,
                "".join(b.thinking for b in response.content if b.type == "thinking"),
                "".join(b.text for b in response.content if b.type == "text"),
            )

        if response.stop_reason != "tool_use":
            break

        # Every tool_use block from one assistant turn is answered in ONE user
        # message. Splitting them across messages teaches the model to stop
        # issuing parallel calls -- the opposite of what this policy is for.
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            ops = block.input.get("ops") or []
            ops_sent += len(ops)
            if trace:
                trace.ops(ops)
            text, is_error, failures = _execute(
                server, ops, block.input.get("continue_on_error")
            )
            op_failures += failures
            if trace:
                trace.result(len(ops), failures, _gained(text))
            results.append({
                "type": "tool_result", "tool_use_id": block.id,
                "content": text, "is_error": is_error,
            })
        budget = _turn_budget(turns, max_turns)
        if budget:
            results.append({"type": "text", "text": budget})
        messages.append({"role": "user", "content": results})

    reply = "".join(b.text for b in response.content if b.type == "text")
    return turns, ops_sent, op_failures, cost, reply


# OpenRouter speaks the OpenAI wire format, so this path uses the OpenAI SDK
# against OpenRouter's base URL. It is kept as a separate function rather than
# folded into the Anthropic one on purpose: the two differ in tool schema
# shape, in how a tool result is returned, and in what usage is called, and a
# single function pretending otherwise is where provider bugs hide.
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _openai_tool() -> dict:
    """The same tool, in the shape the OpenAI wire format wants."""
    return {
        "type": "function",
        "function": {
            "name": TOOL["name"],
            "description": TOOL["description"],
            "parameters": TOOL["input_schema"],
        },
    }


def _openrouter_call(client, **kwargs):
    """One completion, waiting out the shared free pool's rate limits.

    A free stealth model is a shared upstream pool, and it returns 429 with
    "temporarily rate-limited upstream" whenever the pool is busy -- routinely,
    not exceptionally. Over a sweep of hundreds of episodes an unretried 429
    is a lost episode, so this waits rather than failing. The SDK's own retries
    are shorter than the pool's busy periods, hence the outer loop.
    """
    import time

    delay = 8.0
    for attempt in range(8):
        problem = None
        try:
            response = client.chat.completions.create(**kwargs)
            if response.choices:
                return response
            # OpenRouter can answer 200 with an error body shaped like a
            # completion -- no choices, an `error` member instead. The SDK
            # raises nothing, so an unguarded caller dies on choices[0].
            problem = getattr(response, "error", None) or "no choices returned"
        except Exception as exc:
            problem = exc
            text = f"{type(exc).__name__} {exc}".lower()
            # Over hundreds of episodes a dropped connection is as routine as
            # a busy pool, and an unretried one costs a whole episode.
            transient = any(
                marker in text
                for marker in ("429", "rate", "connection", "timeout", "502",
                               "503", "504", "overload")
            )
            if not transient:
                raise
        if attempt == 7:
            raise RuntimeError(f"giving up after 8 attempts: {problem}")
        print(f"  [upstream busy: {str(problem)[:90]} -- waiting {delay:.0f}s]",
              flush=True)
        time.sleep(delay)
        delay = min(delay * 1.8, 120.0)
    raise RuntimeError("unreachable")


def _run_openrouter(goal, server, model, max_turns, reference, client,
                    max_tokens=32000, trace=None):
    from openai import OpenAI

    key = os.environ.get("OPENROUTER_API_KEY")
    client = client or OpenAI(
        base_url=_OPENROUTER_BASE, api_key=key, max_retries=5, timeout=300.0
    )
    messages: list = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "system",
            "content": "The operations available, with their exact parameters:\n"
            + reference,
        },
        {"role": "user", "content": goal},
    ]
    cost, turns, ops_sent, op_failures = Cost(), 0, 0, 0
    reply = ""

    nudged = False
    while turns < max_turns:
        turns += 1
        response = _openrouter_call(
            client, model=model, max_tokens=max_tokens,
            tools=[_openai_tool()], messages=messages,
        )
        usage = response.usage
        if usage is not None:
            cost.input += usage.prompt_tokens or 0
            cost.output += usage.completion_tokens or 0
            details = getattr(usage, "prompt_tokens_details", None)
            cost.cache_read += getattr(details, "cached_tokens", 0) or 0

        choice = response.choices[0].message
        messages.append(choice.model_dump(exclude_none=True))
        reply = choice.content or reply
        if trace:
            trace.turn(turns, getattr(choice, "reasoning", None), choice.content)

        calls = choice.tool_calls or []
        if not calls:
            if not nudged and not _ANSWER_MARK.search(reply or "") and turns < max_turns:
                nudged = True
                messages.append({"role": "user", "content": _NUDGE})
                continue
            break

        for call in calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except ValueError:
                # A model that emits malformed arguments must be told so rather
                # than crashing the episode -- it can usually fix it next turn.
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": "arguments were not valid JSON; send an object "
                               'like {"ops":[{"op":"get_text"}]}',
                })
                continue
            ops = arguments.get("ops") or []
            ops_sent += len(ops)
            if trace:
                trace.ops(ops)
            text, _is_error, failures = _execute(
                server, ops, arguments.get("continue_on_error")
            )
            op_failures += failures
            if trace:
                trace.result(len(ops), failures, _gained(text))
            messages.append({
                "role": "tool", "tool_call_id": call.id,
                "content": text + _turn_budget(turns, max_turns),
            })

    return turns, ops_sent, op_failures, cost, reply or ""


BACKENDS = {"anthropic": _run_anthropic, "openrouter": _run_openrouter}
DEFAULT_MODELS = {"anthropic": DEFAULT_MODEL, "openrouter": "stealth/ox-alpha"}


def run_episode(
    goal: str,
    server: str = "http://127.0.0.1:8766",
    model: str | None = None,
    max_turns: int = 30,
    provider: str = "anthropic",
    client=None,
    max_tokens: int | None = None,
    trace_port: int | None = None,
    trace_path: str | None = None,
    quiet: bool = False,
) -> dict:
    """Drive one task to completion. Returns what it cost and what it did."""
    if provider not in BACKENDS:
        raise SystemExit(f"unknown provider {provider!r}; use {'/'.join(BACKENDS)}")
    model = model or DEFAULT_MODELS[provider]
    reference = ops_reference(server)

    # A reasoning model spends output tokens thinking before it emits a tool
    # call, so the budget has to leave room for that. It does NOT have to be
    # generous: measured over 43 episodes, a turn produces ~387 output tokens
    # including reasoning, so 8000 is twenty times the observed need.
    #
    # The ceiling matters for a second reason. OpenRouter checks affordability
    # against max_tokens rather than usage, so an oversized ceiling is refused
    # outright -- 32000 returned 402 "can only afford 22583" and halted two
    # sweeps without a single token being spent.
    budget = max_tokens or 8000
    trace = Trace(enabled=not quiet, port=trace_port, path=trace_path)
    trace.say(f"goal: {goal}")
    trace.say(f"model: {model} via {provider}  |  toolkit: {server}")
    try:
        turns, ops_sent, op_failures, cost, reply = BACKENDS[provider](
            goal, server, model, max_turns, reference, client, budget, trace
        )
    finally:
        # The page must stop saying "live" whether the run finished or threw.
        trace.running = False
    trace.done(turns, ops_sent, cost.as_dict())
    return {
        "provider": provider,
        "model": model,
        "turns": turns,
        "hit_turn_limit": turns >= max_turns,
        "ops_sent": ops_sent,
        "op_failures": op_failures,
        # The number this policy exists to move. One op per turn means the
        # model is not planning ahead, whatever the prompt told it.
        "ops_per_turn": round(ops_sent / max(turns - 1, 1), 2),
        "usage": cost.as_dict(),
        "reply": reply[-2000:],
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("goal", help="What to do on the page that is already open.")
    ap.add_argument("--server", default="http://127.0.0.1:8766")
    ap.add_argument("--provider", default="anthropic", choices=sorted(BACKENDS))
    ap.add_argument("--model", default=None, help="Defaults per provider.")
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--trace-port", type=int, default=None,
                    help="Serve a live view of the loop at "
                         "http://127.0.0.1:PORT while it runs.")
    ap.add_argument("--quiet", action="store_true",
                    help="No turn-by-turn output on stderr.")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="Output budget per turn. Defaults 32000 on openrouter "
                         "(reasoning models think before answering), 8000 on anthropic.")
    args = ap.parse_args()

    needed = {
        "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        "openrouter": ("OPENROUTER_API_KEY",),
    }[args.provider]
    if not any(os.environ.get(name) for name in needed):
        print(f"warning: none of {', '.join(needed)} is set", flush=True)

    print(json.dumps(run_episode(
        args.goal, args.server, args.model, args.max_turns, args.provider,
        None, args.max_tokens, args.trace_port, args.quiet,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
