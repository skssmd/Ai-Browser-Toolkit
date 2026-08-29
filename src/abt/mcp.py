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

# Sent once, in the initialize reply, and clients put it in the system prompt.
# That is the cheap slot: per-tool descriptions are re-sent every turn, so
# anything that is true of the *toolkit* rather than of one tool belongs here
# and is paid for once. Without it a model knows what each tool does and still
# does not know that the browser is a separate step from the server, or that
# the reply it already holds contains the page.
INSTRUCTIONS = """\
Browser automation against one long-lived Chrome. The server is a separate
process that outlives this session; it owns the browser and this connection
owns nothing.

FIRST, BEFORE ANY OTHER CALL:

  browser_guidelines {"name":"toolkit-workflow"}   -- the workflow document.
  Read it once, at the start, before you start a browser or touch a page. It
  is not reference to reach for when you get stuck; it is how this toolkit is
  driven, and everything below is a summary of it. One call, and it is the
  difference between driving this well and rediscovering its traps the
  expensive way.

Then start a browser:

  browser_session {"action":"start"}   -- the server runs WITHOUT a browser on
  purpose, and nothing starts one for you. Every page command fails with
  browser_dead until you do this. It can take up to two minutes on a profile
  that has logins in it. browser_session {"action":"status"} says what is up.

Then act through command_list. It is the only way to touch the page, and it
takes a LIST, so send every op you already know you need in one call --
typing and pressing Enter is one call, not two. It is the same name and the
same shape as `abt command-list` and POST /command-list.

  command_list {"commands":[{"op":"find","css":"input[name=q]"},
                            {"op":"input","ref":"el_0","value":"hello"},
                            {"op":"press","key":"Enter"}]}

The ops and their exact parameters come from `abt ops` (GET /ops), which
returns every op with its argument names, types and defaults. Read it instead
of guessing -- a guessed name is the single most common failed call.

Then read what you are given. Every op that changes the page returns a
dom_diff: the text that appeared, and dom_diff.actionable listing new controls
with refs. Re-reading the page to see what happened is the most common and most
expensive mistake made with this toolkit -- the answer is already in the reply.

Addressing an element: exactly ONE of ref, css, xpath or text. Refs come from
find and from a diff's actionable list, and they die on navigation.

find searches the document, every frame and (with shadow=true) open shadow
roots. count=0 is an answer, not a bad selector -- the control does not exist
yet, so click whatever creates it. Do not fall back to run_js to scan the DOM.

Site playbooks -- read one, and leave one behind. Both halves, not just the
first:

  READ: before driving an unfamiliar site, call browser_guidelines with that
  domain. Some sites have a written procedure and it is shorter than
  discovering the page. An empty result is a normal and complete answer --
  most sites have none, so carry on rather than searching again another way.

  WRITE: when you work something out that the next run would rather be told
  than rediscover, send guidelines_note through command_list with domain,
  title, url, problem, tried and solution. Name the dead ends too. If an entry
  already there turns out to be wrong, set `replaces` to its exact title
  rather than appending a second entry that contradicts it -- a reader who
  meets both cannot tell which one won.

  This second half is the one agents skip, and it is the half that compounds:
  every other rule here saves tokens once, a playbook saves every future run
  on that site.

Every failure carries a `hint` saying what to do next. Read it before retrying.
"""


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
        "name": "command_list",
        "description": (
            "Run a browser command, or a LIST of them in order -- this is the "
            "only way to act on the page, and the same name and shape the CLI "
            'and HTTP API use. Items are raw op objects: {"op":"click",'
            '"css":"#x"}. Send every op you already know you need in one call: '
            "typing and pressing Enter is one call, not two. Stops at the "
            "first failure and says which, so a list is never a blind leap. "
            "`abt ops` (GET /ops) gives every op with its exact parameters."
        ),
        "inputSchema": _schema({
            "commands": {
                "type": "array",
                "items": {"type": "object"},
                "description": "One or more ops, run in order.",
                "minItems": 1,
            },
            "continue_on_error": {"type": "boolean"},
        }, ["commands"]),
    },
    {
        "name": "browser_guidelines",
        "description": (
            'The toolkit\'s own docs. name="toolkit-workflow" returns the '
            "workflow document, which you should read once at the start of a "
            "session before driving anything -- it is how this toolkit is "
            "meant to be used, not troubleshooting material. domain=<host> "
            "separately asks whether a written playbook exists for one site "
            "-- fuzzy, so 'sheets' finds docs.google.com; an empty result "
            "just means nobody has written one. Neither argument lists what "
            "is installed."
        ),
        "inputSchema": _schema({
            "domain": {"type": "string", "description": "Site to look up. Fuzzy."},
            "name": {"type": "string", "description": "Playbook to read in full."},
        }),
    },
    {
        "name": "browser_session",
        "description": (
            "Start, stop or restart the browser, or ask whether one is running. "
            "Every page command fails with browser_dead until a browser is "
            "started; nothing starts one for you. Use restart after a crash or "
            "after a tab closed the session. start uses the server's defaults, "
            "restart keeps whatever the last browser used. open_manual launches "
            "the real installed browser directly (no automation) on the same "
            "profile, for sites -- Google among them -- that block a "
            "CDP-controlled browser at sign-in: stop the running browser first, "
            "sign in by hand in the window this opens, close it, then start "
            "again to pick the session back up. Do not pass headless with it "
            "-- a manual login needs a visible window, and the call is "
            "rejected if you do."
        ),
        "inputSchema": _schema(
            {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "status", "open_manual"],
                },
                "browser": {"type": "string", "enum": ["chrome", "edge"]},
                "profile": {"type": "string"},
                "headless": {"type": "boolean"},
            },
            ["action"],
        ),
    },
]


def _version() -> str:
    """The installed version, or a placeholder from a source tree.

    Hardcoding it here meant every release since 0.1.0 announced itself as
    0.1.0 to every MCP client.
    """
    from importlib.metadata import PackageNotFoundError, version

    from . import paths

    try:
        return version(paths.DIST_NAME)
    except PackageNotFoundError:
        return "0"


def _one_of(args: dict, *names: str) -> dict:
    return {name: args[name] for name in names if args.get(name) is not None}


def to_op(tool: str, args: dict) -> Any:
    """Translate a tool call into what the HTTP API expects.

    Three tools, so three cases. There used to be sixteen, one per op, and
    every one of them was a second spelling of a vocabulary `abt ops` already
    publishes -- which is how MCP came to teach one-op-per-call while the CLI
    and HTTP taught batching.
    """
    if tool == "command_list":
        return {
            "commands": args.get("commands") or [],
            "continue_on_error": bool(args.get("continue_on_error")),
        }

    if tool == "browser_session":
        payload = {"op": f"browser_{args['action']}"}
        for field in ("browser", "profile", "headless"):
            if args.get(field) is not None:
                payload[field] = args[field]
        return payload

    raise KeyError(tool)


class Bridge:
    """Forwards tool calls to the HTTP API."""

    def __init__(self, api: str = DEFAULT_API, timeout: float = 180.0) -> None:
        self.api = api.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def call(self, tool: str, args: dict) -> tuple[str, bool]:
        """Returns (text, is_error). Never raises -- an agent needs a message."""
        # Playbooks are reads, not ops: they live behind GET /guidelines, and
        # the server never serves an untrusted one. Routed here rather than in
        # to_op because to_op's whole output shape is "an op".
        if tool == "browser_guidelines":
            if args.get("name"):
                request = ("GET", f"/guidelines/{args['name']}", None)
            elif args.get("domain"):
                # /search, not /lookup: lookup is exact-domain only, and an
                # agent that has just landed somewhere has a hostname it is
                # guessing at. No match comes back as an empty list.
                request = ("GET", "/guidelines/search", {"q": args["domain"]})
            else:
                request = ("GET", "/guidelines", None)
        else:
            try:
                payload = to_op(tool, args)
            except KeyError:
                return f"no such tool: {tool}", True
            # One endpoint for everything, named for the plural. See
            # server.py: the two-endpoint shape taught callers to send one op
            # per round trip.
            endpoint = "/command-list"
            request = ("POST", endpoint, payload)

        method, path, body = request
        try:
            if method == "GET":
                response = self.client.get(f"{self.api}{path}", params=body)
            else:
                response = self.client.post(f"{self.api}{path}", json=body)
        except httpx.RequestError as exc:
            return (
                f"cannot reach the toolkit at {self.api} ({exc}). It is a separate, "
                "long-lived process that owns the browser -- start it with "
                "`abt up` and wait for GET /status to answer. Never run "
                "`abt serve` from a tool call: it is a command loop that never "
                "returns, and whatever launched it hangs.",
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
                "serverInfo": {"name": "aibrowsertoolkit", "version": _version()},
                # Where the orientation goes. Clients that honour it put this
                # in the system prompt once; the rest ignore it and lose
                # nothing, because every tool still describes itself.
                "instructions": INSTRUCTIONS,
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
