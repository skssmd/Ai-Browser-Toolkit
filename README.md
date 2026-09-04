```
 █████╗ ██████╗ ████████╗
██╔══██╗██╔══██╗╚══██╔══╝
███████║██████╔╝   ██║
██╔══██║██╔══██╗   ██║
██║  ██║██████╔╝   ██║
╚═╝  ╚═╝╚═════╝    ╚═╝
```

# AI Browser Toolkit (ABT)

A local HTTP server that gives an LLM agent a real browser — driven by
descriptions, not screenshots or snapshot indices.

One persistent browser profile per server instance. Send it JSON ops —
`goto`, `find`, `click`, `input`, `run_js` — one at a time or twenty at once.
Every op that changes the page returns a diff of what changed, so the agent
never re-reads state it already has.

Built for agent harnesses — **Claude Code, Codex, OpenCode, Cursor, Gemini
CLI, Copilot**, or anything you write yourself — over **CLI**, **MCP**, or
plain **HTTP**. Same browser behind all three.

---

## The problem

An agent driving a browser spends most of its budget on one thing: figuring
out what the page looks like now.

The usual loop is act → observe → interpret → decide → act. The observe step
re-sends page state on every turn, whether anything changed or not. The
interpret step often needs a second model pass to reduce that state into
something the planner can use. And because each action is addressed against
whatever snapshot the agent last read, the agent can only ever commit to
**one action at a time** — the moment the page re-renders, its references are
meaningless and it has to look again before it can move.

That last constraint is the expensive one. It means a task with twenty
near-identical steps costs twenty full observe-interpret-decide cycles, even
after the agent has completely understood the pattern on step one.

ABT is built to remove that constraint.

---

## What ABT does differently

### Late-bound addressing

Ops carry a *description* of their target, not a handle to it:

```json
[
  { "op": "click",  "text": "Edit", "near": "SKU-4471" },
  { "op": "input",  "label": "Price", "value": "249.00" },
  { "op": "select", "label": "Status", "choose": "Active" },
  { "op": "click",  "text": "Save" }
]
```

Each target is resolved server-side at the moment that op runs — against the
page as it exists then, not as it existed when the agent wrote the list. A
re-render between op 2 and op 3 is expected, not a hazard.

This is the root capability. Everything below follows from it.

### Batched sequential ops

Because targets resolve late, an agent can plan a whole sequence up front.
Find the pattern once, emit the list, get one response back.

The planning cost is paid **once by the model**. The resolution cost is paid
**twenty times by the server** — and server-side resolution is not a model
call. On bulk operations this is the difference between a handful of turns
and several dozen.

### Diffs that carry actionables

Every interactive and navigation op returns what changed: text that
appeared, text that disappeared, and the interactive elements now available.

Tracking *disappearance* matters as much as appearance. A modal closing, a
spinner clearing, an item leaving a cart — these are how an agent confirms an
action actually landed. ABT reports them mechanically, in the response
payload. No second pass, no summarizer, no inference.

Quiet turns cost close to nothing, because nothing changed and so nothing is
sent.

### Survey before you pay

`find` returns element shells — structure without content. `find_full`
returns the content. An agent can map a page's shape cheaply, then pay for
detail only where it decided to look.

### Halt with a ledger

When an op in a batch fails, execution stops there and the response carries
three things:

- which ops completed
- which op failed, and which error type (`element_not_found`,
  `not_interactable`, `stale_ref`, …)
- which ops were never attempted

Plus the diff of the page at the point of failure. The agent knows exactly
where it is in its own plan and what the page looks like — enough to patch
the failing op and resubmit from that index. No replaying completed writes.

Batches can also be set to continue past failures, which is the right mode
for reads and for genuinely optional steps.

Errors are a closed set, not free text. An agent consuming this API can
branch on failure instead of parsing prose.

### Guidelines that carry forward

When asked, an agent can write down what it learned about a site: which
selectors held, which flows broke, what the retry looked like. Guidelines
are dated.

The next agent reads the date and decides how much to trust it. Recent —
commit directly. Old — verify the structure cheaply, then commit. Stale —
re-explore, but from a map rather than from nothing, because a site redesign
rarely moves everything. The nav holds, the flow order holds, one selector
moved.

These are written by something that actually failed at the task and then
succeeded, which makes them different from human-authored instructions: they
record what actually mattered, not what someone guessed would.

Guidelines can be rewritten and updated as sites change. Each revision adds
signal about which parts of a site churn and which are stable.

---

## Architecture

```
┌───────────────────────────────────────────────┐
│  Agent                                        │
│  any model, any framework                     │
└───────────────────────┬───────────────────────┘
                        │  JSON over HTTP
                        │  single op or batch
┌───────────────────────▼───────────────────────┐
│  Op executor                                  │
│  runs the whole op list sequentially in one   │
│  call, resolving each target at execution     │
│  time — one agent turn, many actions          │
└───────────────────────┬───────────────────────┘
                        │
┌───────────────────────▼───────────────────────┐
│  Playwright                                   │
│  persistent browser profile                   │
└───────────────────────┬───────────────────────┘
                        │  raw page state
┌───────────────────────▼───────────────────────┐
│  Data curation layer                          │
│                                               │
│    Level tree     structural view of the      │
│                   page, addressable by depth  │
│    Diff engine    appeared / disappeared /    │
│                   actionables                 │
└───────────────────────┬───────────────────────┘
                        │
┌───────────────────────▼───────────────────────┐
│  Session log                                  │
│  JSONL, written as it runs, crash-safe        │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
              response to the agent
        diff + ledger + error type, if any
```

**Diff engine.** Every interactive command snapshots the page before and
after and reports only what changed — text that appeared, text that
disappeared, the interactive elements now available. Navigation is settled
first, so the diff reports the destination, not its loading spinner.

**Level tree.** Page text carries its position in the page, so a table comes
back with its row and column boundaries intact instead of as a flat list of
strings with no structure. The position doubles as an address: re-read one
part of the page by it, instead of re-reading all of it. A navigation is
diffed against the page it came from, so the chrome already read once — nav,
header, footer — is summarised rather than repeated on every page.

The agent never touches raw page state. Everything the browser produces
passes through curation before it reaches the model — the level tree gives
it structure, the diff engine gives it change. What comes back is only what
the agent did not already know.

The turn saving lives in the executor. A batch of twenty ops is one request,
one loop through the browser, one response — not twenty round trips through
the model. The agent spends a turn on the plan; the executor spends none on
carrying it out.

Stateless from the agent's side. There is no snapshot the agent must hold
and re-sync; there is no index space that expires. The agent describes
intent, the server resolves it against reality.

A log viewer ships with the server.

Purpose-built endpoints sit on top of the generic ops for specific targets
where the generic path would be needlessly indirect.

---

## Where it stands

**Efficiency.** The unit of work is a batch, not an action. Once a pattern
is known, the model plans once and the server executes the rest. Approaches
that ground actions to a snapshot cannot express a multi-target sequence at
all — their references die on the first re-render — so they pay a full
model turn per action regardless of how well they understand the task.

**Automatability.** Late-bound addressing is what makes real automation
possible rather than supervised stepping. A twenty-product update is one
plan. Failure is recoverable at op granularity instead of task granularity,
so a partial run is a resumable run.

**Context.** Diffs mean the agent's context accumulates changes, not
repeated snapshots of an unchanged page. `find` vs `find_full` keeps
surveying cheap. Guidelines move knowledge *out* of the context window
entirely and onto disk, where it survives the session and the agent.

**Cost.** Three mechanisms, three different axes:

| | what it cuts |
|---|---|
| Diffing | cost within a turn |
| Batching | turns within a task |
| Guidelines | exploration across tasks |

They compound. A first run on an unfamiliar site pays for exploration and
benefits mainly from diffing and mid-task batching. A repeat run reads a
guideline, skips discovery, and executes in a few turns. Cost per task
**declines with use** rather than staying flat — and each re-discovery after
a site change leaves the next run better informed than the last.

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

| | turns/episode | turns | ops | tokens/episode (cached) | tokens (cached) | wall time |
|---|---|---|---|---|---|---|
| shopping | 9 | 1,601 | 2,088 | 185,222 (140,591, 76%) | 34,636,273 (26,290,560, 76%) | 11.1 h |
| admin | 14 | 2,564 | 3,736 | 400,891 (313,741, 78%) | 72,962,196 (57,100,928, 78%) | 21.1 h |
| reddit | 11 | 1,183 | 1,582 | 258,913 (183,892, 71%) | 27,444,731 (19,492,544, 71%) | 10.3 h |
| **combined** | **11** | **5,348** | **7,406** | **284,302 (216,598, 76%)** | **135,043,200 (102,884,032, 76%)** | **42.5 h** |

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
