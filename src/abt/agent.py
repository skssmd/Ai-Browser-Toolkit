"""The desktop app's chat: a model driving the browser through abt's tools.

Any OpenAI-compatible `/chat/completions` endpoint works -- OpenRouter, a local
server, a hosted provider. The model is given exactly the MCP tool set, so it
sees what Claude Code or Cursor see through `abt mcp`, and its tool calls run
in the session the app bound it to. Nothing here chooses a session; nothing
the model says can change it.

The loop is pure apart from two injected functions -- `complete`, which calls
the model, and `call_tool`, which runs a tool -- so it is tested with a scripted
fake model and no network or browser.
"""

from __future__ import annotations

import json
import contextvars
import threading
from typing import Any, Callable

import httpx

from . import mcp

MAX_STEPS = 40
# A tool result is often a whole page. The newest few are kept whole; older
# ones are cut to this, so a long task does not outgrow the context window.
KEEP_WHOLE = 4
OLD_RESULT_CHARS = 1500
RESULT_CHARS = 12000

EXTRA = """
You are running inside the AI Browser Toolkit desktop app. The person you are
helping watches the browser live beside this chat and can click in it too.
Your browser session was chosen for you and you cannot change it. Keep replies
short; say what you did and what you found.

THE BROWSER IS ALREADY OPEN. Ignore anything above about starting it with
browser_session: here the app starts the browser, and reconnects it if it ever
drops, on its own. There is no browser_session tool. Start with command_list.

File pickers never open here. To upload, call files to list this session's
uploads folder and put a path from it into the file field with input. If the
file is not there, ask the person to put it in the uploads folder and wait.

To hand the person a document -- notes, a report, what you found -- write it in
Markdown and save it with save_file (for example {"op": "save_file", "name":
"report.md", "content": "..."}). It lands in the profile's downloads folder,
where they can open it. Say the file name in your reply.

KEEP GOING UNTIL THE TASK IS DONE. Your turn ends when you stop calling tools,
and then nothing happens until the person writes again -- so end it only when
the task is finished or you truly cannot continue without them. Never end it
just to report progress, acknowledge a message or ask permission to go on.

The person can message you while you work. Such a message is marked as sent
while you were working: it steers the task already in hand. Take it into
account and carry on in the same reply. If it asks something ("what's the
update?"), answer in a sentence alongside your next tool call, not instead of
it.
"""

# How a message sent mid-task reaches the model. Saved and shown to the person
# as they typed it; only the model's copy carries this, so it reads the message
# as steering for the task in hand and keeps working rather than treating it as
# a new request to answer and stop.
STEER_NOTE = (
    "[Sent while you were working. Take this into account and keep going with "
    "the task; if it asks something, answer in a sentence alongside your next "
    "tool call. Do not stop to reply.]\n\n"
)


UPDATE_NOTE = "[Update from ABT, not from the person.]\n\n"


def for_model(message: dict) -> dict:
    """The model's view of one saved message."""
    if message.get("update"):
        return {"role": "user", "content": UPDATE_NOTE + (message.get("content") or "")}
    if message.get("steer"):
        return {"role": "user", "content": STEER_NOTE + (message.get("content") or "")}
    return message


# --- agentic chats: a lead that plans, starts helpers, and gathers reports -----------

MAX_WORKERS = 5

ORCHESTRATION_PROMPT = f"""
YOU CAN START HELPER AGENTS. For work that splits into independent parts --
different angles on the same site, several sites to compare -- you may run up
to {MAX_WORKERS} helpers in parallel, each an AI agent with its own browser tabs,
working on one role you give it. Helpers see the same sites you may, write a
report with save_file when they finish, and cannot start helpers of their own.

How to run it:
1. PLAN FIRST. Call propose_plan with each helper's role and task. Then END YOUR
   TURN and wait: the person approves, changes or declines the plan. You cannot
   start helpers before they reply.
2. After they approve, start each helper with start_worker, using the roles and
   tasks from the plan (as the person amended them).
3. Call wait_for_workers to wait for them; check workers any time for status.
   You are told when each one finishes.
4. Read each report with read_report, then write one combined report with
   save_file and summarise it for the person.

Only use helpers when the task really has parts that can run at once. For a
simple task, just do it yourself.
"""


def worker_prompt(role: str, lead: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in role.lower()).strip("-") or "helper"
    return f"""
YOU ARE A HELPER AGENT, in the role of: {role}.
A lead agent ({lead}) started you and will read your report; the person may watch.
Work only on your task, from your role's point of view. You cannot start helpers.
When you are done, write your findings as a Markdown report with save_file,
named "{slug}-report.md", then reply with a short summary and end your turn.
"""


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


_ROLE_TASK = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "description": "The helper's role, e.g. 'SEO expert'"},
        "task": {"type": "string", "description": "What this helper should do and report on"},
    },
    "required": ["role", "task"],
}

ORCHESTRATION_TOOLS: list[dict] = [
    _function("propose_plan",
              f"Show the person your plan -- up to {MAX_WORKERS} helpers, each a role and a task -- "
              "and end your turn to wait for their go-ahead. Required before start_worker.",
              {"summary": {"type": "string", "description": "One or two sentences on the approach"},
               "workers": {"type": "array", "items": _ROLE_TASK}},
              ["workers"]),
    _function("start_worker",
              "Start one helper from the approved plan. Returns its id. It runs in parallel.",
              {"role": {"type": "string"}, "task": {"type": "string"},
               "sites": {"type": "array", "items": {"type": "string"},
                         "description": "Optional: narrower allowed sites for this helper, "
                                        "e.g. ['example.com']. Defaults to yours."}},
              ["role", "task"]),
    _function("workers",
              "Status of your helpers: working or finished, steps taken, current page, "
              "report files, and a short summary once finished. Never their conversation.",
              {}, []),
    _function("wait_for_workers",
              "Wait until a helper finishes (or the time runs out), then return their status.",
              {"timeout_s": {"type": "number", "description": "Seconds to wait, at most 600. Default 180."}},
              []),
    _function("read_report",
              "Read a finished helper's report file.",
              {"worker": {"type": "string", "description": "The helper's id from start_worker"},
               "file": {"type": "string", "description": "Optional: which of its files"}},
              ["worker"]),
    _function("stop_worker",
              "Stop a helper that is still working.",
              {"worker": {"type": "string"}},
              ["worker"]),
]

ORCHESTRATION_NAMES = frozenset(t["function"]["name"] for t in ORCHESTRATION_TOOLS)

# Managed by the app, not the model: offering it only invites a model to
# "start" a browser that is already running, again and again.
APP_EXCLUDED_TOOLS = frozenset({"browser_session"})


class Stopped(Exception):
    """The person pressed Stop: whatever was in progress gives way at once."""


class ModelError(Exception):
    """The endpoint refused or failed. `retry_elsewhere` means another model
    in the list may well succeed (no tool support, rate limit, overload)."""

    def __init__(self, message: str, retry_elsewhere: bool = True) -> None:
        super().__init__(message)
        self.retry_elsewhere = retry_elsewhere


def tools(exclude: frozenset[str] = APP_EXCLUDED_TOOLS) -> list[dict]:
    """The MCP tools, in the shape OpenAI-compatible endpoints take.

    Minus the ones the app manages itself -- by default, browser_session.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            },
        }
        for tool in mcp.TOOLS
        if tool["name"] not in exclude
    ]


def system_prompt(
    rules: list[str] | None,
    run_js: bool,
    only_listed: bool = False,
    agentic: bool = False,
    role: str | None = None,
    lead: str | None = None,
) -> str:
    text = mcp.INSTRUCTIONS + EXTRA
    if role:
        text += worker_prompt(role, lead or "the lead")
    elif agentic:
        text += ORCHESTRATION_PROMPT
    if only_listed and not [r for r in rules or [] if not r.strip().startswith("!")]:
        text += (
            "\nThis session's allowed-sites list is empty: it may not open any site. "
            "Tell the person, who can add sites in the chat settings.\n"
        )
    elif rules and [r.strip().lower() for r in rules] != ["all"]:
        text += (
            "\nThis session may only reach URLs its rules allow: "
            + ", ".join(rules)
            + ". A url_blocked error is final -- tell the person, do not work around it.\n"
        )
    if not run_js:
        text += "\nrun_js is switched off in this session.\n"
    return text


def complete(
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tool_list: list[dict],
    on_text: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """One call to `/chat/completions`. Returns the assistant message.

    Asks for a streamed reply, so the person sees the words as they are
    written, and hands each piece of text to `on_text`. A provider that
    ignores `stream` and answers with one JSON body works the same way.
    """
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # OpenRouter uses these to attribute traffic; other endpoints ignore them.
    headers["X-Title"] = "AI Browser Toolkit"
    # Sent as ASCII-escaped JSON, not raw UTF-8. A router like openrouter/free
    # hands the request to whichever backend is up, and some of them fail on a
    # raw em dash from a page ("'ascii' codec can't encode character '\u2014'").
    # \u escapes are the same JSON to anything that parses it.
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "tools": tool_list,
            "tool_choice": "auto",
            "stream": True,
            # The token counts, in the stream's last chunk. The chat shows them.
            "stream_options": {"include_usage": True},
        },
        ensure_ascii=True,
    )
    try:
        with httpx.stream(
            "POST",
            f"{endpoint.rstrip('/')}/chat/completions",
            headers=headers,
            content=body.encode("ascii"),
            timeout=180,
        ) as response:
            # Stop closes the stream from outside: a reply waiting on the
            # provider has no next line to check a flag on.
            finished = threading.Event()
            if should_stop is not None:
                def watch() -> None:
                    while not finished.wait(0.2):
                        if should_stop():
                            response.close()
                            return
                threading.Thread(target=watch, daemon=True, name="abt-stop-watch").start()
            try:
                kind = response.headers.get("content-type", "")
                if response.status_code >= 400 or "text/event-stream" not in kind:
                    response.read()
                    return _whole_reply(response, model)
                return _streamed_reply(response, model, on_text)
            finally:
                finished.set()
    except (httpx.HTTPError, httpx.StreamError, RuntimeError) as exc:
        if should_stop is not None and should_stop():
            raise Stopped() from None
        if isinstance(exc, (httpx.StreamError, RuntimeError)):
            raise
        raise ModelError(f"could not reach {endpoint}: {exc}") from exc


def _whole_reply(response, model: str) -> dict:
    try:
        body = response.json()
    except ValueError:
        raise ModelError(f"HTTP {response.status_code}: {response.text[:300]}")
    if response.status_code >= 400 or "error" in body:
        error = body.get("error") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error or body)
        # A bad key is the same for every model; trying the next would only
        # repeat the failure.
        retry = response.status_code not in (401, 403)
        raise ModelError(f"{model}: HTTP {response.status_code}: {message}", retry)
    try:
        message = dict(body["choices"][0]["message"])
    except (KeyError, IndexError, TypeError):
        raise ModelError(f"{model}: no message in the reply")
    if isinstance(body.get("usage"), dict):
        message["usage"] = body["usage"]
    return message


def _streamed_reply(response, model: str, on_text: Callable[[str], None] | None) -> dict:
    """Assemble a message from server-sent events.

    Text arrives in pieces; so do tool calls, whose name and arguments are
    split across chunks and joined back together by their index.
    """
    text: list[str] = []
    calls: dict[int, dict] = {}
    usage = None
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue  # blank keep-alives and ": comment" lines
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if chunk.get("error"):
            error = chunk["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ModelError(f"{model}: {message}")
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                text.append(piece)
                if on_text is not None:
                    on_text(piece)
            for part in delta.get("tool_calls") or []:
                slot = calls.setdefault(
                    part.get("index", len(calls)),
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if part.get("id"):
                    slot["id"] = part["id"]
                function = part.get("function") or {}
                if function.get("name"):
                    slot["function"]["name"] += function["name"]
                if function.get("arguments"):
                    slot["function"]["arguments"] += function["arguments"]
    message: dict = {"role": "assistant", "content": "".join(text)}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    if not message["content"] and not calls:
        raise ModelError(f"{model}: the reply was empty")
    if usage is not None:
        message["usage"] = usage
    return message


def add_usage(totals: dict | None, usage: dict | None) -> dict:
    """Add one model call's token counts to a chat's running totals."""
    totals = dict(totals or {"prompt": 0, "completion": 0, "calls": 0})
    if usage:
        totals["prompt"] += int(usage.get("prompt_tokens") or 0)
        totals["completion"] += int(usage.get("completion_tokens") or 0)
        totals["calls"] += 1
        if usage.get("cost") is not None:  # OpenRouter reports what it charged
            totals["cost"] = round(float(totals.get("cost") or 0) + float(usage["cost"]), 6)
    return totals


def trimmed(messages: list[dict]) -> list[dict]:
    """The conversation as sent: older tool results cut short."""
    tool_positions = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    old = set(tool_positions[:-KEEP_WHOLE])
    out = []
    for i, message in enumerate(messages):
        if i in old and len(message.get("content") or "") > OLD_RESULT_CHARS:
            message = {
                **message,
                "content": message["content"][:OLD_RESULT_CHARS] + " … [trimmed: older result]",
            }
        out.append(message)
    return out


def _until_stopped(call_tool, name: str, args: dict, should_stop) -> tuple[str, bool]:
    """Run one tool call, but stop waiting for it the moment Stop is pressed.

    The call itself cannot be interrupted safely mid-way; it finishes (or times
    out) on its own thread and its result is dropped. The chat does not wait.
    """
    box: dict = {}

    def run() -> None:
        try:
            box["out"] = call_tool(name, args)
        except Exception as exc:  # reported like any failed tool call
            box["out"] = (f"{type(exc).__name__}: {exc}", True)

    # Carries the trace context over, so the tool's steps nest under this reply.
    context = contextvars.copy_context()
    worker = threading.Thread(target=context.run, args=(run,), daemon=True, name=f"abt-tool-{name}")
    worker.start()
    while worker.is_alive():
        worker.join(0.2)
        if worker.is_alive() and should_stop():
            return "stopped by the person while this was running", True
    return box["out"]


def run_turn(
    messages: list[dict],
    *,
    models: list[str],
    complete_fn: Callable[[str, list[dict]], dict],
    call_tool: Callable[[str, dict], tuple[str, bool]],
    emit: Callable[[dict], None],
    should_stop: Callable[[], bool] = lambda: False,
    take_steering: Callable[[], list[dict]] = lambda: [],
    system: str = "",
    max_steps: int = MAX_STEPS,
) -> str | None:
    """Answer the last user message, calling tools until the model is done.

    Appends every assistant and tool message to `messages` in place, so the
    caller saves the conversation as it now stands. Returns the model that
    answered, or None if none could.

    `take_steering` hands over what the person sent while this was running,
    as `{"id", "text"}` items. They join the conversation between steps --
    after a step's tool results, never between a tool call and its result --
    so the model reads them before it decides what to do next. A turn about to
    end carries on when some arrived, so nothing sent is left unanswered.
    """

    def steer() -> bool:
        taken = take_steering()
        for item in taken:
            entry = {"role": "user", "content": item["text"], "steer": True}
            if item.get("update"):
                entry["update"] = True
            messages.append(entry)
            emit({"type": "steer_read", "id": item["id"], "text": item["text"]})
        return bool(taken)

    if not models:
        emit({"type": "error", "text": "No model is set. Add one in Settings."})
        return None
    candidates = list(dict.fromkeys(models))
    active = candidates[0]
    for _ in range(max_steps):
        if should_stop():
            emit({"type": "notice", "text": "Stopped."})
            return active
        steer()
        # Errors and notices are saved in the chat for the person; they are
        # not part of the conversation the model sees.
        conversation = [for_model(m) for m in messages if m.get("role") in ("user", "assistant", "tool")]
        request = ([{"role": "system", "content": system}] if system else []) + trimmed(conversation)
        message = None
        while message is None:
            try:
                message = complete_fn(active, request)
            except Stopped:
                emit({"type": "notice", "text": "Stopped."})
                return active
            except ModelError as exc:
                if should_stop():
                    emit({"type": "notice", "text": "Stopped."})
                    return active
                rest = candidates[candidates.index(active) + 1 :]
                if not exc.retry_elsewhere or not rest:
                    emit({"type": "error", "text": str(exc)})
                    return None
                emit({"type": "notice", "text": f"{exc} -- trying {rest[0]}"})
                active = rest[0]
        calls = message.get("tool_calls") or []
        entry: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        if calls:
            entry["tool_calls"] = calls
        messages.append(entry)
        if entry["content"]:
            emit({"type": "assistant", "text": entry["content"], "model": active})
        if not calls:
            # Something was sent while this answer was being written: answer
            # that too, rather than ending with it unread.
            if steer():
                continue
            return active
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            try:
                args = json.loads(function.get("arguments") or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments are not an object")
            except ValueError as exc:
                text, failed = f"arguments were not valid JSON: {exc}", True
                args = {}
            else:
                emit({"type": "tool_call", "name": name, "args": args})
                if should_stop():
                    text, failed = "stopped by the person before this ran", True
                else:
                    text, failed = _until_stopped(call_tool, name, args, should_stop)
            if len(text) > RESULT_CHARS:
                text = text[:RESULT_CHARS] + f" … [{len(text) - RESULT_CHARS} more chars]"
            emit({"type": "tool_result", "name": name, "text": text, "error": failed})
            if should_stop():
                messages.append({"role": "tool", "tool_call_id": call.get("id") or name, "content": text})
                emit({"type": "notice", "text": "Stopped."})
                return active
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name, "content": text})
    emit({"type": "notice", "text": f"Stopped after {max_steps} steps."})
    return active
