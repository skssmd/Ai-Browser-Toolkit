"""The CLI, MCP and HTTP must offer the same vocabulary.

They drifted, and the drift was invisible until an agent hit it. The ops
accept ref/css/xpath/text/index/near; the CLI accepted ref and css, so
`abt click --text Prev` was rejected -- while the workflow document's own
opening example, `abt find --text "Sign in"`, was a command the CLI refused.
Twenty-four of thirty-two ops had no subcommand at all, including `get_text`,
which the same document tells the reader to reach for first.

None of that is visible by reading one file. These tests make the three
surfaces answer for each other.
"""

from __future__ import annotations

import typer.main as typer_main

from abt import cli, mcp
from abt.schema import OP_NAMES

# Ops reached through a grouped subcommand rather than one of their own:
# `abt browser start`, `abt tabs new`. Listed rather than inferred, so adding
# an op cannot quietly join them.
GROUPED = {
    "browser_start": "browser start",
    "browser_stop": "browser stop",
    "browser_restart": "browser restart",
    "browser_status": "browser status",
    "tab_new": "tabs new",
    "tab_switch": "tabs switch",
    "tab_close": "tabs close",
    "tab_list": "tabs list",
}

# Where the subcommand's name is not the op's name.
ALIASES = {
    "get_text": "get-text",
    "get_html": "get-html",
    "run_js": "run-js",
    "wait_for": "wait-for",
    "current_url": "current-url",
    "read_console": "console",
    "read_network": "network",
    "find_full": "find",  # `find --full`
}


def cli_commands() -> set[str]:
    return set(typer_main.get_command(cli.app).commands)


def test_every_op_has_a_named_cli_command():
    commands = cli_commands()
    missing = [
        op
        for op in OP_NAMES
        if op not in GROUPED
        and ALIASES.get(op, op) not in commands
        # `shutdown` and `diff` and `status` are their own commands already.
    ]
    assert missing == [], (
        f"ops with no `abt` subcommand: {missing}. `abt exec` reaching them is "
        f"not enough -- the documentation names ops, and a reader following it "
        f"gets 'No such command'."
    )


def test_target_flags_match_the_ops_targeting():
    """Every command that targets an element offers the ops' full vocabulary."""
    group = typer_main.get_command(cli.app)
    expected = {"--ref", "--css", "--xpath", "--text"}
    for name in ("click", "input", "get-text", "get-html", "press", "hover"):
        command = group.commands[name]
        flags = {opt for param in command.params for opt in param.opts}
        assert expected <= flags, f"`abt {name}` is missing {expected - flags}"


def test_mcp_tools_lower_to_real_ops():
    """Every MCP tool must translate into an op the server actually has."""
    for tool in mcp.TOOLS:
        name = tool["name"]
        if name in {"browser_batch", "browser_command", "browser_guidelines"}:
            continue  # passthroughs, not a single op
        # Per tool: `action` means different things to different tools, and a
        # shared value makes browser_navigate lower "start" as a navigation.
        actions = {"browser_session": "start", "browser_tabs": "list"}
        args = {"url": "x", "what": "console", "key": "a",
                "value": "v", "script": "s", "css": "#x"}
        if name in actions:
            args["action"] = actions[name]
        payload = mcp.to_op(name, args)
        assert payload["op"] in OP_NAMES, f"{name} lowers to unknown op {payload['op']}"


def test_mcp_exposes_the_targeting_vocabulary():
    for tool in mcp.TOOLS:
        properties = tool["inputSchema"]["properties"]
        if "ref" not in properties:
            continue
        assert {"css", "xpath", "text"} <= set(properties), (
            f"MCP tool {tool['name']} takes a ref but not the other selectors"
        )
