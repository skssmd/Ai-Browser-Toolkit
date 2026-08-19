# Profile Sessions — Design

Date: 2026-08-19
Status: Approved

## Purpose

One `abt serve` owns exactly one browser on one unnamed profile directory. That
is enough for a single agent driving a single logged-in identity, and nothing
else. It cannot host two agents playing different roles, cannot keep a
recruiter's login apart from a candidate's, and cannot say which agent did what,
because there is only ever one of everything.

This design makes the profile a first-class, named thing. A single server holds
a pool of browsers, at most one per named profile, launched on request. Commands
name the profile they act on and the agent acting. Several agents work in
genuine parallel across different profiles; agents sharing a profile are
serialized safely, and may opt into exclusive ownership of a tab.

The session log becomes a per-profile history rather than a per-run snapshot, so
"what has this identity ever done, and which agent did it" is answerable.

## Non-goals

- **True parallel execution inside one browser.** Two agents cannot run
  commands simultaneously against the same browser. See "What is actually
  parallel".
- **Security.** `agent` is an unverified string. See "Coordination, not
  authorization".
- **Remote or multi-machine pools.** The server still binds to loopback and the
  pool is in-process.
- **Per-tab browser contexts.** Chrome's incognito-style contexts are not used;
  isolation comes from separate user-data-dirs.

## Decisions

Settled during brainstorming, recorded so the plan does not relitigate them:

| Decision | Choice |
|---|---|
| Concurrency | Parallel *across* profiles. Within one profile, serialized. |
| Tab sharing | Optional, opt-in ownership. Unclaimed tabs stay free for anyone. |
| Routing | `profile:` on the command; omitted means the default profile. |
| Identity | `agent:` on the command — one id serving as log filter and tab owner. |
| Launch | Explicit `browser_start`. Never automatic. |
| Pool limit | A cap that **refuses** a further launch. Never evicts. |
| Logging | One continuous history per profile, never a new run per launch. |
| Migration | `profile/` moves to `profiles/default/`. |

## Architecture

The load-bearing observation: `dispatch(session, cmd)` and everything under
`ops/` take one `BrowserSession` and do not care where it came from. If the
*server* resolves `profile → session` and takes that session's lock before
dispatching, then `ops/`, `targeting`, `diff`, `frames`, `refs` and `shots` need
no changes at all. Routing stays in the layer that routes; the page layer keeps
knowing only about pages.

The alternative — teaching every op about profiles — was rejected: about thirty
signature changes, for the privilege of putting routing logic in the layer that
should only understand documents.

```
ProfileRegistry   names, directories, metadata      profiles/<name>/
BrowserPool       name -> (BrowserSession, Lock)    at most `max_browsers` live
TabOwnership      (profile, tab_id) -> agent        opt-in, TTL'd
server            resolves, locks, dispatches       unchanged ops beneath
```

`BrowserSession` stays ignorant of names. It already takes a `LaunchConfig`
carrying a profile *path* and can start, stop and restart independently — the
decoupling work is what makes this design small.

## What is actually parallel

Stated plainly, because "concurrent agents" invites a reading this cannot
deliver:

- **Different profiles: genuinely parallel.** Separate browsers, separate
  drivers, separate locks. Two agents run at the same instant.
- **Same profile: serialized.** One lock per browser. A second agent's command
  waits for the first to finish. This is concurrency of *access*, not of
  execution.
- **Same profile, same tab, both claimed: refused.** The second agent gets
  `tab_locked` rather than a queue position.

The reason is not laziness. A Selenium `WebDriver` has one *current window* and
one *current frame*, held as state on the driver rather than passed per call.
Two threads interleaving `switch_to.window` retarget each other's clicks, and —
worse than failing — both report success. It is the same hazard `leave_frames`
already exists to contain, and no amount of locking granularity below "one lock
per driver" avoids it.

## ProfileRegistry

Owns `profiles/`. One directory per profile plus a sibling metadata file:

```
profiles/
  default/          <- Chrome user-data-dir
  default.json      <- {"name", "created", "last_used", "browser", "notes"}
  recruiter/
  recruiter.json
```

**Name validation is a security boundary, not tidiness.** A profile name becomes
a filesystem path, so a name is accepted only if it matches
`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`. That rejects `..`, absolute paths, path
separators, leading dots, and empty names by construction rather than by
blacklist. A rejected name raises `invalid_op` naming the rule. The resolved
path is additionally asserted to be inside `profiles/` before any directory is
created or removed — belt and braces, because the cost of being wrong here is
deleting something outside the repo.

`create(name)` makes the directory and metadata; creating an existing profile is
`invalid_op`, not a silent success, for the same reason `browser_start` refuses
a running browser: the caller believes something that is not true.

`delete(name)` is refused while that profile's browser is running — stop it
first — and requires `confirm: true` on the command. Deletion removes a
directory holding live logins and is not undoable; a bare `profile_delete` that
did it immediately would be a trap. Deleting `default` is permitted but leaves
the server with no default until one is recreated, and the response says so.

## Migration

On first start, if `profiles/` does not exist and a legacy `profile/` does, move
it to `profiles/default/` and write `default.json`. A move, not a copy: a Chrome
profile runs to hundreds of megabytes and a stale duplicate would eventually
confuse someone into using the wrong one.

The move is refused, loudly and without partial work, if `profile/` looks locked
(the singleton-lock check the lifecycle work already added). Moving a directory
out from under a running Chrome corrupts it.

An explicit `--profile` path on `abt serve` continues to work and is treated as
the default profile's directory, unmigrated. Existing invocations keep working.

## BrowserPool

`name -> (BrowserSession, threading.Lock)`, plus a `max_browsers` cap
(default 4, `--max-browsers`).

- `get(name)` returns the live session or raises `browser_dead` naming
  `browser_start` and the profile. A profile that exists but has no browser is
  the ordinary case, not an error state.
- `start(name, **overrides)` refuses past the cap with `pool_full`, listing what
  is running so the caller knows what to stop. **It never evicts.** Closing
  another agent's browser to make room is the worst failure mode available for
  orchestration: the victim learns about it as an unexplained `browser_dead`
  halfway through a workflow.
- `stop`/`restart`/`status` per profile, delegating to `BrowserSession`.

Each browser keeps its own lock, which is what makes cross-profile work
parallel. The lock is held for the duration of one command, never across
commands — tab *ownership*, below, is the mechanism for holding something
longer.

## Routing

`profile: str | None` and `agent: str | None` are added to `schema.Base`. Every
command model already inherits `Base`, so this is one edit rather than thirty,
and `extra="forbid"` keeps rejecting anything else.

- `profile` omitted or null means the default profile.
- `agent` omitted means an anonymous command: it is logged with no agent and may
  not claim tabs.

`server.execute` parses each command, resolves the session through the pool,
acquires that profile's lock, and calls `dispatch(session, cmd)` unchanged.

**A batch must be single-profile.** `POST /commands` naming more than one
profile is `invalid_op`. Mixing them would mean taking and releasing different
locks partway through, which silently destroys the one property a batch has —
that nothing else touches the browser in between. A batch is one agent's
sequence; if it needs two profiles it is two batches.

## Tab ownership

Opt-in and off by default. With no claims, behaviour is exactly as it is today
and no agent can block another.

- `tab_claim {tab_id, ttl}` records `(profile, tab_id) -> agent`. Claiming
  requires an `agent`; claiming a tab already owned by another agent is
  `tab_locked`, and re-claiming your own tab refreshes the TTL.
- `tab_release {tab_id}` drops it. Releasing a tab you do not own is
  `tab_locked`; `force: true` overrides, for cleaning up after a crashed agent.
- Any command targeting an owned tab from a different agent is `tab_locked`,
  naming the holder and when the claim expires.
- **Ownership expires.** A claim carries a TTL (default 300s), refreshed by each
  command from its holder. Without expiry, an agent that crashes mid-workflow
  locks a tab until the server restarts, which converts one agent's crash into
  everyone's outage.

### Which tab a command is checked against

Almost no command names a tab: `click`, `input`, `get_text` and the rest act on
whatever the session's *active* tab is. So enforcement reads:

- The tab checked is the session's active tab at the moment the command runs,
  **except** `tab_switch` and `tab_close`, which are checked against the
  `tab_id` they name.
- `tab_new` cannot conflict — the tab does not exist yet — and the created tab
  is unclaimed. An agent that wants it claims it afterwards.
- `tab_list`, `status`, `browser_status` and the profile ops are never checked.
  They read the session rather than a page, and blocking an agent from *seeing*
  the tab list would make orchestration harder for no gain.

This is also why claiming matters more than it first appears: because commands
follow the active tab, an unclaimed workflow is not merely racy at the moment
two commands overlap — an agent's `tab_switch` moves where the *other* agent's
next click lands.

### An anonymous command may not bypass a claim

A command with no `agent` that targets an owned tab is refused with
`tab_locked`, exactly as a foreign agent would be. The alternative — treating
"no agent" as a wildcard — would make ownership optional for anyone who simply
left the field out, which is to say not ownership at all.

Claims live in memory only. They are coordination between agents that are
running now, and a claim that outlived the server would refer to a tab that no
longer exists — the tab registry is rebuilt on browser start.

### Coordination, not authorization

`agent` is a caller-supplied string that nothing verifies. Any client can send
any id, and impersonating another agent takes no effort. This is correct for
cooperating agents in one orchestration and must be documented as such, in the
README and in `AGENTS.md`, so nobody builds on it as a security boundary. If
untrusted callers ever share a server, this mechanism is not the answer.

## Logging

One history per profile, appended forever:

```
logs/<profile>/events.jsonl
logs/<profile>/shots/
```

`session_id` effectively becomes the profile name, which `read_events`,
`list_sessions`, `shot_path` and the viewer already key on — so this is largely
a substitution rather than a rewrite. Each event gains an `agent` field, and
`GET /logs/<profile>` gains an `agent=` filter beside the existing site, tab and
op filters. Answering "what did the recruiter agent do" is the point of the
whole field.

One recorder per profile. Recorders are written from the threadpool under
different profile locks, so each keeps its own append lock — two profiles
logging at once must not interleave a half-written line.

**Retention.** A permanent history changes what the existing `--shots-max-mb`
cap means: it was per run, and runs ended. Frames are the only part that grows
dangerously (a JPEG per command, 50–200KB each), so the cap becomes per profile
and is enforced by pruning oldest frames first, plus an age limit
(`--shots-max-age-days`, default 30). The event log is text, is small, and is
kept: losing the record of what happened to save kilobytes would be a poor
trade. An event whose frame has been pruned reports `shot: null`, which the
viewer already handles for commands captured with shots off.

## Surface

**Ops:** `profile_list`, `profile_create`, `profile_delete`, `tab_claim`,
`tab_release`. `browser_start|stop|restart|status` gain `profile` through
`Base`. All profile and browser ops join `NO_HEALTH_CHECK` — like the lifecycle
ops, they are what you reach for when a browser is broken.

**HTTP:** `GET /profiles`, `POST /profiles`, `DELETE /profiles/{name}`,
`GET /browsers` (every live browser, its profile, and its claimed tabs).
`GET /status` and `GET /browser` take `?profile=`. `/health` is unchanged — it
answers about the server and must stay free of all this.

**Messenger endpoints** take `profile` too, defaulting as everything else does.
They resolve through the pool exactly like `/command`.

**CLI:** `abt profiles`, `abt profile create|delete`, and `--profile-name` /
`--agent` on the command-sending subcommands. `abt up` is unchanged.

**MCP:** the existing `browser_session` tool gains `profile`; one new
`browser_profiles` tool covering list/create/delete. Tab claiming is deliberately
*not* given a tool — an MCP client is a single agent, and the tool budget is
measured in tokens per turn; `browser_command` reaches it when genuinely needed.

## Errors

Three new types join `errors.ERROR_TYPES`. Each earns its place by having a
distinct remedy, which is the test — a caller branching on the type must be able
to act differently:

| Type | Means | Remedy |
|---|---|---|
| `profile_not_found` | No such named profile | `profile_create`, or fix the name |
| `pool_full` | At `max_browsers` | Stop another browser, or raise the cap |
| `tab_locked` | Tab owned by another agent | Wait for expiry, use another tab, or force-release |

`browser_dead` keeps its meaning — no browser for that profile right now — and
its message gains the profile name.

## Testing

Most of this needs no browser, which the lifecycle work already established as
the pattern worth following.

**Unit, no browser:** name validation, including the traversal cases
(`..`, `../x`, `/abs`, `C:\x`, empty, 64+ chars) asserted as rejections, and the
containment assertion on resolved paths. Registry create/delete/list. Pool cap
refusal and that refusal does not evict. Ownership claim, refresh, expiry,
foreign-claim refusal, force-release. Batch multi-profile rejection. Migration
against a fixture directory, including the refusal on a locked profile.

**Server, no browser:** routing to a named profile with no browser returns
`browser_dead` naming that profile; unknown profile returns `profile_not_found`;
`agent` reaches the recorder; `/logs/<profile>?agent=` filters.

**Live, two browsers:** two profiles started, a command on each, asserting both
sessions are independent (different tabs, different URLs) and that neither
sees the other's refs. One live test that two profiles run without serializing
behind each other.

**Live, ownership:** agent A claims a tab, agent B is refused with `tab_locked`,
the claim expires, B succeeds.

## Documentation

- `README.md` — a profiles section, the parallelism table from "What is actually
  parallel" verbatim, and the retention behaviour.
- `AGENTS.md` — `profile` and `agent` on every command, the claim protocol, and
  the coordination-not-authorization warning stated flatly.
- `guidelines/toolkit-workflow.md` — how an orchestration should be structured:
  one profile per role, explicit starts, claims only where two agents share.
- `docs/known-issues.md` — a note that same-profile agents serialize, so a slow
  command blocks the other agent on that profile.

## File layout

```
src/abt/profiles.py     new    ProfileRegistry, name validation, migration
src/abt/pool.py         new    BrowserPool, cap, per-profile locks
src/abt/ownership.py    new    TabOwnership, TTLs
src/abt/schema.py       edit   profile/agent on Base; five new command models
src/abt/ops/control.py  edit   profile and claim handlers
src/abt/ops/__init__.py edit   registry, NO_HEALTH_CHECK
src/abt/server.py       edit   resolve-then-lock, /profiles, /browsers, filters
src/abt/recorder.py     edit   per-profile root, agent field, pruning
src/abt/cli.py          edit   profile subcommands, --agent
src/abt/mcp.py          edit   profile on browser_session, browser_profiles
src/abt/viewer.py       edit   profile and agent in the log viewer
tests/                  new    unit + server + two live modules
```
