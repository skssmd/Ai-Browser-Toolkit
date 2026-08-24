# HANDOFF -- BrowserGym benchmark for ai-browser-toolkit

For the next AI (or human) taking over. Read this top to bottom before doing
anything. Everything below was verified by actually running it, not assumed.

## 0. Ground rules (violating these breaks the user's machine)

* The repo lives at `C:\Users\Dipto.SHAHARIARDIPTO\documents\github\aibrowsertoolkit`.
  **Work only on branch `browsergym-benchmark`** (base: main @ `1dd0e17`).
  Never modify `main` or the working tree outside this branch's scope.
* A PRODUCTION abt server runs on port **8765** holding the user's real
  browser profile. NEVER kill it, never `abt shutdown` it, never restart its
  browser. All benchmark traffic goes to the BENCH server on **8766**.
* The benchmark browser is headed on purpose (user wants to watch).
* No LLM API keys exist in the environment; irrelevant anyway because the
  benchmark policy is an agent CLI session (opencode), not an inline loop.

## 1. Architecture (why it looks like this)

One Chromium launched by BrowserGym with `--remote-debugging-port=9222`;
the abt bench server attaches over CDP (`ABT_CDP_URL` env var, new in
`src/abt/pwdriver.py`). BrowserGym owns observations + scoring
(`task.validate()`); every page action flows through abt ops. BrowserGym
stamps elements with `bid` attributes; abt targets them as CSS `[bid="..."]`.
Score is never self-graded.

Runner: `benchmarks/browsergym/run_miniwob.py`. Adapter/CDP-injection:
`benchmarks/browsergym/adapter.py` (`inject_cdp_port` monkeypatches
playwright's chromium.launch because BrowserEnv splats explicit args).

## 2. Environment map

| Thing | Path / value |
|---|---|
| Repo venv (editable install -> src\abt) | `<repo>\.venv\Scripts\python.exe` |
| Benchmark venv (browsergym etc.) | `%TEMP%\opencode\bgvenv\Scripts\python.exe` |
| MiniWoB html clone | `%TEMP%\opencode\miniwob\miniwob\html` (serve base_url + `/miniwob/`) |
| Bench server start | `$env:ABT_CDP_URL="http://127.0.0.1:9222"; cmd /c "start-server.bat --port 8766"` |
| Global CLI | `py -m abt` — NOW editable pointing at repo src (reinstalled this session). Version prints 0.2.2 but code is live from the checkout. |
| bgvenv pin workaround | browsergym-core/miniwob 0.14.3 installed `--no-deps` over playwright 1.62 (browsergym pins playwright==1.44 which has no py3.13 wheels). Verified working. |

CLI facts (verified): named subcommands are goto/find/click/input/tabs/status/
exec/exec-batch/diff/logs/ops/mcp — there is NO `press`/`select` subcommand,
those go through `exec`. Every command takes `-p/--port`. On PowerShell pipe
JSON: `'{"op":"press","key":"Enter"}' | py -m abt exec - -p 8766`.

## 3. Runner features added this session (uncommitted!)

`git status`: `M benchmarks/browsergym/run_miniwob.py`, untracked `results/`.
All changes below are in run_miniwob.py unless noted:

* **Agent policy** (`--policy agent --agent opencode|claude`): one agent CLI
  session per episode; runner scores afterwards via a single
  `env.step("noop(500)")`. Agent never sees bids or BrowserGym DSL.
* **AGENT_PROMPT**: teaches 5 concrete habits — css-first find, read
  dom_diff.actionable refs, batch ops in one call, get_text for content,
  screenshot-on-ambiguity — plus traps (stale_ref → fresh ref from last diff,
  never goto/reload task page = resets goal, dialogs offering "Exit/Home" =
  failure → Cancel, submit then stop). CLI fallback block with `-p {port}`.
* **--agent-mcp**: writes a throwaway dir with an `opencode.json`
  registering `abt mcp --api <server>` and passes `--dir <tmpdir>` to
  opencode (project config trick — no global config touched). For claude:
  writes mcp.json + `--strict-mcp-config --mcp-config ... --allowedTools
  "mcp__abt:*"`. MCP is a big win: agent used typed tools exclusively and
  stopped guessing CLI flags.
* **FREEZE_TIMERS_JS + default-on injection after each attach**: MiniWoB
  pages call `core.endEpisode(-1,'timed out')` after EPISODE_MAX_TIME
  (often 10–15 s) and some scale reward by elapsed time. An out-of-process
  CLI agent boots in 30–60 s and can NEVER act inside that window, so the
  wrapper swallows reason==='timed out' and forces time_proportional=false.
  Correctness is still fully graded by validate(). **This MUST stay
  disclosed in README honesty notes.** `--no-freeze-timers` restores stock.
* **Streaming + transcripts**: agent output streams live through
  `_pretty_event()` (`[tool]`/`[think]`/`[agent]` lines); full raw output is
  kept in `results/agent-transcripts/ep<seed>.json`. opencode always runs
  with `--format json` so tool RESULTS land in the transcript (default
  format collapses them). stdout/stderr force-reconfigured to utf-8
  (cp1252 console crashed on unicode glyphs).
* **Results json** records policy/agent/agent_mcp/freeze_timers for honesty.
* Fixed: `--policy agent` used to fall through to scripted-policy lookup and
  die on tasks without one.

## 4. Verified results so far

| Run | Task | Result |
|---|---|---|
| Scripted smoke | click-button x3, enter-text x3 | 6/6 reward=1.0 |
| Agent+CLI prompt | form-sequence-2 (ALL_MINIWOB_TASKS[80]) | reward=0 — did everything except press Submit |
| Agent+MCP | form-sequence-2 | **reward=1.0**, ~90 s, clean session |
| Agent+MCP | login-user-popup ([90]) attempt 1 | reward=0 — clicked popup's OK (= endEpisode(-1) trap) |
| Agent+MCP | login-user-popup attempt 2 | reward=0 despite audit log showing correct-looking flow (see §5) |

Audit trail works: bench server session log
`GET http://127.0.0.1:8766/logs/20260821-230309?limit=N` gives every op +
response JSONL + screenshot filename per event (shots at `/logs/<sid>/shots/<file>`,
saved copies in `%TEMP%\opencode\abtshots`). NOTE: the assistant model in
this session cannot view images — use response JSON instead.

## 5. OPEN MYSTERY — login-user-popup scored 0 with correct values submitted

Server log shows: username input ok (value=vanda), password typed but popup
disabled field mid-type (input returned ok with value:"" — toolkit gap:
input() doesn't verify the value landed), Cancel clicked (el_3), password
retyped ok (value:"JtqK"), find button → single #subbtn el_4, clicked ok.
Goal string confirmed as 'Enter the username "vanda" and the password
"JtqK"...'. Expected reward 1.0, got 0.0.

Candidate causes to check next:
1. Was `window.WOB_REWARD_GLOBAL` actually set? Replay manually: same seed,
   no agent — drive ops exactly like the log, then run_js dump
   `{u,p,WOB_REWARD_GLOBAL,WOB_DONE_GLOBAL}` BEFORE env.step. If GLOBAL==1
   but validate()==0, browsergym reads a different global (maybe it expects
   `WOB_REWARD_NEW`, absent in MiniWob-PlusPlus core.js) — compare with why
   form-sequence-2 passed.
2. Did something fire endEpisode(-1) between submit and step?
3. Is d3's `.on('click')` handler lost after our wrapper? (form-sequence
   uses jQuery — passed.)

Also worth reporting upstream (product repo, separate issue): `input`
returning `"ok":true` with `value:""` when the target gets disabled mid-op.

## 6. Tasks remaining

1. Diagnose §5 (scripted replay is the fast path).
2. README.md honesty notes are STALE: still claims "task timing budgets are
   unaffected". Must document freeze-timers + MCP mode + agent-session
   methodology + how to reproduce (commands in §7).
3. User asked for "the max one": run ALL_MINIWOB_TASKS[124] =
   **miniwob.visual-addition** (agent+MCP, seed 9001). Visual task — may
   need screenshot use; good stress test of hint #5.
4. Multi-seed sweeps for any number worth publishing (e.g. 10 seeds across
   a handful of tasks), results/*.json committed on the branch.
5. Commit everything on `browsergym-benchmark` (only with user's OK).
   `run_webarena.py` is still a skeleton.
6. Optional polish: teach `input` op to fail loudly when value doesn't stick.

## 7. Reproduce commands (exact)

```powershell
# bench server (skip if GET :8766/health answers)
$env:ABT_CDP_URL="http://127.0.0.1:9222"; cmd /c "start-server.bat --port 8766"

# one agent episode, streamed pretty, MCP tools, frozen timers
& "$env:TEMP\opencode\bgvenv\Scripts\python.exe" benchmarks\browsergym\run_miniwob.py `
  --task form-sequence-2 --episodes 1 --seed 9001 --policy agent `
  --agent opencode --agent-mcp --agent-timeout 300 `
  --server http://127.0.0.1:8766 --out results/agent-formseq2.json

# audit trail of what the agent did server-side
Invoke-RestMethod "http://127.0.0.1:8766/logs/20260821-230309?limit=40"
```

Task index lookup: `ALL_MINIWOB_TASKS[i].get_task_id()` via bgvenv python;
125 tasks total. HTML source of any task: `%TEMP%\opencode\miniwob\miniwob\html\miniwob\<subdomain>.html`.

## 8. Gotchas learned the hard way

* PowerShell eats inline JSON quotes — always pipe to `exec -`.
* opencode `--dir X` loads project config from X (used for MCP injection);
  `--format json` events include tool results, default hides them.
* MiniWoB popup tasks: popup-OK calls endEpisode(-1) instantly — clicking it
  ends the episode as failure while the page keeps looking alive.
* After endEpisode, miniwob freezes/blanks the page — agents misread this as
  "nothing happened" and keep poking; prompt now warns about it.
* `py -m abt` default port is 8765 (PRODUCTION). Agents must pass `-p 8766`
  every time; the prompt hammers this.
* Each `env.reset()` launches a brand-new browser; bench server re-attaches
  per episode (`browser_restart`). If the bench server reports browser_dead
  between runs, that's normal until the next runner invocation.
