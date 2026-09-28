# Multi-Profile Sessions — Design

Date: 2026-09-28
Status: Draft — awaiting review

## Purpose

One abt server drives one browser on one profile today. `create_app`
(`server.py`) takes a single `BrowserSession`, a single `SessionRecorder` and one
global `threading.Lock`, and every command from every client passes through all
three. Two agents pointed at the same server share tabs, trample each other's
"current tab", and wait on each other's commands. Running agents on different
profiles means running a server per port — the `server-87xx.log` files in the
repo root are the trace of that workaround.

This design makes the **session** the unit every command runs in. A session
names a profile, owns the tabs it opens, has its own lock, its own Playwright
connection and its own log. One server runs one hidden Chrome per profile in
use, and sessions on different profiles — or on the same profile — execute in
parallel.

It is the first of three specs:

1. **Multi-profile sessions** (this document).
2. **Session policy** — per-session URL allow/deny rules, enforced at the op
   and network level, and the `run_js` switch. Adds fields to session
   `settings`; nothing here depends on it.
3. **Desktop app** — one window, a dockable/hideable chat beside a live view of
   the session's tabs, driven by an OpenAI-compatible endpoint the user
   configures. Built on the sealed sessions and screencast defined here.

## Non-goals

- URL rules, `run_js` gating, the model/agent loop and the desktop UI (specs 2
  and 3).
- Multiple profiles inside one Chrome process via isolated contexts. Considered
  and rejected: it cannot reuse a real Chrome profile (logins, saved passwords,
  extensions). Each profile gets its own Chrome.
- The Selenium engine. Sessions are built on the Playwright engine's attach
  mode. With `--engine selenium` the server keeps today's single-browser
  behaviour and only the `default` session exists.
- Protection against malware running as the user's own OS account. See
  *Threat model*.

## Concepts

| Term | Meaning |
|---|---|
| **Profile** | A named Chrome user-data directory under abt's profile root (`paths.default_profile().parent`). `default` is today's profile. |
| **Session** | A named context commands run in: a profile, settings, owned tabs, a lock, a Playwright connection, a log. |
| **Open session** | Selected by name only. Isolation between cooperating agents; **not** a security boundary. |
| **Sealed session** | Created with a secret token; every command must carry it. Strongly enforced. Created by the desktop app. |
| **Run** | One server lifetime. What `recorder.py` currently calls a "session"; renamed to free the word. |
| **Operator** | The human at the GUI. Holds the operator token; can view and take over any tab. |

## Architecture

```
 MCP / HTTP / CLI / GUI agent
        │  session: --session, ABT_SESSION, header/field, bound by launcher; else "default"
        │  token:   sealed sessions only, held by the launcher (GUI), never by the model
        ▼
 ┌──────────────────────── abt server (FastAPI) ─────────────────────────┐
 │ SessionRegistry ─ Session "research"                                   │
 │                    ├ profile: work                                     │
 │                    ├ lock (serial within the session)                  │
 │                    ├ PlaywrightDriver (attach mode, own thread) ───────┼─► Chrome[work] (hidden)
 │                    ├ owned tabs                                        │        ▲
 │                    └ recorder → logs/sessions/research/<run>.jsonl     │        │ CDP
 │                  Session "default" (profile: default) ─────────────────┼─► Chrome[default]
 │ ProfileRegistry: launch/stop one Chrome per profile, cap, idle stop    │
 │ TabRegistry:     tab (CDP target id) → owner session, per profile      │
 │ Screencast:      WebSocket stream + input for any tab (GUI)            │
 └────────────────────────────────────────────────────────────────────────┘
```

### New units

- **`profiles.py` — `ProfileRegistry`.** Launches Chrome for a profile as a
  plain subprocess, discovers its CDP endpoint, reuses a running one, stops idle
  ones, enforces the cap, and keeps one **operator connection** per running
  profile (used for target events and the screencast). Knows nothing about
  sessions.
- **`sessions.py` — `SessionRegistry`, `Session`.** CRUD, persistence, token
  checks, resolving which session a request belongs to. A `Session` holds its
  profile, lock, driver, and recorder.
- **`tabs.py` — `TabRegistry`.** Per profile: tab → owner. Answers "may session
  S see / act on tab T" with one of `own`, `locked`, `invisible`. Assigns
  popups to their opener's owner; drops entries when tabs close.
- **`screencast.py`.** WebSocket endpoint streaming a tab and forwarding input.

### Changed units

- **`server.py`.** `create_app` takes the registries instead of one
  `BrowserSession`. `run_one` resolves the session, then runs under
  `session.lock` with `session.driver`. The global lock is removed. New routes
  for profiles, sessions and the screencast.
- **`pwdriver.py`.** Attach mode takes its CDP URL from the driver config rather
  than the process-wide `ABT_CDP_URL` (which stays as an override for the
  BrowserGym harness). Its page list is filtered through `TabRegistry`; tab ids
  become CDP target ids. The console init script is installed once per profile
  by the operator connection, not once per session connection (otherwise it
  runs N times per page).
- **`ops/tabs.py`** and every op that selects a tab consult `TabRegistry`.
  New ops `claim_tab`, `release_tab`.
- **`mcp.py`.** `abt mcp --session NAME` (or `ABT_SESSION`) binds the
  connection's session; `Bridge` sends it with every call. No tool exposes
  session management or a `session` parameter.
- **`cli.py`.** Global `--session` option and `ABT_SESSION`; new `abt profile`
  and `abt session` command groups.
- **`recorder.py`, `viewer.py`.** Per-session log directories; viewer groups by
  session, then run, tab, site.

### Unchanged

The engine, targeting, `dom_diff`, frames, shadow handling, and the behaviour of
every op inside a tab the session owns.

## Profiles

- Stored as directories under the profile root. `default` always exists.
- `abt profile list | new NAME | rm NAME`; HTTP `GET /profiles`,
  `POST /profiles {"name"}`, `DELETE /profiles/NAME`.
- Names: `[a-z0-9][a-z0-9_-]{0,39}`.
- `rm` is refused with `profile_in_use` while any session references the
  profile, and refused for `default`. The CLI asks for confirmation.

## Sessions

### Fields

```json
{
  "name": "research",
  "profile": "work",
  "sealed": false,
  "created": "2026-09-28T10:00:00Z",
  "settings": {}
}
```

`settings` is empty in this spec; spec 2 adds URL rules and `run_js`, spec 3
the model. Unknown keys are preserved so specs 2 and 3 extend without a
migration.

Persisted as `sessions/<name>.json` under abt's config directory. Sessions
survive a server restart; their tabs do not (Chrome is restarted too), so tab
ownership is not persisted.

### Commands

| CLI | HTTP |
|---|---|
| `abt session list` | `GET /sessions` |
| `abt session new NAME --profile P` | `POST /sessions {"name","profile","sealed"?}` |
| `abt session show NAME` | `GET /sessions/NAME` |
| `abt session set NAME --profile P …` | `PATCH /sessions/NAME` |
| `abt session rm NAME` | `DELETE /sessions/NAME` |

- `set` applies from the session's next command, including mid-task. Changing
  the profile closes the session's tabs first and returns a warning saying so.
- `rm` closes the session's tabs and disconnects its driver. Logs are kept.
- `default` always exists, uses the `default` profile, has empty settings, and
  cannot be removed or sealed.

### Selecting a session

| Client | Source, in precedence order |
|---|---|
| CLI | `--session NAME`, then `ABT_SESSION`, then `default` |
| HTTP | `session` field in the command body, then `X-ABT-Session` header, then `default` |
| MCP | `abt mcp --session NAME`, then `ABT_SESSION`, then `default`; fixed for the connection |
| Desktop app | Bound by the app's agent loop; never visible to the model |

A name that does not exist is always `unknown_session` — never a silent
fallback to `default`, which would drop a session's restrictions on a typo.

Within one `/command-list` batch, all commands run in one session: the first
item's (or the header's) session applies, and an item naming a different one
is rejected with `bad_request`.

### Open and sealed sessions

**Open** sessions are what the CLI and HTTP create by default. Any process can
name any open session, so they only keep cooperating agents out of each other's
way. The CLI help and `guidelines/` say this plainly: `--session` is
convenience, not containment, and the CLI's normal mode is the `default`
session.

**Sealed** sessions are created with `"sealed": true`. The response carries a
256-bit random `token`, returned exactly once.

- Every command, log read, screencast and settings change for a sealed session
  must carry the token (`X-ABT-Token` header, or `token` field). Without it:
  `session_sealed`. Knowing the name is worth nothing.
- `abt session set` / `rm` on a sealed session without the token is refused.
  `abt session list` shows it with `sealed: true`.
- The model inside the desktop app emits tool calls only; the app's agent loop
  attaches session and token. There is nothing for the model to spoof.
- The token is stored in `sessions/<name>.token`, created with owner-only
  permissions (`0600`; on Windows an ACL granting only the current user), so
  the app can reconnect after a server restart.

The server stores only a hash of the token alongside the session and compares
in constant time.

### Threat model

Sealed sessions protect against: the model in a GUI chat, and any other agent
using abt through CLI, HTTP or MCP. They do **not** protect against a program
running as the same OS user, which can read the token and operator-token files
just as the GUI does. The spec for the desktop app repeats this in the UI.

## Tabs

### Identity

Tab ids are Chrome's **CDP target ids**. They are identical on every connection
to the same Chrome, so the TabRegistry, every session's driver and the
screencast agree on which tab is which. (Today's ids are indices local to one
Playwright connection.) Responses keep a short `tab` field for readability
alongside the id.

### Ownership

- A tab opened by a session (`new_tab`, or a `goto` with no tab yet) is owned by
  that session from creation.
- A tab opened by the page — popup, `target=_blank`, `window.open` — is owned by
  its opener's owner. The operator connection sees `Target.targetCreated` with
  `openerId`; ownership is assigned before any session can act on the tab.
- A tab with no owning opener (pre-existing, or opened by the operator in the
  live view) is **unowned**. A session must `claim_tab` it before acting on it.
- `release_tab` gives a tab up (it becomes unowned).

### Visibility and access

For a session S and tab T:

| T is | `list_tabs` | Any action on T |
|---|---|---|
| owned by S | listed | allowed |
| unowned, same profile | listed as `unowned` | only `claim_tab` |
| owned by another session, same profile | listed with `locked: "<owner>"` | `tab_locked` |
| in a different profile | not listed | `tab_not_found` (same as a tab that does not exist) |

A sealed session's tabs follow the same table for everyone else; the owner's
name is shown, nothing else.

`new_tab`, `switch_tab` and `close_tab` act only on owned tabs. Each session
has its own current tab; switching never affects another session. Playwright
acts on a page object directly, so nothing brings a tab to the front for
another session's command to work.

### Lifecycle

- Tab closes → its entry is dropped.
- Session removed → its tabs are closed.
- Profile's Chrome restarts → all its tabs are gone; sessions start with none.

## Parallel execution

### Launching Chrome

`ProfileRegistry.ensure(profile)` launches, if not already running:

```
chrome --user-data-dir=<profile dir>
       --remote-debugging-port=0
       --headless=new                        (unless the profile is set headed)
       --no-first-run --no-default-browser-check
       --disable-background-timer-throttling
       --disable-renderer-backgrounding
       --disable-backgrounding-occluded-windows
```

It reads the chosen port from `<profile>/DevToolsActivePort`, then opens the
operator connection. Remote debugging is permitted because these are custom
user-data directories; Chrome refuses it only on its own default profile.

`default` goes through the same path; the `launch_persistent_context` branch in
`PlaywrightDriver._boot` is no longer used by the server (it remains for
direct library use).

A profile can be marked `headed` (`abt profile set NAME --headed`) for sites
that misbehave headless. The GUI remains the intended way to see it.

### Connections and locks

- Each session gets its own `PlaywrightDriver` in attach mode connected to its
  profile's Chrome, created on the session's first command. Each driver owns
  its thread (`ThreadPoolExecutor(max_workers=1)`, as today).
- Each session has its own lock. Commands and batches within a session run in
  order; sessions never wait on each other.
- `TabRegistry` has one internal lock per profile, held only to read or change
  ownership, never across browser work.
- Result: different profiles and different sessions on the same profile both
  run concurrently.
- A session's driver disconnects on session removal or profile change. It never
  closes Chrome; `ProfileRegistry` owns Chrome's lifetime.

### Limits and failure

- `--max-profiles` (default 4): launching beyond it returns `profile_limit`
  listing the running profiles. Nothing is evicted.
- `--profile-idle-minutes` (default 30; 0 disables): a profile's Chrome stops
  when none of its sessions has sent a command for that long **and** no
  screencast is open on it.
- If a profile's Chrome dies, its sessions' next command returns `browser_dead`
  once, and the command after that relaunches it. The existing attach-mode
  `browser_dead` hint ("externally owned, cannot restart") applies only when
  `ABT_CDP_URL` is set; profile-registry browsers get a relaunch hint.
- `/status` reports each running profile (pid, port, headed, sessions, tab
  count) and each session (profile, sealed, owned tab count, last command).

## Logs

- Layout: `logs/sessions/<session>/<run>.jsonl` and
  `logs/sessions/<session>/shots/`.
- Each event gains `tab_id` (target id) and, for refusals such as `tab_locked`,
  the error code — refused actions are part of the record.
- `/viewer` lists sessions first, then runs, then tabs and sites.
- Reading a sealed session's logs over HTTP requires its token. Files on disk
  are created owner-only.
- Existing `logs/<run>.jsonl` files remain readable as a legacy "default"
  group.

## Screencast

- `GET /screencast?tab=<target id>` upgraded to a WebSocket.
- Uses the profile's operator connection: `Page.startScreencast` (JPEG,
  default quality 60, max width 1600) with `Page.screencastFrameAck`; input via
  `Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`, `Input.insertText`.
  Watching never contends with a session's own connection.
- Frames stream only while a socket is open. An open socket counts as activity
  for idle shutdown.
- Access: a session's own tabs with that session's token (open sessions need
  none); **any** tab with the **operator token**, including taking over a
  locked one. The operator token is generated at server start and written
  owner-only to `<config>/operator.token`.
- The operator can also release or claim a tab on behalf of a session through
  `POST /tabs/<id>/owner` with the operator token.

## Errors

All follow the existing `OpError` shape (`code`, `message`, `hint`).

| Code | When |
|---|---|
| `unknown_session` | Named session does not exist |
| `session_exists` | Creating a session whose name is taken |
| `session_sealed` | Sealed session addressed without a valid token |
| `tab_locked` | Acting on a same-profile tab another session owns |
| `tab_not_found` | Tab id not visible to this session (other profile, or gone) |
| `profile_limit` | `--max-profiles` would be exceeded |
| `profile_in_use` | Removing a profile a session references |

Hints are written for the agent: `tab_locked` says to open its own tab rather
than retry; `session_sealed` says the session is not addressable from here.

## Compatibility

- A client that never mentions sessions uses `default` on the `default` profile
  and must behave as it does today. The existing test suite runs unchanged
  against it.
- Tab ids change from indices to target ids. Ops that accept a tab id keep
  accepting a numeric index into the session's own `list_tabs` for one minor
  version, with a deprecation note in the response.
- `--engine selenium`: sessions other than `default` are refused with a clear
  error.

## Testing

Unit tests, no browser (fast, run per task):

- `TabRegistry`: ownership, visibility table, popup inheritance, release,
  close, profile restart.
- `SessionRegistry`: create/set/rm, persistence round trip, unknown keys kept,
  `default` protections.
- Tokens: sealed refusal, hash comparison, file permissions.
- Session resolution precedence for CLI, HTTP body/header, MCP; unknown names.
- Error shapes and hints.

Integration tests, real Chrome, marked slow:

- Two profiles, two slow `goto`s in parallel complete in about the time of one.
- Two sessions on one profile run in parallel; acting on the other's tab gives
  `tab_locked`; the other profile's tabs are `tab_not_found`.
- A popup opened from an owned tab is owned by the same session.
- A sealed session refuses a command without its token and accepts it with.
- Killing a profile's Chrome → `browser_dead`, then relaunch.
- Idle shutdown stops Chrome and a later command restarts it.
- Screencast delivers frames and a click lands.
- The existing suite passes against `default`.

The first implementation task is hardening attach mode — dialogs, console and
network capture, downloads — against a registry-launched Chrome, with its own
tests, before anything is built on it. Attach mode has so far only been used by
the BrowserGym harness.

## Risks

- **Attach-mode gaps.** Behaviours built for launch mode may not hold over CDP
  attach. Mitigated by doing it first.
- **Headless detection.** Some sites treat `--headless=new` differently.
  Per-profile `headed` is the escape hatch.
- **Memory.** Each running profile is a full Chrome (roughly 300–500 MB).
  Bounded by `--max-profiles` and idle shutdown.
- **Tab-id change.** Clients storing numeric tab ids break after the
  deprecation window. Called out in the changelog.
