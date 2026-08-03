# Selenium Browser API — Design

Date: 2026-08-03
Status: Approved

## Purpose

An AI agent needs to drive a real browser: load pages, inspect structure cheaply, click
things, fill fields, manage tabs. It needs to do this across many turns without the
browser restarting between them, and without the agent writing Selenium code itself.

This project provides a long-lived HTTP server that owns one Chrome instance with a
persistent profile. The agent sends JSON commands; the server translates them into
Selenium calls and returns JSON results. The server stays up waiting for more commands
until it receives an explicit `shutdown`.

## Non-goals

- Multiple concurrent browser sessions. One server process owns exactly one browser.
- Remote access. The server binds to loopback only.
- Browsers other than Chrome/Chromium.
- Recording or replaying command sequences.

## Architecture

```
abt serve  ──starts──>  FastAPI :8765  ──owns──>  Chrome (persistent profile dir)
                             ^
   abt exec / curl / AI ─────┘   POST /command  |  POST /commands
```

One Python process. FastAPI holds the HTTP surface; a `BrowserSession` object holds the
Selenium driver, the profile path, and the tab registry. Op handlers are pure functions
of `(session, validated_args) -> result`.

The server process is the command loop. It starts, opens Chrome, and blocks on the port
indefinitely. There is no polling and no busy-wait. `shutdown` quits the driver and
stops the server.

Selenium's WebDriver is not thread-safe. All command execution is serialized behind a
single `asyncio.Lock`; concurrent requests queue rather than interleave.

### Components

| Module | Responsibility | Depends on |
|---|---|---|
| `server.py` | HTTP routes, execution lock, app lifespan | `browser`, `ops`, `schema` |
| `browser.py` | Driver lifecycle, Chrome options, profile, tab registry | selenium |
| `refs.py` | Element ref allocation, lookup, staleness detection | selenium |
| `schema.py` | One pydantic model per op; discriminated union on `op` | pydantic |
| `ops/*.py` | Op handlers grouped by domain | `browser`, `refs` |
| `cli.py` | Thin HTTP client + `serve` entrypoint | httpx, typer |

Each ops module is independently testable: hand it a session and args, assert on the
result. No module reaches into another's internals.

## HTTP API

### `POST /command`

Body is a single command object. Response:

```json
{"ok": true, "result": <op-specific>}
{"ok": false, "error": {"type": "...", "message": "...", "op_index": 0}}
```

### `POST /commands`

Body is either a bare array of command objects, or
`{"commands": [...], "continue_on_error": false}`.

Commands run in order. Default is stop-on-first-error: execution halts, and the response
carries the results collected so far plus the error with its `op_index`.

```json
{"ok": false,
 "results": [{"ok": true, "result": "..."}],
 "error": {"type": "element_not_found", "message": "...", "op_index": 1}}
```

With `continue_on_error: true`, every command runs and each entry in `results` carries
its own `ok`.

### `GET /status`

Returns `{"ok": true, "result": {"url", "title", "tabs", "active_tab", "refs_valid"}}`
without acquiring the lock, so it works while a long command is running.

## Command set

Every command is an object with an `op` field. Unknown ops and malformed args are
rejected by pydantic validation as `invalid_op`, before any browser interaction.

### Targeting

Ops that act on an element accept exactly one of:

| Field | Meaning |
|---|---|
| `ref` | A ref returned by a prior `find` |
| `css` | CSS selector |
| `xpath` | XPath expression |
| `text` | Exact visible text match |

Supplying more than one is `invalid_op`. Supplying none is `invalid_op` except on ops
documented as accepting optional targeting, where it means "the whole document".

When a selector matches multiple elements, acting ops (`click`, `input`, `select`,
`hover`, `scroll`, `press`) use the first match unless `index` is given. Reading ops
(`find`, `find_full`) return every match up to `limit`.

### Navigation

| Op | Args | Result |
|---|---|---|
| `goto` | `url` | `{"url", "title"}` after load |
| `back` | — | `{"url", "title"}` |
| `forward` | — | `{"url", "title"}` |
| `reload` | — | `{"url", "title"}` |
| `current_url` | — | `{"url", "title"}` |

All four navigating ops invalidate the ref cache for the active tab.

### Reading

| Op | Args | Result |
|---|---|---|
| `get_html` | targeting (optional) | Full `outerHTML` of the element, or whole document if untargeted |
| `get_text` | targeting (optional) | Visible text, HTML stripped |
| `find` | targeting (required), `mode`, `limit`, `visible_only` | List of matches |
| `find_full` | targeting (required), `limit`, `visible_only` | Same as `find` with `mode: "full"` |
| `screenshot` | targeting (optional) | `{"format": "png", "base64": "..."}` |

`find` returns:

```json
[{"ref": "el_0", "html": "<div class=\"card\" id=\"p1\"></div>", "visible": true}]
```

- `mode: "shell"` (default) — the element's own tag and attributes only, children and
  text removed. Produced by `element.cloneNode(false).outerHTML` executed in-page.
- `mode: "full"` — `outerHTML` unmodified.

`limit` defaults to 100 and caps the number of matches returned; the response includes
`truncated: true` when matches were dropped. `visible_only` defaults to `false`.

### Interaction

| Op | Args | Behavior |
|---|---|---|
| `click` | targeting | Waits for the element to be present and clickable, then clicks |
| `input` | targeting, `value`, `clear` | Clears (default `true`) then types `value` |
| `select` | targeting, one of `text`/`value`/`index` | Native `<select>` only; errors with `not_a_select` on other tags |
| `hover` | targeting | ActionChains move-to-element; opens hover-triggered menus |
| `scroll` | targeting **or** `y` | Scrolls element into view, or to an absolute y offset |
| `wait_for` | targeting, `state`, `timeout` | Blocks until condition holds |
| `press` | targeting (optional), `key` | Sends a named key (`Enter`, `Tab`, `Escape`, …) |

`wait_for.state` is one of `present`, `visible`, `clickable`, `absent`. `timeout` is in
seconds, default 10, and a breach raises `timeout`.

Custom dropdown navigations — the kind that are not `<select>` — are driven by `hover`
followed by `click`. That pair is sufficient; no dedicated op is needed.

### Tabs

| Op | Args | Result |
|---|---|---|
| `tab_new` | `url` (optional), `activate` | `{"tab_id", "tabs"}` |
| `tab_list` | — | `[{"tab_id", "url", "title", "active"}]` |
| `tab_switch` | `tab_id` | `{"tab_id", "url", "title"}` |
| `tab_close` | `tab_id` (optional, defaults to active) | `{"tabs", "active_tab"}` |

Tab ids are stable strings assigned by the server (`tab_0`, `tab_1`, …) mapped to
Selenium window handles, so ids stay meaningful across switches. `activate` defaults to
`true`. Closing the active tab activates the nearest remaining tab; closing the last tab
is an error (`last_tab`) rather than leaving the session browserless.

Each tab has its own ref namespace. Switching tabs does not invalidate refs in the tab
being left.

### Control

| Op | Args | Result |
|---|---|---|
| `run_js` | `script`, `args` | Whatever the script returns, JSON-serialized |
| `status` | — | Same payload as `GET /status` |
| `shutdown` | — | `{"stopping": true}`, then driver quits and process exits |

`shutdown` returns its response before tearing down, so the caller receives confirmation
rather than a dropped connection.

## Element refs

`find` allocates a ref per match and stores the live `WebElement` in a per-tab cache.
Refs let the agent search once and then act, instead of constructing selectors it may
get wrong.

Refs are invalidated when the tab navigates (`goto`, `back`, `forward`, `reload`) or
when the underlying element goes stale in the DOM. Acting on an invalidated ref returns
`error.type = "stale_ref"`, instructing the agent to re-run `find`. The server never
silently falls back to a different element.

Ref counters are per-tab and reset on navigation, so `el_0` after a `goto` refers to the
new page's first match.

## Error handling

All errors use a closed set of `type` values so callers can branch programmatically:

| Type | Cause |
|---|---|
| `invalid_op` | Unknown op, missing/conflicting args, failed validation |
| `element_not_found` | Selector matched nothing within the wait window |
| `stale_ref` | Ref no longer valid for the current DOM |
| `not_interactable` | Element found but obscured or disabled |
| `not_a_select` | `select` targeted a non-`<select>` element |
| `timeout` | `wait_for` or an implicit action wait expired |
| `navigation_failed` | `goto` could not load the URL |
| `js_error` | `run_js` threw |
| `last_tab` | `tab_close` would leave zero tabs |
| `browser_dead` | Driver crashed or was closed manually |

`browser_dead` is detected by a health check before each command. When it fires, the
server reports it rather than hanging on a dead driver.

Implicit waits are disabled globally. `click`, `input`, `select`, and `hover` apply a
short explicit wait (default 5s, configurable via `--action-timeout`) for presence and
interactability. This avoids Selenium's implicit-wait stalls on every failed lookup.

## Browser configuration

- Profile: a persistent user-data-dir, defaulting to `./profile` in the project
  directory, overridable with `--profile <path>`. Cookies and logins survive restarts.
  The profile is isolated from the user's daily Chrome, so a crash cannot corrupt it.
- Window visible by default. `--headless` runs without a window.
- Chromedriver resolved by Selenium Manager; no manual driver download.
- Server binds `127.0.0.1:8765`; `--port` overrides. No external interface, no auth
  token in v1 — loopback-only binding is the boundary.

## CLI

`abt` is a thin client. Every subcommand maps to an HTTP call.

```
abt serve [--profile PATH] [--port N] [--headless]
abt exec '<json>'                 # POST /command
abt exec-batch <file.json>        # POST /commands
abt goto <url>
abt find <css> [--full] [--limit N]
abt click (--ref R | --css S)
abt input (--ref R | --css S) <value>
abt status
abt shutdown
```

Convenience subcommands exist only for the ops an operator types by hand. Anything else
goes through `abt exec` or curl.

## Testing

- pytest, with a session-scoped headless Chrome fixture.
- Fixture pages are static HTML in `tests/fixtures/`, served by `http.server` on a
  random port. No network access; results are deterministic. Fixtures cover: nested
  cards for shell-vs-full output, a form with text inputs and a native `<select>`, a
  hover-triggered dropdown nav, a page with delayed content for `wait_for`, and a
  multi-link page for tab tests.
- Shell-HTML stripping, schema validation, error-type mapping, and batch stop-on-error
  semantics are unit-tested without a browser.
- Integration tests exercise the full HTTP surface against the live driver, including
  ref staleness after navigation and tab id stability.

## File layout

```
pyproject.toml
src/abt/
  __init__.py
  server.py
  browser.py
  refs.py
  schema.py
  cli.py
  ops/
    __init__.py     # op name -> handler registry
    navigate.py
    read.py
    interact.py
    tabs.py
    control.py
tests/
  conftest.py
  fixtures/*.html
  test_schema.py
  test_refs.py
  test_ops_navigate.py
  test_ops_read.py
  test_ops_interact.py
  test_ops_tabs.py
  test_server.py
```
