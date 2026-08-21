# BrowserGym benchmark adapter for ai-browser-toolkit

`ai-browser-toolkit` executes every page interaction; BrowserGym owns the
browser, the observations, and the scoring. The score is therefore not ours
to grade: each episode ends with BrowserGym's own `task.validate()` deciding
pass/fail against the browser both parties share.

## Architecture

One Chromium instance, two clients:

```
        Chromium  (launched by BrowserGym, CDP port 9222)
          |  observations + scoring        |  actions
   +------v----------+              +------v---------+
   |  BrowserGym env |              | abt server:8766|  ABT_CDP_URL attach mode
   +------^----------+              +------^---------+
          | a11y tree, bids                | HTTP ops {"op":"click","css":"[bid='13']"}
          +-------- runner / policy --------+
```

Why this shape:

* **BrowserGym must launch the browser** because its observation pipeline
  stamps every interactable element with a literal `bid` DOM attribute and
  its validators read that same DOM. The runner wraps playwright's
  `chromium.launch` once (`adapter.inject_cdp_port`) so the launch carries
  `--remote-debugging-port`. BrowserGym's own code is untouched.
* **abt attaches over CDP** instead of launching its own Chrome
  (`ABT_CDP_URL=http://127.0.0.1:9222`, new in `pwdriver.py`). Because both
  clients sit on one browser, every `bid` the observation names is directly
  targetable by abt as CSS `[bid="..."]` -- including inside iframes.
* **Every action goes through the toolkit's HTTP API**: the runner lowers
  standard BrowserGym action strings (`click(bid='x')`, `fill(...)`,
  `select_option(...)`, ...) into abt ops (`adapter.lower_action`) and POSTs
  them to `/commands`. Episode advancement and reward harvesting use
  `env.step("noop(wait_ms)")`.
* **Per-episode lifecycle**: `env.reset()` starts a fresh browser each
  episode; the runner re-attaches via `POST /browser/restart`. On detach,
  abt's attach mode only disconnects -- it never closes the harness browser.

## What ran where

| Concern | Owner |
|---|---|
| Browser process, task setup/teardown | BrowserGym |
| Observations (a11y tree, goal, screenshot) | BrowserGym |
| Every click/fill/select/press/navigation | ai-browser-toolkit HTTP ops |
| Pass/fail | BrowserGym `task.validate()` |
| Execution audit trail | abt session logs (`events.jsonl` + frames) |

The last row is the cross-reference: BrowserGym's per-episode rewards land in
the results json; the exact ops that produced them are in the abt server's
session log of the run (`GET /logs/<session_id>` on the bench port), each op
with its own screenshot frame.

## Reproducing

Requirements: Python 3.11+, Google Chrome, an abt checkout (this branch),
and the benchmark venv used during development:

```bash
# 1. benchmark venv (kept separate from the product venv)
py -m venv bgvenv
bgvenv\Scripts\pip install "playwright==1.62" greenlet gymnasium numpy pillow \
    beautifulsoup4 "lxml>=4.9,<6" cloudpickle jsonschema pyparsing requests
# browsergym pins playwright==1.44 exactly; on modern pythons we install it
# without deps against the newer playwright (verified working) -- see note
bgvenv\Scripts\pip install --no-deps browsergym-core==0.14.3 browsergym-miniwob==0.14.3
bgvenv\Scripts\python -m playwright install chromium chromium-headless-shell

# 2. MiniWoB++ html (served locally by the runner)
git clone --depth 1 https://github.com/Farama-Foundation/MiniWob-PlusPlus %TEMP%\opencode\miniwob

# 3. abt server in attach mode, on its own port (8765 may be in use)
set ABT_CDP_URL=http://127.0.0.1:9222
start-server.bat --port 8766

# 4. run episodes
bgvenv\Scripts\python benchmarks/browsergym/run_miniwob.py \
    --task click-button --episodes 20 --policy llm \
    --server http://127.0.0.1:8766 --out results/miniwob/click-button.json
```

WebArena additionally needs its docker stack and config; see
`run_webarena.py`. The loop is identical.

### The playwright pin, honestly stated

browsergym-core 0.14.3 declares `playwright==1.44`, which predates Python
3.13 wheels for its greenlet dependency. We install browsergym with
`--no-deps` against playwright 1.62 and verified the surface browsergym uses
(observation marking, action execution, task validation, chat) behaves
identically -- the smoke suite below runs green on it. Anyone reproducing on
Python 3.12 can install with plain `pip install browsergym-miniwob==0.14.3`
and get upstream's exact pin instead; nothing in this adapter depends either
way.

## Smoke results (2026-08-21, this branch)

Scripted no-LLM policies, headed browser, Windows 11 host:

| Task | Episodes | Score |
|---|---|---|
| miniwob click-button | 3 | 3/3 |
| miniwob enter-text | 3 | 3/3 |

These are plumbing checks, not benchmark claims: they show actions flowing
through the toolkit while BrowserGym scores them, on both the click and
fill paths. Real numbers need an LLM policy, many more episodes, all tasks,
and the fixed seeds documented next to the results.

## Honesty notes

* Scoring is never ours: `validate()` reads state only BrowserGym's task
  logic defines; the adapter cannot write rewards.
* The subset of the action space mapped by `lower_action` raises loudly on
  anything unmapped rather than approximating.
* Known deviation from stock AgentLab runs: actions execute through our
  server instead of BrowserGym's executor, and `noop()` steps advance the
  episode clock. Task timing budgets (MiniWoB `episode_max_time`) are
  unaffected at current step counts; WebArena has none.
