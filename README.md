# AI Browser Toolkit

**Give your coding agent a real browser.** `abt` is a JSON-over-HTTP server
that owns one long-lived Chrome or Edge window and hands an agent back what
changed after every action — not a page to re-read, a diff to act on.

## The goal

An agent driving a browser through raw WebDriver calls spends most of its
turns re-establishing where it is: re-reading the whole page after every
click, guessing at selectors, falling back to hand-written JavaScript when a
selector fails to say why. `abt` exists to make browsing something an agent
does with the same confidence it edits a file — one action, one honest report
of the consequence, on a browser that keeps its logins between sessions
instead of starting cold every time.

Built for agent harnesses — **Claude Code, Codex, OpenCode, Cursor, Gemini
CLI, Copilot**, or anything you write yourself — over **CLI**, **MCP**, or
plain **HTTP**. Same browser behind all three.

## Architecture

### One browser, kept alive

`abt serve` owns exactly one browser on a persistent profile — the opposite of
a headless scraper's throwaway one. Log into Gmail, a CRM, a ticket system
once, by hand; every agent session after that is already signed in, and the
window outlives your editor.

```
abt up  ──starts──>  server :8765  ──owns──>  Chrome/Edge (your profile)
                          ^
   abt CLI  /  abt mcp  /  your HTTP client
```

### Diff, not re-read

Every interactive command snapshots the page before and after and reports
what changed, instead of leaving the caller to go find out. A click that adds
three lines of text returns exactly those three lines — not the whole
document, and not a second round trip to fetch it. Navigation is settled
first (no request in flight, a DOM that has stopped changing) so the diff
reports the destination rather than its loading spinner. This is the whole
feedback loop: read the diff, act on it, and reach for a fresh read only when
the diff itself says it hasn't looked somewhere — a frame it entered, a
shadow root it counted but didn't walk.

### Structure, not a wall of text

Page text used to arrive as a flat list of strings — every word on the page,
with no way to tell which cells belonged to one table row. That is what sent
agents to hand-written JavaScript to reconstruct a table they had already been
handed. Every string now carries its position in the page, so two strings
sharing a prefix are visibly in the same container — and the position doubles
as an address: ask for one part of the page again by it, instead of
re-reading all of it. A navigation is diffed against the page it came from, so
the chrome already read once — nav, header, footer — is summarised rather
than repeated on every page.

### Refs, not selectors typed twice

`find` hands back a stable `ref` for each match, good until the tab navigates
or the element leaves the DOM. Act on it directly instead of writing a second
selector for what the first one already found. A dead ref fails loudly
(`stale_ref`) rather than silently retargeting whatever now sits in that spot.

### Nothing invisible on purpose

Frames and, on request, shadow roots are read straight through — the same
`find`, `get_text`, and diff that cover the main document cover an embedded
sign-in widget or a web component too, because the alternative is a confident
answer with the page's actual control quietly missing from it. A frame or
shadow root that exists but wasn't looked at is reported as a count, never as
silence, so an agent can tell "nothing is there" from "I didn't look".

## Three ways in

| | Use it when |
|---|---|
| **CLI** — `abt command-list` | The agent already has a shell. Nothing to configure. |
| **MCP** — `abt mcp` over stdio | Your client speaks MCP. Typed schemas, no shell quoting. |
| **HTTP** — `POST /command-list` on :8765 | You are writing the integration yourself. |

## Install and run

```bash
pip install ai-browser-toolkit
abt doctor          # what browsers are installed, and where
./start-server.sh   # start-server.bat on Windows -- the safe way to bring it up
```

`abt serve` is a command loop that never returns on its own; running it inline
from an agent or script hangs forever. `abt up` and the start scripts exist so
nothing has to know that — they background it correctly and return once it
answers.

Full install options (winget, Scoop, Homebrew, AUR, a source checkout,
autostart at login) and the complete API — every op, every endpoint, the CLI,
MCP, and the mechanics behind the diff and the text track — are in
**[docs/reference.md](docs/reference.md)**.

> **Agents: read the workflow before driving anything** — `abt guidelines
> show toolkit-workflow`, or
> [`guidelines/toolkit-workflow.md`](guidelines/toolkit-workflow.md). Not "if
> the site looks tricky" — always. That file, not this one, is what teaches an
> agent to use the toolkit well.

## Benchmark

Four MiniWoB++ tasks, driven end to end by **Claude Haiku 4.5** through the
`abt` CLI, told nothing but the task and the port: **46 ops, 174,167 tokens,
0.90 average reward** — MiniWoB's own scoring, read off the page, not the
agent's account of itself. Full table, honest caveats about what these numbers
do and don't mean, and the sweep runner for all 125 tasks: see
[docs/reference.md](docs/reference.md#benchmark).

### WebArena

475 tasks across shopping, the Magento admin back office, and reddit
(Postmill), driven by **z-ai/glm-5.3-flash** through `abt`, one fresh agent
process per task, 30-turn ceiling.

| | tasks | passed, as the harness scored it | final (+ fuzzy judging) | did the task (correctness) |
|---|---|---|---|---|
| shopping | 187 | 98 — 52.4% | 109 — 58.3% | 124 — 66.3% |
| admin | 182 | 95 — 52.2% | 108 — 59.3% | 118 — 64.8% |
| reddit | 106 | 87 — 82.1% | 89 — 84.0% | 95 — 89.6% |
| **combined** | **475** | **280 — 58.9%** | **306 — 64.4%** | **337 — 70.9%** |

| | turns | ops | tokens (cached) | wall time |
|---|---|---|---|---|
| shopping | 1,601 | 2,088 | 34,636,273 (26,290,560, 76%) | 11.1 h |
| admin | 2,564 | 3,736 | 72,962,196 (57,100,928, 78%) | 21.1 h |
| reddit | 1,183 | 1,582 | 27,444,731 (19,492,544, 71%) | 10.3 h |
| **combined** | **5,348** | **7,406** | **135,043,200 (102,884,032, 76%)** | **42.5 h** |
| mean per task | 11 | 16 | 284,302 | 322 s |

"Did the task" is a second, separate measure kept apart from the score: an
episode counts correct there when everything the evaluator required actually
appears in what the agent produced, even when the harness's exact string, URL,
or subreddit case didn't match it. Full per-task tables, what each task's
evaluator actually checks, and why each failure happened:
[shopping](benchmarks/browsergym/results/shopping/REPORT.md),
[admin](benchmarks/browsergym/results/admin/REPORT.md),
[reddit](benchmarks/browsergym/results/reddit/REPORT.md).

## Tests

```bash
.venv/Scripts/python -m pytest
```

669 tests drive a real headless Chrome against static fixture pages — no
network, deterministic, about seven minutes. The same suite also runs against
Playwright (`--engine selenium` switches it the other way); both pass. Detail
in [docs/reference.md](docs/reference.md#tests).

## Licence

[Apache License 2.0](LICENSE) — © the Ai-Browser-Toolkit contributors.

You may use, modify, and redistribute this code, including commercially. In
return the licence asks for three things, and they are not optional:

1. **Credit the project.** Mention this repository in your own README, or cite
   it, with a link to <https://github.com/skssmd/Ai-Browser-Toolkit>.
2. **Ship the licence.** Keep `LICENSE` and the copyright and attribution
   notices with any copy or derivative work.
3. **Say what you changed.** Mark modified files as modified.

Taking the code without the credit is not "borrowing" — it is using it outside
the terms that made it available to you.
