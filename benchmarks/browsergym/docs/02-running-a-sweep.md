# Setting up and running a sweep

From nothing to two workers grinding through WebArena. Every step here was
arrived at by getting it wrong first; the traps at the end are the ones that
cost hours, and each is written as the symptom you will actually see.

---

## 1. Sites

WebArena ships each site as a Docker image. Only the ones you run are
plannable — a task needing an absent site is recorded `skipped_site`, never
failed.

| site | download | on disk | RAM | tasks |
|---|---|---|---|---|
| shopping | 5.4 GB | 19.5 GB | 1.4 GB | 187 |
| shopping_admin | 1.2 GB | 4.5 GB | 1.1 GB | 182 |
| reddit | 4.6 GB | ~16 GB | ~1 GB | 106 |
| map | 1.2 GB | ~6 GB | ~1–2 GB | 109 |
| gitlab | 22 GB | **~60–80 GB** | **4–8 GB** | 180 |
| wikipedia | 47 MB + an **85–115 GB** `.zim` | — | — | few |

On a 96 GB disk / 7.8 GB RAM box, **wikipedia** is the one that does not fit
(its `.zim` alone is 85–115 GB). GitLab does fit, but only with the Puma and
Sidekiq caps plus a 4 GB swapfile — see
[00 — setting it up](00-setting-up-from-scratch.md#4-the-containers), and it was
retired on 2026-09-17 for exactly that cost. **Right now the three running
workers are shopping, shopping_admin and a shopping+reddit multisite pass**
(§4).

```bash
docker run -d --name webarena-shopping --restart unless-stopped --shm-size=256m \
  -p 127.0.0.1:7770:80 -p 127.0.0.1:7771:8877 \
  am1n3e/webarena-verified-shopping:latest

docker run -d --name webarena-shopping_admin --restart unless-stopped --shm-size=256m \
  -p 127.0.0.1:7780:80 -p 127.0.0.1:7781:8877 \
  am1n3e/webarena-verified-shopping_admin:latest

docker run -d --name webarena-reddit --restart unless-stopped --shm-size=256m \
  -p 127.0.0.1:9999:80 -p 127.0.0.1:9998:8877 \
  am1n3e/webarena-verified-reddit:latest
```

Bound to loopback deliberately. **The two Magento images expect `80` inside**
(`-p 7770:80`, `-p 7780:80`), unlike gitlab whose inside port was `8023` — `-p
8023:80` ran but answered nothing.

**Wait for it properly.** Magento answers `302` within seconds but takes
minutes to serve the panel; the storefront root answers `200`, the admin panel
`200` on `/admin`. Poll the real thing:

```bash
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' http://localhost:7770/
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' http://localhost:7780/admin
```

Pull images detached — they take a long time and an ssh drop should not kill
one:

```bash
nohup setsid sh -c 'for i in shopping shopping_admin reddit; do
  docker pull am1n3e/webarena-verified-$i:latest; done' \
  >> /opt/webarena/pull.log 2>&1 < /dev/null &
```

## 2. Toolkit servers

One per worker, each attached to its own CDP port. See
[01-servers-and-tunnels.md](01-servers-and-tunnels.md) for the commands.

## 3. Plan, then run

The plan is written once and is what the run is reproducible from — model,
provider, every port, and the exact task list.

```bash
cd /opt/webarena/bench/toolkit
export WA_SHOPPING=http://localhost:7770
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-shopping --sites shopping \
  --server http://127.0.0.1:8766 --cdp-port 9222 --trace-port 9100 \
  --provider openrouter --model stealth/union-alpha
```

The admin plan is identical with `wa-admin`, `shopping_admin`, `8767`, `9223`,
`9101` — and its site URL must include the path: `WA_SHOPPING_ADMIN=http://localhost:7780/admin`.

`--sites` filters to tasks whose sites are all running, so the completion
figure means something.

The launcher holds the environment. Each launcher `source`s `run-sweep.sh`
rather than repeating the key, so rotating stays a one-file job:

```bash
# /opt/webarena/bench/run-shopping.sh
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_SHOPPING='http://localhost:7770'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-shopping --timeout 2400
```

```bash
nohup setsid /opt/webarena/bench/run-shopping.sh \
  >> /opt/webarena/bench/sweep-shopping.log 2>&1 < /dev/null &
```

**Use an absolute path.** `cd /x && nohup … &` backgrounds the whole
`cd && nohup`, so the parent's directory never changes and a relative path in
the next command misses.

## 4. Multisite (shopping+reddit)

WebArena's 812 tasks include several multisite pairings. With gitlab retired,
the only pairing these containers can serve is **shopping + reddit — 5 tasks,
ids 671-675**. The others (gitlab+reddit 18, map+wikipedia 17, gitlab+wikipedia
6, map+shopping_admin 2) each need at least one container that is not running.

They are invisible to the single-site plans (`--sites shopping` excludes them,
because their site set is not a subset of `{shopping}`).

Do **not** reach for `--sites shopping,reddit`: its filter is
`set(task_sites) <= wanted`, so it keeps every shopping-only and reddit-only
task too. A `--cross-site` flag (added to `cmd_plan`) filters to
`len(set(task_sites)) > 1`, and the plan records `cross_site: true`:

```bash
cd /opt/webarena/bench/toolkit
export WA_SHOPPING=http://localhost:7770 WA_REDDIT=http://localhost:9999
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-multisite --sites shopping,reddit --cross-site \
  --server http://127.0.0.1:8768 --cdp-port 9224 --trace-port 9103 \
  --provider openrouter --model stealth/union-alpha
# planned 5 tasks -> results/wa-multisite/plan.json
```

Unlike the old gitlab+reddit pass, this one gets **its own worker** (8768 /
9224 / 9103, profile `profile-multi`), so it does not queue behind anything —
it runs in parallel with the other two. The launcher sets *both* site URLs:

```bash
# /opt/webarena/bench/run-multisite-shop.sh
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_SHOPPING='http://localhost:7770' WA_REDDIT='http://localhost:9999'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-multisite --timeout 2400
```

The dashboard gives it its own **Multisite** tab; it shows up under that name
as soon as the plan file exists.

## 5. Resuming

A sweep resumes from what it recorded. Only *settled* outcomes count as done:

```
ok            ran and was scored          -> done
skipped_site  the site is not up          -> done
harness_error something broke around it   -> RETRY
```

A harness error says something about the environment at a moment — a 402, a
container mid-boot, a wedged driver — not about the task. Counting those as
done struck 39 tasks off one plan without a turn being spent on them.

Retried tasks get a second row in `episodes.jsonl`; anything reading the file
must take the best row per task (`dedupe_rows`) or it will count one task as
both a failure and a pass.

## 6. Watching it

<http://localhost:9102> after tunnelling. Or:

```bash
../venv/bin/python benchmarks/browsergym/sweep_webarena.py report --out results/wa-shopping
```

---

## Traps, as the symptom you will see

**Every task scores 0 no matter how well the agent does.**
Two independent causes, both silent:

1. *The answer never reaches the evaluator.* WebArena's `string_match` reads
   the last `send_msg_to_user` of the episode, not your record. An episode
   ending on `noop` scores an empty string. The runner sends the answer as the
   final action; the model marks it with `ANSWER: <value>` on its last line
   and the harness lifts that line out.
2. *`127.0.0.1` is not `localhost`.* `validate()` rejects any open tab whose
   netloc is missing from the `WA_*` URLs, **before** running the evaluator.
   Magento redirects to its configured base URL on `localhost`. Same task,
   same model, one flag: `127.0.0.1` → 0.0, `localhost` → 1.0.

   Always address a site by **the host it redirects to**.

**Every admin task dies in ~20s during login.**
`WA_SHOPPING_ADMIN` must include the path: `http://localhost:7780/admin`.
BrowserGym's login does `goto(url)` and does not append `/admin`, so without
it you land on the storefront and `get_by_label("Username")` finds nothing.

**Every request refused with 402 and no tokens spent.**
OpenRouter checks affordability against `max_tokens`, not usage, so an
oversized ceiling is refused outright — *"you requested up to 32000 tokens,
but can only afford 22583"* — and that halted two sweeps without a token being
spent. The ceiling is therefore a **balance** decision, not a capability one.

`loop_policy.py` ships with a **32000** window (`budget = max_tokens or 32000`):
a reasoning model spends output tokens thinking before it emits a tool call, so
the window has to leave room for that. A thin balance still refuses the request
outright — top the balance up rather than shrink the window — and `--max-tokens`
overrides it per run.

**The turn ceiling is 100, everywhere.**
`--max-turns` defaults to **100** in `sweep_webarena.py`, `run_webarena_one.py`
and `loop_policy.py`. A `plan.json` freezes the ceiling it was built with, so
raising it means rebuilding the plan (`plan --force`, or a fresh `--out`); the
code default alone does not reach an existing run.

**One worker, one browser.** Give each its own port, profile, CDP port,
trace port and results directory. A shared CDP port does not error; it hands
one worker's browser to the other worker's agent.

**A run of identical failures.** The sweep halts after 6 consecutive harness
errors rather than spending the plan on them. If you see that, something the
sweep depends on changed — read the tail it prints.
