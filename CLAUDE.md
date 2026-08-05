# Instructions for agents

The instructions for this repository live in **[AGENTS.md](AGENTS.md)** — read
that file. The full workflow is
[`guidelines/toolkit-workflow.md`](guidelines/toolkit-workflow.md).

The one rule worth repeating here, because getting it wrong wedges your session:

**Never run `abt serve` from a tool call.** It is a command loop that never
returns, so the call that launched it hangs forever. Start the server with
`start-server.bat` (Windows cmd) or `./start-server.sh` (bash) in this
directory. Both are safe to run at any time — they no-op if a server is already
up, install dependencies only when missing, launch it detached, and exit once
`/status` answers. `--status` alone reports whether one is running.
