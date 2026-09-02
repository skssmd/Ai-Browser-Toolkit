# The servers, and how to see them from your machine

Five processes listen on the benchmark host, all on `127.0.0.1` so nothing is
exposed to the internet. Three of them are worth tunnelling. This says what
each one is, how to start it, and how to look at it.

Host: `root@169.58.213.174` (graft remote `contabo`). Everything lives under
`/opt/webarena/bench/`.

---

## What listens, and why

| port | what | lifetime | tunnel? |
|---|---|---|---|
| 7770 | shopping site (Magento) | container, always up | no |
| 7780 | shopping_admin site | container, always up | no |
| 8766 | abt server, worker 1 | long-running | optional — `/viewer` |
| 8767 | abt server, worker 2 | long-running | optional — `/viewer` |
| **9100** | **live trace, worker 1** | **per episode** | **yes** |
| **9101** | **live trace, worker 2** | **per episode** | **yes** |
| **9102** | **analytics dashboard** | **long-running** | **yes** |

The one thing that surprises people: **9100 and 9101 do not answer between
tasks.** The trace server lives inside each `run_webarena_one.py` process, so
it appears when an episode starts and disappears when it ends. A refused
connection there means "no episode running right now", not "broken". 9102 is
always up, which is why it is the one to leave open.

---

## 9102 — the analytics dashboard

The one to watch. Recomputes every episode's metrics on a timer and serves
them as a page and as JSON.

- **file:** `/opt/webarena/bench/dashboard.py`
- **reads:** `toolkit/results/*/episodes.jsonl` and `plan.json` — read-only,
  it never writes to the sweep's files
- **recompute interval:** 180s, on the server; the page polls every 20s
- **log:** `/opt/webarena/bench/dashboard.log`

```bash
# start (detached, survives your ssh dropping)
nohup setsid /opt/webarena/bench/venv/bin/python \
  /opt/webarena/bench/dashboard.py \
  > /opt/webarena/bench/dashboard.log 2>&1 < /dev/null &

# check
curl -s localhost:9102/data | head -c 200

# stop
pkill -f 'dashboard.p[y]'
```

It recomputes on a timer rather than per request so that a browser tab left
open overnight cannot become load on the machine the sweep is using.

`GET /` is the page. `GET /data` is the same numbers as JSON, if you would
rather script against it than read it.

---

## 9100 / 9101 — live traces

Turn-by-turn narrative of the episode running right now: what the model
thought, what ops it sent, what the page gave back.

- **not a file** — served from memory inside the episode's own process
- **enabled by:** `--trace-port` in the plan (`trace_port: 9100` / `9101`)
- **the same content, persisted:** `results/<sweep>/traces/<task>.log`

```
GET /              the auto-refreshing page
GET /raw           plain text
GET /since?n=0     JSON, for scripting
```

You do not start these. They come and go with each task. If you want the
history rather than the live view, read the `traces/` files — those are
written line by line as the episode runs and survive it.

---

## 8766 / 8767 — the abt servers

The toolkit itself, one per worker. Each **attaches** to a browser that
BrowserGym launched, addressed by `ABT_CDP_URL` — it does not launch its own.

- **worker 1:** port 8766, CDP 9222, profile `profile/`, log `server.log`
- **worker 2:** port 8767, CDP 9223, profile `profile-admin/`, log
  `server-admin.log`

```bash
cd /opt/webarena/bench
nohup setsid env ABT_CDP_URL=http://127.0.0.1:9222 \
  ./venv/bin/python -m abt serve --port 8766 --headless \
  --profile /opt/webarena/bench/profile \
  > /opt/webarena/bench/server.log 2>&1 < /dev/null &
```

Worker 2 is the same with `9223`, `8767`, `profile-admin`, `server-admin.log`.

**Every value must differ between the two.** Sharing the CDP port is the
dangerous one: it does not error, it hands one worker's browser to the other
worker's agent.

`/viewer` on either port replays every command and response with screenshots.

### When a server stops answering

`GET /health` answers even when everything else hangs, because it never
touches the driver. If `/health` is fine but `/status` times out, the driver's
owner thread is wedged inside a Playwright call and **nothing** will get
through — not `status`, not `alert`, not `browser_restart`. Observed once,
when a click opened a blocking dialog.

There is no graceful recovery. Kill it by pid and start it again:

```bash
pid=$(pgrep -f 'port 876[7]' | head -1)   # bracket stops the pattern matching your own shell
kill -9 $pid
```

---

## Tunnelling to your machine

The tunnel drops — it did three times in one session. Use a loop, not a bare
`ssh -N`, so a drop costs three seconds instead of your visibility:

```bash
while true; do
  ssh -i ~/.graft/graftpem -o StrictHostKeyChecking=no \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o TCPKeepAlive=yes \
      -N -L 9102:127.0.0.1:9102 \
         -L 9100:127.0.0.1:9100 \
         -L 9101:127.0.0.1:9101 \
      root@169.58.213.174
  echo "dropped $(date +%H:%M:%S), reconnecting"; sleep 3
done
```

Then:

| open | to see |
|---|---|
| <http://localhost:9102> | pass rate, tokens, per-sweep metrics, latest episodes |
| <http://localhost:9100> | what worker 1 is thinking, right now |
| <http://localhost:9101> | what worker 2 is thinking, right now |

Add `-L 8766:127.0.0.1:8766` if you also want `/viewer`.

**A dropped tunnel never affects the run.** Both sweeps are detached from any
ssh session — `setsid`, no controlling terminal, reparented to PID 1, output
to files. Reconnect and the run is where you left it.
