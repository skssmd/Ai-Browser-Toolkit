# WebArena sweeps — the operator playbook

Not a site playbook. This is the *harness* around the toolkit: how the WebArena
workers are planned, launched and watched on the benchmark VPS. If you are
driving a WebArena site by hand, read
[`toolkit-workflow.md`](toolkit-workflow.md) and treat `localhost:7770`
(shopping) / `localhost:7780/admin` (shopping_admin) / `localhost:9999`
(reddit) as ordinary sites.

The long version, with every command as it was run and the reasoning, is
[`../benchmarks/browsergym/docs/00-setting-up-from-scratch.md`](../benchmarks/browsergym/docs/00-setting-up-from-scratch.md).
This page is the short form you can paste.

Host: `root@169.58.213.174` (graft remote `contabo`). Everything under
`/opt/webarena/bench/`. A site container answers on `127.0.0.1` only.

## The three workers

| | worker 1 | worker 2 | worker 3 |
|---|---|---|---|
| site | `localhost:7770` | `localhost:7780/admin` | `localhost:7770` + `localhost:9999` |
| container | `webarena-shopping` | `webarena-shopping_admin` | `webarena-reddit` |
| abt server | `:8766` | `:8767` | `:8768` |
| CDP | `9222` | `9223` | `9224` |
| profile | `bench/profile` | `bench/profile-reddit` | `bench/profile-multi` |
| trace | `:9100` | `:9101` | `:9103` |
| results | `results/wa-shopping` | `results/wa-admin` | `results/wa-multisite` |
| model | `stealth/union-alpha` | `stealth/union-alpha` | `stealth/union-alpha` |

Sharing *any* of server / CDP / profile / trace / results between workers
breaks silently. Each `abt serve` attaches to its own browser over
`ABT_CDP_URL`; it never launches one, and it runs `--headless --no-run-js`.

GitLab (`localhost:8023`) was retired 2026-09-17. Its `wa-gitlab` records and
dashboard tab remain, read-only.

## Run one sweep

```bash
cd /opt/webarena/bench/toolkit

# plan once; refuses to overwrite without --force. --sites filters to what's up.
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-shopping --sites shopping \
  --server http://127.0.0.1:8766 --cdp-port 9222 --trace-port 9100 \
  --provider openrouter --model stealth/union-alpha

# the API key lives only here; all launchers source it
cat /opt/webarena/bench/run-sweep.sh            # export OPENROUTER_API_KEY='sk-or-…'

# launch detached, absolute paths, output to a file
nohup setsid /opt/webarena/bench/run-shopping.sh \
  < /dev/null > /opt/webarena/bench/sweep-shopping.log 2>&1 &
```

`run-shopping.sh` (admin is the same with `wa-admin`/`shopping_admin`/`8767`,
and `WA_SHOPPING_ADMIN='http://localhost:7780/admin'`):

```bash
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_SHOPPING='http://localhost:7770'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-shopping --timeout 2400
```

## Multisite (shopping+reddit) — parallel, on worker 3

Some WebArena tasks need **two** sites at once. WebArena's 812 contain several
pairings; with gitlab retired the only one these containers can serve is
**shopping + reddit — 5 tasks, ids 671-675**. (The others: gitlab+reddit 18,
map+wikipedia 17, gitlab+wikipedia 6, map+shopping_admin 2.) Full enumeration
in [docs/04](../benchmarks/browsergym/docs/04-multisite-tasks.md#what-the-multisite-pairs-are).

`--sites shopping,reddit` alone is **not** what you want: its filter is
`set(task_sites) <= wanted`, so it also re-plans every shopping-only and
reddit-only task the other workers already cover. A `--cross-site` flag
filters to `len(set(task_sites)) > 1`, giving exactly those 5:

```bash
cd /opt/webarena/bench/toolkit
export WA_SHOPPING='http://localhost:7770' WA_REDDIT='http://localhost:9999'
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-multisite --sites shopping,reddit --cross-site \
  --server http://127.0.0.1:8768 --cdp-port 9224 --trace-port 9103 \
  --provider openrouter --model stealth/union-alpha
# planned 5 tasks -> results/wa-multisite/plan.json
```

It runs on **worker 3's own ports** (`8768`/`9224`/`9103`, profile
`profile-multi`), so unlike the old gitlab+reddit pass it does **not** queue
behind another sweep — it runs in parallel. `run-multisite-shop.sh` sources
the key and sets **both** site URLs:

```bash
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_SHOPPING='http://localhost:7770' WA_REDDIT='http://localhost:9999'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-multisite --timeout 2400
```

```bash
nohup setsid /opt/webarena/bench/run-multisite-shop.sh \
  < /dev/null > /opt/webarena/bench/sweep-multisite.log 2>&1 &
```

It appears in the dashboard as the **Multisite** tab, and as `wa-multisite` in
the All tab, the moment its plan exists.

## Settings that ship with the harness

These live in the repo (`benchmarks/browsergym/`) — a fresh checkout already has
them, and the VPS copy is just a clone plus the launchers below.

Two settings ship in `benchmarks/browsergym/loop_policy.py` and need no edit:

- a **32000** output window (`budget = max_tokens or 32000`), so reasoning
  models have room to think before emitting a tool call;
- `default_headers` on the OpenAI client, identifying the caller to OpenRouter
  (`"HTTP-Referer": "https://localhost", "X-Title": "abt"`).

A third applies to the whole harness: **`--max-turns` defaults to 100** in
`sweep_webarena.py`, `run_webarena_one.py` and `loop_policy.py`. The value is
copied into `plan.json`, so a sweep keeps the ceiling its plan was built with —
rebuild the plan when you mean to raise it.

The harness (`sweep_webarena.py` and the flags below) is committed on `main`.

- `--cross-site` on `plan`: keep only tasks needing >1 of the listed sites,
  added after the `set(by_id[t]) <= wanted` subset filter in `cmd_plan` and as
  a flag next to `--sites`; also recorded as `cross_site` in plan.json.
- `--retry-faults` on `run`: fail again only the tasks whose last verdict was
  a harness fault.
- `store_row`: dedupe at write time, so a retry overwrites the verdict it
  supersedes instead of leaving a stranded `harness_error` under it.

Without `--cross-site` the multisite plan cannot be expressed, and `--sites
shopping,reddit` re-plans the single-site tasks too instead of the 5 wanted.

## Watch it

```bash
# dashboard (the same dashboard.py in benchmarks/browsergym/)
nohup setsid ./venv/bin/python dashboard.py \
  < /dev/null > /opt/webarena/bench/dashboard.log 2>&1 &
curl -s http://127.0.0.1:9102/data | head -c 300

# wedge guard, one per worker: poll /status, 3 misses -> kill + restart
nohup setsid /opt/webarena/bench/watchdog.sh 8766 9222 /opt/webarena/bench/profile &
nohup setsid /opt/webarena/bench/watchdog.sh 8767 9223 /opt/webarena/bench/profile-reddit &
nohup setsid /opt/webarena/bench/watchdog.sh 8768 9224 /opt/webarena/bench/profile-multi &
```

From your machine, tunnel 9102 (dashboard), 9100/9101/9103 (live traces) and
8766/8767/8768 (`/viewer`) in a reconnect loop — see docs/01. A dropped tunnel
never touches the run; everything is `setsid`ed.

## The traps, one line each

- **`127.0.0.1` is not `localhost`.** WebArena `validate()` rejects tabs whose
  host is not in the `WA_*` URLs *before* scoring. Say `localhost:7770`.
- **The Magento images expect `80` inside** (`-p 7770:80`, `-p 7780:80`), and
  `WA_SHOPPING_ADMIN` must include the `/admin` path or every admin episode
  dies in login.
- **402 means the ceiling, not usage.** OpenRouter prices `max_tokens`; lower
  it on a thin balance. 32000 needs a funded key.
- **The turn ceiling is 100.** `plan.json` records the ceiling it was built
  with; raise it by rebuilding the plan and confirm the new `max_turns` before
  launching.
- **A launcher that dies leaves an empty log.** Check
  `pgrep -af sweep_webarena`, not just the file.
- **Six harness errors in a row stops the sweep** — the environment changed
  (key, container, model), not the tasks.
- **`--sites` is what makes completion honest.** A task needing an absent site
  is `skipped_site`, never `failed`.
- **Retries double a task's row.** Read `episodes.jsonl` through
  `dedupe_rows`; the dashboard already does.

## Where the records are

Per sweep: `results/wa-<site>/` — `plan.json` (the commitment),
`episodes.jsonl` (one row per episode), `traces/<task>.log` (turn by turn),
`raw/<task>.json`. The cross-site pass is just another sweep,
`results/wa-multisite/`, with its run log at `sweep-multisite.log`. Toolkit
side: `~/.local/state/aibrowsertoolkit/logs/` (commands + screenshots,
`/viewer`). Dashboard: memory only, recomputed every 30s, six tabs (All,
Shopping, Shopping admin, Multisite, Reddit, Gitlab). Full detail in
[`../benchmarks/browsergym/docs/03-what-gets-logged.md`](../benchmarks/browsergym/docs/03-what-gets-logged.md).
