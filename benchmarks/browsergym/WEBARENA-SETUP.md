# WebArena on the VPS: what was built, and how to check it

Written so the numbers can be traced back to the machine that produced them.
Every claim below is something that was run and observed, and the command that
observed it is given. Where a thing was assumed and then turned out to be wrong,
the wrong version is kept — the failures are the reason the setup looks as it
does.

Host: `root@169.58.213.174` (graft remote `contabo`). Everything lives under
`/opt/webarena/`, which can be deleted in one command to undo all of this.

---

## 1. The shape of it

Two independent workers, one per site. Nothing is shared between them except
the machine.

| | worker 1 | worker 2 |
|---|---|---|
| site | shopping | shopping_admin |
| site port | 7770 (+7771 ctrl) | 7780 (+7781 ctrl) |
| container | `webarena-shopping` | `webarena-shopping-admin` |
| toolkit server | `:8766` | `:8767` |
| Chrome profile | `/opt/webarena/bench/profile` | `.../profile-admin` |
| CDP port | 9222 | 9223 |
| live trace | `:9100` | `:9101` |
| results | `results/wa-vps/` | `results/wa-admin/` |
| launcher | `run-sweep.sh` | `run-sweep-admin.sh` |
| tasks planned | 187 | 182 |

Every one of those columns had to differ. Two workers sharing any of them
fails, and two of the failures are silent rather than loud:

- **Chrome profile** — a profile can only be open once; the second browser
  refuses to start.
- **CDP port** — this one is the dangerous one. BrowserGym launches its
  chromium with `--remote-debugging-port=<n>` and the toolkit *attaches* to
  that port via `ABT_CDP_URL`. Sharing the port does not error; it hands one
  worker's browser to the other worker's agent.

Why one worker per site rather than one worker doing both: the toolkit server
owns exactly one browser, so parallelism has to come from more servers. That
was verified directly rather than assumed — see §5.

---

## 2. Building it, in the order it was actually done

### 2.1 Images

Pulled from `am1n3e/webarena-verified-*` on Docker Hub. Sizes as measured, not
as estimated:

| site | download (compressed) | on disk | RAM in use |
|---|---|---|---|
| shopping | 5.4 GB | 19.5 GB | 1.40 GB |
| shopping_admin | 1.2 GB | 4.49 GB | 1.13 GB |
| reddit | 4.6 GB | ~16 GB (est.) | — |
| map | 1.2 GB + 0.6 GB web | ~6 GB (est.) | — |
| gitlab | 22.0 GB | ~60–80 GB (est.) | 4–8 GB (est.) |
| wikipedia | 47 MB image | + an 85–115 GB `.zim` | — |

Download sizes came from Docker Hub's API:

```bash
curl -s "https://hub.docker.com/v2/repositories/am1n3e/webarena-verified-shopping/tags?page_size=1" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['results'][0]['full_size']/1e9)"
```

On-disk and RAM came from the machine (`docker images`, `docker stats
--no-stream`). The estimated rows are extrapolations from shopping's measured
5.4 → 19.5 GB ratio and are marked as such; do not quote them as measurements.

The box is 96 GB disk / 7.8 GB RAM with no swap. **GitLab and Wikipedia do not
fit** — each alone is near or over the free space, and GitLab's RAM appetite
would not co-exist with a running sweep.

Pulls were run detached so they survived a dropped connection:

```bash
nohup setsid sh -c 'for i in shopping_admin reddit map; do
  docker pull am1n3e/webarena-verified-$i:latest; done' \
  >> /opt/webarena/pull.log 2>&1 < /dev/null &
```

### 2.2 Containers

Started to mirror how the shopping container already ran — bound to loopback
only, so nothing is exposed to the internet:

```bash
docker run -d --name webarena-shopping-admin --restart unless-stopped \
  -p 127.0.0.1:7780:80 -p 127.0.0.1:7781:8877 \
  am1n3e/webarena-verified-shopping_admin:latest
```

The image carries `WA_ENV_CTRL_EXTERNAL_SITE_URL=http://localhost:7780`, so
7780 is not an arbitrary choice — the image expects it.

Readiness is `GET /admin` answering 200. It answers 302 within seconds but
takes a couple of minutes to serve the admin panel; check the real thing:

```bash
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' -L http://localhost:7780/admin
```

### 2.3 Toolkit servers

One per worker, detached, each attached to its own CDP port:

```bash
nohup setsid env ABT_CDP_URL=http://127.0.0.1:9223 \
  ./venv/bin/python -m abt serve --port 8767 --headless \
  --profile /opt/webarena/bench/profile-admin \
  > /opt/webarena/bench/server-admin.log 2>&1 < /dev/null &
```

Never `abt serve` in the foreground from a script that expects to return — it
is a command loop and never exits on its own.

### 2.4 Plan, then run

The plan is written once and is what the run is reproducible from. It records
the model, the provider, and every port, so a result can be traced to the
configuration that produced it:

```bash
python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-admin --sites shopping_admin \
  --server http://127.0.0.1:8767 --cdp-port 9223 --trace-port 9101 \
  --provider openrouter --model stealth/ox-alpha

nohup setsid /opt/webarena/bench/run-sweep-admin.sh \
  > /opt/webarena/bench/sweep-admin.log 2>&1 < /dev/null &
```

`--sites` filters to tasks whose sites are all running, so the completion
figure means something. Tasks needing an absent site are recorded `skipped`,
never `failed`.

Use an **absolute path** in the launch line. `cd /x && nohup … &` backgrounds
the whole `cd && nohup`, so the parent shell's directory never changes and a
relative path in the next command misses.

### 2.5 Watching it

Detachment was verified, not assumed:

```
sweep:  PID 266518  TT ?  STAT Ss  SID=PGID=PID  parent → systemd
        fd0 /dev/null   fd1,fd2 → sweep.log
```

`TT ?` = no controlling terminal, `Ss` = own session leader, parent = PID 1.
There is no SSH session left in the chain to receive a SIGHUP, so a dropped
connection cannot stop the run. Only the *tunnel* dies; reconnect and the run
is still there.

```bash
ssh -i ~/.graft/graftpem -N \
  -L 9100:127.0.0.1:9100 -L 9101:127.0.0.1:9101 \
  -L 8766:127.0.0.1:8766 -L 8767:127.0.0.1:8767 root@169.58.213.174
```

- `:9100` / `:9101` — the live loop view for whichever task is running
- `:8766/viewer` / `:8767/viewer` — the toolkit's own session log

---

## 3. Three harness bugs, and how each was proven

All three produced *plausible-looking* results. That is what made them
expensive: the sweep ran for an hour and a half and reported 0 passes across 40
tasks, which reads as "the agent is bad" and was in fact "the harness never
asked".

### 3.1 The answer never reached the evaluator

Every episode ended with `env.step("noop(500)")`. WebArena's `string_match`
does not read the harness's record — it reads the last `send_msg_to_user` of
the episode. With only a noop, it scored an empty string, every time.

**Proof, before any fix:** `webarena.126` required the strings `2.56` and
`649.99`. The stored reply read `**$2.56 – $649.99**`. Both present. Reward
`0.0`.

**Fix:** end on the answer, falling back to noop when there is none.

```python
answer = (session.get("reply") or "").strip()
final_action = f"send_msg_to_user({answer!r})" if answer else "noop(500)"
```

The record now also carries `scored_action`, so a future 0 can be told apart
from an answer that never arrived.

### 3.2 `127.0.0.1` is not `localhost`

`validate()` opens with a safeguard: every open tab's netloc must appear in the
authorized list built from the `WA_*` URLs. Magento's configured base URL is
`localhost:<port>` and it **redirects there**. Pointing `WA_SHOPPING` at
`127.0.0.1:7770` meant the very first navigation landed on an "unauthorized"
host, and validate returned `0, True, "Unauthorized url, terminating task"`
*before the evaluator ran*.

**Proof:** same task, same model, same code, one flag changed.

```
--shopping-url http://127.0.0.1:7770   ->  reward 0.0
--shopping-url http://localhost:7770   ->  reward 1.0
```

They are the same machine, which is exactly why this looked harmless. The
safeguard compares strings.

The site URL must be **the host the site redirects to**, not merely one that
reaches it.

### 3.3 `SHOPPING_ADMIN` includes its path

BrowserGym's login for shopping_admin is `page.goto(url)` — it does not append
`/admin`. Set without the path, login lands on the storefront, `get_by_label
("Username")` finds nothing, and every task dies as `harness_error` in ~20s.

```
WA_SHOPPING_ADMIN=http://localhost:7780        -> harness_error, all 182
WA_SHOPPING_ADMIN=http://localhost:7780/admin  -> logs in, task runs
```

The login page itself was never the problem — checked separately: it loads in
1.2s and `get_by_label("Username")` resolves instantly. Ruling that out first
is what pointed at the URL.

### A wrong diagnosis worth keeping

The first admin failures were a `Page.goto` timeout, and the first guess was a
cold container. That was **wrong**: timing the page in a real browser gave
1.4–2.2s against a 10s limit. Had the guess been acted on — raising the
timeout — it would have masked the real bug (§3.3) *and* silently changed the
benchmark. Measure before widening a limit.

---

## 4. What this means for results produced before the fixes

The first run (40 tasks, archived at `results/wa-vps-unscored-127/`) has:

- **invalid** `reward` / `success` — every zero is §3.1 and §3.2, not the agent
- **valid** everything else — `ops`, `op_failures`, `op_success_rate`,
  `turns`, `ops_per_turn`, token counts, `wall_s`

It is archived rather than deleted for exactly that reason: the efficiency
numbers are real and were measured over 40 episodes.

Both sweeps were replanned and restarted on the fixed harness. Worker 1
produced a `PASS` within six tasks.

---

## 5. Concurrency, as tested

Claims about running more than one agent were checked on the machine rather
than reasoned about.

**Two clients, one server.** Both sent `goto` + `find` simultaneously. Both got
coherent, self-consistent answers — the command lock wraps the *whole list*, so
a `command-list` is atomic and two callers cannot interleave inside one. But
there is one browser and one ref namespace, so between batches they clobber
each other: the loser's refs go stale and its next op acts on the wrong page.
Fine for agents cooperating on one task; wrong for independent work.

**Two servers, two profiles.** Verified working:

```
:8801  profile prof-a  ->  https://example.com/       Example Domain
:8802  profile prof-b  ->  https://www.iana.org/...   Example Domains
```

Separate processes, browsers, cookie jars and logs, driven at the same time
with no interference. This is the supported way to run independent agents, and
is what the two workers here are.

Two servers on the *same* profile does not work — Chrome refuses the second
lock.

---

## 6. Metrics recorded per task

Beyond BrowserGym's `reward`, each episode records what it cost and whether the
agent used the tool well. These are the point of the exercise: the toolkit
exists to reduce token cost, so cost is measured, not just success.

| field | what it answers |
|---|---|
| `turns` | how many model round trips |
| `ops`, `op_failures`, `op_success_rate` | did the agent learn the tool |
| `ops_per_turn` | is it batching, or paying per op |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_share` | what it cost |
| `wall_s`, `model_s` | time, split into thinking and everything else |
| `hit_turn_limit` | did it run out of room rather than finish |
| `goal`, `reply`, `final_url`, `eval_types`, `reference_answer` | enough to re-judge afterwards without re-running |
| `scored_action` | what the evaluator actually saw |

`reply`, `final_url` and the eval spec are gathered **before** `env.close()`.
BrowserGym deletes the task config on close and the browser goes with it, so
gathering afterwards silently yields `None` — the kind of empty field nobody
notices until the judging pass has nothing to judge.

### Traces

Each task now writes `results/<sweep>/traces/<task>.log` — the full turn-by-turn
narrative, line-buffered so a task that hangs or is killed still leaves
everything it had said.

This was not always true. The trace used to be memory-only: the `:9100` page
served it out of RAM for the task running right now, and the sweep captured the
child's stderr and threw it away unless the task failed, keeping 500
characters. A task that went *well* left no record of how.

The write happens in the child process on purpose. The sweep parent imported
its module once and will not see an edit until it restarts, but every task is a
fresh process — so the change took effect on the next task instead of the next
sweep. For the same reason the path is derived from `--out` rather than passed
as a new flag: the running parent cannot learn a new argument.

---

## 7. Judging what the automatic scorer cannot

Of the 182 shopping_admin tasks:

| eval type | count | scores itself? |
|---|---|---|
| `string_match` → `must_include` | 48 | yes |
| `string_match` → `exact_match` | 14 | yes |
| `string_match` → `fuzzy_match` | 26 | no — wants a GPT-4 judge |
| `program_html` | 66 | no — inspects live server state |
| `url_match` + `program_html` | 25 | partly |
| `url_match` | 3 | yes |

`fuzzy_match` calls an OpenAI judge that is not wired up; it returns 0
unconditionally. Those are judged by hand afterwards from the recorded
`goal` / `reference_answer` / `reply`, which is why those fields are stored.

`program_html` reads the site's database and DOM directly, so it only scores
correctly **while the container is still up**. Judge those during the run, not
after teardown.

---

## 8. Undoing all of it

```bash
docker rm -f webarena-shopping webarena-shopping-admin
docker rmi am1n3e/webarena-verified-shopping am1n3e/webarena-verified-shopping_admin \
           am1n3e/webarena-verified-reddit am1n3e/webarena-verified-map
rm -rf /opt/webarena
```

Nothing was installed outside `/opt/webarena` and the two containers. The
pre-existing containers on this host were not touched.

## 9. One thing to fix

The OpenRouter API key sits in plaintext in
`/opt/webarena/bench/run-sweep.sh`. `run-sweep-admin.sh` reads it out of that
file rather than repeating it, so rotating it is a one-file job — but it is
still on disk in the clear, and the same key was pasted into a chat transcript.
It should be rotated.
