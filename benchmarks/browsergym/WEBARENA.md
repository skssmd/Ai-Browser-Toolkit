# WebArena setup — what is attached to what, and how to check it

Every claim below was verified by running the command shown, not assumed. If
you are reading this to decide whether to trust a number, start with
**Provenance of the score**.

## The chain

```
  your laptop                          Contabo VPS (169.58.213.174)
┌──────────────────────────────┐     ┌───────────────────────────────┐
│ sweep_webarena.py            │     │ /opt/webarena/compose.yml     │
│   └─ loop_policy.py          │     │   └─ webarena-shopping        │
│        │ model: OpenRouter   │     │        127.0.0.1:7770  store  │
│        │ ops:   POST /commands│     │        127.0.0.1:7771  ctrl   │
│        ▼                     │     └───────────────────────────────┘
│ abt server :8766             │                    ▲
│   └─ Chrome (own profile)  ──┼── SSH tunnel ──────┘
└──────────────────────────────┘     ssh -L 7770 -L 7771
```

Nothing on the VPS is reachable from the internet: both ports bind
`127.0.0.1`, and the laptop reaches them through an SSH tunnel opened with the
key at `~/.graft/graftpem`.

## What lives where

| thing | where | why there |
|---|---|---|
| site containers | VPS | 19.5 GB on disk, and the VPS has the bandwidth |
| browser + toolkit | laptop | 16 GB RAM here vs 8 GB there; the two memory costs stay apart |
| the model | OpenRouter | `stealth/ox-alpha`, free preview |
| scoring | BrowserGym, in-process on the laptop | see below |

## Provenance of the score — the part that matters

**Task success is not ours.** It comes from `browsergym-webarena`, which wraps
WebArena's own evaluators: string match, URL match, or a program that queries
the site's backend. This benchmark cannot write a reward, only read one.

**Everything else in the results IS ours**, and is labelled as such in the
output. BrowserGym reports success and nothing else — it has no notion of how
many operations a toolkit spent, or how many of them failed. Those are the
numbers this benchmark exists to produce, so they are recorded separately and
never mixed into the score:

| metric | source | what it answers |
|---|---|---|
| `success`, `reward` | BrowserGym / WebArena | did it do the task |
| `turns` | our loop | how many round trips to the model |
| `ops` | the abt server's session log | how much work the toolkit did |
| `op_failures` | the abt server's session log | how often the toolkit said no |
| `op_success_rate` | derived | **did the agent learn to drive the tool** |
| `ops_per_turn` | derived | did it batch, or work one step at a time |
| `input/output/cache tokens` | the provider's usage field | what it cost |
| `wall_s`, `model_s`, `browser_s` | measured | where the time went |
| `tool_choice` | classified after the run | did it reach for the right op |

Ops are counted by the **server**, from its own log, never self-reported by
the agent. An agent that says it did three things and did nine is counted at
nine.

## Verifying each link yourself

```bash
# the site is up, on the VPS, and healthy
graft -r contabo -sh "curl -s localhost:7771/status | head -c 200"

# the tunnel reaches it from here
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7770     # 200

# it is a real store with real data, not a stub
curl -sL http://127.0.0.1:7770 | grep -c 'product-item'            # 121

# the toolkit drives it
abt exec '{"op":"goto","url":"http://127.0.0.1:7770"}' -p 8766

# the ops the agent actually ran, from the server not the agent
abt logs -p 8766
```

## Verified facts, with the command that produced them

| fact | how checked |
|---|---|
| shopping image is 19.5 GB unpacked | `docker images` on the VPS |
| it uses 1.2 GB RAM running | `docker stats webarena-shopping --no-stream` |
| the store carries 17,241 Home & Kitchen items | read off the category page during a live run |
| a store page is 164 KB of HTML | `curl -sL :7770 \| wc -c` |
| 812 WebArena tasks are loadable | `from browsergym.webarena import ALL_WEBARENA_TASK_IDS` |
| the 11 pre-existing VPS containers were untouched | `docker ps` before and after, same 11 names |

## Install deviations — stated because they affect reproducibility

* `browsergym-webarena` was installed with `--no-deps`. Its pin chain fails to
  build `greenlet` on Python 3.13. `nltk` was then installed by hand, which is
  the only dependency the import actually needed. Anyone on Python 3.12 can
  install it normally and skip this.
* Only the **shopping** site is running. WebArena tasks that need reddit,
  gitlab, wikipedia or map cannot be scored here and are excluded from the
  plan rather than recorded as failures.

## Teardown

```bash
graft -r contabo -sh "docker compose -f /opt/webarena/compose.yml down -v \
    && docker rmi am1n3e/webarena-verified-shopping \
    && sudo rm -rf /opt/webarena"
```

Nothing outside `/opt/webarena` was created on the VPS.
