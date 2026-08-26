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

from abt import mcp
from abt.mcp import TOOLS, Bridge, Server, to_op, serve


# --- translation --------------------------------------------------------------
#
# There were sixteen tools and a test per translation. Thirteen of them were
# one-per-op -- browser_click lowering to click, browser_read to get_text --
# which is a second spelling of a vocabulary `abt ops` already publishes, and
# it is the reason MCP kept teaching one-op-per-call after the CLI and HTTP
# had stopped. The tools are gone; so are their tests.


def test_command_list_becomes_a_commands_payload():
    payload = to_op("command_list", {"commands": [{"op": "reload"}]})
    assert payload == {"commands": [{"op": "reload"}], "continue_on_error": False}


def test_command_list_carries_a_whole_sequence_untouched():
    """Ops pass through verbatim -- there is no per-op translation left to
    disagree with the server."""
    ops = [
        {"op": "input", "css": "#email", "value": "me@example.com"},
        {"op": "input", "css": "#password", "value": "hunter2"},
        {"op": "click", "css": "#submit"},
    ]
    payload = to_op("command_list", {"commands": ops})
    assert payload["commands"] == ops


def test_continue_on_error_is_a_real_boolean_not_a_passthrough():
    assert to_op("command_list", {"commands": [{"op": "reload"}]})["continue_on_error"] is False
    assert to_op(
        "command_list", {"commands": [{"op": "reload"}], "continue_on_error": True}
    )["continue_on_error"] is True


def test_session_actions_are_the_only_other_translation():
    assert to_op("browser_session", {"action": "start"}) == {"op": "browser_start"}
    assert to_op("browser_session", {"action": "restart"}) == {"op": "browser_restart"}


def test_a_tool_that_no_longer_exists_raises_rather_than_guessing():
    """The per-op tools are gone. A client still calling one must be told,
    not quietly handed something adjacent."""
    with pytest.raises(KeyError):
        to_op("browser_click", {"ref": "el_1"})


# --- what the surface prevents -------------------------------------------------


def tool(name):
    return next(t for t in TOOLS if t["name"] == name)


@pytest.mark.parametrize("name", [t["name"] for t in TOOLS])
def test_every_tool_refuses_unknown_parameters(name):
    """`label`, `diff`, `filename`, `path` -- every observed failure was a
    parameter the op did not have. additionalProperties makes them invalid
    before the call is ever sent."""
    assert tool(name)["inputSchema"]["additionalProperties"] is False


def test_there_is_one_way_to_act_on_the_page():
    """Thirteen per-op tools were thirteen ways to send one op each, and a
    model that met browser_click first had no reason to look for the list."""
    names = {t["name"] for t in TOOLS}
    assert names == {"command_list", "browser_guidelines", "browser_session"}


def test_the_page_tools_are_gone_not_renamed():
    names = {t["name"] for t in TOOLS}
    for gone in (
        "browser_click", "browser_input", "browser_select", "browser_find",
        "browser_navigate", "browser_read", "browser_press", "browser_tabs",
        "browser_run_js", "browser_screenshot", "browser_diff",
        "browser_inspect", "browser_wait_for",
    ):
        assert gone not in names


def test_the_schemas_stay_small_because_they_are_re_sent_every_turn():
    """They were ~2,329 tokens a turn, charged whether used or not. That was
    the whole of MCP's measured overhead against raw HTTP."""
    import json

    assert len(json.dumps(TOOLS)) < 4000


def test_the_instructions_point_at_the_op_reference():
    """With no per-op schemas, this is where parameter names come from -- and
    a guessed name was the most common failed call in the wild."""
    assert "/ops" in mcp.INSTRUCTIONS


def test_the_instructions_show_a_batch_not_a_single_op():
    """The example is the lesson. Leading with one op per call is what the
    CLI documentation did, and agents copied it 64% of the time."""
    assert "command_list" in mcp.INSTRUCTIONS
    body = mcp.INSTRUCTIONS
    assert body.count('{"op"') >= 3, "the worked example should send several ops"


def test_the_one_command_says_it_takes_a_list():
    """The name teaches, and the description has to finish the lesson.

    `browser_batch` sat beside `browser_command`, so a model that found the
    singular first had no reason to look for the other and sent one op per
    call forever. One tool, named for the plural, cannot be read that way.
    """
    desc = tool("command_list")["description"]
    assert "LIST" in desc
    assert "one call" in desc.lower()


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
    text, failed = Bridge(api="http://127.0.0.1:9").call(
        "command_list", {"commands": [{"op": "goto", "url": "u"}]}
    )
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

    text, failed = _Stub().call("command_list", {"commands": [{"op": "reload"}]})
    assert failed is False
    assert "\n" not in text and ", " not in text
    assert text == '{"ok":true,"result":{"a":1,"b":2}}'


def test_run_js_advertises_script_not_code():
    """Both blind runs guessed run_js's parameter name -- `code`, then `js` --
    and a typed tool used to be what prevented it. There is no typed tool now,
    so the reference has to carry it: /ops publishes every op's real
    parameters, and that is where a caller is sent instead of guessing.
    """
    from abt.schema import op_signatures

    params = op_signatures()["run_js"]
    assert "script" in params
    assert "code" not in params and "js" not in params
    assert params["script"]["required"] is True


def test_screenshot_advertises_no_path_or_filename():
    """The first blind run guessed `path`, then `filename`, then gave up. The
    op takes neither -- it names the frame the server already wrote."""
    from abt.schema import op_signatures

    params = op_signatures()["screenshot"]
    assert "path" not in params and "filename" not in params


def test_the_one_command_points_at_the_op_reference():
    """There is no separate escape hatch now -- command_list is both.

    It carries raw ops, so it has to say where their exact parameters live:
    a caller guessing `js` for `script` is what /ops exists to prevent.
    """
    desc = tool("command_list")["description"]
    assert "/ops" in desc


def test_browser_session_tool_is_offered():
    from abt.mcp import TOOLS

    names = [tool["name"] for tool in TOOLS]
    assert "browser_session" in names


def test_browser_session_maps_each_action_to_its_op():
    from abt.mcp import to_op

    assert to_op("browser_session", {"action": "status"})["op"] == "browser_status"
    assert to_op("browser_session", {"action": "stop"})["op"] == "browser_stop"
    assert to_op("browser_session", {"action": "restart"})["op"] == "browser_restart"


def test_browser_session_passes_launch_overrides_through():
    from abt.mcp import to_op

    payload = to_op(
        "browser_session", {"action": "start", "browser": "edge", "headless": True}
    )
    assert payload == {"op": "browser_start", "browser": "edge", "headless": True}


def test_browser_session_omits_absent_overrides():
    from abt.mcp import to_op

    assert to_op("browser_session", {"action": "start"}) == {"op": "browser_start"}
