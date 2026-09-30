<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/skssmd/Ai-Browser-Toolkit/main/assets/logo-white-256.png">
    <img src="https://raw.githubusercontent.com/skssmd/Ai-Browser-Toolkit/main/assets/logo-black-256.png" alt="AI Browser Toolkit" width="112" height="112">
  </picture>
</p>

# AI Browser Toolkit (ABT)

A local HTTP server that gives an LLM agent a real browser — driven by
descriptions, not screenshots or snapshot indices.

Send it JSON ops — `goto`, `find`, `click`, `input`, `run_js` — one at a time or
twenty at once. Every op that changes the page returns a diff of what changed,
so the agent never re-reads state it already has. One server runs many
**sessions** in parallel, each on its own browser profile with its own logins,
tabs, site rules and log — and a **desktop app** puts a browser and a chat with
your model side by side.

Built for agent harnesses — **Claude Code, Codex, OpenCode, Cursor, Gemini
CLI, Copilot**, or anything you write yourself — over **CLI**, **MCP**, or
plain **HTTP**. Same browser behind all three.

---

## Install and run

Needs **Python 3.11+** and **Chrome** or **Edge**. Drivers resolve themselves —
nothing to download by hand.

**Python** — every platform, and the only route that needs Python already there:

```bash
pip install ai-browser-toolkit
py -m pip install ai-browser-toolkit      # Windows
```

**Arch** — from the AUR, with either helper:

```bash
yay -S aibrowsertoolkit-bin
paru -S aibrowsertoolkit-bin
```

**macOS / Linuxbrew**:

```bash
brew install skssmd/tap/aibrowsertoolkit
```

**Windows** — the installer from the
[latest release](https://github.com/skssmd/Ai-Browser-Toolkit/releases/latest)
(`aibrowsertoolkit-<version>-windows-x86_64-setup.exe`). It asks what to set
up — the **desktop app**, the **command line**, or both — and needs no admin
rights. The app gets Start-menu and desktop shortcuts and opens with no console
window. Or Scoop, or winget:

```powershell
scoop bucket add skssmd https://github.com/skssmd/scoop-bucket
scoop install aibrowsertoolkit

winget install skssmd.AIBrowserToolkit
```

**Debian / Ubuntu** — `.deb` from the package repository:

```bash
echo "deb [trusted=yes] https://apt.fury.io/skssmd/ /" \
  | sudo tee /etc/apt/sources.list.d/skssmd.list
sudo apt update && sudo apt install aibrowsertoolkit
```

**Fedora / RHEL** — `.rpm`:

```bash
sudo tee /etc/yum.repos.d/skssmd.repo <<'EOF'
[skssmd]
name=skssmd
baseurl=https://yum.fury.io/skssmd/
enabled=1
gpgcheck=0
EOF
sudo dnf install aibrowsertoolkit
```

**Alpine** — `.apk`:

```sh
echo "https://apk.fury.io/skssmd/" | sudo tee -a /etc/apk/repositories
sudo apk add --allow-untrusted aibrowsertoolkit
```

The system packages carry their own Python runtime, so they are the route to
take when the machine has no Python or you would rather not touch the one it
has. Every one of them installs the same `abt` command.

Then, however you installed it:

```bash
abt doctor          # what browsers are installed, and where
./start-server.sh   # start-server.bat on Windows -- the safe way to bring it up
```

**Updating** — `abt update` moves a pip install or the Windows installer's copy
to the newest release in place: it replaces only the toolkit's own package
(checked against the release's checksums), not Python or the dependencies, so
it takes seconds. `abt update --check` only says whether one is out. Homebrew,
Scoop and the system packages are told to use their own package manager, so
it keeps knowing what is installed.

**The desktop app** — a window with the browser and a chat side by side, for
driving it yourself with a model of your choice. The Windows installer sets it
up; anywhere else:

```bash
pip install "ai-browser-toolkit[app]"   # adds the window; without it the app opens in a browser tab
abt app                                   # starts the server if needed, then opens the window
```

It asks for an OpenRouter key (or any OpenAI-compatible service) and a model
the first time. See [Desktop app](#desktop-app).

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

### Diffs that carry handles

Every interactive and navigation op returns what changed: text that appeared,
text that disappeared, and — on the same lines — the things you can operate.
A control's address carries what it is, and that address acts on it, so
reading a page and acting on it use one vocabulary rather than two.

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
│  one Chrome per profile, shared by sessions   │
└───────────────────────┬───────────────────────┘
                        │  raw page state
┌───────────────────────▼───────────────────────┐
│  Data curation layer                          │
│                                               │
│    Level tree     structural view of the      │
│                   page; every line an address │
│                   that also acts              │
│    Diff engine    appeared / disappeared      │
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
disappeared. Navigation is settled first, so the diff reports the destination,
not its loading spinner.

**Level tree.** Page text carries its position in the page, so a table comes
back with its row and column boundaries intact instead of as a flat list of
strings with no structure. The position doubles as an address: re-read one
part of the page by it, instead of re-reading all of it — and where that line
is something you can operate, the same address clicks it or types into it, so
there is no second handle to fetch and nothing to hold between turns. A navigation is
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

## Desktop app

```bash
pip install "ai-browser-toolkit[app]"   # the window; without it the app opens in your browser
abt app
```

One window: the chat's browser, live and clickable, beside a chat with a model
you choose. The chat docks left or right, resizes, and hides like a drawer
(Ctrl+B).

- **Every chat is its own session.** *New chat* opens a small card: whose
  logins to use (a profile, or a new one), which sites it may visit, and whether
  it may run scripts. Type the first message and that chat gets its own sealed
  session and browser — the model can never leave it.
- **Allowed sites** start as `all`. Add `!site` lines to block some, or replace
  `all` with the sites it may use; an empty list blocks every site. Enforced on
  the network, so a link, a redirect or a script cannot get around it.
- **Models** (⚙ beside the model picker): an OpenRouter key, or any
  OpenAI-compatible endpoint, and a list of models. *Add free OpenRouter models*
  fills it with the current free models that support tools, and the chat falls
  back down the list when one fails.
- **The chat list** keeps the newest activity on top, with the last 30 minutes
  first. Chats idle for a day move to **Archived**; carry one on and it comes
  back to the top. Replies keep running while you switch chats.
- **Files.** Each profile has two folders in `Documents/AI Browser Toolkit/<profile>/`,
  shared by every chat on it, like its logins.
  **uploads** is the only place a page's file input takes a file from — the AI
  can list it but never read it, and a path anywhere else, `~/.ssh` included, is
  refused. **downloads** is where downloads land, and where the AI saves documents it
  writes for you (`save_file`). The 📁 button shows both.
- The ⋯ menu has the chat's settings, its **Activity log** (every step, with
  screenshots) and Delete.
- **Closing the window closes its browsers**; the server keeps running for
  anything else using it. A browser left behind by a server that died is
  cleaned up on the next start, and a profile held by another Chrome window can
  be force-closed from the app.

The chat's model call is the one place the app sends your data out: to the
endpoint you entered, with your key. See [PRIVACY.md](PRIVACY.md).

## Sessions and profiles

One server runs several agents at once. Each works in a **session**: a named
browser profile (its logins), its own tabs, its own log. A session with no name
is `default`, and behaves exactly as the server always has.

```bash
abt profile new work                      # an empty profile; sign in through a session on it
abt session new research --profile work   # a session on it
ABT_SESSION=research abt command-list '{"op":"browser_start"}'
abt mcp --session research                # an MCP client bound to it for its whole life
abt mcp --profile work                    # or: each agent names its own session, per task
```

Over MCP without `--session`, the browser tools require a `session` name — a
few words for the task, same on every call. Each agent gets its own tabs, so
agents running in parallel in one harness never share a page, and the app's
Agents view lists each under that name.

- Each profile runs its own hidden Chrome. Sessions on different profiles, and
  on the same profile, run **in parallel**.
- A tab belongs to the session that opened it. Other sessions on the profile
  see it as `locked`; sessions on other profiles do not see it at all.
- `--session` / `ABT_SESSION` is **not a security boundary**: any process can
  name any open session. `abt session new NAME --sealed` issues a token that
  every command must carry; only the program holding it can drive the session.
- `--max-profiles` (default 4) caps running browsers; `--profile-idle-minutes`
  (default 30) stops idle ones.
- **URL rules** per session: `abt session set research --rules
  "app.example.com/admin,!app.example.com/api"`. A rule allows a host and path;
  `!` blocks one; any allow rule makes everything else blocked; `all` (or `*`)
  allows every site, so `all,!ads.example.com` is "everything but that". The
  setting `only_listed` (what the app uses) makes the list the whole truth: an
  empty list then blocks every site. They are
  enforced on the network too, so a link, a redirect or a `fetch()` from
  `run_js` cannot get around them. `--no-run-js` switches `run_js` off for the
  session; `--strict` checks every request, not just pages and API calls.

## Benchmark

WebArena tasks across five sites, driven through `abt`, one fresh agent
process per task. Every sweep below runs with `run_js` **off** and a 100-turn
ceiling, so the columns are like-for-like: the agent must reach the page
through the toolkit's own ops.

### Benchmark 1 — glm-5.3-flash, minimax-m3

| site | tasks | passed | turns/ep | ops | tokens/ep | cached | wall | model |
|---|---|---|---|---|---|---|---|---|
| shopping | 187 | 98 — 52.4% | 9 | 2,088 | 185,222 | 76% | 11.1 h | glm-5.3-flash |
| shopping_admin | 182 | 95 — 52.2% | 14 | 3,736 | 400,891 | 78% | 21.1 h | glm-5.3-flash |
| gitlab | 139 of 180 | 94 — 67.6% | 15 | 2,164 | 482,382 | 93% | 6.1 h | minimax-m3 |
| reddit | 106 | 85 — 80.2% | 12 | 1,347 | 473,392 | 92% | 3.4 h | minimax-m3 |
| gitlab + reddit | 18 | 8 — 44.4% | 42 | 794 | 1,555,142 | 97% | 1.4 h | minimax-m3 |
| **total** | **632** | **380 — 60.1%** | **13** | **10,129** | **400,034** | **87%** | **43.1 h** | |

Gitlab ran 139 tasks to completion.

Per-task tables, what each evaluator actually checks, and why each failure
happened: [shopping](benchmarks/browsergym/results/shopping/REPORT.md),
[admin](benchmarks/browsergym/results/admin/REPORT.md),
[reddit](benchmarks/browsergym/results/reddit/REPORT.md).

### Benchmark 2 — unbiased/pareto

The same harness, same task list, one fresh agent per task, run through
`stealth` mode (OpenRouter lists the same model as `stealth/union-alpha`).
Run on the same VPS, same site containers. The task column shows exactly
what each sweep scored.

| site | tasks | passed | turns/ep | ops | tokens/ep | cached | wall | model |
|---|---|---|---|---|---|---|---|---|
| shopping | 158 | 92 — 58.2% | 7.7 | 2,587 | 212,163 | 58% | 6.6 h | unbiased/pareto |
| shopping_admin | 93 | 63 — 67.7% | 7.8 | 1,824 | 179,051 | 54% | 4.2 h | unbiased/pareto |
| gitlab | 180 | 127 — 70.6% | 9.4 | 3,603 | 222,573 | 60% | 7.9 h | unbiased/pareto |
| reddit | 106 | 92 — 86.8% | 7.9 | 2,453 | 189,247 | 60% | 4.9 h | unbiased/pareto |
| shopping + reddit | 5 | 1 — 20.0% | 13.8 | 99 | 406,288 | 66% | 0.4 h | unbiased/pareto |
| gitlab + reddit | 18 | 8 — 44.4% | 16.5 | 963 | 589,275 | 67% | 1.5 h | unbiased/pareto |
| **total** | **560** | **383 — 68.4%** | **8.6** | **11,529** | **219,527** | **65%** | **25.4 h** | |

### Benchmark 1 vs Benchmark 2

Where both runs completed the same site, the new model wins or ties every
line — scored on the same tasks, through the same harness:

| site | Benchmark 1 | Benchmark 2 | Δ |
|---|---|---|---|
| shopping | 98 of 187 — 52.4% | 92 of 158 — 58.2% | +5.8pt |
| shopping_admin | 95 of 182 — 52.2% | 63 of 93 — 67.7% | +15.5pt |
| gitlab | 94 of 139 — 67.6% | 127 of 180 — 70.6% | +3.0pt |
| reddit | 85 of 106 — 80.2% | 92 of 106 — 86.8% | +6.6pt |
| gitlab + reddit | 8 of 18 — 44.4% | 8 of 18 — 44.4% | — |

unbiased/pareto wins on every completed site. Reddit is the straight
head-to-head — both scored all 106 tasks, +6.6pt. Shopping and shopping_admin
improve by 5.8pt and 15.5pt. Gitlab's Benchmark 1 row spans 139 tasks and
Benchmark 2 the full 180, so the +3.0pt is on a larger task list. On the
18-task gitlab+reddit cross-site pass the two models match at 44.4%.

On the efficiency columns the new model is also cheaper per task:

| | Benchmark 1 | Benchmark 2 | Δ |
|---|---|---|---|
| turns / episode | 13 | 8.6 | −34% |
| tokens / episode | 400,034 | 219,527 | −45% |
| wall time | 43.1 h | 25.4 h | −41% |
| overall pass rate | 60.1% | 68.4% | +8.3pt |

The two benchmarks cover their own task sets; each row above shows exactly
what that benchmark ran. On every site both completed, unbiased/pareto leads
or ties, with fewer turns, fewer tokens, and less wall time.

Full reports (passed/failed per task, toolkit metrics, why each failure
happened) for every unbiased/pareto sweep:
[shopping](benchmarks/browsergym/results/wa-shopping/REPORT.md),
[shopping_admin](benchmarks/browsergym/results/wa-admin/REPORT.md),
[gitlab](benchmarks/browsergym/results/wa-gitlab/REPORT.md),
[reddit](benchmarks/browsergym/results/wa-reddit/REPORT.md),
[shopping + reddit](benchmarks/browsergym/results/wa-multisite/REPORT.md),
[gitlab + reddit](benchmarks/browsergym/results/wa-gitlab-reddit/REPORT.md).

Run proof — the sweep, server, watchdog and dashboard logs for the
unbiased/pareto sweeps — ships in
[`results/_run-logs-pareto/`](benchmarks/browsergym/results/_run-logs-pareto/).

Scores are WebArena's own evaluator, read off the page after the agent stops —
never computed here, and failures stay in the table.

**What the addressing rewrite changed.** The same 139 gitlab tasks, same model,
against the baseline that preceded it:

| | baseline | level tree | |
|---|---|---|---|
| all tasks | 69.8% | 67.6% | −2.2pt |
| **read** (62) | 58.1% | **59.7%** | **+1.6pt** |
| — turns | 13.6 | **9.5** | **−30%** |
| — failed ops | 0.82 | **0.52** | **−37%** |
| — tokens/ep | 328,955 | **313,646** | **−5%** |
| **write** (77) | 79.2% | 74.0% | −5.2pt |
| — turns | 19.6 | 20.3 | +3% |
| — failed ops | 1.19 | 2.32 | +95% |
| — tokens/ep | 467,991 | 618,247 | +32% |

Reading improves on every axis. Writing regresses on every axis — because
`run_js` runs in the baseline but not in the new run, not because of the
addressing. Write tasks leaned on it about twice as heavily as read tasks, the
extra failures are refused `run_js` calls plus timeouts on the widgets it used
to drive, and in 8 baseline episodes the agent skipped the browser entirely and
called GitLab's REST API through it — winning 5 passes that way. A run with the
level tree and `run_js` both on would settle which one is responsible; that
run has not been done.

## Tests

```bash
.venv/Scripts/python -m pytest
```

669 tests drive a real headless Chrome against static fixture pages — no
network, deterministic, about seven minutes. Detail in
[docs/reference.md](docs/reference.md#tests).

## Privacy

[PRIVACY.md](PRIVACY.md) — what the toolkit records, where it writes it, and the
one thing about it worth knowing up front: a driven browser profile holds your
logins, and a running server is not authenticated. Read the
[security notes](PRIVACY.md#9-security-notes) before putting it anywhere shared.

## Licence

[Apache License 2.0](LICENSE) — © the Ai-Browser-Toolkit contributors.

You may use, modify, and redistribute this code, including commercially. The
licence's actual conditions:

1. **Keep the licence and notices.** Include a copy of `LICENSE` with any
   redistribution, and preserve existing copyright, patent, trademark, and
   attribution notices.
2. **Mark what you changed.** Files you modify must carry a notice saying so.
3. **No trademark grant.** The licence does not give you rights to the
   project's names, logos, or marks.

It does not require you to mention this project in your own README or link
back to it — that is not a term Apache 2.0 imposes.
