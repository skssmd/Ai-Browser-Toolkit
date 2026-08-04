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
    "ref": {
        "type": "string",
        "description": "A ref from a previous find, or from a diff's actionable "
        "track. Cheapest and least ambiguous way to point at something.",
    },
    "css": {"type": "string", "description": "CSS selector."},
    "xpath": {"type": "string", "description": "XPath expression."},
    "text": {"type": "string", "description": "Exact visible text."},
    "index": {
        "type": "integer",
        "description": "Which match to use when the selector matches several. Defaults to 0.",
    },
}

_TARGET_NOTE = (
    "Supply exactly ONE of ref, css, xpath or text -- more than one is an error."
)


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# Deliberately a small surface. Every tool definition sits in the model's
# context for the whole session, so 25 thin wrappers would cost more than they
# earn -- `batch` and `command` between them reach everything not listed here.
TOOLS: list[dict] = [
    {
        "name": "browser_navigate",
        "description": (
            "Go to a URL, or move through history. Returns the destination's "
            "title and, in dom_diff.text.added, the full text of the page it "
            "landed on -- already waited for it to finish rendering. You do not "
            "need a separate read to see what is on the page."
        ),
        "inputSchema": _schema(
            {
                "url": {"type": "string", "description": "URL to open. Omit when using action."},
                "action": {
                    "type": "string",
                    "enum": ["back", "forward", "reload"],
                    "description": "Move through history instead of opening a URL.",
                },
            }
        ),
    },
    {
        "name": "browser_find",
        "description": (
            "Search the page. Returns each match's own tag and attributes with "
            "children stripped, plus a ref for acting on it. Use full=true only "
            "when you need the inner content -- it is far larger."
        ),
        "inputSchema": _schema(
            {
                "css": {"type": "string"},
                "xpath": {"type": "string"},
                "text": {"type": "string", "description": "Exact visible text."},
                "full": {"type": "boolean", "description": "Include inner content."},
                "limit": {"type": "integer", "description": "Cap the number of matches."},
                "visible_only": {"type": "boolean"},
            }
        ),
    },
    {
        "name": "browser_click",
        "description": (
            "Click an element. " + _TARGET_NOTE + " The response's dom_diff "
            "reports what changed, and dom_diff.actionable lists any controls "
            "that appeared with refs to use them -- act on those directly "
            "instead of searching again. Refuses to click something covered by "
            "an overlay rather than silently missing."
        ),
        "inputSchema": _schema(
            {
                **_TARGET,
                "force": {
                    "type": "boolean",
                    "description": "Dispatch through an overlay that is intercepting the click.",
                },
                "new_tab": {
                    "type": "boolean",
                    "description": "Open the target's href in a new tab instead of clicking.",
                },
            }
        ),
    },
    {
        "name": "browser_input",
        "description": (
            "Type into a field. " + _TARGET_NOTE + " Works on a file input that "
            "the page keeps hidden behind a custom uploader -- pass the local "
            "path as the value."
        ),
        "inputSchema": _schema(
            {
                **_TARGET,
                "value": {"type": "string", "description": "Text to type, or a file path for an upload."},
                "clear": {"type": "boolean", "description": "Empty the field first. Defaults to true."},
            },
            ["value"],
        ),
    },
    {
        "name": "browser_select",
        "description": "Choose an option in a native <select>. " + _TARGET_NOTE,
        "inputSchema": _schema(
            {
                **_TARGET,
                "by_text": {"type": "string", "description": "Match the option's visible text."},
                "value": {"type": "string", "description": "Match the option's value attribute."},
                "option_index": {"type": "integer", "description": "Match by position."},
            }
        ),
    },
    {
        "name": "browser_press",
        "description": (
            "Send a key to whatever has focus, or to a target. A single "
            "character, a named key such as Enter or Tab, or a chord such as "
            "ctrl+v or ctrl+alt+1."
        ),
        "inputSchema": _schema({**_TARGET, "key": {"type": "string"}}, ["key"]),
    },
    {
        "name": "browser_read",
        "description": (
            "Read visible text, or HTML with html=true. Prefer the dom_diff a "
            "command already returned; reach for this when you need the state "
            "of a page nothing has just changed."
        ),
        "inputSchema": _schema({**_TARGET, "html": {"type": "boolean"}}),
    },
    {
        "name": "browser_wait_for",
        "description": "Wait for an element to reach a state before continuing.",
        "inputSchema": _schema(
            {
                **_TARGET,
                "state": {
                    "type": "string",
                    "enum": ["present", "visible", "clickable", "absent"],
                },
                "timeout": {"type": "number", "description": "Seconds."},
            }
        ),
    },
    {
        "name": "browser_diff",
        "description": (
            "What changed since the last command touched the page. Use when an "
            "update landed asynchronously, after the command that triggered it "
            "had already returned."
        ),
        "inputSchema": _schema(
            {
                "reset": {"type": "boolean", "description": "Make the current page the new baseline."},
                "element_diff": {"type": "boolean"},
            }
        ),
    },
    {
        "name": "browser_inspect",
        "description": (
            "Console messages or network requests. The DOM cannot tell you why "
            "a request failed; these can. Console is captured from document "
            "start, so a reload shows what the page logged while loading."
        ),
        "inputSchema": _schema(
            {
                "what": {"type": "string", "enum": ["console", "network"]},
                "failures_only": {"type": "boolean", "description": "Network only."},
                "pattern": {"type": "string", "description": "Filter with a regex."},
            },
            ["what"],
        ),
    },
    {
        "name": "browser_tabs",
        "description": "List, open, switch, or close tabs.",
        "inputSchema": _schema(
            {
                "action": {"type": "string", "enum": ["list", "new", "switch", "close"]},
                "url": {"type": "string", "description": "For action=new."},
                "tab_id": {"type": "string", "description": "For action=switch or close."},
            },
            ["action"],
        ),
    },
    {
        "name": "browser_batch",
        "description": (
            "Run several operations in ONE call, in order. Strongly preferred "
            "for any sequence you already know -- filling a form, walking a "
            "wizard -- because it costs one round trip instead of one per step. "
            "Each item is a raw op object, e.g. "
            '{"op":"click","css":"#next"}. Stops at the first failure unless '
            "continue_on_error is set."
        ),
        "inputSchema": _schema(
            {
                "commands": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Op objects, each with an 'op' key.",
                },
                "continue_on_error": {"type": "boolean"},
            },
            ["commands"],
        ),
    },
    {
        "name": "browser_command",
        "description": (
            "Escape hatch: send one raw op the named tools do not cover, such "
            "as screenshot, run_js, alert or status. GET /ops on the server "
            "lists everything available."
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
        payload.update(_one_of(args, "css", "xpath", "text", "limit", "visible_only"))
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
        return json.dumps(body, indent=2), failed


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
