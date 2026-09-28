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
"""


class ModelError(Exception):
    """The endpoint refused or failed. `retry_elsewhere` means another model
    in the list may well succeed (no tool support, rate limit, overload)."""

    def __init__(self, message: str, retry_elsewhere: bool = True) -> None:
        super().__init__(message)
        self.retry_elsewhere = retry_elsewhere


def tools() -> list[dict]:
    """The MCP tools, in the shape OpenAI-compatible endpoints take."""
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
    ]


def system_prompt(rules: list[str] | None, run_js: bool) -> str:
    text = mcp.INSTRUCTIONS + EXTRA
    if rules:
        text += (
            "\nThis session may only reach URLs its rules allow: "
            + ", ".join(rules)
            + ". A url_blocked error is final -- tell the person, do not work around it.\n"
        )
    if not run_js:
        text += "\nrun_js is switched off in this session.\n"
    return text


def complete(
    endpoint: str, api_key: str, model: str, messages: list[dict], tool_list: list[dict]
) -> dict:
    """One call to `/chat/completions`. Returns the assistant message."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # OpenRouter uses these to attribute traffic; other endpoints ignore them.
    headers["X-Title"] = "AI Browser Toolkit"
    # Sent as ASCII-escaped JSON, not raw UTF-8. A router like openrouter/free
    # hands the request to whichever backend is up, and some of them fail on a
    # raw em dash from a page ("'ascii' codec can't encode character '—'").
    # \u escapes are the same JSON to anything that parses it.
    body = json.dumps(
        {"model": model, "messages": messages, "tools": tool_list, "tool_choice": "auto"},
        ensure_ascii=True,
    )
    try:
        response = httpx.post(
            f"{endpoint.rstrip('/')}/chat/completions",
            headers=headers,
            content=body.encode("ascii"),
            timeout=180,
        )
    except httpx.HTTPError as exc:
        raise ModelError(f"could not reach {endpoint}: {exc}") from exc
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
        return body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ModelError(f"{model}: no message in the reply")


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


def run_turn(
    messages: list[dict],
    *,
    models: list[str],
    complete_fn: Callable[[str, list[dict]], dict],
    call_tool: Callable[[str, dict], tuple[str, bool]],
    emit: Callable[[dict], None],
    should_stop: Callable[[], bool] = lambda: False,
    system: str = "",
    max_steps: int = MAX_STEPS,
) -> str | None:
    """Answer the last user message, calling tools until the model is done.

    Appends every assistant and tool message to `messages` in place, so the
    caller saves the conversation as it now stands. Returns the model that
    answered, or None if none could.
    """
    if not models:
        emit({"type": "error", "text": "No model is set. Add one in Settings."})
        return None
    candidates = list(dict.fromkeys(models))
    active = candidates[0]
    for _ in range(max_steps):
        if should_stop():
            emit({"type": "notice", "text": "Stopped."})
            return active
        request = ([{"role": "system", "content": system}] if system else []) + trimmed(messages)
        message = None
        while message is None:
            try:
                message = complete_fn(active, request)
            except ModelError as exc:
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
                    text, failed = call_tool(name, args)
            if len(text) > RESULT_CHARS:
                text = text[:RESULT_CHARS] + f" … [{len(text) - RESULT_CHARS} more chars]"
            emit({"type": "tool_result", "name": name, "text": text, "error": failed})
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name, "content": text})
    emit({"type": "notice", "text": f"Stopped after {max_steps} steps."})
    return active
