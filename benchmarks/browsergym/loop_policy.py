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
import os
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
    """The op vocabulary, straight from the server that will run it.

    Fetched rather than written down, so it cannot drift from the server the
    episode is actually talking to -- the same reason `abt ops` exists.
    """
    with urllib.request.urlopen(server.rstrip("/") + "/ops", timeout=30) as response:
        return json.dumps(json.load(response), separators=(",", ":"))



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
            "/commands",
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


def _run_anthropic(goal, server, model, max_turns, reference, client, max_tokens=8000):
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
            text, is_error, failures = _execute(
                server, ops, block.input.get("continue_on_error")
            )
            op_failures += failures
            results.append({
                "type": "tool_result", "tool_use_id": block.id,
                "content": text, "is_error": is_error,
            })
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


def _run_openrouter(goal, server, model, max_turns, reference, client, max_tokens=32000):
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

        calls = choice.tool_calls or []
        if not calls:
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
            text, _is_error, failures = _execute(
                server, ops, arguments.get("continue_on_error")
            )
            op_failures += failures
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": text}
            )

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
) -> dict:
    """Drive one task to completion. Returns what it cost and what it did."""
    if provider not in BACKENDS:
        raise SystemExit(f"unknown provider {provider!r}; use {'/'.join(BACKENDS)}")
    model = model or DEFAULT_MODELS[provider]
    reference = ops_reference(server)

    # A reasoning model spends output tokens thinking before it emits a tool
    # call; too small a budget truncates it mid-thought and the turn produces
    # nothing. Hence a far larger default on the OpenRouter path.
    budget = max_tokens or (32000 if provider == "openrouter" else 8000)
    turns, ops_sent, op_failures, cost, reply = BACKENDS[provider](
        goal, server, model, max_turns, reference, client, budget
    )
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
        None, args.max_tokens,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
