# Reference

Everything about installing, starting, and driving `abt`: every op, every
endpoint, the CLI, MCP, and the mechanics behind the diff and the text track.
For what the toolkit is and why it's built this way, see the
[README](../README.md). If you're an agent about to drive it, read
[`guidelines/toolkit-workflow.md`](../guidelines/toolkit-workflow.md) first —
this document is the detail behind that one, not a replacement for it.

## Install

Needs **Python 3.11+** and **Google Chrome** or **Microsoft Edge** installed.
Drivers are resolved automatically — nothing to download by hand.

```bash
pip install ai-browser-toolkit
abt doctor        # what browsers are installed, and where
```

Also on **winget** (`winget install skssmd.AIBrowserToolkit`), **Scoop**,
**Homebrew** (`brew install skssmd/tap/abt`) and the **AUR**.

Point an MCP client at it:

```json
{"mcpServers": {"browser": {"command": "abt", "args": ["mcp"]}}}
```

<details>
<summary>From a source checkout instead</summary>

```bash
git clone https://github.com/skssmd/Ai-Browser-Toolkit
cd Ai-Browser-Toolkit

python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
.venv/Scripts/python -m pytest -q                   # 485 tests, needs Chrome
```

The `abt` command lands in the venv. Either activate it
(`.venv\Scripts\activate` / `source .venv/bin/activate`) so `abt` is on your
PATH, or call it explicitly as `.venv/Scripts/python -m abt.cli …` everywhere
below.

</details>

## Run

> **Start the server as a separate process.** `abt serve` is the command loop —
> it listens and **never returns on its own**. Run it in the foreground and it
> holds that terminal until you shut it down, so an agent or script that
> launches it inline will hang there forever. Background it, or give it its own
> terminal.

**`abt up` is the shortest safe way**, and the one to reach for from an agent:

```bash
abt up            # start a server if none is running, then return
```

It returns in seconds and never blocks. On Windows it asks WMI (falling back to
Task Scheduler) to do the spawning, so the server's parent is a Windows service
rather than your shell — which means it sits **outside your caller's job
object**. That distinction is the whole point: a harness that waits on its job
will hang on a plain background launch no matter how you redirect stdio, and
`CREATE_BREAKAWAY_FROM_JOB` fails silently when the job forbids breakaway. On
POSIX it double-forks with `setsid`.

**The server starts with no browser.** It listens in about a second instead of
waiting up to two minutes for Chrome on the persistent profile. Ask for a
browser when you want one:

```bash
curl -X POST http://127.0.0.1:8765/browser/start
curl http://127.0.0.1:8765/browser     # running? on what config?
curl http://127.0.0.1:8765/health      # is the *server* up (never touches the driver)
```

Pass `--start-browser` to `abt serve` for the old eager behaviour.

**When the browser dies, the server survives it.** Every page command returns
`browser_dead` naming the remedy, and `browser_restart` gives you a fresh
browser on the same profile without losing the server or the session log. You
stay logged in; tabs and refs do not survive.

**The safe way — use the start script.** It does the whole dance for you and is
the only thing an agent or CI job should call:

```bash
./start-server.sh              # Linux / macOS / Git Bash / WSL
start-server.bat               # Windows cmd
```

It no-ops if a server is already running, creates `.venv` and installs
dependencies only when they are missing, launches the server detached with its
output redirected to `server.log` / `server.err`, then polls `/health` and exits
0 once the server answers (about a second now that no browser is launched at
startup). Exit 1 means it never came up — it prints the tail
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

## Start at login

The toolkit is most useful already up: an agent that has to start a server
first pays for the start, and one that starts it wrongly wedges itself.

```bash
abt autostart install --browser chrome --dry-run   # read it first
abt autostart install --browser chrome
abt autostart status
abt autostart uninstall
```

| Platform | What it writes |
|---|---|
| Windows | a Task Scheduler logon task |
| macOS | `~/Library/LaunchAgents/com.aibrowsertoolkit.server.plist` |
| Linux | `~/.config/systemd/user/abt-server.service` |

User-level, never elevated, and **opt in** — nothing is installed unless you
ask. It runs in the account that owns the browser profile, because a system
service would run as somebody else and find none of your logins.

**No browser is launched at login.** The entry runs `abt serve` without
`--start-browser`, so logging in costs about a second and the browser arrives
when you ask for it with `browser_start`. This is the whole reason the feature
is sane: against the old eager behaviour it would have opened Chrome on the
persistent profile at every logon.

`--browser` is required rather than prompted, and every path is resolved to an
absolute one at install time. A logon entry has neither a terminal to answer a
prompt nor a working directory to resolve against — a relative `./profile`
would land in `C:\Windows\System32` and quietly build a second, empty profile
there.

On Linux a user unit stops at logout. For a server that outlives the session:

```bash
loginctl enable-linger $USER
```

## Send commands

One command:

```bash
curl -s localhost:8765/command-list -H 'content-type: application/json' \
  -d '{"op":"goto","url":"https://example.com"}'
```

A list, run in order:

```bash
curl -s localhost:8765/command-list -H 'content-type: application/json' -d '[
  {"op":"goto","url":"https://example.com"},
  {"op":"find","css":"a"},
  {"op":"click","level":"AEDBa"},
  {"op":"get_text","css":"h1"}
]'
```

Every response is `{"ok": true, "result": ...}` or
`{"ok": false, "error": {"type", "message", "op_index"}}`.

Batches stop at the first failure by default. Send
`{"commands": [...], "continue_on_error": true}` to run them all regardless.

## Console and network

The DOM cannot tell you why a request failed. These can:

```bash
curl -s localhost:8765/command-list -d '{"op":"read_network","failures_only":true}'
curl -s localhost:8765/command-list -d '{"op":"read_console","levels":["error"]}'
```

`read_console` captures from **document start**, so a reload hands back what the
page logged while loading — uncaught errors and unhandled rejections included.
`read_network` returns each request with its status, duration, and size;
`failures_only` keeps the 4xx/5xx and anything the browser would not disclose.
Both take a `pattern` regex.

## Levels: every string says where it sits

Text comes back with its position in the page in front of it — one letter per
level down from the body, so `AEDB` sits inside `AED`, which sits inside `AE`:

```
AEDBAAAB
  a 000000192
  b Sep 3, 2022
  c $109.00
AEDBAAAC
  a 000000174
  b May 2, 2022
```

Two strings sharing a prefix sit in the same container — the same table row, the
same form group. That is what a flat list of strings cannot say, and what
counting rows and matching a value to its label depend on.

Past the 52nd sibling a level is a number (`AB53`); a dot separates two numbers
(`AB100.200`) and appears nowhere else.

**A `#` marks something you can operate, and the same address acts on it.**

```
AEDBa#btn         Save changes
AEDBb#lnk         Issues → /dashboard/issues?assignee_username=byteblaze
AEDBc#inp-q       laptop
AEDBd#sel-country United Kingdom
AEDBe#lnk         → /notifications
```

| mark | what |
|---|---|
| `#btn` | button, or anything behaving as one — `role="button"`, a focusable div |
| `#lnk` | link; its target follows the text after `→` |
| `#inp` | text input or textarea |
| `#sel` | select, or a custom `role="combobox"` widget |
| `#chk` `#rad` `#opt` `#file` | checkbox, radio, option, file input |

For `#inp` and `#sel` the **name rides in the mark** (`#inp-q`) and the line's
text is the **current value** — which is what you want to read back, and what
makes a field changing value show up in a diff at all.

The last line is a link with no text: an icon. Its target is all it has to say,
and before this it appeared nowhere.

Act on it with the same address:

```json
{"op": "click", "level": "AEDBa"}
{"op": "input", "level": "AEDBc", "value": "laptop pro"}
```

**`input` and `select` are two names for one intent** — make this control hold
that value — and either works on any of them. On a `#sel` the value is the
option's visible text (its underlying `value` is accepted too, and an option
matching neither is refused with the list of options that do exist). On a
`#chk` or `#rad` it is `"true"` or `"false"`, and the click is spent only if the
state actually changes, so setting a ticked box to `true` leaves it ticked
rather than toggling it off. A radio cannot be switched off directly; set the
one you want instead. A date field takes its value, and a text field is typed
into.

Neither spelling is a dead end. `select` at a checkbox used to be refused as
"not a `<select>`" — which left the working op undiscovered, and cost one agent
six turns of clicks and element diffs on a control the other name would have set
first time. Only `option_index` still needs real options.

This exists because the alternative was silence. Typing at a `<select>` used to
reach the browser's own typeahead, which lands on the wrong option whenever the
value prefixes two of them and on nothing when it is spelled differently — and
at a checkbox it did nothing whatsoever. Both reported the value as written.

A `#` line is interactable and is an edge: everything inside it is on that one
line.

A level is positional, so it is checked before it acts: if the page re-rendered
and something else now sits at that address, the op fails with `stale_ref`
rather than clicking the wrong control.

**The prefix is an address.** Give it back to read one part of the page:

```json
{"op": "get_text", "level": "AEDBAAAB"}
→ "AEDBAAAB\n  a 000000192\n  b Sep 3, 2022\n  c $109.00"
```

That returns one subtree rather than the whole document — the way to re-read a
table after acting on it, or to look at something a navigation reported as
unchanged. Levels describe one page: a navigation renumbers them, so use one
from the result you were last given.

### How it works

**Where the path comes from.** One `TreeWalker` pass over the document produces
the text track. An element's level is its index among its parent's *element*
children — counted from `previousElementSibling`, not from the order the walk
happens to reach text-bearing nodes, so the number means the element's real
position rather than "the third thing that had words in it". Ancestors are
cached as the walk descends, so each element pays for its depth once.

**Why letters.** `A`–`Z` then `a`–`z` gives 52 siblings in one character.
Beyond that the level is written as a decimal number, and digits are kept out of
the alphabet precisely so a run of them can only ever mean one level: `ABr100C`
is unambiguously `A B r 100 C`, with nothing escaped or bracketed. Two adjacent
numeric levels are the one case that would run together, so a dot separates
those and only those — it takes a 53rd child that itself has a 53rd child, and
costs a character nowhere else.

**Why the path is written once per group.** Text on a Magento page sits at a
median DOM depth of 15 and reaches 20. A full path on every string costs more
characters than the strings it labels — measured at 120–175% overhead. Writing
it on the parent and giving each member its own letter is the same information
for about a fifth of the price, and it makes the row boundary explicit instead
of something you infer from a shared prefix. A group holding a single string
keeps that string on its own line, so the common case never costs two lines to
say one thing.

**How the navigation diff decides.** `page_text` receives the outgoing page's
text and matches against it **on the string, not the path**. That distinction
matters: paths shift between documents, so matching on position would suppress
real content any time two pages happened to nest something the same way. What
repeats is what the agent has already read. The count and a level holding some
of it travel with the result, because an agent cannot ask for what it does not
know is missing.

**What it costs.** Paths add tokens to every string; suppression removes the
chrome. On one admin task the net was 47k tokens per turn down to 33k, with
`run_js` 8 → 0 and ops 60 → 30. It does not reduce turn counts — a task needing
thirty decisions still needs thirty — and `find` results still carry no path,
so an element you located by searching cannot yet be addressed by level.

## Two ways to read a page

`find` returns element **shells** — each match's own tag and attributes, with all
children and text stripped. This is how an agent surveys page structure without
paying for the content:

```json
{"op": "find", "css": ".card"}
→ {"count": 3, "matches": [
     {"level": "AEDBa", "html": "<div class=\"card\" id=\"p1\"></div>",
      "text": "Cheap Widget", "path": "ACDa", "visible": true}
   ]}
```

Each match carries the text it **owns** — its own child text nodes, not its
descendants' — along with a form control's live value and its `path`, so a
result can be read straight back with `get_text` at that level.

`find_full` (or `{"mode": "full"}`) returns the same matches with everything inside:

```json
{"op": "find_full", "css": ".card"}
→ {"matches": [{"level": "AEDBa", "html": "<div class=\"card\" id=\"p1\"><h2>Cheap Widget</h2>…"}]}
```

## Element addresses

Every `find` match gets a `level` — the same address the text track prints. Act
on it directly instead of writing another selector:

```json
{"op": "find",  "css": "button.buy"}
{"op": "click", "level": "AEDBa"}
```

A level names a position, so it is checked before it acts: if the page changed
and something else now sits there, the op fails with `stale_ref` rather than
quietly hitting a different element.

Levels describe one page — a navigation renumbers them, so use one from the
result you were most recently given.

## Targeting

**`near` — one selector, many matches.** A documents table gives every row an
`Edit` button, so `text: "Edit"` matches a dozen and `index` is a guess:

```json
{"op": "click", "text": "Edit", "near": "Medication"}
```

The match sharing the **smallest container** with that text wins — its row on a
table, its section on a card. Size rather than depth, because a control sitting
directly in `<body>` has every string on the page as a zero-depth ancestor and
would otherwise beat the right answer.

`near` qualifies a selector, so it combines with `css`, `xpath` or `text`, and
is refused on a `ref` — a ref already names one element. When nothing is near
it, the error lists what *is*.



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

**What appeared on screen, and where it sits.** Every element's own text plus
every form control's live value, in document order, each carrying its position
in the page.

```json
{"op": "click", "css": "#products"}
→ {"clicked": "css='#products'", "forced": false, …,
   "dom_diff": {
     "url_before": "https://shop.example/", "url_after": "https://shop.example/",
     "text": {"added": ["ACBa Widgets", "ACBb Gadgets", "ACD 3 items"],
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

**An arrival reports the page minus everything you have already been shown** —
not minus the page you just left. That older rule was one page deep: it held
while you moved forward and broke the moment you doubled back, because relative
to the page you left, a page you read three turns ago is entirely new. Measured
over 61 gitlab episodes, 21.6% of every character delivered was a line already
delivered in that same episode, and doubling back is what these tasks do — open
a list, open an item, return to the list, open the next.

The reference is each page's full snapshot, held server-side, never the diff
printed from it: a line withheld from one report is still on that page, so it
still counts as read when the next one is reported.

```json
{"op": "goto", "url": "https://shop.example/cart"}
→ {"url": "…/cart", "title": "Your cart",
   "dom_diff": {"navigation": true,
                "text": {"added": ["ACD", "  a 2 items", "  b Total: $42",
                                   "ACF#btn Checkout",
                                   "… 41 strings you have already been shown (most of it "
                                   "on …/products) are not repeated here — …"],
                         "unchanged_count": 41,
                         "removed_count": 18, "truncated": false}}}
```

The nav, header and footer are absent because you have read them. Measured
across a benchmark campaign that furniture was 38% of admin page text, 47% of
the forum's and 60% of the storefront's — re-sent on every navigation and then
carried in the conversation for every turn after it. The summary names the page
the withheld text came from, because "you have read this" is not something you
can act on and "you read this on /products" is.

**Nothing is ever unreachable, only unrepeated.** `get_text` with a level
returns that subtree in full, and the level cited is *this* page's, not the one
the text sat at when you first read it.

**An arrival is never empty.** If a page's content has all been seen, reporting
nothing would leave two different pages coming back identical — no way to tell
which one you are on, no address to act on, and a full page read as the only
move, costing a turn *and* the whole payload. So the page answers with its
controls instead: address and role, no text and no href, about ten characters a
line rather than sixty.

```json
   "text": {"added": ["AEDBa#lnk", "AEDBb#btn", "AECc#inp-q",
                      "… nothing on this page is new to you — all 47 of its strings "
                      "you have already been shown. You read them on …/issues. …"],
            "unchanged_count": 47}
```

**Withholding that would not pay is not done.** The explanation costs a couple
of hundred characters, so on a short page it can cost more than the text it
saves — measured at 327 characters to withhold a 121-character page. There the
page comes back whole, with no note and nothing withheld to reason about.

**A reload is neither.** It lands on the document it started from, so there is
no other page to measure against and nothing is withheld — suppressing here once
hid the very content a reload had been asked for.

This covers `goto` `back` `forward` `reload` and any interactive op that
redirected — a `click` that leaves the page lands in exactly the same place and
is treated the same way. The element track is skipped whenever the document was
replaced, since a unified diff across two documents is noise at any budget.
`"diff": false` turns it off per command.

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

### Controls arrive on the text track

There is no separate actionable block. A control appears as a line whose
address carries `#role`, and that address acts on it — see **Levels** above.

```json
{"op": "click", "css": "#insert-menu"}
→ {…, "dom_diff": {"text": {"added": [
     "AEDBa#btn Chart",
     "AEDBb#btn Pivot table",
     "AEDBc#btn Macro"
   ], "removed_count": 0}}}

{"op": "click", "level": "AEDBb"}     ← act on it directly; no find in between
```

This used to be two tracks: the words on one, and a separate role-and-handle
object for the same control on the other. Sending both cost twice for one
thing, and a control with no accessible name was dropped entirely — it had no
text line to decorate, so an icon-only button appeared on neither track. Both
problems were the same problem, and merging the tracks settles them together.

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
→ {"count": 1, "matches": [{"level": "AEDCb", "html": "…", "shadow": true}]}
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
[`guidelines/toolkit-workflow.md`](https://github.com/skssmd/Ai-Browser-Toolkit/blob/main/guidelines/toolkit-workflow.md).

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

### Extra fields that appear only when they are worth saying

`dom_diff` carries a few keys that show up only in the specific case they
apply to — an ordinary response on an ordinary page has none of them.

**`no_change: true`** — the command succeeded and nothing in either track
changed: no added text, no element changes. That is a real outcome, not an
error — the click landed and the page did not react, usually because the
control you hit was not the one that produces the effect you expected.
`element_diff: true` is the next thing to try, for an attribute-only change a
text diff cannot see.

**`status_hint`** — the text just returned names a status like `Canceled`,
`Rejected`, `Declined`, `Deleted`, `Refunded` or `Voided`. It is a reminder,
not a filter: if you are about to count or sum across rows, check each row's
status before including it. Matches only the status *form* — "Canceled"
fires, the button labelled "Cancel" does not — so it does not fire on
ordinary page chrome.

**`forced_past`** on a `click` response — the click was dispatched through
something covering the target that was not a dialog, and this names it. A
click behind an open dialog still refuses outright, because something there
is waiting on an answer; anything else is treated as the target's own
furniture (a split-button's dropdown toggle overlapping the button it
belongs to) and clicked through rather than blocked.

## Ops

| Group | Ops |
|---|---|
| Navigate | `goto` `back` `forward` `reload` `current_url` |
| Read | `get_html` `get_text` `find` `find_full` `screenshot` |
| Interact | `click` `input` `select` `hover` `scroll` `wait_for` `press` |
| Tabs | `tab_new` `tab_list` `tab_switch` `tab_close` |
| Control | `run_js` `diff` `status` `shutdown` |
| Browser lifecycle | `browser_start` `browser_stop` `browser_restart` `browser_status` |

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
abt command-list '{"op":"click","css":"a.result","force":true}'
abt command-list '{"op":"click","css":"a.result","new_tab":true,"activate":false}'
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

**Subcommands are lifecycle. Every page action goes through `command-list`.** There is
one spelling of each op — the one `abt ops` prints — so nothing can drift out
of step with the server.

```bash
# lifecycle
abt up                      # start a server if none is running
abt browser start           # a separate step; up to 2 min on a real profile
abt status                  # URL, tabs, live refs
abt ops                     # every op and its exact parameters
abt logs
abt shutdown
```

```bash
# one page action
abt command-list '{"op":"goto","url":"https://example.com"}'
abt command-list '{"op":"find","css":"a.product","limit":20}'
abt command-list '{"op":"click","level":"AEDBa"}'
```

**A sequence you already know is one round trip, not six.** This is the
biggest single thing you can do to work faster with the toolkit:

```bash
abt command-list '[{"op":"input","css":"#search","value":"hello"},
                   {"op":"click","css":"#go"}]'

abt command-list steps.json --continue-on-error
'[{"op":"press","key":"Enter"}]' | abt command-list -    # PowerShell-safe
```

It stops at the first failure and names it, so batching is never a blind leap.

The CLI once had a subcommand per op. Keeping two spellings in step by hand
did not work — the ops take `ref/css/xpath/text/index/near` while `click` took
two of them, and this README's own examples were commands the CLI rejected. It
also billed a process per op, which quietly taught serial work.

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

**Three tools, not one per op.** Every schema sits in the model's context for
the whole session and is re-sent on every turn, so a tool per op is a bill you
pay forever: sixteen of them measured ~2,300 tokens a turn. Worse, thirteen of
those were single actions, so the easy path was always one op per call — the
tools taught serial work while the documentation asked for batching, and
agents obliged 64% of the time.

| tool | mirrors |
|---|---|
| `command_list` | `abt command-list` — every page action, one op or a list |
| `browser_session` | `abt browser` — start, stop, restart, status |
| `browser_guidelines` | `abt guidelines` — the workflow and site playbooks |

The parameter schemas the per-op tools carried are not lost. `GET /ops`
returns every op with its exact parameters, types and defaults, so a caller
reads them once when it needs them instead of being told all of them every
turn.

The server also answers `initialize` with MCP `instructions` — how the pieces
fit together, which most clients place in the system prompt once. That is where
the orientation goes, because it is paid for once rather than re-sent with the
schemas on every turn. `browser_guidelines` reads the rest: the whole
workflow document, or a fuzzy search for a site's playbook.
## Benchmark

Four MiniWoB++ tasks, driven end to end by **Claude Haiku 4.5** through the
`abt` CLI. The agent is given the task in plain English and the port — nothing
else. It reads `abt --help`, works out the page for itself, and the page scores
it.

| task | ops | tokens | reward |
|---|---|---|---|
| `book-flight` | 15 | 44,663 | 1.00 |
| `email-inbox-forward-nl` | 16 | 54,260 | 1.00 |
| `terminal` | 8 | 38,445 | 1.00 |
| `click-checkboxes-soft` | 7 | 36,799 | 0.60 |
| **total** | **46** | **174,167** | **0.90 avg** |

`book-flight` and `terminal` are two of the harder tasks in the suite: one needs
two autocompletes, a datepicker and a comparison across four results; the other
is a simulated shell. `terminal` took eight operations.

**Scoring is not ours.** Every reward above is MiniWoB's own
`WOB_REWARD_GLOBAL`, read from the page after the agent stopped — not the
agent's account of how it went. The 0.60 is a real partial: the agent picked
*assassinate* as a word similar to *initiate*, which the task disagreed with.
That is a reasoning miss, not a toolkit one, and it stays in the table.

**Read these honestly:**

* **n=1 per task.** MiniWoB generates a fresh instance each run, so these are
  single samples, not averages over seeds. Treat them as a demonstration that
  the tasks are solvable at this cost, not as a score.
* **The episode clock is neutralized.** MiniWoB ends an episode after ten
  seconds and scales a successful reward by elapsed time. An agent CLI takes
  30–60s just to start, so under stock rules every out-of-process agent scores
  0.00 on every task regardless of what it does — the run would measure process
  startup. The runner patches `endEpisode` to drop the timeout and the
  time-scaling. Correctness is untouched: the task's own scoring code decides,
  and we never patch it. **These numbers are therefore not comparable to
  published MiniWoB scores**, which run the stock clock.
* **Tokens are the whole agent session** — reading `--help`, reasoning, and
  every command — not just traffic to the toolkit.
* **Ops are counted by the server**, from its own session log, not reported by
  the agent.

The harness is in [`benchmarks/browsergym/`](benchmarks/browsergym/README.md),
including a resumable sweep runner for seed-controlled runs across all 125
tasks.

## Tests

```bash
.venv/Scripts/python -m pytest
```

The suite drives a real headless Chrome against static fixture pages served from a
local port — no network, deterministic. Around seven minutes for the full run.

```bash
.venv/Scripts/python -m pytest --engine playwright   # the same 485 against Playwright
```

**Two engines, one suite.** Playwright is the default; `--engine selenium` runs
every assertion against the Selenium backend instead. Both pass. The flag exists
because "a caller cannot tell which engine is underneath" is a claim worth
checking by running the tests rather than by reading the diff.

`tests/test_engine.py` needs no browser and runs in under a second. It guards the
driver seam: that nothing outside `engine.py` and `browser.py` imports Selenium
directly, and that the key table stays derived from the driver rather than typed
out by hand. Both are properties no single diff makes visible.

