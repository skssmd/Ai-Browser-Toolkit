# Browser / Server Decoupling — Design

Date: 2026-08-19
Status: Approved

## Purpose

The server process and the browser it drives currently live and die together.
`cli.serve` builds a `BrowserSession`, calls `session.start()` — which blocks for
up to two minutes launching Chrome on the persistent profile — and only then
constructs the FastAPI app and hands control to uvicorn. Chrome is a child of
chromedriver, which is a child of the server.

Two failures follow from that coupling, and both are routine rather than
exotic:

1. **A browser death is terminal.** `session.quit()` sets `_driver = None`, and
   the `driver` property then raises `browser_dead` for every subsequent
   command, forever. Nothing in the codebase can launch a replacement. The only
   recovery is killing the server and starting a new one, which throws away the
   session log, the tab registry, and the readiness the caller already paid two
   minutes for.
2. **Starting the server wedges the agent that starts it.** `abt serve` never
   returns. `start-server.bat` and `start-server.sh` exist to work around this
   and launch it detached, but both leave the new process a child inside the
   caller's console and job object (`start /MIN cmd /c` on Windows; `nohup … &`
   in bash, where Git Bash has no `setsid`). A harness that waits on the process
   group or holds a job handle — opencode, observed — still blocks. Redirecting
   stdio does not escape a job object.

This design makes the browser a resource the server *manages* rather than a
precondition it *requires*. The server starts in about a second with no browser
at all, and gains an explicit lifecycle API to launch, stop, and relaunch one on
demand. Separately, it adds a launcher that spawns the server outside the
calling process's job object.

## Non-goals

- **Chrome outliving the server.** Attaching to a separately launched Chrome
  over `--remote-debugging-port` / `debuggerAddress`, so tabs survive a server
  restart, was considered and rejected for this spec. It carries a real unknown
  (whether `driver.quit()` closes an attached browser) and is not needed for
  either failure above.
- **Automatic recovery.** A dead browser is not silently relaunched, and no
  command is ever retried against a replacement. See "Recovery policy".
- **Multiple concurrent browsers.** One server still owns at most one browser.
  This spec changes that count from exactly-one to zero-or-one, not to many.
- **The packaged application and installer.** Parked in `docs/TODO.md`, and
  deliberately sequenced behind this work: its headline feature is an opt-in
  always-on logon task, which is only sane once the server starts without
  launching a browser.

## Recovery policy

**Explicit only.** When the browser is absent — never started, stopped, or
crashed — every page-driving command returns `browser_dead` and keeps returning
it until someone calls `browser_start`. The server never relaunches on its own
and never replays a command.

The rejected alternative was relaunching transparently on a failed health check.
It reads as convenient and is not: the replacement browser opens a blank tab, so
a `click` or `input` that triggered the relaunch either fails again or acts on
something unintended. A `goto` would appear to succeed while silently having
discarded the session's entire tab and login state. Predictability is worth more
here than the round trip it saves, because the caller is usually an agent that
will otherwise narrate a success it did not have.

The cost of this choice is that the `browser_dead` **message** becomes the whole
of the recovery interface. It is specified accordingly below.

## Architecture

Three pieces change shape. Nothing moves between files except the launch
parameters.

```
LaunchConfig      what to launch          browser, profile, headless
BrowserSession    how to drive it         everything else, plus start/stop/restart
server/cli        when to launch it       lifecycle routes, ops, and abt up
```

### Why the session object is mutated rather than replaced

The alternative considered was a `SessionManager` handing out a fresh
`BrowserSession` per launch, which separates lifecycle from page-driving more
cleanly. It was rejected on a concrete ground, not on diff size: `create_app`
closes over `session` in nine places and `messenger.py` takes it as a parameter
in twenty-seven more. Under a manager, every one of those references would hold
a **stale** session object after a restart, so correctness would require routing
each one through a `manager.current()` indirection.

Keeping one `BrowserSession` for the server's lifetime, with a swappable driver
underneath it, makes object identity stable and every existing reference correct
by construction. The state that must be discarded on stop is already enumerated
inside `_sync_tabs`, so the reset is small and unit-testable with no browser.

## `LaunchConfig`

A frozen dataclass holding the only parameters that describe the browser process
itself:

| Field | Default | Notes |
|---|---|---|
| `browser` | `"chrome"` | `chrome` or `edge`; validated here |
| `profile` | `./profile` | expanded and resolved to an absolute path |
| `headless` | `False` | |

The `bad_browser` validation moves here from `BrowserSession.__init__`, so an
invalid browser is rejected identically whether it arrives from `abt serve` or
from `POST /browser/start`.

`merge(**overrides) -> LaunchConfig` returns a new config with only the supplied
fields replaced; fields absent or `None` keep their current value. That one
method is the entirety of the "serve flags are defaults, per-start calls
override them" behaviour.

**What deliberately stays on the session:** `action_timeout`, `diff_enabled`,
`diff_max_tokens`, `settle_timeout`, `settle_network_grace`, `frames_enabled`,
`max_frames`, `max_frame_depth`. These are behaviour knobs that hold regardless
of which browser is up. Keeping that boundary sharp is what prevents
`/browser/start` from accreting into a second copy of `abt serve`'s flag list.

## `BrowserSession` lifecycle

`__init__` no longer launches anything. It takes a `LaunchConfig` as the
session's defaults, stores it as `self.defaults`, sets `self.launch = None`, and
leaves `_driver = None`.

`self.browser`, `self.profile`, and `self.headless` become read-through
properties over the effective config (`self.launch or self.defaults`), so
existing readers — `_make_options`, `session_status`, tests — keep working
unchanged.

### `start(**overrides) -> dict`

Raises `invalid_op` if a browser is already running. **Not idempotent, on
purpose:** silently no-op'ing a start that named a different `profile` would
hand back a session on the wrong identity with no way to tell. A caller that
genuinely wants "running, whatever it takes" calls `restart`.

Merges overrides into `self.defaults`, stores the result as `self.launch`,
launches the driver, applies `implicitly_wait(0)`, installs console capture, and
syncs tabs — the existing body of `start`, unchanged apart from taking its
parameters from the config.

### `stop() -> dict`

Quits the driver, swallowing `WebDriverException` as `quit()` already does, then
runs `_reset_state()`. Safe to call when nothing is running; reports whether
there was anything to stop.

Stopping is not complete when `quit()` returns — see "Releasing the profile"
below.

### Releasing the profile

`guidelines/toolkit-workflow.md` already records this hazard for the manual
restart path: *if a Chrome is still holding the toolkit profile, the fresh
Chrome hands off to it and the new session dies immediately.* Chrome
single-instances per `--user-data-dir`; a second launch against a locked profile
does not open its own browser, it signals the incumbent and exits, and
chromedriver is left with a session that dies on first use.

`driver.quit()` returns once chromedriver has been told to go away, which is
before the Chrome process has exited and released the lock. A `restart` that
launches immediately therefore hits this window essentially every time — it is
the common path, not an edge case.

Handled in two halves — prevention on the way out, detection on the way in.

**Prevention, in `stop()`:**

1. Quit the driver.
2. Poll the profile's singleton lock files until they are gone, bounded to a
   few seconds.
3. If the timeout expires, `stop()` still succeeds and clears state — it did
   what it was asked — but reports `profile_released: false` in its result and
   in the session log.

**Detection, in `start()`:** after the driver comes up, probe it once
(`window_handles` plus `current_url`). A browser that handed off to an incumbent
leaves chromedriver holding a session that dies on first use, so the probe is
what actually distinguishes the two outcomes. On failure, quit the driver, reset
state, and raise `browser_dead` naming the profile hand-off as the likely cause
and the stale process as the thing to close.

**`start()` deliberately does *not* refuse on the lock file's presence.** A
hard-killed Chrome leaves its lock behind as a *stale* file, and Chrome's own
recovery is to inspect the hostname and pid encoded in it rather than to trust
its existence. Gating startup on the file would make the post-crash case — the
one where you most need to start a browser — permanently unstartable, which is
exactly backwards. Probing after launch cannot false-positive that way: it tests
the session that actually exists.

The lock poll in `stop()` is therefore an optimisation, not a guarantee, and a
stale lock there costs a bounded wait and an honest `profile_released: false`.
Nothing downstream refuses to act on that flag.

### `restart(**overrides) -> dict`

`stop()` then `start()`, with overrides layered onto the **currently effective**
config rather than the serve-time defaults. Restarting a session that was
started headless keeps it headless; restarting one started on a throwaway
profile stays on that profile. Passing no overrides means "the same browser
again", which is what the word restart should mean.

If the browser is not currently running, `restart` behaves as `start` rather
than failing — this is the "just make it work" entry point.

### `is_running` and `quit()`

`is_running` is `self._driver is not None`. `quit()` remains as an alias for
`stop()` so `tests/conftest.py:81` and `server.teardown` do not change meaning.

### `_reset_state()`

Clears exactly what is tied to a live driver, and nothing else:

`_handles`, `_order`, `_counter` (back to `0`, so a fresh browser starts at
`tab_0`), `_captured`, `_baselines`, `refs`, `last_target`, `_in_frame`.

Config, behaviour knobs, and the recorder are untouched — the session log spans
the server's life and must survive a browser restart, since a crash and its
recovery are among the more interesting things a log can hold.

## Error semantics

**No new error type.** `browser_dead` stays the single type for "you cannot
drive the page right now". It is already documented in `README.md:620`,
`AGENTS.md:128`, and `guidelines/toolkit-workflow.md:332`, and a second name for
a condition with an identical remedy would only force every existing error
branch to learn it.

The **message** changes, because under explicit-only recovery it is the entire
recovery interface. Today's `"browser is not running"` is a dead end. It must
name the remedy and distinguish the two ways of arriving there:

- Never started or explicitly stopped:
  `no browser is running; start one with {"op": "browser_start"} or POST /browser/start`
- Was running and became unreachable:
  `browser is no longer reachable: <driver message>; relaunch it with {"op": "browser_restart"} or POST /browser/restart`

The distinction is informational — both remedies work in both states — but a
crash and a clean stop are different events and an agent reading the log deserves
to see which one it hit.

## Ops

Four new ops, added to `schema.py`, implemented in `ops/control.py`, and
registered in `ops/__init__.py`:

| Op | Parameters | Returns |
|---|---|---|
| `browser_start` | `browser`, `profile`, `headless` — all optional | effective config, `active_tab` |
| `browser_stop` | — | `{"stopped": bool}` |
| `browser_restart` | same as `browser_start` | effective config, `active_tab` |
| `browser_status` | — | `{"running": bool, "config": {...}}` |

All four join `NO_HEALTH_CHECK`. Gating a command whose entire job is to fix the
browser behind a check that requires a working browser is exactly the bug the
existing comment beside `shutdown`/`status` describes.

They are **not** added to `DIFFABLE_OPS`, `NAVIGATION_OPS`, or
`DOM_TOUCHING_OPS`. `browser_start` does land on a blank tab, but there is no
prior state to diff it against and `_reset_state` has just dropped every
baseline.

## HTTP API

### `POST /browser/start`, `POST /browser/stop`, `POST /browser/restart`

Thin wrappers that build the corresponding op and run it through the existing
`execute` path, so they are serialized under the same command lock and recorded
by the same logger as everything else. A start racing an in-flight command
therefore waits rather than launching Chrome underneath it.

`start` and `restart` accept an optional JSON body of `{browser, profile,
headless}`; an absent or empty body means "use the defaults".

### `GET /browser`

Lifecycle state, answerable with no browser present:

```json
{
  "running": false,
  "config":   {"browser": "chrome", "profile": "…", "headless": true},
  "defaults": {"browser": "chrome", "profile": "…", "headless": false}
}
```

Two keys, because one cannot answer both questions. `config` is the
**effective** config — what is running now, or what ran most recently, which is
also what a bare `browser_restart` will use. `defaults` is what `abt serve` was
given, which is what a bare `browser_start` will use.

That difference between `start` and `restart` after a stop is deliberate and
worth stating plainly: **`browser_start` means "fresh, from the server's
defaults"; `browser_restart` means "that same browser again"**. A session
started headless and then stopped comes back headless under `restart` and
windowed under `start`. Reporting both keys is what makes that predictable
rather than a surprise.

### `GET /status` — gains `running`

`session_status` currently calls `session.tabs()` and `session.driver.current_url`,
both of which raise when no browser is up. This matters beyond tidiness:
`/status` is the readiness probe both start scripts poll and the one `abt up`
will poll, so a `/status` that errors whenever no browser is up makes a
perfectly healthy lazy server look broken to its own launcher.

`/status` gains a `running: bool` that is always present. Every existing key —
`url`, `title`, `active_tab`, `tabs`, `refs_valid`, `headless`, `profile` — is
kept and reported when running. When not running, the response is
`{"running": false, "config": {...}}` with `ok: true`.

**Known compatibility risk:** a caller that checks `ok: true` and reads `url`
without consulting `running` will now see the key missing rather than an error.
Accepted, because the alternative — a `/status` that fails on a healthy
server — is worse, and because the readiness use case is served by `/health`
below rather than by `/status` at all.

### `GET /health`

Answers `{"ok": true, "running": <bool>}` unconditionally, touching neither the
driver nor the command lock. This is what launchers and readiness polls should
use: it is true when the *server* is up, which is the question they are actually
asking. Existing `/status` polling in the start scripts moves here.

## CLI

### `abt serve`

Stops calling `session.start()`. Existing `--browser`, `--profile`, and
`--headless` flags become the `LaunchConfig` defaults rather than launch
instructions.

Gains `--start-browser/--no-start-browser`, defaulting to **off**. The old
behaviour — a server that comes up with Chrome already open — is one flag away
for anyone who wants it.

`_choose_browser`'s interactive prompt becomes a way of setting the default for
later `browser_start` calls rather than a gate on the server booting. Its
existing non-tty guard stays as is.

Startup output changes to say plainly that no browser is running and how to
start one, since that is now the expected steady state on boot.

### `abt up`

A new subcommand that ensures a server is running and **returns immediately**,
never blocking. This is the piece that fixes the wedging.

- **Windows:** spawn the server through a third party so its parent is a
  Windows service rather than the calling shell, placing it outside the caller's
  job object. Task Scheduler (`schtasks /create … /run`) is the primary path;
  WMI `Win32_Process.Create` is the fallback. `DETACHED_PROCESS |
  CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB` is *not* relied on:
  breakaway silently fails when the enclosing job forbids it, which is precisely
  the case this needs to survive.
- **POSIX:** double-fork with `setsid`, stdio redirected to the log files.

It then polls `GET /health` briefly — a second or two, not the current 180, now
that no browser launch is in the path — and reports whether the server answered.

`start-server.bat` and `start-server.sh` keep their dependency-bootstrap
responsibility (create the venv, `pip install -e .` when imports fail) and
delegate the launch itself to `abt up`. Their `--status` mode moves to
`GET /health`.

## MCP

One new tool, `browser_session`, with an `action` enum of
`start` / `stop` / `restart` / `status` and optional `browser`, `profile`, and
`headless`.

`mcp.py` notes that tool definitions are re-sent every turn at a measured ~2,661
tokens per session, and that each must earn its place by preventing a wrong
call. This one does: recovering from a dead browser unaided is the entire point
of the work, and the existing alternative is `browser_raw`, an unvalidated
pass-through — exactly the shape of call the module's own docstring documents
models getting wrong five times in sixty-six commands.

## Testing

Most of this is testable without launching a browser at all, which is a
meaningful gain in coverage per second for a suite that currently needs Chrome
for nearly everything.

**Unit, no browser:**
- `LaunchConfig` validation, and that `merge` replaces only supplied fields
  while `None` and absent both mean "keep".
- `_reset_state()` clears every driver-tied field, asserted field by field so a
  future field added to `__init__` and forgotten here shows up as a failure.
- `restart` layers overrides onto the effective config, not the defaults.

**Server routes against a never-started session, via `TestClient`:**
- `GET /health` answers `ok` with `running: false`.
- `GET /status` answers `ok` with `running: false` and no `url` key.
- `GET /browser` reports the defaults.
- `POST /command {"op": "goto"}` returns `browser_dead` whose message names
  `browser_start`.
- `browser_start` on an already-running session returns `invalid_op`.

This requires a fixture for an unstarted session, which the current
`conftest.py` does not have — `session` starts the browser eagerly. Added
alongside, not in place of it; the existing fixture calls `browser.start()`
explicitly and keeps working.

**Live, headless:**
- start → `goto` → stop → `status` shows `running: false` → start → `goto`,
  asserting that tab ids restart at `tab_0` and that refs from before the stop
  are gone.
- **Back-to-back `browser_restart` twice, then `goto`.** This is the regression
  test for the profile hand-off: without the wait in `stop()` the second browser
  attaches to the dying first one and the `goto` fails. It is the one live test
  that must not be skipped, because the hazard it covers is the common path
  rather than an edge case, and because it fails in a way that looks like a
  flaky network rather than a lifecycle bug.

**`abt up`:** the spawn mechanism is platform-specific and not unit-testable in
a useful way. Covered by an integration check that `abt up` returns in under a
few seconds and that `GET /health` answers afterwards, skipped when a server is
already running on the port.

## Documentation

- `README.md` — ops table, the `browser_dead` entry, and the lifecycle section.
- `AGENTS.md` — the error list, and the startup story.
- `CLAUDE.md` / global instructions — "check `GET /status` first" becomes
  `/health` for liveness and `/browser` for whether a browser is up.
- `guidelines/toolkit-workflow.md`, "A tab that closes itself takes the session
  with it" — **the most important single edit.** It currently tells agents that
  once the active tab self-closes, *"the only way back is `{"op":
  "shutdown"}` … followed by `start-server.sh` / `start-server.bat`"*. That
  becomes false: the way back is `browser_restart`, with no server bounce and no
  lost session log. Left alone it is the line most likely to keep an agent stuck
  after this ships. Its following paragraph — on making sure no Chrome still
  holds the profile — stops being the reader's problem and becomes `stop()`'s,
  per "Releasing the profile" above.
- `docs/known-issues.md` entry 4 (`/status` returned a raw 500) — **not**
  superseded; its fix stays correct and `/status` must still answer on a dead
  browser. What changes is the sentence about the process having to be killed by
  hand. Worth a short note that the recovery is now `browser_restart`.

## File layout

```
src/abt/launch.py      new    LaunchConfig
src/abt/browser.py     edit   lifecycle: start/stop/restart/is_running/_reset_state
src/abt/schema.py      edit   four new command models
src/abt/ops/control.py edit   four new handlers
src/abt/ops/__init__.py edit  registry entries, NO_HEALTH_CHECK
src/abt/server.py      edit   /browser/*, /health, /status running flag
src/abt/cli.py         edit   serve no longer starts; abt up
src/abt/mcp.py         edit   browser_session tool
src/abt/proc.py        new    detached spawn, per platform
tests/                 new    unit + unstarted-session fixture + one live test
```
