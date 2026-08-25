"""The CLI, MCP and HTTP must offer the same vocabulary.

The CLI once carried a subcommand per op, and it drifted: the ops accept
ref/css/xpath/text/index/near while `click` accepted two of them, `find`
wanted a positional where everything else wanted `--css`, and `input` wanted
a positional where `select` wanted `--value`. Each gap was a rejected call an
agent had guessed correctly. The workflow document's own opening example,
`abt find --text "Sign in"`, was a command the CLI refused.

So the CLI no longer spells the ops at all. Subcommands are lifecycle --
start the server, start the browser, read what was recorded -- and every page
action goes through `exec`/`exec-batch`, which take the op verbatim. There is
no translation left to drift, and batching stops being the road less
travelled: it is the same command with a list.

These tests hold that line.
"""

from __future__ import annotations

import typer.main as typer_main

from abt import cli, mcp
from abt.schema import OP_NAMES

# Subcommands that are allowed to exist. Anything else means an op has grown
# a bespoke spelling again.
LIFECYCLE = {
    "serve", "up", "shutdown", "browser", "autostart",   # run the thing
    "status", "doctor", "logs", "ops", "guidelines", "mcp",  # look at the thing
    "messenger",                                          # a site shortcut
    "exec", "exec-batch",                                 # every page action
}


def cli_commands() -> set[str]:
    return set(typer_main.get_command(cli.app).commands)


def test_the_cli_does_not_respell_the_ops():
    extra = cli_commands() - LIFECYCLE
    assert extra == set(), (
        f"subcommands that are not lifecycle: {sorted(extra)}. Page actions go "
        f"through `exec`/`exec-batch` so there is one spelling of each op, the "
        f"one `abt ops` prints. A subcommand is a second spelling that can "
        f"disagree with it -- which is how `abt click --text` came to be "
        f"rejected while the click op accepted `text`."
    )


def test_exec_is_present_to_carry_them():
    assert {"exec", "exec-batch"} <= cli_commands()


def test_help_teaches_batching():
    """The reason MCP callers batch and CLI callers did not: nobody said to."""
    assert "exec-batch" in cli._EPILOG_HEADER
    assert "ONE call" in cli._EPILOG_HEADER or "ONE round trip" in cli._EPILOG_HEADER


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
