# aibrowsertoolkit

A Selenium-backed HTTP server that lets an AI agent drive a real Chrome browser by
sending JSON. The server process is the loop: it opens Chrome with a persistent
profile, stays up waiting for commands, and only stops when you send `shutdown`.

```
abt serve  ──starts──>  FastAPI :8765  ──owns──>  Chrome (persistent profile)
                             ^
   abt / curl / your agent ──┘   POST /command  |  POST /commands
```

## Install

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
```

Chrome must be installed. The driver is resolved automatically by Selenium Manager.

## Run

```bash
abt serve                        # visible window, profile in ./profile
abt serve --headless --port 9000 # no window, different port
abt serve --profile ~/work-profile
```

The profile directory persists cookies and logins across restarts, and is isolated
from your everyday Chrome. Log in by hand once in the visible window and the session
sticks around.

## Send commands

One command:

```bash
curl -s localhost:8765/command -H 'content-type: application/json' \
  -d '{"op":"goto","url":"https://example.com"}'
```

A list, run in order:

```bash
curl -s localhost:8765/commands -H 'content-type: application/json' -d '[
  {"op":"goto","url":"https://example.com"},
  {"op":"find","css":"a"},
  {"op":"click","ref":"el_0"},
  {"op":"get_text","css":"h1"}
]'
```

Every response is `{"ok": true, "result": ...}` or
`{"ok": false, "error": {"type", "message", "op_index"}}`.

Batches stop at the first failure by default. Send
`{"commands": [...], "continue_on_error": true}` to run them all regardless.

## Two ways to read a page

`find` returns element **shells** — each match's own tag and attributes, with all
children and text stripped. This is how an agent surveys page structure without
paying for the content:

```json
{"op": "find", "css": ".card"}
→ {"count": 3, "matches": [
     {"ref": "el_0", "html": "<div class=\"card\" id=\"p1\"></div>", "visible": true}
   ]}
```

`find_full` (or `{"mode": "full"}`) returns the same matches with everything inside:

```json
{"op": "find_full", "css": ".card"}
→ {"matches": [{"ref": "el_0", "html": "<div class=\"card\" id=\"p1\"><h2>Cheap Widget</h2>…"}]}
```

## Element refs

Every `find` match gets a `ref` (`el_0`, `el_1`, …). Act on it directly instead of
writing another selector:

```json
{"op": "find",  "css": "button.buy"}
{"op": "click", "ref": "el_0"}
```

Refs die when the tab navigates or the element leaves the DOM. Using a dead ref
returns `stale_ref` telling you to search again — it never quietly hits a different
element. Each tab keeps its own refs.

## Targeting

Ops that touch an element take exactly one of `ref`, `css`, `xpath`, or `text`
(exact visible text). When a selector matches several elements, acting ops use the
first unless you pass `index`.

## Ops

| Group | Ops |
|---|---|
| Navigate | `goto` `back` `forward` `reload` `current_url` |
| Read | `get_html` `get_text` `find` `find_full` `screenshot` |
| Interact | `click` `input` `select` `hover` `scroll` `wait_for` `press` |
| Tabs | `tab_new` `tab_list` `tab_switch` `tab_close` |
| Control | `run_js` `status` `shutdown` |

`select` drives native `<select>` elements via `by_text`, `value`, or `option_index`.
Custom dropdown navs that only open on mouseover are `hover` then `click`.

### Clicking past an overlay, and opening in a new tab

Ad networks park a transparent div at max z-index over the whole page, so the
first click anywhere is swallowed. `click` reports that as `not_interactable` and
names the intercepting element. Two opt-ins deal with it:

```json
{"op": "click", "css": "a.result", "force": true}     → dispatches a JS click
{"op": "click", "css": "a.result", "new_tab": true}   → opens the href beside you
```

`force` only defeats occlusion. Hidden and disabled targets are ruled out before
it engages, so it never fakes input a user could not have given. The result says
`"forced": true` only when the fallback actually fired.

`new_tab` reads the target's `href` and opens it in a fresh tab, returning its
`tab_id`. Nothing is clicked, so an overlay is irrelevant — which makes it the
cleaner answer of the two when the target is a link. Add `"activate": false` to
open it in the background. The two flags are mutually exclusive.

```bash
abt click --css "a.result" --force
abt click --css "a.result" --new-tab --background
```

`GET /ops` lists them live; `GET /status` reports the current URL, open tabs, and
live ref count without waiting for a running command to finish.

### Errors

A closed set, so you can branch on `error.type` instead of parsing prose:

`invalid_op` `element_not_found` `stale_ref` `not_interactable` `not_a_select`
`timeout` `navigation_failed` `js_error` `last_tab` `tab_not_found` `browser_dead`

A failed page load is caught even though Chrome reports success for it — Chrome
renders its own error page, and `goto` raises `navigation_failed` rather than
letting an agent read that page as if it were the site.

## Session logs

Every command is recorded to `./logs/<session-id>/events.jsonl` — one line per
command, holding what ran, what came back, which tab it ran in, and which site was
loaded at the time. One session per server run.

JSONL rather than a JSON array so a killed server still leaves every line up to the
kill readable. Long strings are truncated with a marker, so a `get_html` of a big
page doesn't bloat the log. Logging can never fail a command: recorder errors are
swallowed.

```bash
abt serve --log-dir ./logs   # default
abt serve --no-log           # off
```

**Browse them in the browser** at `http://127.0.0.1:8765/viewer` — a self-contained
page that lists sessions and sites down the side, and each command with its request
and response expandable. Filter by tab, site, op, or errors only.

**Or over the API:**

| Endpoint | Returns |
|---|---|
| `GET /logs` | Every session, newest first, with event and error counts |
| `GET /logs/sites` | Every site seen across all sessions |
| `GET /logs/{session_id}` | That session's events |

`/logs/{session_id}` accepts `?site=`, `?tab=`, `?op=`, and `?errors_only=true`,
which combine.

```bash
abt logs                              # list sessions
abt logs --sites                      # list sites
abt logs 20260803-061843              # one session
abt logs 20260803-061843 --errors     # just the failures
abt logs 20260803-061843 --site example.com --tab tab_1
```

An event looks like this:

```json
{"seq": 4, "at": "2026-08-03T05:18:49Z", "session_id": "20260803-061843",
 "tab_id": "tab_0", "site": "example.com", "url": "https://example.com/",
 "op": "click", "ok": false, "error_type": "element_not_found",
 "duration_ms": 5190.7,
 "request": {"op": "click", "css": "#does-not-exist"},
 "response": {"type": "element_not_found", "message": "nothing matched …"}}
```

## CLI

`abt` is a thin client over the same API; anything it does, curl can do.

```bash
abt goto https://example.com
abt find "a.product" --limit 20
abt find "a.product" --full
abt click --ref el_0
abt input "hello" --css "#search"
abt exec '{"op":"select","css":"#size","by_text":"Large"}'
abt exec-batch steps.json --continue-on-error
abt tabs
abt status
abt logs
abt shutdown
```

## Tests

```bash
.venv/Scripts/python -m pytest
```

The suite drives a real headless Chrome against static fixture pages served from a
local port — no network, deterministic.
