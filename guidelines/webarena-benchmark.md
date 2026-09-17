# WebArena sweeps — the operator playbook

Not a site playbook. This is the *harness* around the toolkit: how the two
WebArena workers are planned, launched and watched on the benchmark VPS. If
you are driving a WebArena site by hand, read
[`toolkit-workflow.md`](toolkit-workflow.md) and treat `localhost:8023`
(gitlab) / `localhost:9999` (reddit) as ordinary sites.

The long version, with every command as it was run and the reasoning, is
[`../benchmarks/browsergym/docs/00-setting-up-from-scratch.md`](../benchmarks/browsergym/docs/00-setting-up-from-scratch.md).
This page is the short form you can paste.

Host: `root@169.58.213.174` (graft remote `contabo`). Everything under
`/opt/webarena/bench/`. A site container answers on `127.0.0.1` only.

## The two workers

| | gitlab | reddit |
|---|---|---|
| site | `localhost:8023` | `localhost:9999` |
| container | `webarena-gitlab` | `webarena-reddit` |
| abt server | `:8766` | `:8767` |
| CDP | `9222` | `9223` |
| profile | `bench/profile` | `bench/profile-reddit` |
| trace | `:9100` | `:9101` |
| results | `results/wa-gitlab` | `results/wa-reddit` |
| model | `stealth/union-alpha` | `stealth/union-alpha` |

Sharing *any* of server / CDP / profile / trace / results between the two
breaks silently. Each `abt serve` attaches to its own browser over
`ABT_CDP_URL`; it never launches one, and it runs `--headless --no-run-js`.

## Run one sweep

```bash
cd /opt/webarena/bench/toolkit

# plan once; refuses to overwrite without --force. --sites filters to what's up.
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-gitlab --sites gitlab \
  --server http://127.0.0.1:8766 --cdp-port 9222 --trace-port 9100 \
  --provider openrouter --model stealth/union-alpha

# the API key lives only here; both launchers source it
cat /opt/webarena/bench/run-sweep.sh            # export OPENROUTER_API_KEY='sk-or-…'

# launch detached, absolute paths, output to a file
nohup setsid /opt/webarena/bench/run-gitlab.sh \
  < /dev/null > /opt/webarena/bench/sweep-gitlab.log 2>&1 &
```

`run-gitlab.sh` (reddit is the same with `wa-reddit`/`9999`/`8767`):

```bash
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_GITLAB='http://localhost:8023'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-gitlab --timeout 2400
```

## Multisite (gitlab+reddit) — queued after reddit

Some WebArena tasks need **two** sites at once. Of the 812, exactly **18** need
gitlab *and* reddit (ids 552-555, 562-566, 681-688, 791). They are the only
multisite tasks runnable with these two containers up.

`--sites gitlab,reddit` alone is **not** what you want: its filter is
`set(task_sites) <= wanted`, so it also re-plans all 180 gitlab-only and 106
reddit-only tasks the other workers already cover. A `--cross-site` flag
filters to `len(set(task_sites)) > 1`, giving exactly those 18:

```bash
cd /opt/webarena/bench/toolkit
export WA_GITLAB='http://localhost:8023' WA_REDDIT='http://localhost:9999'
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-multisite --sites gitlab,reddit --cross-site \
  --server http://127.0.0.1:8767 --cdp-port 9223 --trace-port 9101 \
  --provider openrouter --model stealth/union-alpha
# planned 18 tasks -> results/wa-multisite/plan.json
```

It runs on the **reddit worker's** ports (`8767`/`9223`/`9101`), so it is
queued behind that worker's single-site sweep and starts the moment it ends.
`run-multisite.sh` sources the key and sets **both** site URLs:

```bash
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_GITLAB='http://localhost:8023' WA_REDDIT='http://localhost:9999'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-multisite --timeout 2400
```

`run-queue-reddit.sh` does the waiting — it polls for the reddit sweep to exit,
then `exec`s the multisite run, sending the run's output to
`sweep-multisite.log`:

```bash
while pgrep -f 'sweep_webarena.py run --out results/wa-reddit' >/dev/null 2>&1; do
  sleep 60
done
exec /opt/webarena/bench/run-multisite.sh >> /opt/webarena/bench/sweep-multisite.log 2>&1
```

Arm it detached (safe to leave; it is a plain poll loop):

```bash
nohup setsid /opt/webarena/bench/run-queue-reddit.sh \
  < /dev/null > /dev/null 2>&1 &
cat /opt/webarena/bench/queue-reddit.log     # "armed: waiting for..."
```

It appears in the dashboard as the **Multisite** tab, and as `wa-multisite` in
the All tab, the moment its plan exists — before the queue even fires.

## The edits the VPS carries

Two of them are `loop_policy.py`, uncommitted on the VPS:

Two settings ship in `benchmarks/browsergym/loop_policy.py` and need no edit:

- a **32000** output window (`budget = max_tokens or 32000`), so reasoning
  models have room to think before emitting a tool call;
- `default_headers` on the OpenAI client, identifying the caller to OpenRouter
  (`"HTTP-Referer": "https://localhost", "X-Title": "abt"`).

The harness (`sweep_webarena.py` and the flags below) is committed on `main`.

- `--cross-site` on `plan`: keep only tasks needing >1 of the listed sites,
  added after the `set(by_id[t]) <= wanted` subset filter in `cmd_plan` and as
  a flag next to `--sites`; also recorded as `cross_site` in plan.json.
- `--retry-faults` on `run`: fail again only the tasks whose last verdict was
  a harness fault.
- `store_row`: dedupe at write time, so a retry overwrites the verdict it
  supersedes instead of leaving a stranded `harness_error` under it.

Without `--cross-site` the multisite plan cannot be expressed, and `--sites
gitlab,reddit` re-plans the 286 single-site tasks instead of the 18.

## Watch it

```bash
# dashboard (the same dashboard.py in benchmarks/browsergym/)
nohup setsid ./venv/bin/python dashboard.py \
  < /dev/null > /opt/webarena/bench/dashboard.log 2>&1 &
curl -s http://127.0.0.1:9102/data | head -c 300

# wedge guard, one per worker: poll /status, 3 misses -> kill + restart
nohup setsid /opt/webarena/bench/watchdog.sh 8766 9222 /opt/webarena/bench/profile &
nohup setsid /opt/webarena/bench/watchdog.sh 8767 9223 /opt/webarena/bench/profile-reddit &
```

From your machine, tunnel 9102 (dashboard), 9100/9101 (live traces) and
8766/8767 (`/viewer`) in a reconnect loop — see docs/01. A dropped tunnel
never touches the run; everything is `setsid`ed.

## The traps, one line each

- **`127.0.0.1` is not `localhost`.** WebArena `validate()` rejects tabs whose
  host is not in the `WA_*` URLs *before* scoring. Say `localhost:8023`.
- **gitlab's inside port is `8023`, not `80`.** `-p 8023:80` runs and answers
  nothing.
- **GitLab OOMs a 7.8 GB box.** Cap `puma['worker_processes']=2` and
  `sidekiq['max_concurrency']=8` in `gitlab.rb`, `gitlab-ctl reconfigure`, and
  add the 4 GB swapfile.
- **402 means the ceiling, not usage.** OpenRouter prices `max_tokens`; lower
  it on a thin balance. 32000 needs a funded key.
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
`raw/<task>.json`. The queued cross-site pass is just another sweep,
`results/wa-multisite/`, with its run log at `sweep-multisite.log`. Toolkit
side: `~/.local/state/aibrowsertoolkit/logs/` (commands + screenshots,
`/viewer`). Dashboard: memory only, recomputed every 30s, four tabs (All,
Gitlab, Reddit, Multisite). Full detail in
[`../benchmarks/browsergym/docs/03-what-gets-logged.md`](../benchmarks/browsergym/docs/03-what-gets-logged.md).
