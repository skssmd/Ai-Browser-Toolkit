# aibrowsertoolkit

A Selenium-backed HTTP server that lets an AI agent drive a real browser — **Chrome or Edge** — by
sending JSON. The server process is the loop: it opens the chosen browser with a persistent
profile, stays up waiting for commands, and only stops when you send `shutdown`.

> **Agents: read [`guidelines/toolkit-workflow.md`](guidelines/toolkit-workflow.md)
> before driving anything.** Not "if your site looks tricky", not "if there is a
> playbook for it" — always. Most sites have no playbook, and that file is the
> whole answer for them. Then, only if one exists, add the site playbook from
> [`guidelines/`](guidelines/README.md).
>
> Skipping it costs you the things that are hard to guess: that `find` hands
> back refs you act on directly, that a click already reports what changed so
> you need not re-read the page, and that ops can be sent in batches.


```
abt serve  ──starts──>  FastAPI :8765  ──owns──>  Chrome/Edge (persistent profile)
                             ^
   abt / curl / your agent ──┘   POST /command  |  POST /commands
```

## Install

Needs **Python 3.11+** and **Google Chrome** or **Microsoft Edge** installed. The matching
chromedriver/msedgedriver is resolved automatically by Selenium Manager — nothing to download by hand.

```bash
git clone https://github.com/skssmd/Ai-Browser-Toolkit
cd Ai-Browser-Toolkit

python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
```

Check it worked:

```bash
.venv/Scripts/python -m pytest -q     # 300 tests, needs Chrome
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

**The safe way — use the start script.** It does the whole dance for you and is
the only thing an agent or CI job should call:

```bash
./start-server.sh              # Linux / macOS / Git Bash / WSL
start-server.bat               # Windows cmd
```

It no-ops if a server is already running, creates `.venv` and installs
dependencies only when they are missing, launches the server detached with its
output redirected to `server.log` / `server.err`, then polls `/status` and exits
0 once the server answers (waiting up to 180s, since a cold Chrome on the
persistent profile is slow). Exit 1 means it never came up — it prints the tail
of `server.err`; exit 2 means dependencies failed.

```bash
./start-server.sh --status     # only report up/down, start nothing (exit 0 = up)
./start-server.sh --no-wait    # launch and return immediately, skip polling
./start-server.sh --browser edge --port 9000 --headless   # extra flags go to `abt serve`
```

A server on a non-default port writes `server-<port>.log` instead, so starting
one never clobbers the logs of the server on 8765.

**By hand,** if you prefer. Detaching is not enough on its own — redirect the
output too, or the launching process keeps waiting on the inherited pipe:

```bash
# Linux / macOS — background it and keep the log
nohup abt serve --browser chrome > server.log 2>&1 &

# Windows PowerShell
Start-Process .venv\Scripts\abt.exe `
  -ArgumentList "serve","--browser","chrome" `
  -RedirectStandardOutput server.log -RedirectStandardError server.err

# or just give it its own terminal and leave it there
abt serve --browser chrome
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
abt serve --settle-timeout 10        # give a slow SPA longer to render
abt serve --no-frames                # stop reading inside iframes
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

## Messenger

Driving `messenger.com` through the generic ops takes a dozen round trips and
the order matters — a stale draft glued to your text, an Enter that fires
before the upload finished. That sequence is packaged as its own endpoints:

```bash
curl -s localhost:8765/messenger/sendmessage -H 'content-type: application/json' -d '{
  "thread_url": "https://www.messenger.com/t/927345869967156/",
  "message": "@Yaleed @Samin here is the capture",
  "mentions": ["Yaleed", "Samin"],
  "attachments": ["C:/shots/page.png", "https://example.com/logo.png"],
  "reply_to": "Step 1/4 DONE"
}'
```

`mentions` are real @-mentions: each name must appear in `message` as
`@<name>`, and that spot is typed through Messenger's suggestion popup, so
`@Yaleed` lands as `@Yaleed Haque`. `attachments` take local paths or http(s)
links, which are downloaded first. `reply_to` is a substring of the message
you are answering, or an index into the thread.

Every failure raises **before** Enter is pressed — an attachment that never
staged, a mention with no suggestion — so a bad send stays a draft instead of
going out wrong.

`POST /messenger/sendmessage/async` answers immediately with a `job_id` and
does the work in a new tab that it closes afterwards, leaving your current tab
untouched. Poll `GET /messenger/jobs/{id}`.

Reading:

```bash
curl -s 'localhost:8765/messenger/threads?url=https://www.messenger.com/'
curl -s 'localhost:8765/messenger/messages?thread_url=…&since_last=true'
```

`/messenger/threads` gives each thread's name, preview, time, and URL.
`/messenger/messages` parses rows into `{sender, time, text}`; `since_last=true`
returns only what arrived since your last read of that thread — matched by
content, not position, because Messenger trims the top of a long thread as it
grows.

Full details and the traps behind them: [guidelines/messenger.md](guidelines/messenger.md).

## Console and network

The DOM cannot tell you why a request failed. These can:

```bash
curl -s localhost:8765/command -d '{"op":"read_network","failures_only":true}'
curl -s localhost:8765/command -d '{"op":"read_console","levels":["error"]}'
```

`read_console` captures from **document start**, so a reload hands back what the
page logged while loading — uncaught errors and unhandled rejections included.
`read_network` returns each request with its status, duration, and size;
`failures_only` keeps the 4xx/5xx and anything the browser would not disclose.
Both take a `pattern` regex.

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

Numbering does **not** restart after a navigation: the counter runs for the tab's
life, so `el_0` never means two different elements. That is what makes the
guarantee above true — if numbering restarted, the new page's `el_0` would answer
to a handle you were still holding for the old one. Expect the numbers to climb
over a long session.

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

There are three tracks, and they answer different questions.

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
instead of going empty, and you skip the separate read you would otherwise need.

The page is **waited for** first. `driver.get` returns when the *document* has
loaded, which on a single-page app is the moment a spinner mounts and nothing
else has rendered — so without this the diff reported `Loading dashboard…` /
`Please wait while we process your request` as though that were the page, and an
agent learned to distrust it and re-read the body every time. Navigation now
settles on two signals before snapshotting: **no request in flight** (a slow
fetch holds the DOM perfectly still, so a DOM-only check would call the spinner
"done") and **a DOM that has stopped changing** (which catches a render that
owes nothing to the network). A page that never stops — a poller, a clock —
costs `--settle-timeout` and then proceeds, because a late diff beats no diff.

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
{"op": "click", "css": "#menu", "actionable": false}        // skip refs and roles
```

### The actionable track — on by default

**Which of what appeared you can actually click.** The text track hands you
strings. A string is not addressable, so acting on one used to mean a `find` to
turn it back into an element. This closes that gap: the interactive elements
among the additions come back with their role, their name, and a **ref**.

```json
{"op": "click", "css": "#insert-menu"}
→ {…, "dom_diff": {
     "text": {"added": ["Chart", "Pivot table", "Macro"], "removed_count": 0},
     "actionable": {"added": [
       {"ref": "el_7", "role": "menuitem", "name": "Chart"},
       {"ref": "el_8", "role": "menuitem", "name": "Pivot table"},
       {"ref": "el_9", "role": "button", "name": "Macro", "disabled": true}
     ], "truncated": false}
   }}

{"op": "click", "ref": "el_8"}     ← act on it directly; no find in between
```

`role` is the ARIA role, explicit if the element declares one and implicit from
the tag otherwise. `name` is the accessible name — `aria-label`, then
`aria-labelledby`, then the associated `<label>`, then the element's own text.
`disabled` appears only when the control is disabled, so you can tell "it showed
up but you cannot use it yet" from "it is ready".

**Text is the anchor.** Every entry's `name` is a string the text track reported
in the same response, so the two always line up. A control with **no** accessible
name is dropped entirely rather than handed back as a nameless ref — an entry
you cannot tie to something you have read is noise.

**It does not run after a navigation.** On a new document every control is new,
so the diff would degenerate into an inventory of the whole page — which the
text track already returned in full, and which would burn a ref on every control
to say it. Use `find` when you land somewhere; use this when something appeared.

**Uploads are the one exception to "must be rendered".** The standard pattern
hides the real `<input type=file>` behind a custom control that validates or
resizes, so the element you must send a path to is never the one on screen. File
inputs are therefore reported even when invisible, with `role: "file"`, a name
taken from their `<label>` (falling back to `name` or `id`), and `multiple: true`
when they accept more than one. `input` writes to them hidden:

```json
{"op": "input", "css": "#upload", "value": "C:/shots/page.png"}
```

**What it costs.** Unlike the text track this one is not free: about a quarter
again on top of a diffed op, and more when controls actually appear. Turn it off
per command with `"actionable": false` for the steps in a batch whose new
controls you will never click.

### Frames — on by default

**A frame is a separate document, and everything reads straight through it.**
All three tracks, plus `find`, `get_text` and every selector, cover the frames a
page embeds as well as the page itself. Refs from inside one act normally; the
toolkit remembers which document each came from and goes back there.

This exists because the alternative is silence. On `linkedin.com/login`, Google
draws **Continue with Google** inside a frame from `accounts.google.com`. Before
this, the button was plainly on screen and:

```json
{"op": "find", "text": "Continue with Google"}   → {"count": 0, "matches": []}
{"op": "get_text"}                               → "…Sign in with Microsoft\nSign in with Apple…"
```

No error, no warning, no truncation notice — just a confident answer with the
page's main control missing from it. An error is something an agent reacts to;
an empty answer is something it believes. The same blindness covers Stripe card
fields, CAPTCHAs, embedded editors, and most OAuth widgets.

**What it costs.** Nothing on a page with no frames — the snapshot script
already walks the document, so it reports the frames it found in the call that
was happening anyway, and a frameless answer ends there without one extra
request. Measured on a frameless page: **9.9 ms before, 9.2 ms after.** A page
with one frame pays about **+60 ms** per snapshot for content it previously
could not see at all. At most 8 frames and 2 levels deep, and frames too small
to see or click are skipped — including the 0×0 preload sign-in widgets mount
beside their real button.

A faster version of this entered frames by number instead of by element, which
saved about 32 ms a frame. It was wrong. A page has *two* orderings of its
frames — document order, and the `window.frames` order the WebDriver spec says
a number indexes — and on `linkedin.com/login` they are exactly reversed. It
skipped Google's 0×0 boot frame, entered it anyway, and reported its contents
as the page. See `frames.enter` if you are ever tempted to speed this up.

Turn it off with `--no-frames`, or tune with `--max-frames` / `--max-frame-depth`.

### Shadow roots — counted, not walked

Frames are folded into the tracks because a page that has them almost always has
content in them. **Shadow roots are the opposite trade**, so they are opt-in:
most pages have no author roots at all, and the ones that do keep component
internals there. On the LinkedIn page that prompted this there was one root and
nothing in it — walking it every snapshot would have cost the whole session and
bought nothing.

So the snapshot **counts** hosts without looking inside. That is one property
read on a walk already happening (measured: no change from ~11 ms), and it turns
an empty diff from a silence into a signpost:

```json
{"op": "click", "css": "#next"}
→ {"dom_diff": {"text": {"added": []},
                "shadow": {"hosts": 2, "note": "not walked; …"}}}

{"op": "find", "css": "#resume"}
→ {"count": 0, "shadow_hosts": 2, "note": "… retry with \"shadow\": true"}
```

Both appear **only** when hosts exist and the result is otherwise silent, so an
ordinary diff on an ordinary page carries neither.

To look inside, ask:

```json
{"op": "find", "css": "input[type=file]", "shadow": true}
→ {"count": 1, "matches": [{"ref": "el_12", "html": "…", "shadow": true}]}
```

Refs from a shadow root click like any other. `css` and `text` only — the walk
is `querySelectorAll` on each root, which is the only way across the boundary
and does not speak xpath.

Note that `get_text` **already** reports open shadow content, because rendered
text follows the composed tree. So discovery is free and `shadow: true` is only
needed to turn something you can read into something you can act on.

**The limit:** `mode: "closed"` makes `.shadowRoot` null. No JavaScript can read
such a root or prove it exists, so nothing here can either. "Not found" means
nothing reachable has it — see the search ladder in
[`guidelines/toolkit-workflow.md`](guidelines/toolkit-workflow.md).

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

Without `force`, `click` **hit-tests before it dispatches**: whatever sits at the
target's centre must be the target, an ancestor of it, or a descendant. Selenium
judges an element by its own state and never asks what is painted over it, so
without this check a click could be swallowed by an overlay while the op reported
`ok: true` — the worst answer an agent can be handed. The error names the
element that would have received the click instead:

```
not_interactable: css='a.result' is covered by div#promo-overlay, which would
receive the click instead. Pass force:true to dispatch it anyway, or
new_tab:true if the target is a link
```

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

### Frames: the visual audit trail

Alongside each command the server stores **a screenshot of the page it produced**.
An agent that worked unattended for an hour leaves a log saying it clicked Save;
the frame beside that line is how you check it clicked Save on the right page.

Frames are captured for the ops that change what is on screen — `goto`, `click`,
`input`, `press`, `select`, `hover`, `scroll`, the tab ops — **plus every failure,
whatever the op was**. A `find` or `get_text` changes nothing, so it gets none.
They are JPEGs, downscaled to 1280px at quality 60, and consecutive identical
frames are stored once, which puts a long session in the single-digit megabytes.

When the command acted on an element, the frame records where that element sat as
fractions of the viewport, and the viewer draws a box on it — so you see *what*
was clicked, not just that something was. A click that navigated away leaves no
box: the element is gone, and a box would be pointing at a page that no longer
exists.

```bash
abt serve --no-shots            # off
abt serve --shot-quality 40     # smaller files
abt serve --shot-width 900      # smaller still
abt serve --shots-max-mb 50     # stop capturing past this much, per session
```

Frames live in `logs/<session-id>/shots/` and are served at
`GET /logs/{session_id}/shots/{name}`, where `name` is the `shot` field on the
event. **They contain whatever was on screen**, including logged-in accounts and
private messages — treat `logs/` as secret.

**Browse them in the browser** at `http://127.0.0.1:8765/viewer` — a self-contained
page that lists sessions and sites down the side. It opens on a **timeline**: one
row per command, its frame on the left, what the agent did and what came back on
the right, failures tinted red, with a header counting commands, errors, elapsed
time and sites. Click any frame to enlarge it and step through the session with
the arrow keys. Switch the first dropdown to **raw log** for the older
request/response view. Filter by tab, site, op, errors only, or frames only.

**Or over the API:**

| Endpoint | Returns |
|---|---|
| `GET /logs` | Every session, newest first, with event and error counts |
| `GET /logs/sites` | Every site seen across all sessions |
| `GET /logs/{session_id}` | That session's events |
| `GET /logs/{session_id}/shots/{name}` | One captured frame, as named by an event's `shot` |

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
 "response": {"type": "element_not_found", "message": "nothing matched …"},
 "shot": "00004.jpg",
 "shot_box": {"x": 0.2, "y": 0.15, "w": 0.6, "h": 0.04}}
```

`shot` names a file under `logs/<session-id>/shots/`; `shot_box` is where the
command's target sat, as fractions of the frame. Both are absent when there was
nothing to capture or nothing to point at.

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

The Messenger endpoints have their own group:

```bash
abt messenger threads --url https://www.messenger.com/
abt messenger read -t https://www.messenger.com/t/<id>/ --new
abt messenger send "@Yaleed here it is" -t <thread-url> -m Yaleed -a C:/shots/page.png
abt messenger send "step 2 done" -t <thread-url> --async
abt messenger jobs <job-id>
```

## MCP

`abt mcp` serves the ops as typed tools over stdio, for any MCP client — Claude
Code, Claude Desktop, Cursor, VS Code:

```json
{"mcpServers": {"browser": {"command": "abt", "args": ["mcp"]}}}
```

It is a **proxy, not a second server**. `abt serve` still owns the browser, so
the window, its tabs and its logins outlive your editor — start it first. The
shim owns nothing and can come and go.

Why bother, when curl already works: driving the toolkit through a shell means
the model writes each request as a shell command, and it gets them wrong. One
66-command session against a live site produced five schema errors, every one a
guessed parameter name — `label` on a `select`, `diff` on a `get_text`, a
`run_js` script sent as an object. Typed schemas make those unrepresentable, and
the JSON never meets a shell, which on Windows is its own source of quoting
failures.

Thirteen tools rather than one per op, since every schema sits in the model's
context for the whole session. `browser_batch` sends a whole sequence in one
call, and `browser_command` passes through any raw op the named tools miss.

## Tests

```bash
.venv/Scripts/python -m pytest
```

The suite drives a real headless Chrome against static fixture pages served from a
local port — no network, deterministic.

## Licence

[Apache License 2.0](LICENSE) — © the Ai-Browser-Toolkit contributors.

You may use, modify, and redistribute this code, including commercially. In
return the licence asks for three things, and they are not optional:

1. **Credit the project.** Mention this repository in your own README, or cite
   it, with a link to <https://github.com/skssmd/Ai-Browser-Toolkit>.
2. **Ship the licence.** Keep `LICENSE` and the copyright and attribution
   notices with any copy or derivative work.
3. **Say what you changed.** Mark modified files as modified.

Taking the code without the credit is not "borrowing" — it is using it outside
the terms that made it available to you.
