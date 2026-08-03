# aibrowsertoolkit

A Selenium-backed HTTP server that lets an AI agent drive a real Chrome browser by
sending JSON. The server process is the loop: it opens Chrome with a persistent
profile, stays up waiting for commands, and only stops when you send `shutdown`.

> **Agents: read [`guidelines/toolkit-workflow.md`](guidelines/toolkit-workflow.md)
> before driving anything, and the site playbooks in
> [`guidelines/`](guidelines/README.md) for the site you touch.** They encode
> the concepts and the traps so you skip the trial-and-error.

```
abt serve  ──starts──>  FastAPI :8765  ──owns──>  Chrome (persistent profile)
                             ^
   abt / curl / your agent ──┘   POST /command  |  POST /commands
```

## Install

Needs **Python 3.11+** and **Google Chrome** installed. The matching chromedriver
is resolved automatically by Selenium Manager — nothing to download by hand.

```bash
git clone https://github.com/skssmd/Ai-Browser-Toolkit
cd Ai-Browser-Toolkit

python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
```

Check it worked:

```bash
.venv/Scripts/python -m pytest -q     # 168 tests, needs Chrome
```

The `abt` command lands in the venv. Either activate it
(`.venv\Scripts\activate` / `source .venv/bin/activate`) so `abt` is on your
PATH, or call it explicitly as `.venv/Scripts/python -m abt.cli …` everywhere
below.

## Run

> **Start the server as a separate process.** `abt serve` is the command loop —
> it opens Chrome, listens, and **never returns on its own**. Run it in the
> foreground and it holds that terminal until you shut it down, so an agent or
> script that launches it inline will hang there forever. Background it, or give
> it its own terminal.

```bash
# Linux / macOS — background it and keep the log
nohup abt serve > server.log 2>&1 &

# Windows PowerShell
Start-Process .venv\Scripts\python.exe `
  -ArgumentList "-m","abt.cli","serve" `
  -RedirectStandardOutput server.log -RedirectStandardError server.err -NoNewWindow

# or just give it its own terminal and leave it there
abt serve
```

It is ready when `/status` answers — poll rather than sleeping a fixed amount,
since first launch has to start Chrome:

```bash
until curl -s -m 3 localhost:8765/status > /dev/null; do sleep 1; done
```

Options:

```bash
abt serve --headless                 # no window
abt serve --port 9000                # another port
abt serve --profile ~/work-profile   # another profile
abt serve --no-log --no-diff         # leanest responses
```

Stop it with `abt shutdown` (or `POST {"op":"shutdown"}`), which closes Chrome
and exits the process. `Ctrl+C` works too if it has its own terminal.

Because the server owns exactly one browser, run **one server per browser** —
use `--port` and `--profile` together to run more than one side by side.

The profile directory persists cookies and logins across restarts, and is isolated
from your everyday Chrome. Log in by hand once in the visible window and the session
sticks around — including across a restart to pick up new code.

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

## Diffs: what the last command changed

Every interactive op (`click` `input` `select` `hover` `scroll` `press`
`wait_for` `run_js`) and every navigation op (`goto` `back` `forward` `reload`)
reports what it changed as a `dom_diff` key on its response. The page is
snapshotted before and after; the two snapshots `difflib` into what appeared and
what disappeared. This is the feedback loop — you find out what a command did
without re-fetching the page.

There are two tracks, and they answer different questions.

### The text track — always on

**What appeared on screen.** Every element's own text plus every form control's
live value, collected in document order as separate entries. One element, one
entry: two adjacent labels stay two strings and never merge into a blob, so you
can tell which text belongs to which thing without any markup being present.

```json
{"op": "click", "css": "#products"}
→ {"clicked": "css='#products'", "forced": false, …,
   "dom_diff": {
     "url_before": "https://shop.example/", "url_after": "https://shop.example/",
     "text": {"added": ["Widgets", "Gadgets", "3 items"],
              "removed_count": 1,
              "truncated": false}
   }}
```

This carries no tags, no classes, and no attributes, so it stays small enough to
be unconditional — there is no budget to set and nothing to tune. What it costs
you is state that has no visible text: a `class` flip, an `aria-expanded`
toggle, or a `data-` attribute produces an empty text diff.

**Removals are counted, not listed.** Additions are what you act on — the new
options, the result, the error. What *left* is usually the page you were already
looking at, and on a page that replaces its body the removals are the entire old
document for no benefit. So you get `removed_count` for free, and the strings
themselves only when you ask:

```json
{"op": "click", "css": "#products", "include_removed": true}
→ …, "text": {"added": […], "removed": ["Loading…"], "removed_count": 1, …}
```

The count is there so you can tell when asking is worth it: `removed_count: 1`
after a click is a spinner disappearing, `removed_count: 340` means the page
rewrote itself.

**When the page navigates, you get the page.** A diff against a document that no
longer exists is meaningless, but the question behind it — *what am I looking at
now?* — still has an answer. So `added` becomes the destination's full text
instead of going empty, and you skip the separate read you would otherwise need:

```json
{"op": "goto", "url": "https://shop.example/cart"}
→ {"url": "…/cart", "title": "Your cart",
   "dom_diff": {"navigation": true,
                "note": "text is the full page you landed on, not a diff",
                "text": {"added": ["Your cart", "2 items", "Total: $42", "Checkout"],
                         "removed_count": 18, "truncated": false}}}
```

This covers `goto` `back` `forward` `reload` and any interactive op that
redirected — a `click` that leaves the page returns the page it arrived at. The
element track is skipped in this case, since a unified diff of two unrelated
documents is noise at any budget. `"diff": false` turns it off per command.

Only rendered text counts. An element with `display: none` has not appeared yet,
so a hover that reveals a menu shows up as its items being *added* — which is
usually exactly the event you were waiting for. Password field values are never
captured, since diffs are written to the session log.

### The element track — opt in

**Which element the text belongs to.** Pass `element_diff: true` for the
line-per-element unified diff: tag, id, classes, sorted attributes, own text.
This is the one to reach for when the change was an attribute with no text at
all, or when you need a selector for something the text track just told you
appeared.

```json
{"op": "click", "css": "#insert-menu", "element_diff": true}
→ {…, "dom_diff": {
     "text": {"added": ["Chart", "Pivot table", …], "removed_count": 0, "truncated": false},
     "elements": {"added": 2, "removed": 1, "truncated": false,
                  "diff": "@@ -1 +1 @@\n-div#insert-menu [aria-expanded=\"false\"] …"}
   }}
```

`added`/`removed` are exact counts; `diff` is the unified diff; `truncated`
means it outgrew the token budget — the counts are still right. Budget it with
`diff_max_tokens` per command or `--diff-max-tokens` on the server. Passing
`diff_max_tokens` implies `element_diff: true`, since budgeting something you
never asked for is a typo.

```json
{"op": "click", "css": "#menu", "diff": false}              // no diff at all
{"op": "click", "css": "#menu", "include_removed": true}    // list what left too
{"op": "click", "css": "#menu", "element_diff": true}       // both tracks
{"op": "click", "css": "#menu", "diff_max_tokens": 20000}   // both, generous budget
```

### The manual check

`{"op": "diff"}` diffs the current page against the baseline — the state after
the last command that touched the page. Use it to catch async SPA updates that
land *after* the command that triggered them. Because you asked for it
explicitly, it returns **everything** by default: both tracks, removals listed.

```json
{"op": "diff"}
→ {"baseline": "present", "tab_id": "tab_0", "url_before": "…", "url_after": "…",
   "text": {"added": ["Order confirmed"], "removed": ["Placing order…"],
            "removed_count": 1, "truncated": false},
   "elements": {"added": 3, "removed": 2, "truncated": false, "diff": "…"}}

{"op": "diff", "reset": true}             → baseline is now the current page
{"op": "diff", "element_diff": false}     → text alone
{"op": "diff", "include_removed": false}  → count removals instead of listing them
{"op": "diff", "max_tokens": 500}         → smaller element-diff budget
```

### Two behaviours worth knowing

Every DOM-touching op re-baselines after itself, so the op that caused a change
also consumes it. A manual `{"op": "diff"}` straight after a `click` comes back
empty — the click already reported that change. Each tab keeps its own baseline;
`diff` on a fresh tab sets one instead of failing.

Diffing costs two snapshots per op — roughly **180 ms** on a heavy SPA like
Google Sheets, far less on ordinary pages. Interactively that is invisible;
across a 60-command batch it is about 11 seconds. Use `"diff": false` on the
commands in a batch whose effects you do not care about, `--no-diff` when
running a script you have already debugged, and `"diff": true` to force one back
on when the server default is off.

## Ops

| Group | Ops |
|---|---|
| Navigate | `goto` `back` `forward` `reload` `current_url` |
| Read | `get_html` `get_text` `find` `find_full` `screenshot` |
| Interact | `click` `input` `select` `hover` `scroll` `wait_for` `press` |
| Tabs | `tab_new` `tab_list` `tab_switch` `tab_close` |
| Control | `run_js` `diff` `status` `shutdown` |

`select` drives native `<select>` elements via `by_text`, `value`, or `option_index`.
Custom dropdown navs that only open on mouseover are `hover` then `click`.

### press: keys, named keys, and chords

`press` sends a single character, a named key, or a modifier chord to whatever has
focus (or to a target when one is given):

```json
{"op": "press", "key": "H"}
{"op": "press", "key": "Enter"}
{"op": "press", "key": "ctrl+v"}        // paste from the clipboard
{"op": "press", "key": "ctrl+alt+1"}    // Google Docs: Heading 1
{"op": "press", "key": "shift+enter"}
```

Modifiers combine with `+` and are named `ctrl`/`control`, `shift`,
`alt`/`option`, and `meta`/`command`/`cmd`/`windows`. A chord is one or more
modifiers plus a final key (a single character or a named key). Unknown keys and
modifiers are rejected up front with `invalid_op`.

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
abt diff
abt diff --reset
abt logs
abt shutdown
```

## Tests

```bash
.venv/Scripts/python -m pytest
```

The suite drives a real headless Chrome against static fixture pages served from a
local port — no network, deterministic.
