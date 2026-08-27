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

On a 96 GB / 7.8 GB box, **gitlab and wikipedia do not fit.** Shopping,
shopping_admin, reddit and map do — about 584 of the 812 tasks.

```bash
docker run -d --name webarena-shopping-admin --restart unless-stopped \
  -p 127.0.0.1:7780:80 -p 127.0.0.1:7781:8877 \
  am1n3e/webarena-verified-shopping_admin:latest
```

Bound to loopback deliberately. The image already expects `localhost:7780`.

**Wait for it properly.** Magento answers `302` within seconds but takes
minutes to serve the admin panel. Poll the real thing:

```bash
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' -L http://localhost:7780/admin
```

Pull images detached — they take a long time and an ssh drop should not kill
one:

```bash
nohup setsid sh -c 'for i in shopping_admin reddit map; do
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
../venv/bin/python benchmarks/browsergym/sweep_webarena.py plan \
  --out results/wa-admin --sites shopping_admin \
  --server http://127.0.0.1:8767 --cdp-port 9223 --trace-port 9101 \
  --provider openrouter --model z-ai/glm-5.3-flash
```

`--sites` filters to tasks whose sites are all running, so the completion
figure means something.

The launcher holds the environment. `run-sweep-admin.sh` reads the API key out
of `run-sweep.sh` rather than repeating it, so rotating stays a one-file job:

```bash
export OPENROUTER_API_KEY="$(sed -n "s/^export OPENROUTER_API_KEY='\(.*\)'$/\1/p" \
  /opt/webarena/bench/run-sweep.sh)"
export WA_SHOPPING_ADMIN='http://localhost:7780/admin'
exec ../venv/bin/python benchmarks/browsergym/sweep_webarena.py run \
  --out results/wa-admin --timeout 2400
```

```bash
nohup setsid /opt/webarena/bench/run-sweep-admin.sh \
  >> /opt/webarena/bench/sweep-admin.log 2>&1 < /dev/null &
```

**Use an absolute path.** `cd /x && nohup … &` backgrounds the whole
`cd && nohup`, so the parent's directory never changes and a relative path in
the next command misses.

## 4. Resuming

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

## 5. Watching it

<http://localhost:9102> after tunnelling. Or:

```bash
../venv/bin/python benchmarks/browsergym/sweep_webarena.py report --out results/wa-vps
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
OpenRouter checks affordability against `max_tokens`, not usage. A 32,000
ceiling is refused outright on a thin balance — *"you requested up to 32000
tokens, but can only afford 22583"*. Measured need is ~370 output tokens per
turn including reasoning, so 8,000 is twenty times enough and always fits.

**Two workers, one browser.** Give each its own port, profile, CDP port,
trace port and results directory. A shared CDP port does not error; it hands
one worker's browser to the other worker's agent.

**A run of identical failures.** The sweep halts after 6 consecutive harness
errors rather than spending the plan on them. If you see that, something the
sweep depends on changed — read the tail it prints.
