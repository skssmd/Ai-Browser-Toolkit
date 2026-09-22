# Cross-site tasks, and the one line that tells the agent so

Most WebArena tasks live on one site, and the prompt says so: *"You are on a
self-contained store at `<url>`. Everything you need is on this site. Do NOT
navigate to any other domain."*

Several WebArena tasks are not like that. They start on one site and finish on
another — and that sentence, taken literally, forbids exactly the half of the
task that matters. An agent that obeys it answers from the wrong site and
scores zero for being well-behaved.

The fix is one line, and it is deliberately the *only* difference.

**Which pairs are runnable changes with which containers are up.** The
mechanism below is site-agnostic. The current pass is **shopping + reddit,
5 tasks** (ids 671-675); the gitlab+reddit 18 it was originally written for
are listed in [What the multisite pairs are](#what-the-multisite-pairs-are)
alongside the other pairings that would need containers not currently running.

---

## The one line

For a cross-site task the access sentence becomes:

```
You only have a connection to these sites: <url1> and <url2>.
```

Everything after it — the `ANSWER:` format, "leave the browser on the page",
the N/A guidance, the playbook nudge — is byte-for-byte the same as a
single-site task. Nothing else in the prompt moves.

A single-site task is passed no site list at all, so its prompt, its command
line and **every number already recorded from it** are unchanged. That was the
constraint that shaped the change: adding cross-site support must not alter a
single already-recorded single-site episode. Verified byte-identical — a
single-site `goal` is 2151 characters and its opencode `oc_goal` 247, before
and after.

The one spelling difference to know: the tool-calling prompt calls the site a
"self-contained **store**", the opencode prompt a "self-contained **site**".
Both are untouched by this change; only the cross-site branch is new.

---

## How a task is decided to be cross-site

Two flags with two jobs share one name. This is the trap worth stating plainly.

**`plan --sites`** is a *filter*. `plan --sites shopping,reddit --cross-site`
plans only the tasks whose site set has more than one member, so a multisite
pass does not re-plan the single-site tasks the other workers already cover.
The choice is frozen into `plan.json` as `"cross_site": true`.

**runner `--sites`** is the *access line*. The sweep reads each task's site
list from WebArena's own task file (`_task_sites()` — read rather than
hardcoded, because a copy here would drift the moment the task set changed)
and passes the flag **only when the task needs more than one site**:

```python
if sites and len(set(sites)) > 1:
    cmd += ["--sites", ",".join(sites)]
```

Leaving the flag off a single-site task keeps its command line — and so its
recorded runs — exactly as they were.

The runner then turns names into reachable URLs:

```python
needed     = [n.strip().upper() for n in (args.sites or "").split(",") if n.strip()]
site_urls  = [u for u in (os.environ.get(f"WA_{n}") for n in needed) if u and u != absent]
cross_site = len(site_urls) > 1
```

`cross_site` is `len(site_urls) > 1`, **not** "was `--sites` given". A list
that resolves to one real site is a single-site task and is prompted as one.

---

## The sentinel, and why one URL is not a site

Before BrowserGym is imported, every `WA_*` is set: the one the run is about,
and a sentinel for the rest.

```python
absent = "http://127.0.0.1:19999"
```

A high, unused port on purpose. Chrome refuses a *low* port outright with
`ERR_UNSAFE_PORT`, which is not a connection failure and so never reaches the
"site not running" branch — such an episode would die as a harness error
instead of being recorded as skipped.

The sentinel must never be named to the agent as a site it can reach, so
`site_urls` filters it out with `!= absent`. Without that, a task listing a
site that is not up would tell the model to go and use
`http://127.0.0.1:19999`.

---

## What the multisite pairs are

Read from WebArena's own task file (`test.raw.json`, via `_task_sites()` —
never hardcoded, because a copy here drifts the moment the task set changes):

| pairing | tasks | runnable now? |
|---|---|---|
| gitlab + reddit | 18 (552-555, 562-566, 681-688, 791) | no — gitlab retired |
| map + wikipedia | 17 | no — neither container up |
| gitlab + wikipedia | 6 | no |
| **reddit + shopping** | **5 (671-675)** | **yes — this is the current pass** |
| map + shopping_admin | 2 | no — map not up |

Only **reddit + shopping** is servable with the shopping, shopping_admin and
reddit containers running, which is why `results/wa-multisite` plans exactly
those 5.

---

## Confirming it in a record

`goal` in `episodes.jsonl` (and in `raw/<task>.json`) is the prompt the agent
was given. A cross-site episode contains the line

```
You only have a connection to these sites: http://localhost:7770 and http://localhost:9999.
```

A single-site episode contains the original "self-contained store" sentence
instead. If a multisite episode shows that sentence, the sweep ran before the
flag reached it — that run cannot be compared to one that has it, which is why
the previous six-task multisite attempt was discarded and restarted from zero
rather than resumed.
