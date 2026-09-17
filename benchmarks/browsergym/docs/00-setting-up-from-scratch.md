# Setting it up from scratch

Everything below is a command that was actually run on the host (via the
`graft`-wrapped `ssh` that this project uses), then verified. Nothing is
invented or "should work". If you arrive here from a blank VPS, run these in
order and you arrive at the same two workers this repo's `results/` came from.

What you are building:

| | worker 1 | worker 2 |
|---|---|---|
| site | gitlab | reddit |
| site port | `8023` (+ `8024` ctrl) | `9999` (+ `9998` ctrl) |
| container | `webarena-gitlab` | `webarena-reddit` |
| toolkit server | `:8766` | `:8767` |
| Chrome profile | `bench/profile` | `bench/profile-reddit` |
| CDP port | `9222` | `9223` |
| live trace | `:9100` | `:9101` |
| results | `toolkit/results/wa-gitlab/` | `toolkit/results/wa-reddit/` |
| launcher | `run-gitlab.sh` | `run-sweep-reddit.sh` |
| tasks planned | 180 | 106 |

Every column has to differ. Two workers sharing a profile, CDP port or trace
port break in a way that does not announce itself (see
[`01-servers-and-tunnels.md`](01-servers-and-tunnels.md)).

`ssh`/graft is how this host is reached. The host is `root@169.58.213.174`.
Commands below are shown as they were run: wrapped in `graft -r contabo -sh`,
but each block is the plain command you would pass to a shell on the host.

---

## 0. The three rules that shaped everything

1. **A site container answers on `127.0.0.1` only.** Nothing on this host is
   reachable from outside. You tunnel to see the dashboard and traces.
2. **The pull of a 22 GB image survives an ssh drop.** `nohup setsid … <
   /dev/null &` everywhere a long job starts. If your connection dies, the run
   is still there.
3. **Plan once, then run.** The plan fixes model, provider, ports and the task
   list; the run is reproducible from it. Do not hand the run new flags.

---

## 1. Get the code

The benchmark lives in `bench/toolkit` — a plain clone of this repo, with the
harness files (`sweep_webarena.py`, `run_webarena_one.py`, `adapter.py`,
`loop_policy.py`) pulled in from the `browsergym-benchmark` branch because
they are not on `main`:

```bash
mkdir -p /opt/webarena/bench
cd /opt/webarena && git clone -b main https://github.com/skssmd/Ai-Browser-Toolkit bench/toolkit
cd /opt/webarena/bench/toolkit
git fetch -q origin browsergym-benchmark
git checkout FETCH_HEAD -- benchmarks/browsergym
```

Two settings in `benchmarks/browsergym/loop_policy.py` were learned the hard way
and now ship in the file, so a fresh checkout needs no edit:

- **A 32000 output window** (`budget = max_tokens or 32000`). The user asks for
  room to think; an 8000 budget clipped reasoning on long tasks. Later runs
  confirmed 32k is never *used*, only *allowed* — OpenRouter refuses a request
  outright if the ceiling exceeds the account balance, so the ceiling is the
  thing that must be safe.

- **Identify the caller to OpenRouter.** Requests without `HTTP-Referer` /
  `X-Title` are fine but the official route is to send them. Shipped in
  `loop_policy.py`:

  ```python
  client = openai.OpenAI(
      api_key=…, base_url=…,
      default_headers={"HTTP-Referer": "https://localhost", "X-Title": "abt"},
  )
  ```

## 2. The Python environment

```bash
cd /opt/webarena/bench
python3 -m venv venv
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -e /opt/webarena/bench/toolkit -q
venv/bin/pip install -q 'browsergym[webarena]' openai anthropic
venv/bin/playwright install chromium
```

That is `ai-browser-toolkit` editable (so `abt serve` runs the checkout you
just edited), `browsergym-webarena` 0.14.3, `playwright` 1.44 and Python 3.12.
Verified at run time:

```
Python 3.12.3
ai-browser-toolkit  0.6.2   /opt/webarena/bench/toolkit   (editable)
browsergym-webarena 0.14.3
playwright          1.44.0
```

## 3. The site images

Pull detached; each is gigabytes. `docker pull` writes its own log per site so
a failure is visible in the right file:

```bash
cd /opt/webarena/bench
nohup setsid sh -c 'docker pull am1n3e/webarena-verified-gitlab:latest > pull-gitlab.log 2>&1' &
nohup setsid sh -c 'docker pull am1n3e/webarena-verified-reddit:latest > pull-reddit.log 2>&1' &
```

Watch both without re-running the command:

```bash
tail -3 /opt/webarena/bench/pull-gitlab.log
tail -3 /opt/webarena/bench/pull-reddit.log
df -h / | tail -1
```

Measured on this box (96 GB disk): gitlab ~22 GB compressed / ~60 GB on disk,
reddit ~4.6 GB / ~15 GB. **GitLab does not fit alongside everything else
without a swapfile — see [§6](#6-make-room-4g-swapfile).**

## 4. The containers

The port maps are not guesses. Each image ships an env-ctrl responder on
`8877`, and each image's own config expects a particular *inside* port:

- **reddit** expects `80` inside → host `9999`; ctrl `8877` → host `9998`.
- **gitlab** expects `8023` inside → host `8023`; ctrl `8877` → host `8024`.

The gitlab line was wrong once (`8023:80`) and silently answered nothing —
the inside port is **`8023`, not `80`**. Use the exact lines:

```bash
docker run -d --name webarena-reddit --restart unless-stopped --shm-size=256m \
  -p 127.0.0.1:9999:80 -p 127.0.0.1:9998:8877 \
  am1n3e/webarena-verified-reddit:latest

docker run -d --name webarena-gitlab --restart unless-stopped --shm-size=256m \
  -p 127.0.0.1:8023:8023 -p 127.0.0.1:8024:8877 \
  am1n3e/webarena-verified-gitlab:latest
```

**Wait, properly.** GitLab takes minutes to be ready. Poll until the storefront
answers `200` (not a `302` and not `000`):

```bash
for i in 1 2 3 4 5 6 7 8; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 http://localhost:8023/)
  echo "8023 -> $code"; [ "$code" != "000" ] && break; sleep 30
done
curl -s -m 10 http://localhost:8024/status | head -c 300
```

### GitLab is a RAM hog — cap it before it OOMs the box

The image defaults to many Puma workers + Sidekiq concurrency. On a 7.8 GB
box that was the difference between a healthy sweep and a wedged one. The
override was appended to the container's `/etc/gitlab/gitlab.rb`:

```
puma['worker_processes'] = 2
sidekiq['max_concurrency'] = 8
```

then applied (in the container):

```bash
docker exec webarena-gitlab gitlab-ctl reconfigure
```

And a 4 GB swapfile went in on the host [§6](#6-make-room-4g-swapfile). Together
they keep `free` comfortably positive with both sweeps live.

## 5. The toolkit servers

One `abt serve` per worker, each attached to *its own* browser via
`ABT_CDP_URL` — the toolkit does not launch the browser; BrowserGym does, and
the server attaches to it over CDP. `--no-run-js` is required by the sweeps
(the harness forbids the agent reaching for raw JS) and `--headless` keeps the
VPS quiet:

```bash
cd /opt/webarena/bench
nohup setsid env ABT_CDP_URL=http://127.0.0.1:9222 \
  ./venv/bin/python -m abt serve --port 8766 --headless --no-run-js \
  --profile /opt/webarena/bench/profile \
  > /opt/webarena/bench/server.log 2>&1 < /dev/null &

nohup setsid env ABT_CDP_URL=http://127.0.0.1:9223 \
  ./venv/bin/python -m abt serve --port 8767 --headless --no-run-js \
  --profile /opt/webarena/bench/profile-reddit \
  > /opt/webarena/bench/server-reddit.log 2>&1 < /dev/null &
```

Health-check with the ports that matter:

```bash
curl -s -m 15 http://127.0.0.1:8766/status | head -c 180
curl -s -m 15 http://127.0.0.1:8767/status | head -c 180
```

If `/status` hangs while `/health` answers, the driver thread is wedged
inside a Playwright call — nothing recovers it, kill and restart by pid.

## 6. Make room: 4 G swapfile

GitLab alone can push the box into OOM on a 7.8 GB machine. Added once:

```bash
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null
swapon /swapfile
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
sysctl -p /etc/sysctl.d/99-swappiness.conf
grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 7. Plan, then run

The plan fixes everything the run must not change — model, provider, ports,
turn ceiling, task list — and refuses to overwrite itself without `--force`.
`--sites gitlab` / `--sites reddit` filters to tasks whose site is actually
running; the rest are recorded `skipped_site`, never `failed`.

```bash
cd /opt/webarena/bench/toolkit
export WA_GITLAB=http://localhost:8023 WA_REDDIT=http://localhost:9999
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-gitlab --sites gitlab \
  --server http://127.0.0.1:8766 --cdp-port 9222 --trace-port 9100 \
  --provider openrouter --model stealth/union-alpha
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-reddit --sites reddit \
  --server http://127.0.0.1:8767 --cdp-port 9223 --trace-port 9101 \
  --provider openrouter --model stealth/union-alpha
```

The API key is not in the plan. It lives in `run-sweep.sh`, which the two
launchers `source` — rotating a key is a one-file job:

```bash
# /opt/webarena/bench/run-sweep.sh
export OPENROUTER_API_KEY='sk-or-…'
```

The launchers pin the site URL (the host the site redirects to — for these
two, `localhost` is correct) and `exec` the run:

```bash
# /opt/webarena/bench/run-gitlab.sh
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_GITLAB='http://localhost:8023'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-gitlab --timeout 2400
```

```bash
# /opt/webarena/bench/run-sweep-reddit.sh
set -a; source /opt/webarena/bench/run-sweep.sh; set +a
export WA_REDDIT='http://localhost:9999'
cd /opt/webarena/bench/toolkit
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-reddit --timeout 2400
```

Launched detached (absolute paths — see the harness docs for why relative ones
break):

```bash
nohup setsid /opt/webarena/bench/run-gitlab.sh \
  < /dev/null > /opt/webarena/bench/sweep-gitlab.log 2>&1 &
nohup setsid /opt/webarena/bench/run-sweep-reddit.sh \
  < /dev/null > /opt/webarena/bench/sweep-reddit.log 2>&1 &
```

Verify they actually started (a launcher that dies on a bad env leaves the log
empty but the process gone):

```bash
ps -eo pid,etime,args | grep -e sweep_webarena | grep -v grep
tail -3 /opt/webarena/bench/sweep-gitlab.log
tail -3 /opt/webarena/bench/sweep-reddit.log
```

### Queue the multisite pass behind reddit

18 tasks need both gitlab and reddit. They are not in either single-site plan
(their site set is not a subset of one site), and `--sites gitlab,reddit`
would wrongly drag in all 286 single-site tasks. A `--cross-site` flag on
`plan` keeps only tasks needing more than one site:

```bash
cd /opt/webarena/bench/toolkit
export WA_GITLAB=http://localhost:8023 WA_REDDIT=http://localhost:9999
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-multisite --sites gitlab,reddit --cross-site \
  --server http://127.0.0.1:8767 --cdp-port 9223 --trace-port 9101 \
  --provider openrouter --model stealth/union-alpha
```

It runs on the reddit worker's ports, so it is queued behind that worker: a
poll loop waits for `wa-reddit` to exit, then `exec`s the multisite run.

```bash
# /opt/webarena/bench/run-queue-reddit.sh
while pgrep -f 'sweep_webarena.py run --out results/wa-reddit' >/dev/null 2>&1; do
  sleep 60
done
exec /opt/webarena/bench/run-multisite.sh >> /opt/webarena/bench/sweep-multisite.log 2>&1
```

```bash
nohup setsid /opt/webarena/bench/run-queue-reddit.sh < /dev/null > /dev/null 2>&1 &
```

## 8. The dashboard

`benchmarks/browsergym/dashboard.py` in this repo *is* the dashboard — the
same file runs live on `:9102`. It reads `toolkit/results/*/plan.json` and
`episodes.jsonl` (and tails the `sweep-*.log` files), never writes into them,
and recomputes on a timer so an open tab cannot load the box. Endpoints:

```
GET /                the page
GET /data            the same numbers as JSON
GET /task/<sweep>/<task>   one episode + its live trace
GET /logs/<sweep>    the sweep's run log tail
```

Deploy + start (detached):

```bash
# copy the file up first (graft/ssh), then:
cd /opt/webarena/bench
nohup setsid ./venv/bin/python dashboard.py \
  < /dev/null > /opt/webarena/bench/dashboard.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:9102/data | head -c 300
```

## 9. Watchdogs

A wedged driver (see [§5](#5-the-toolkit-servers)) never recovers on its own.
`watchdog.sh` polls `/status` every 60 s, and after 3 missed checks kills the
pid on the port and restarts the server with the exact flags the sweep needs:
`--headless --no-run-js --profile …` and the right `ABT_CDP_URL`. One per
worker:

```bash
nohup setsid /opt/webarena/bench/watchdog.sh 8766 9222 /opt/webarena/bench/profile \
  < /dev/null > /dev/null 2>&1 &
nohup setsid /opt/webarena/bench/watchdog.sh 8767 9223 /opt/webarena/bench/profile-reddit \
  < /dev/null > /dev/null 2>&1 &
```

## 10. See it from your machine

Tunnel the three things that are worth it (9100/9101 exist **only while a task
runs**; 9102 is always up). No tunnel touches the run — everything is
`setsid`ed with no controlling terminal:

```bash
while true; do
  ssh -i ~/.graft/graftpem -o StrictHostKeyChecking=no \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o TCPKeepAlive=yes \
      -N -L 9102:127.0.0.1:9102 \
         -L 9100:127.0.0.1:9100 \
         -L 9101:127.0.0.1:9101 \
         -L 8766:127.0.0.1:8766 \
         -L 8767:127.0.0.1:8767 \
      root@169.58.213.174
  echo "dropped $(date +%H:%M:%S), reconnecting"; sleep 3
done
```

Then open in a browser:

| open | to see |
|---|---|
| <http://localhost:9102> | both sweeps, pass rate, tokens, live task logs |
| <http://localhost:9100> | what gitlab's agent is doing, right now |
| <http://localhost:9101> | what reddit's agent is doing, right now |
| <http://localhost:8766/viewer> | gitlab worker's full op history |
| <http://localhost:8767/viewer> | reddit worker's full op history |

## 11. The traps that cost hours (repeated so you don't repeat them)

- **Every value must differ between the two workers.** Sharing the CDP port
  does not error; it hands one worker's browser to the other worker's agent.
  Sharing a profile refuses the second browser. Sharing a trace port poisons
  which sweep the page reports.
- **`127.0.0.1` is not `localhost`.** WebArena's `validate()` rejects any open
  tab whose host is not in the `WA_*` URLs *before* scoring. These two sites
  are configured to live at `localhost:8023` / `localhost:9999` — the plan env
  must say `localhost`, the containers bind `127.0.0.1`. Same task, one flag:
  `127.0.0.1` → 0.0, `localhost` → 1.0.
- **gitlab's inside port is `8023`, not `80`.** `-p 8023:80` runs but answers
  nothing.
- **GitLab's defaults OOM the box.** Cap Puma/Sidekiq (§4) *and* add swap (§6)
  before the first long run.
- **A launcher that dies silently.** The run kills itself after 6 consecutive
  harness errors, and prints why to the sweep log. Read the tail it prints.
- **A `302` is not ready.** Magento (shopping) answers `302` in a second but
  takes minutes to serve the panel. For GitLab, `200` on `localhost:8023/`.
- **The answer never reached the evaluator.** WebArena scores the last
  `send_msg_to_user` of the episode, not your record. The harness sends the
  agent's `ANSWER: …` line as the final action, falling back to `noop` when
  there is none.

## 12. Undoing all of it

```bash
docker rm -f webarena-gitlab webarena-reddit
docker rmi am1n3e/webarena-verified-gitlab am1n3e/webarena-verified-reddit
rm -rf /opt/webarena
swapoff /swapfile && sed -i '/swapfile/d' /etc/fstab && rm -f /swapfile
```

Nothing was installed outside `/opt/webarena`, the two containers and the
swapfile. The pre-existing containers on this host were never touched.