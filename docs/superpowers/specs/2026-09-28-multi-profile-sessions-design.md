# Multi-Profile Sessions — Design

Date: 2026-09-28
Status: Approved
Supersedes: `2026-08-19-profile-sessions-design.md` (approved, never built).
That design serialized sessions on a shared profile and treated agent ids as
unverified strings; this one gives each session its own connection, so a shared
profile runs in parallel, and adds sealed sessions for real enforcement. Its
profile-name rule and per-profile metadata file are kept.

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
  ones, enforces the cap, and lists a running profile's tabs through Chrome's
  own `GET /json/list`. Knows nothing about sessions. There is no long-lived
  "operator" Playwright connection: listing uses plain HTTP and the screencast
  opens Chrome's per-tab DevTools WebSocket directly.
- **`sessions.py` — `SessionRegistry`, `Session`.** CRUD, persistence, token
  checks, resolving which session a request belongs to. A `Session` holds its
  profile, lock, driver, and recorder.
- **`tabs.py` — `TabRegistry`.** Per profile: tab → owner. Answers "may session
  S see / act on tab T" with one of `own`, `locked`, `invisible`. Assigns
  popups to their opener's owner; drops entries when tabs close.
- **`screencast.py`.** WebSocket endpoint streaming a tab and forwarding input.

### Changed units

- **`server.py`.** `create_app` gains a `registry=` keyword. With it, each
  request resolves a session and runs under that session's lock with that
  session's `BrowserSession`; the global lock is gone. Without it —
  `create_app(browser_session)`, which the whole existing test suite and
  `--engine selenium` use — the one `BrowserSession` is wrapped as the
  `default` session and behaves exactly as today. New routes for profiles,
  sessions, tab ownership and the screencast.
- **`browser.py`.** `BrowserSession` gains an optional attach spec: where to get
  the CDP URL (the ProfileRegistry), and the session's `TabGate`. In attach mode
  `start` connects instead of launching, `stop` closes the session's own tabs
  and disconnects instead of quitting Chrome, and tab ids are allocated by the
  profile's `TabRegistry` so every session agrees on them.
- **`pwdriver.py`.** Attach mode takes its CDP URL as a constructor argument
  (`ABT_CDP_URL` stays as the BrowserGym override, with its "externally owned"
  hint). With a gate it starts on a fresh page of its own rather than adopting
  every open page, only ever sees pages its session owns, adopts popups whose
  opener it owns (via Playwright's `page.opener()`), and does not
  `bring_to_front`. Handles become CDP target ids. The console and network
  probes are already idempotent (`if (window.__abtConsole) return;`), so N
  sessions registering them on one profile is harmless.
- **`mcp.py`.** `abt mcp --session NAME` (or `ABT_SESSION`) binds the
  connection's session; `Bridge` sends it with every call. No tool exposes
  session management or a `session` parameter.
- **`cli.py`.** Global `--session` option and `ABT_SESSION`; new `abt profile`
  and `abt session` command groups.
- **`recorder.py`, `viewer.py`.** The recorder is unchanged; it is simply given
  a per-session root. The viewer gains a session picker.
- **`schema.py`, `ops/tabs.py`.** New ops `tab_claim` and `tab_release`;
  `tab_list` includes same-profile tabs the session cannot act on; `tab_switch`
  and `tab_close` on one of those raise `tab_locked`.

### Unchanged

The engine, targeting, `dom_diff`, frames, shadow handling, and the behaviour of
every op inside a tab the session owns.

## Profiles

- Stored as directories under the profile root, each with a sibling
  `<name>.json` metadata file (`{"name", "created", "headed"}`). `default`
  always exists; an explicit `abt serve --profile PATH` is used as the default
  profile's directory, as today.
- `abt profile list | new NAME | rm NAME | set NAME --headed/--headless`; HTTP
  `GET /profiles`, `POST /profiles {"name"}`, `PATCH /profiles/NAME`,
  `DELETE /profiles/NAME`.
- Names must match `^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$` (lowercase, no trailing dot: NTFS folds case and drops a trailing dot), and the resolved path
  is asserted to sit inside the profile root before anything is created or
  removed. A name becomes a path, so this is a security check, not tidiness.
- `rm` is refused with `profile_in_use` while any session references the
  profile or its Chrome is running, and refused for `default`. The CLI asks
  for confirmation.

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

Persisted as `sessions/<name>.json` beside the profile root (`<repo>/sessions`
in a checkout, `<data dir>/sessions` when installed). Sessions
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
- Every session starts with no browser connection, exactly as the server does
  today: `browser_start` in a session ensures its profile's Chrome is running
  and connects. `browser_stop` closes the session's own tabs and disconnects;
  Chrome itself is stopped only when no other session is connected to it.
- `browser_start` / `browser_restart` naming a `profile` other than the
  session's are refused with `invalid_op`: a session's profile changes only
  through `session set`, never from inside the session.

### Selecting a session

| Client | Source, in precedence order |
|---|---|
| CLI | `--session NAME`, then `ABT_SESSION`, then `default` |
| HTTP | `session` field in the command body, then `X-ABT-Session` header, then `default` |
| MCP | `abt mcp --session NAME`, then `ABT_SESSION`, then `default`; fixed for the connection |
| Desktop app | Bound by the app's agent loop; never visible to the model |

A name that does not exist is always `unknown_session` — never a silent
fallback to `default`, which would drop a session's restrictions on a typo.

`session` and `token` are transport fields, stripped before a command is
validated. Within one `/command-list` batch, all commands run in one session:
the header, else the envelope's field, else the first item's applies, and an
item naming a different one fails the batch with `invalid_op` before anything
runs.

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
- The token is stored in `sessions/<name>.token` so the app can reconnect
  after a server restart. On POSIX it is created `0600`; on Windows it relies on
  the per-user ACL that `%LOCALAPPDATA%` and the user's home already carry.

The server stores only a hash of the token alongside the session and compares
in constant time.

### Threat model

Sealed sessions protect against: the model in a GUI chat, and any other agent
using abt through CLI, HTTP or MCP. They do **not** protect against a program
running as the same OS user, which can read the token and operator-token files
just as the GUI does. The spec for the desktop app repeats this in the UI.

## Tabs

### Identity

Underneath, a tab is Chrome's **CDP target id**, identical on every connection
to the same Chrome. Callers still see today's `tab_N` ids, but in registry mode
they are allocated by the profile's `TabRegistry` rather than per session, so
every session, the GUI and the screencast agree on which tab is `tab_3`. No
caller-visible id format changes.

### Ownership

- A tab opened by a session (`tab_new`, or the fresh page `browser_start`
  opens for it) is owned by that session from creation.
- A tab opened by the page — popup, `target=_blank`, `window.open` — is owned by
  its opener's owner. Every connection sees every page, so whichever session
  first encounters an unassigned page reads `page.opener()` and hands the
  opener's target id to the registry, which assigns the page to the opener's
  owner. A `tab_claim` of such a page by anyone else is refused with
  `tab_locked`, so there is no window in which another session can take it.
- A tab with no owning opener (pre-existing, or opened by the operator in the
  live view) is **unowned**. A session must `tab_claim` it before acting on it.
- `tab_release` gives a tab up (it becomes unowned).

### Visibility and access

For a session S and tab T:

| T is | `tab_list` | Any action on T |
|---|---|---|
| owned by S | listed | allowed |
| unowned, same profile | listed as `unowned` | only `tab_claim` |
| owned by another session, same profile | listed with `locked: "<owner>"` | `tab_locked` |
| in a different profile | not listed | `tab_not_found` (same as a tab that does not exist) |

A locked tab, sealed session or not, is listed with its owner's name and
nothing else: what is on another session's tab is that session's business.
An unowned tab shows its url and title, since claiming it is the only thing to
do with it.

`tab_new`, `tab_switch` and `tab_close` act only on owned tabs. Each session
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

It also passes the anti-detection flags `_make_options` already uses
(`--disable-blink-features=AutomationControlled`). It reads the chosen port
from `<profile>/DevToolsActivePort`. Remote debugging is permitted because these
are custom user-data directories; Chrome refuses it only on its own default
profile. The browser binary is found with `doctor.find_browsers()`.

In registry mode `default` goes through the same path. The
`launch_persistent_context` branch in `PlaywrightDriver._boot` stays for the
legacy `create_app(browser_session)` path and direct library use.

A profile can be marked `headed` (`abt profile set NAME --headed`) for sites
that misbehave headless. The GUI remains the intended way to see it. Until it
is set, the `default` profile follows `abt serve`'s `--headless` flag, so a
server started the way it always was still shows its window.

### Connections and locks

- Each session gets its own `PlaywrightDriver` in attach mode connected to its
  profile's Chrome, created by the session's `browser_start`. Each driver owns
  its thread (`ThreadPoolExecutor(max_workers=1)`, as today). Because each
  driver's ambient `switch_to` state belongs to its own connection, two
  sessions on one profile cannot retarget each other — the hazard that made the
  superseded design serialize them.
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
  screencast is open on it. The `default` profile is never stopped this way, as
  it was never stopped before sessions existed. A stopped profile stays stopped
  until a session sends `browser_start`.
- If a profile's Chrome dies, its sessions' commands return `browser_dead`,
  and `browser_restart` in any of them relaunches it — explicit, like every
  other start. The existing attach-mode
  `browser_dead` hint ("externally owned, cannot restart") applies only when
  `ABT_CDP_URL` is set; profile-registry browsers get a relaunch hint.
- `/status` names the session it answered for. `GET /profiles` reports each
  profile (running, port, headed, connected sessions) and `GET /sessions` each
  session (profile, sealed, running, owned tab count).

## Logs

- Layout: `logs/sessions/<session>/<run>/events.jsonl` and `.../shots/` — the
  recorder's existing per-run layout, rooted per session. The recorder's own
  field is still called `session_id` and holds the run id; renaming it would
  churn the viewer and the log format for no behavioural gain.
- Events already carry `tab_id` and, for failures, `error_type` — so refusals
  such as `tab_locked` are part of the record with no format change.
- `/logs` routes take the session like every other route; `/viewer` gains a
  session picker.
- Reading a sealed session's logs over HTTP requires its token.
- Legacy mode keeps writing `logs/<run>/` exactly as today.

## Screencast

- `GET /screencast?tab=<tab id>&session=<name>` upgraded to a WebSocket.
- The server opens Chrome's own DevTools WebSocket for that tab
  (`ws://127.0.0.1:<port>/devtools/page/<target id>`) and relays:
  `Page.startScreencast` (JPEG, default quality 60, max width 1600) with
  `Page.screencastFrameAck`; input via `Input.dispatchMouseEvent`,
  `Input.dispatchKeyEvent`, `Input.insertText`. It is a separate DevTools
  client, so watching never contends with a session's own connection. This
  adds `websockets` as a dependency (it is also what gives uvicorn WebSocket
  support).
- Frames stream only while a socket is open. An open socket counts as activity
  for idle shutdown.
- Access: a session's own tabs with that session's token (open sessions need
  none); **any** tab with the **operator token**, including taking over a
  locked one. The operator token is generated at server start and written
  owner-only to `<config>/operator.token`.
- The operator can also release or assign a tab on behalf of a session through
  `POST /tabs/owner {"profile", "tab_id", "session" | null}` with the operator
  token.

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
| `profile_in_use` | Removing a profile a session references or that is running |
| `profile_not_found` | Named profile does not exist |

Malformed names, a batch naming two sessions, and a session-scoped
`browser_start` naming another profile are `invalid_op`, like every other
malformed request.

Hints are written for the agent: `tab_locked` says to open its own tab rather
than retry; `session_sealed` says the session is not addressable from here.

## Compatibility

- A client that never mentions sessions uses `default` on the `default` profile
  and behaves as it does today: explicit `browser_start`, same ops, same
  `tab_N` ids, same responses.
- `create_app(browser_session)` is unchanged, so the existing suite runs as-is
  and does not exercise the registry; new tests cover registry mode.
- `--engine selenium`: `abt serve` uses the legacy path; naming any session
  other than `default` is `unknown_session`.

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
- The existing suite passes unchanged (legacy path).

Per the repo's standing rule, tests are written locally and run by CI on push,
never locally.

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
- **Chrome single-instance handoff.** Launching Chrome on a profile another
  Chrome already holds signals the incumbent and exits. `ensure` detects this
  (no `DevToolsActivePort` appears, process exits) and reports `browser_dead`
  naming the lock, reusing `browser._profile_locked`.
