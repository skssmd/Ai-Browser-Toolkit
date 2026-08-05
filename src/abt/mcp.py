"""An MCP server that fronts the HTTP API over stdio.

Why a proxy and not a rewrite: MCP's stdio transport makes the *client* spawn
the server, so an MCP server that owned the browser would take the browser down
every time the client exited. `abt serve` deliberately outlives any number of
agent sessions -- log in once by hand, leave the window up, restart your editor,
carry on. So this process owns nothing. It forwards, and if it dies the browser
does not notice.

Why it exists at all: driving the toolkit through curl means the model writes
the request as a *shell command*, and it gets them wrong. Observed in one
66-command session against a live site:

    get_text {"diff": ...}      -> diff: Extra inputs are not permitted
    select   {"label": ...}     -> label: Extra inputs are not permitted
    select   {css and text}     -> supply only one of ref, css, xpath, text
    run_js   {"script": {...}}  -> script: Input should be a valid string

Five schema errors in sixty-six commands, every one of them a guess at a
parameter name. Typed tool schemas make all of them unrepresentable, and the
JSON never touches a shell -- which on Windows is its own recurring source of
quoting failures.

The protocol is small enough to speak directly: initialize, tools/list,
tools/call. That is cheaper than taking on a dependency for three methods.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_API = "http://127.0.0.1:8765"

_TARGET = {
    "ref": {"type": "string", "description": "Ref from a find, or from a diff's actionable list."},
    "css": {"type": "string"},
    "xpath": {"type": "string"},
    "text": {"type": "string", "description": "Exact visible text."},
    "index": {"type": "integer", "description": "Nth match. Default 0."},
}

_TARGET_NOTE = "Give exactly ONE of ref/css/xpath/text."


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# These definitions are re-sent to the model on every turn -- measured at ~2,661
# tokens across 102 turns in one session, which is the whole of MCP's measured
# overhead against raw HTTP. So each description earns its place by preventing a
# wrong call, and nothing here explains *why*.
TOOLS: list[dict] = [
    {
        "name": "browser_navigate",
        "description": (
            "Open a URL, or go back/forward/reload. Returns the landed page's "
            "full text in dom_diff.text.added, already waited for render. No "
            "separate read needed."
        ),
        "inputSchema": _schema({
            "url": {"type": "string"},
            "action": {"type": "string", "enum": ["back", "forward", "reload"]},
        }),
    },
    {
        "name": "browser_find",
        "description": (
            "Search the page, iframes included. Each match returns its tag and "
            "attributes with children stripped, plus a ref. full=true adds inner "
            "content and is much larger. count=0 is an answer, not a bad "
            "selector: do not retry with wider selectors or run_js DOM scans. If "
            "the reply carries shadow_hosts, retry once with shadow=true; "
            "otherwise the element does not exist yet, so click whatever would "
            "create it (upload inputs are mounted on click)."
        ),
        "inputSchema": _schema({
            "css": {"type": "string"},
            "xpath": {"type": "string"},
            "text": {"type": "string", "description": "Exact visible text."},
            "full": {"type": "boolean"},
            "limit": {"type": "integer"},
            "visible_only": {"type": "boolean"},
            "shadow": {
                "type": "boolean",
                "description": (
                    "Also search open shadow roots. css/text only. Use when a "
                    "reply reported shadow_hosts."
                ),
            },
        }),
    },
    {
        "name": "browser_click",
        "description": (
            "Click an element. " + _TARGET_NOTE + " dom_diff.actionable lists "
            "controls that appeared, with refs -- use those instead of searching "
            "again. Refuses a click an overlay would swallow."
        ),
        "inputSchema": _schema({
            **_TARGET,
            "force": {"type": "boolean", "description": "Click through an intercepting overlay."},
            "new_tab": {"type": "boolean", "description": "Open the href in a new tab instead."},
        }),
    },
    {
        "name": "browser_input",
        "description": (
            "Type into a field. " + _TARGET_NOTE + " Also writes a path to a "
            "file input the page keeps hidden behind a custom uploader."
        ),
        "inputSchema": _schema({
            **_TARGET,
            "value": {"type": "string", "description": "Text, or a file path for an upload."},
            "clear": {"type": "boolean", "description": "Empty first. Default true."},
        }, ["value"]),
    },
    {
        "name": "browser_select",
        "description": "Pick an option in a native <select>. " + _TARGET_NOTE,
        "inputSchema": _schema({
            **_TARGET,
            "by_text": {"type": "string"},
            "value": {"type": "string"},
            "option_index": {"type": "integer"},
        }),
    },
    {
        "name": "browser_press",
        "description": "Send a key: a character, a named key (Enter, Tab), or a chord (ctrl+v).",
        "inputSchema": _schema({**_TARGET, "key": {"type": "string"}}, ["key"]),
    },
    {
        "name": "browser_read",
        "description": (
            "Visible text, or HTML with html=true. Prefer the dom_diff you were "
            "already given."
        ),
        "inputSchema": _schema({**_TARGET, "html": {"type": "boolean"}}),
    },
    {
        "name": "browser_wait_for",
        "description": "Wait for an element to reach a state.",
        "inputSchema": _schema({
            **_TARGET,
            "state": {"type": "string", "enum": ["present", "visible", "clickable", "absent"]},
            "timeout": {"type": "number", "description": "Seconds."},
        }),
    },
    {
        "name": "browser_diff",
        "description": "What changed since the last command. For updates that land asynchronously.",
        "inputSchema": _schema({
            "reset": {"type": "boolean", "description": "Re-baseline to the current page."},
            "element_diff": {"type": "boolean"},
        }),
    },
    {
        "name": "browser_inspect",
        "description": "Console messages or network requests. Console is captured from document start.",
        "inputSchema": _schema({
            "what": {"type": "string", "enum": ["console", "network"]},
            "failures_only": {"type": "boolean"},
            "pattern": {"type": "string", "description": "Regex filter."},
        }, ["what"]),
    },
    {
        "name": "browser_run_js",
        "description": (
            "Run JavaScript, return its value. Escape hatch -- to locate "
            "something use browser_find and act on the ref."
        ),
        "inputSchema": _schema({
            "script": {"type": "string", "description": "Body. Use `return` to send a value back."},
            "args": {"type": "array", "description": "Exposed as arguments[0], arguments[1], ..."},
        }, ["script"]),
    },
    {
        "name": "browser_screenshot",
        "description": "Capture the viewport, or one element. Returns base64 PNG; writes no file.",
        "inputSchema": _schema({**_TARGET}),
    },
    {
        "name": "browser_tabs",
        "description": "List, open, switch, or close tabs.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["list", "new", "switch", "close"]},
            "url": {"type": "string"},
            "tab_id": {"type": "string"},
        }, ["action"]),
    },
    {
        "name": "browser_batch",
        "description": (
            "Run several ops in ONE call, in order. Prefer this for any sequence "
            "you already know -- one round trip instead of one per step. Items "
            'are raw op objects: {"op":"click","css":"#x"}. Stops at the first '
            "failure unless continue_on_error."
        ),
        "inputSchema": _schema({
            "commands": {"type": "array", "items": {"type": "object"}},
            "continue_on_error": {"type": "boolean"},
        }, ["commands"]),
    },
    {
        "name": "browser_command",
        "description": (
            "Last resort: one raw op no named tool covers (alert, scroll, "
            "status). Passed through WITHOUT validation, so check GET /ops for "
            "exact parameter names rather than guessing."
        ),
        "inputSchema": _schema({"command": {"type": "object"}}, ["command"]),
    },
]


def _one_of(args: dict, *names: str) -> dict:
    return {name: args[name] for name in names if args.get(name) is not None}


def to_op(tool: str, args: dict) -> Any:
    """Translate a tool call into the op (or batch) the HTTP API expects."""
    target = _one_of(args, "ref", "css", "xpath", "text", "index")

    if tool == "browser_navigate":
        if args.get("action"):
            return {"op": args["action"]}
        return {"op": "goto", "url": args.get("url")}

    if tool == "browser_find":
        payload = {"op": "find_full" if args.get("full") else "find"}
        payload.update(
            _one_of(args, "css", "xpath", "text", "limit", "visible_only", "shadow")
        )
        return payload

    if tool == "browser_click":
        return {"op": "click", **target, **_one_of(args, "force", "new_tab")}

    if tool == "browser_input":
        return {"op": "input", **target, **_one_of(args, "value", "clear")}

    if tool == "browser_select":
        return {"op": "select", **target, **_one_of(args, "by_text", "value", "option_index")}

    if tool == "browser_press":
        return {"op": "press", **target, **_one_of(args, "key")}

    if tool == "browser_read":
        return {"op": "get_html" if args.get("html") else "get_text", **target}

    if tool == "browser_wait_for":
        return {"op": "wait_for", **target, **_one_of(args, "state", "timeout")}

    if tool == "browser_diff":
        return {"op": "diff", **_one_of(args, "reset", "element_diff")}

    if tool == "browser_inspect":
        if args.get("what") == "network":
            return {"op": "read_network", **_one_of(args, "failures_only", "pattern")}
        return {"op": "read_console", **_one_of(args, "pattern")}

    if tool == "browser_tabs":
        action = args.get("action")
        if action == "list":
            return {"op": "tab_list"}
        if action == "new":
            return {"op": "tab_new", **_one_of(args, "url")}
        if action == "switch":
            return {"op": "tab_switch", **_one_of(args, "tab_id")}
        return {"op": "tab_close", **_one_of(args, "tab_id")}

    if tool == "browser_run_js":
        return {"op": "run_js", **_one_of(args, "script", "args")}

    if tool == "browser_screenshot":
        return {"op": "screenshot", **target}

    if tool == "browser_batch":
        return {
            "commands": args.get("commands") or [],
            "continue_on_error": bool(args.get("continue_on_error")),
        }

    if tool == "browser_command":
        return args.get("command") or {}

    raise KeyError(tool)


class Bridge:
    """Forwards tool calls to the HTTP API."""

    def __init__(self, api: str = DEFAULT_API, timeout: float = 180.0) -> None:
        self.api = api.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def call(self, tool: str, args: dict) -> tuple[str, bool]:
        """Returns (text, is_error). Never raises -- an agent needs a message."""
        try:
            payload = to_op(tool, args)
        except KeyError:
            return f"no such tool: {tool}", True

        endpoint = "/commands" if tool == "browser_batch" else "/command"
        try:
            response = self.client.post(f"{self.api}{endpoint}", json=payload)
        except httpx.RequestError as exc:
            return (
                f"cannot reach the toolkit at {self.api} ({exc}). It is a separate, "
                "long-lived process that owns the browser -- start it with "
                "`abt serve --browser chrome` and wait for GET /status to answer.",
                True,
            )

        try:
            body = response.json()
        except ValueError:
            return f"HTTP {response.status_code}: {response.text[:800]}", True

        failed = isinstance(body, dict) and body.get("ok") is False
        if isinstance(body, list):
            failed = any(item.get("ok") is False for item in body if isinstance(item, dict))
        # Compact, not pretty. The reader is a model, and indent=2 inflated the
        # identical payload by about 1.6x -- measured at a median 368 chars per
        # response against 302 for the same work over raw HTTP. Every one of
        # those characters is read back on the next turn.
        return json.dumps(body, separators=(",", ":")), failed


class Server:
    """Just enough MCP to be a tool provider: initialize, tools/list, tools/call."""

    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        request_id = message.get("id")

        # Notifications carry no id and must never be answered.
        if request_id is None:
            return None

        if method == "initialize":
            return self._ok(request_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aibrowsertoolkit", "version": "0.1.0"},
            })

        if method == "tools/list":
            return self._ok(request_id, {"tools": TOOLS})

        if method == "tools/call":
            params = message.get("params") or {}
            text, failed = self.bridge.call(
                params.get("name") or "", params.get("arguments") or {}
            )
            return self._ok(request_id, {
                "content": [{"type": "text", "text": text}],
                "isError": failed,
            })

        if method == "ping":
            return self._ok(request_id, {})

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    @staticmethod
    def _ok(request_id: Any, result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(api: str = DEFAULT_API, stdin=None, stdout=None) -> None:
    """Read newline-delimited JSON-RPC from stdin, write replies to stdout."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    server = Server(Bridge(api))

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue

        reply = server.handle(message)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
