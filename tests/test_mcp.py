"""The MCP shim: typed tools in, toolkit ops out.

The point of the shim is that a malformed command becomes unrepresentable. The
errors it exists to prevent were all parameter guesses -- `label` on a select,
`diff` on a get_text, a `run_js` script sent as an object instead of a string --
so the tests that matter are the ones about translation and about what the
schemas do and do not permit.

No browser here: the shim never touches one, it only forwards.
"""

from __future__ import annotations

import io
import json

import pytest

from abt.mcp import TOOLS, Bridge, Server, to_op, serve


# --- translation --------------------------------------------------------------


def test_navigate_translates_to_goto():
    assert to_op("browser_navigate", {"url": "https://example.com"}) == {
        "op": "goto",
        "url": "https://example.com",
    }


def test_navigate_history_actions():
    assert to_op("browser_navigate", {"action": "back"}) == {"op": "back"}
    assert to_op("browser_navigate", {"action": "reload"}) == {"op": "reload"}


def test_find_defaults_to_shells_and_opts_into_full():
    assert to_op("browser_find", {"css": ".card"})["op"] == "find"
    assert to_op("browser_find", {"css": ".card", "full": True})["op"] == "find_full"


def test_click_carries_only_the_target_that_was_given():
    op = to_op("browser_click", {"ref": "el_7"})
    assert op == {"op": "click", "ref": "el_7"}
    assert "css" not in op and "text" not in op


def test_read_switches_between_text_and_html():
    assert to_op("browser_read", {"css": "h1"})["op"] == "get_text"
    assert to_op("browser_read", {"css": "h1", "html": True})["op"] == "get_html"


def test_inspect_routes_console_and_network():
    assert to_op("browser_inspect", {"what": "console"})["op"] == "read_console"
    net = to_op("browser_inspect", {"what": "network", "failures_only": True})
    assert net == {"op": "read_network", "failures_only": True}


def test_tabs_actions_map_to_their_ops():
    assert to_op("browser_tabs", {"action": "list"})["op"] == "tab_list"
    assert to_op("browser_tabs", {"action": "new", "url": "u"}) == {"op": "tab_new", "url": "u"}
    assert to_op("browser_tabs", {"action": "close", "tab_id": "tab_1"})["op"] == "tab_close"


def test_batch_becomes_a_commands_payload():
    payload = to_op("browser_batch", {"commands": [{"op": "reload"}]})
    assert payload == {"commands": [{"op": "reload"}], "continue_on_error": False}


def test_absent_options_are_omitted_not_sent_as_null():
    """A null would be rejected by the server's schema as surely as a typo."""
    op = to_op("browser_input", {"css": "#a", "value": "x"})
    assert op == {"op": "input", "css": "#a", "value": "x"}


# --- what the schemas prevent --------------------------------------------------


def tool(name):
    return next(t for t in TOOLS if t["name"] == name)


@pytest.mark.parametrize("name", [t["name"] for t in TOOLS])
def test_every_tool_refuses_unknown_parameters(name):
    """`label`, `diff`, `filename`, `path` -- every observed failure was a
    parameter the op did not have. additionalProperties makes them invalid
    before the call is ever sent."""
    assert tool(name)["inputSchema"]["additionalProperties"] is False


def test_select_has_no_label_parameter():
    """The exact guess that failed in the wild."""
    assert "label" not in tool("browser_select")["inputSchema"]["properties"]


def test_read_has_no_diff_parameter():
    """The other exact guess."""
    assert "diff" not in tool("browser_read")["inputSchema"]["properties"]


def test_targeting_options_are_advertised_together():
    for name in ("browser_click", "browser_input", "browser_select"):
        props = tool(name)["inputSchema"]["properties"]
        assert {"ref", "css", "xpath", "text"} <= set(props)
        assert "exactly ONE" in tool(name)["description"]


def test_batch_is_described_as_preferred():
    """It is the toolkit's real latency advantage; the model has to know."""
    assert "ONE call" in tool("browser_batch")["description"]


# --- protocol ------------------------------------------------------------------


class FakeBridge:
    def __init__(self, text="{}", failed=False):
        self.text, self.failed, self.calls = text, failed, []

    def call(self, name, args):
        self.calls.append((name, args))
        return self.text, self.failed


def test_initialize_reports_tool_capability():
    reply = Server(FakeBridge()).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert reply["result"]["capabilities"] == {"tools": {}}
    assert reply["result"]["serverInfo"]["name"] == "aibrowsertoolkit"


def test_tools_list_returns_every_tool():
    reply = Server(FakeBridge()).handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(reply["result"]["tools"]) == len(TOOLS)


def test_tools_call_forwards_and_wraps():
    bridge = FakeBridge(text='{"ok": true}')
    reply = Server(bridge).handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "browser_navigate", "arguments": {"url": "u"}},
    })
    assert bridge.calls == [("browser_navigate", {"url": "u"})]
    assert reply["result"]["content"][0]["text"] == '{"ok": true}'
    assert reply["result"]["isError"] is False


def test_a_failed_op_is_reported_as_an_error_not_a_success():
    bridge = FakeBridge(text='{"ok": false}', failed=True)
    reply = Server(bridge).handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "browser_click", "arguments": {"css": "#x"}},
    })
    assert reply["result"]["isError"] is True


def test_notifications_are_never_answered():
    """A reply to a notification is a protocol violation."""
    assert Server(FakeBridge()).handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_returns_a_json_rpc_error():
    reply = Server(FakeBridge()).handle({"jsonrpc": "2.0", "id": 5, "method": "nope"})
    assert reply["error"]["code"] == -32601


def test_unknown_tool_is_an_error_message_not_a_crash():
    text, failed = Bridge().call("browser_teleport", {})
    assert failed is True
    assert "no such tool" in text


def test_a_server_that_is_not_running_says_how_to_start_it():
    text, failed = Bridge(api="http://127.0.0.1:9").call("browser_navigate", {"url": "u"})
    assert failed is True
    assert "abt serve" in text


# --- the stdio loop ------------------------------------------------------------


def test_serve_reads_and_writes_newline_delimited_json():
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    stdout = io.StringIO()
    serve(api="http://127.0.0.1:9", stdin=stdin, stdout=stdout)

    replies = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert [r["id"] for r in replies] == [1, 2], "the notification must not be answered"


def test_serve_survives_a_malformed_line():
    stdin = io.StringIO(
        "not json\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
    )
    stdout = io.StringIO()
    serve(api="http://127.0.0.1:9", stdin=stdin, stdout=stdout)
    assert json.loads(stdout.getvalue().strip())["id"] == 1


def test_responses_are_compact_not_pretty_printed():
    """Whitespace is tokens. Measured at ~1.6x inflation from indent=2, paid on
    every response the model reads back."""
    import httpx

    class _Stub(Bridge):
        def __init__(self):
            self.api = "http://stub"
            self.client = httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"ok": True, "result": {"a": 1, "b": 2}})
                )
            )

    text, failed = _Stub().call("browser_navigate", {"url": "u"})
    assert failed is False
    assert "\n" not in text and ", " not in text
    assert text == '{"ok":true,"result":{"a":1,"b":2}}'


def test_run_js_is_a_typed_tool_not_only_an_escape_hatch():
    """Both blind runs reached run_js through browser_command and guessed its
    parameter name -- `code` instead of `script`. A typed tool cannot."""
    assert to_op("browser_run_js", {"script": "return 1;"}) == {"op": "run_js", "script": "return 1;"}
    props = tool("browser_run_js")["inputSchema"]["properties"]
    assert "script" in props and "code" not in props
    assert tool("browser_run_js")["inputSchema"]["required"] == ["script"]


def test_screenshot_is_typed_and_takes_no_path():
    """The first blind run guessed `path`, then `filename`, then gave up."""
    assert to_op("browser_screenshot", {"css": "#chart"}) == {"op": "screenshot", "css": "#chart"}
    props = tool("browser_screenshot")["inputSchema"]["properties"]
    assert "path" not in props and "filename" not in props


def test_the_escape_hatch_warns_that_it_does_not_validate():
    desc = tool("browser_command")["description"]
    assert "WITHOUT" in desc and "GET /ops" in desc
