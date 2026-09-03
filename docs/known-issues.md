# Known issues

Found by driving the toolkit against live sites. Fixed entries are kept, not
deleted — the failure is the reason the code looks the way it does.

## Fixed

### 1. `input` corrupted `<input type="date">` — fixed 2026-08-03

`send_keys` types into the browser's *locale* segment boxes, not the ISO value,
so the separators were consumed as segment breaks and the digits shifted.

Seen on `hr.dataclans.com/admin/staff/add`: `"2026-08-03"` landed as
`"60803-02-20"`. The form submitted and the server answered "Failed to create
staff entry" twice, naming no field.

`interact.input` now detects `date`, `time`, `datetime-local`, `month`, `week`
and writes through `HTMLInputElement.prototype`'s own `value` setter (a plain
assignment is ignored by React), then fires `input` and `change`. A value the
field will not parse raises `not_interactable` naming the expected format,
rather than silently emptying the field.

Covered by `tests/test_inspect.py`.

### 2. No console or network capture — fixed 2026-08-03

Diagnosing a failed request meant hand-patching `window.fetch` and
`XMLHttpRequest.prototype.send` through `run_js`, and a patch installed after
load missed everything logged during load.

Two ops now: `read_console` and `read_network` (`src/abt/ops/inspect.py`).
Console capture is installed via CDP `Page.addScriptToEvaluateOnNewDocument`, so
it exists before the page does and survives navigation. Network comes from the
Resource Timing API — nothing to patch, no overhead, and it is what found the R2
404 on the first try.

*Caught during review:* the first version registered the init script once at
startup. CDP registers against one **target**, so every tab opened afterwards —
`tab_new`, a `new_tab` click, every background Messenger send — had no console
at all. It passed in isolation and failed in the full suite, because the tab
tests leave a different tab active. Capture is now armed per tab, once each
(`BrowserSession._captured`), on open, on switch, and after a close hands
focus to a neighbour.

### 3. `click` did not scroll to its target — fixed 2026-08-03

An element below the fold failed `element_to_be_clickable` and came back
`not_interactable`, because Selenium judges an element where it currently sits.
Seen on the HR documents page: an Edit button at `y=1009` refused to be clicked
until scrolled to by hand.

`targeting.resolve_one` now centres the element in the viewport before waiting
for `visible`/`clickable`. `present` deliberately does not scroll, so asserting
that something exists never moves the page under you.

### 4. `/status` returned a raw 500 when the browser had died — fixed 2026-08-03

`session_status` raises Selenium's `InvalidSessionIdException`, which is not an
`OpError`, so the route's handler missed it and the client got an HTML
traceback. A dead browser must still be able to report that it is dead.

The route now also catches `WebDriverException` and answers `browser_dead`.

Related, same cause: `dispatch` ran `health_check()` before *every* op, so
`shutdown` could not shut down a server whose browser had already died — the
check failed first, and the process had to be killed by hand. `shutdown` and
`status` are now exempt (`NO_HEALTH_CHECK`).

Superseded in part on 2026-08-19: a dead browser no longer costs you the
server. `browser_restart` (also exempt from the health check) replaces it in
place, so "killed by hand" is no longer the remedy for anything here. The fix
above still stands — `/status` must answer on a dead browser, which is how a
caller learns it is dead.

### 5. `OpError("bad_browser", …)` raised `ValueError` — fixed 2026-08-03

`browser.py` raised it for an unsupported `--browser`, but `bad_browser` was not
in `ERROR_TYPES`, and `OpError.__init__` rejects unknown types. Added.

### 8. No coordinate click — fixed 2026-08-04

Every interactive op targeted by `css`/`xpath`/`text`/`ref`, so a control with
no addressable DOM node — canvas, closed shadow DOM, an image map — could be
seen in a `screenshot` and then not acted on. Hit while annotating a canvas PDF
editor: the only available move was to click the canvas centre, with no way to
place a mark anywhere specific.

`click` now takes `at: [x, y]`, driven through the W3C pointer actions, so
`event.isTrusted` is true. With a target it is an offset inside that element
and the element is scrolled into view first; alone it is a viewport point. The
response reports `hit` from `elementFromPoint`, because a coordinate click is
blind and ought to say what it landed on. Off-screen points raise
`not_interactable` rather than clicking nothing.

A viewport point is only accurate to about a pixel — the mouse is on whole
pixels while layout is fractional. The element-relative form has no such
error, which is why the guideline prefers it.

### 6. `_choose_browser` prompted, breaking detached launches — fixed 2026-08-03

`typer.prompt` needs a TTY, and `abt serve` is routinely started detached, where
there is no stdin to answer with. It now defaults to chrome when
`sys.stdin.isatty()` is false, and still prompts for a human.

### 7. A click could report `ok: true` and do nothing — fixed 2026-08-04

Seen on `hr.dataclans.com`: with the site's own error dialog open, a
`click {"text": "Create Employee"}` returned `ok: true`, made no request, and
changed nothing.

Root cause: `element_to_be_clickable` judges an element by its *own* state —
displayed, enabled — and never asks what is painted over it. An overlay at a
higher z-index therefore passes the gate, swallows the click, and the op
reports success. Issue 3 was a separate symptom of the same blind spot.

`interact.click` now hit-tests before dispatching: `elementFromPoint` at the
target's centre must return the element, an ancestor of it (a `<label>` wrapping
its input), or a descendant (the `<span>` inside a button). Anything else raises
`not_interactable` naming what would have received the click instead.

`force: true` skips the test, because clicking through an overlay is exactly
what force is for. Any failure *running* the test counts as a pass — this
exists to catch a silent success, not to invent a new way to fail.

Covered by `tests/test_hit_test.py`.

### 9. A dead ref could silently hit a different element — fixed 2026-08-04

`RefCache.invalidate` dropped the ref table *and reset the counter*, so the next
`find` after a navigation started again at `el_0`. Anything still holding `el_0`
from the previous page then resolved — to a completely unrelated element on the
new one. Confirmed by driving the pre-fix `RefCache` directly:

```
page one: find allocated 'el_0' -> BUTTON ON PAGE ONE
page two: find allocated 'el_0' -> BUTTON ON PAGE TWO
holding the OLD 'el_0' now resolves to: BUTTON ON PAGE TWO
```

This is precisely what `stale_ref` exists to prevent, and the guarantee the
README makes ("it never quietly hits a different element"). It stayed hidden
because the test for it used a dead ref *before* anything reallocated, which is
the one order where the bug cannot show.

The counter now survives navigation and is dropped only when the tab closes, so
a name is never reused within a tab's life. Ref numbers climb over a long
session; that is the cheaper problem by a wide margin.

*Found while adding the actionable track (issue 10), which allocates refs after
an op and so hit the collision immediately.*

### 10. Nothing connected the text diff to what could be clicked — fixed 2026-08-04

The text diff said *what appeared*; acting on any of it still meant a `find` to
turn a string into something addressable. Every action cost an extra round trip
and an extra model turn.

The snapshot now has a third track. In the same `TreeWalker` pass, interactive
elements are collected with their role and accessible name, and the diff reports
the ones that are new, each with a ref:

```json
"text": {"added": ["Chart", "Pivot table"], "removed_count": 0},
"actionable": {"added": [{"ref": "el_7", "role": "menuitem", "name": "Pivot table"}]}
```

Two rules keep it a decoration on the text track rather than a second inventory:

* **A control with no accessible name is dropped.** Text is the anchor; an entry
  the agent cannot tie to something it has read is noise.
* **It never runs after a navigation.** On a new document every control is
  "new", so the diff degenerates into a listing of the whole page — which the
  text track already returned in full.

*Caught while measuring:* the first version returned every collected element
handle on every snapshot and cost **+52%** on a diffed op (26.5 ms → 40.4 ms on
a 400-element page). Handles are now parked on the page in `window.__abtActionable`
and only the few positions the diff actually picked are fetched, and the
per-element checks were reordered cheapest-first.

### 11. A hidden file input could not be used — fixed 2026-08-04

The standard upload pattern hides the real `<input type=file>` and fronts it
with a custom control that validates or resizes. `input` resolved its target
with `state="visible"`, so the one element that must receive the path was the
one element it refused to touch.

Two changes. The actionable track exempts file inputs from "must be rendered" —
the sole exception, since nothing else is both invisible and unreachable by
other means. And `input` falls back to a `present` lookup when the visible one
fails, confirms the target really is a file input, then borrows the unhide trick
`messenger.py` already used (`UNHIDE_FILE_INPUT_JS`, now shared rather than
duplicated) — and restores the original style afterwards, which the Messenger
version does not, so the next diff does not report a phantom change.

An ordinary missing or hidden field still reports its real error; the exemption
checks the type before it applies.

### 12. A navigation reported the spinner as the page — fixed 2026-08-04

Found by watching a blind agent drive `hr.dataclans.com`. Every `goto` came back
with the same 19 strings: navigation chrome plus `Loading dashboard...`,
`Processing`, `Please wait while we process your request.` The staff list was
not in there. The agent re-read the body after every navigation — and was right
to, because the diff genuinely did not contain the answer.

`driver.get` returns when the *document* has loaded. On a React app that is the
instant a spinner mounts and nothing else has rendered, so the snapshot
photographed a loading state and `page_text` labelled it "the full page you
landed on".

It survived 261 passing tests because every fixture was complete at load —
nothing in the suite had ever rendered after load. `tests/fixtures/late.html`
and `slowfetch.html` now do, and the test server understands `?delay=` so a
fetch can be made genuinely slow.

`BrowserSession.settle()` waits on **two** signals before snapshotting, and
neither is sufficient alone:

* **No request in flight**, and none finished in the last 150 ms. This is the
  one that matters on a real app: while a slow fetch is outstanding the DOM
  holds *perfectly* still, so a DOM-only check calls the spinner settled. An
  in-flight counter patched over `fetch` and `XMLHttpRequest` is installed at
  document start, the same way console capture is. Completion counts whatever
  the status — a 404 or a dropped connection ends a request just as a 200 does,
  and waiting for success would hang on every page with a failing call.
* **A DOM that has stopped changing** for 350 ms. Catches a render that owes
  nothing to the network, which the counter cannot see at all. The window has to
  be this wide because a page that has not *started* rendering looks exactly
  like one that has *finished*.

Verified load-bearing by disabling the network term: exactly the two fetch tests
fail and the DOM-quiet ones still pass.

### 13. The ref for a hidden upload was the one thing that could not use it — fixed 2026-08-04

Also from the blind run:

```
input ref='el_14'              FAIL  not_interactable: has no size and location
input css='input[type=file]'   ok
```

Same element. `targeting.resolve_one` returns a `ref` straight from the cache
without a visibility check, so `state="visible"` never raised, so the
`_hidden_file_input` fallback added earlier the same day never fired, and
`send_keys` hit the raw Selenium error.

The irony was exact: the actionable track exists to hand out a ref for the
hidden upload, and a ref was the one way of reaching it that did not work.
`input` now routes **every** file input through the staged writer regardless of
how it was targeted.

### 14. `input` silently appended when clear did not take — fixed 2026-08-06

Found by reproducing the one thing an hour-long LinkedIn session could not
finish (`logs/20260806-040306`, reviewed in
`session-review-20260806-linkedin.md`).

```
field before:  "Technology, Information and Internet"
input {clear: true, value: "Finance"}
field after:   "Technology, Information and InternetFinance"    ← ok: true
```

An event log on the live field shows the mechanism:

```
change   trusted=false  val=''                                     ← clear(): change only, no input
keydown  trusted=true   val='Technology, Information and Internet' ← already restored
```

Selenium's `clear()` empties the value, fires `change` **alone**, and blurs the
field. A framework-controlled component learns nothing from `change` — `input`
is the event it tracks — so it reverts to its last committed text the moment
`send_keys` takes focus, and the typing appends to what was supposed to be
gone. `_field_value` then reported the concatenation as the value written.

Checking straight after `clear()` does not catch it: the field really is empty
until something touches it, and a JS-only clear stays empty for at least 400ms.
The restore is triggered by the refocus, not by a timer.

Two layers now, because the two kinds of field fail differently:

- `_clear_field` follows `clear()` with `_CLEAR_VALUE_JS` — the prototype's own
  value setter plus `input`/`change`, mirroring `_SET_VALUE_JS`. A component
  that listens on `input` records the empty state, so there is nothing left to
  restore. This is what fixes LinkedIn.
- `input` then checks what it actually wrote. A result of exactly
  `previous + value` is the signature of a clear that came undone, and it earns
  one retry through `_clear_by_keystrokes` — real select-all-and-delete, which
  even a component that ignores untrusted events believes.

Regression tests use two fixtures that reproduce each half:
`controlled.html` (tracks `input`, re-renders on `change`) and
`controlled_trusted.html` (additionally ignores `isTrusted: false`, defeating
the scripted clear and forcing the keystroke retry).

The wider lesson, and the reason this one was expensive: the op returned
`ok: true` with the corrupted value in `value`. Nothing downstream could tell.

### 16. A native dialog killed the Playwright driver -- fixed 2026-09-03

Nothing in the toolkit listened for `dialog`, so Playwright's own auto-dismiss
ran, and that dismiss rejected inside the Node driver and took the process down:

```
Dialog._dismiss -> Page.handleJavaScriptDialog -> unhandled rejection
Node.js v24.18.1
```

Python survived, holding a driver that no longer existed. `/health` kept
answering because it never touches the driver, while `/status` hung for ever, so
the server looked alive and was not. One `confirm()` on a Magento admin page put
a benchmark worker into a two-minute crash loop that ran for hours before anyone
read the server log.

`_watch` in `src/abt/pwdriver.py` now attaches a handler to every page,
including ones the site opens itself, which records the dialog and dismisses it
inside `try/except`. Dismiss is the safe default: accepting a `confirm()` agrees
to something nobody asked for. Shipped in 0.3.6.

### 17. A dead attached browser advised a restart that cannot work -- fixed 2026-09-03

In attach mode (`ABT_CDP_URL`) the browser belongs to whoever launched it: a
harness owns the launch and the scoring, the toolkit only drives the pages. So
there is no relaunching it from inside the session. When the endpoint died, the
failure still offered the generic remedy, restart it.

A benchmark agent spent twenty of its thirty turns and 640k tokens cycling
`browser_start` / `browser_stop` / `browser_restart` against a socket that was
never going to answer, then guessed at an answer it could no longer check.

The attach failure now carries a terminal hint: externally owned, cannot be
started or restarted from here, retrying will fail the same way, report what you
have and stop. Shipped in 0.3.6.

### 18. Silent client retries stalled an episode for 25 minutes -- fixed 2026-09-03

Benchmark harness, not the toolkit. The model client was built with
`max_retries=5, timeout=300.0`, and the client's own retries print nothing, so a
stalled request could spend twenty-five minutes inside one call while the outer
retry loop -- the one that logs `upstream busy` and backs off -- never got
control.

Observed: an admin episode sat on turn 10 for twenty minutes, its browser op
long since returned `ok`, holding a single open socket to the API edge. Across
every sweep the outer loop had logged `upstream busy` exactly zero times, which
is what gave it away.

Now `max_retries=1, timeout=120.0`: fail fast in the client, retry loudly in the
loop.

### 19. The answer nudge fired only once -- fixed 2026-09-03

Benchmark harness. An episode that ends with text and no tool calls has that
text scored as its answer. A nudge existed for the case where no `ANSWER:`
marker was emitted, but it was one-shot:

```python
if not nudged and not _ANSWER_MARK.search(reply or "") and turns < max_turns:
    nudged = True
```

A second narrated reply therefore broke the loop, and a sentence about what the
agent was *about to* do became the scored answer.

Measured over 393 episodes: 26 (6.8%) were scored on narration, 21 of them
failed, together 10.2M tokens -- about a tenth of the run's spend. Nine of the
26 had the complete gold answer in their own transcript and never stated it.
Several stopped at turn 3 or 4 with twenty-six turns unspent.

Replaced with a consecutive-stall counter, capped at 3 and reset by any turn
that calls a tool, with a firmer second message that forbids narrating or
running more ops and asks for a defensible answer from the evidence in hand.

## Open

### 15. The shared test browser sometimes dies partway through a full run

Running the whole suite occasionally kills the session-scoped Chrome that
`conftest.py` starts. Every fixture after that point errors with
`InvalidSessionIdException: invalid session id`, so one crash reports as
hundreds of failures and buries whatever real change you were testing.

Observed 2026-08-19: two consecutive full runs died inside `test_diff.py`, then
a third passed 413/413 with the same code. The same files run in isolation
passed every time (61 tests, 78s, with and without the change under test), which
is what proves it is not the code under test.

The tell is the shape of the report, not any single message: a *contiguous tail*
of errors that all say `invalid session id`, starting mid-file. A genuine
regression fails a related handful of tests; this fails everything after a
point, including tests that have nothing to do with each other.

When it happens, re-run the affected files alone before believing the result.
Do not bisect against it — two runs of the same code disagree, so a bisect
converges on noise.

Not yet diagnosed. The suspicion is resource pressure: ~400 tests share one
browser, and `test_diff` builds deliberately large DOMs. If it becomes routine,
the fix is probably a function-scoped browser for the heavy modules rather than
one for the whole session — at a real cost in runtime, which is why it has not
been done pre-emptively.

### `_profile_locked` never fires on Windows — found 2026-08-19

`PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")`
are POSIX artifacts. Chrome does not create any of them on Windows, which uses a
named mutex and a hidden window class instead. So `_profile_locked()` returns
`False` on Windows unconditionally — not "no browser is holding it", but "this
check cannot tell you".

Demonstrated while preparing the Playwright spike: eight `chrome.exe` processes
were live on `profile/` (`--user-data-dir=...\aibrowsertoolkit\profile`,
Chrome 151.0.7922.138) with the server down, and the profile root held
`DevToolsActivePort` and `First Run` but no `Singleton*` file. A `robocopy` of
the profile then failed on `Default/Network/Cookies` because the live browser
held it — which is the same lock the check reported absent.

Harmless today: nothing refuses to act on the answer, and `_verify_session` is
what actually decides whether a session is usable.

**Not harmless under the profile-sessions design.** That spec refuses the
`profile/` -> `profiles/default/` move "if `profile/` looks locked ... moving a
directory out from under a running Chrome corrupts it", and names this check as
the guard. On Windows the guard never fires, so the migration would move a live,
logged-in 1.2GB profile and corrupt it. Fix the check before implementing that
migration.

A signal that does work on Windows: query `Win32_Process` for a `chrome.exe`
whose command line carries `--user-data-dir=<profile>`. `DevToolsActivePort`
exists while a browser runs but survives a crash, so it over-reports.

### A correct refusal that read as a toolkit bug — 2026-08-20

Found by reading a 203-command session log, and worth recording mostly because
the first diagnosis was wrong.

An agent clicked `Approve` (`#110`, succeeded), which opened a confirmation
dialog. It then clicked the *same ref* twice more (`#111`, `#112`), and both
were refused:

```
not_interactable: ref='el_85' is still covered by
div.data-[state=open]:animate-in.data-[state=closed]:animate-out after 1.0s
```

**The refusal was correct.** The button really was behind the dialog's overlay,
and clicking through would have hit the overlay. `_HIT_TEST_WINDOW = 1.0` with
50ms polling already waits out an animating cover -- `test_a_cover_that_flashes_
is_waited_out` proves it -- so this was never the animation case it resembled.

The failure was the message. `div.data-[state=open]:animate-in.data-[state=
closed]:animate-out` is a Tailwind class list: it names an animation, says
nothing about a dialog being open, and offers no next step. A reader could
reasonably conclude the toolkit was flaky, which is exactly what happened here
before the log was read properly.

Fixed by naming the obstacle rather than its classes: the hit test now walks up
from the blocking element for `role=dialog`, `role=alertdialog` or
`aria-modal=true`, and the error reads "is behind an open dialog ('Confirm
approval') ... act on the dialog or close it first -- the command that opened it
already reported its controls". The specific element is still named alongside
the kind, because dropping it would make the error less useful than the one it
replaced.

**The agent's own shortcoming stands separately**: it retried an identical
command instead of reading the diff from `#110`, which had already reported the
dialog and its controls. No error message prevents that.


## Open -- found by the WebArena campaign, 2026-09-03

Measured over 393 episodes across three sites (shopping, shopping_admin,
reddit): 6,367 ops, 4,239 responses carrying page text, and 734 `run_js` scripts
recovered from the session logs. `run_js` is 9.1% of all ops and appears in 34%
of episodes -- 27% of shopping episodes, 47% of admin ones. Entries are ordered
by measured cost.

### 20. Page text arrives as a flat string list, so structure is lost

**Status: fixed in 0.4.0.** The text track carries a position per string and
groups siblings under their parent; a navigation is diffed against the page it
came from, so repeated chrome is summarised rather than re-sent. Measured on
one admin task, `run_js` went 8 to 0 and `find` 13 to 7. It did not move turn
counts, and one counting failure became a pass.


This is the root cause behind several of the entries below, and it is worth
stating first because the obvious suspect is innocent: **the text is not
truncated**. Of 4,239 responses carrying page text, 2 were truncated (0.0%).
Median payload is 1,848 characters, p99 is 26,332. A navigation really does hand
back the whole page, exactly as `dom_diff.text` promises with its note, "text is
the full page you landed on, not a diff".

The problem is the shape. `goto` on `localhost:7780/admin/catalog/product/`
returns **3,241 separate flat strings**, beginning:

```
'Marketing'  'Marketing'  'Promotions'  'Catalog Price Rule'  'Cart Price Rules'
'Communications'  'Email Templates'  ...  'Reports'  'Reports'  'Marketing'
'Products in Cart'  'Search Terms'  ...  'Sales'  'Orders'  'Tax'  'Invoiced'
```

Three consequences:

**No hierarchy.** No rows, no columns, no containment. A grid's cells arrive as
a bare sequence with no row boundary, so there is no reliable way to tell which
cells belong together. This is the likeliest explanation for the counting
failures, which are consistently off by a small amount rather than wrong in
kind: `webarena.128` answered 8 against a gold of 9, `.130` 17 against 18, `.131`
19 against 25.

**No separation of chrome from content.** Roughly the first hundred items of
every Magento admin page are the same navigation menu. It is paid for in tokens
on every navigation, and the data has to be found inside it.

**The menu repeats itself.** 'Marketing' twice, 'Reports' twice, 'Content'
twice, 'Orders' under both Sales and Reports. That is why `webarena.64` found
three elements reading "Orders" and had to walk parent chains to tell the
customer sidebar tab from two menu entries.

An agent that cannot recover table structure from the stream goes to `run_js`
with `querySelectorAll` to get rows back, which is the single largest use of it.

#### What to do about it

Three changes, measured, in the order they pay:

**a. Diff a navigation against the page it came from.** `page_text()` in
`src/abt/diff.py` already receives `before`, the outgoing page's text, and
already counts it for `removed_count`. It is deliberately not diffed against, on
the stated reasoning that "the two documents are unrelated". That holds between
sites and is false within one: the nav, header, footer and grid furniture are
identical from page to page.

Measured over the campaign, suppressing strings the agent was shown on the
immediately preceding page of the same site would remove:

| site | chars kept | suppressed |
|---|---|---|
| shopping (7770) | 1.08M / 2.69M | **60%** |
| shopping_admin (7780) | 1.79M / 2.88M | **38%** |
| reddit (9999) | 606k / 1.14M | **47%** |
| map (3000) | 1,892 / 5,594 | 66% |

About **3.2M of 6.7M characters** delivered in the whole run -- roughly half --
is text the agent had already been given on the page it just left. It compounds,
because page text enters the message history and is re-sent on every later turn.

The suppressed part must be summarised, not silently dropped ("nav: 122 items
unchanged"), with a way to ask for it back. Hiding content an agent cannot know
is missing is the one way this change could do harm.

**b. Number the tree, and group by prefix.** Give every element a positional
path (`0`, `0.1`, `0.1.2`) and attach each string to its own. Shared prefix then
means shared parent, which is what recovers rows, pagination groups and "these
cells belong together" -- the thing a flat list cannot express.

Emitting a full path on every text node is too expensive: text on the Magento
storefront sits at median DOM depth 15 and up to 20, so full paths add 120-175%
to the payload -- more than the text they label. Emit the path **once per group,
prefix-compressed against the previous group**, and let each string carry only
its own index:

```
0.1.2.3        table row
   .1          "000000192"
   .2          "Sep 3, 2022"
   .3          "$109.00"
0.1.2.4        (next row -- only the tail changed)
```

Measured, that is about 4.5x cheaper than a path per node, and it makes the row
boundary explicit instead of inferred. Two things come free with it: the path is
a stable *address*, usable where a `ref` cannot be (in prose, across turns); and
it resolves entry 23 outright, since three elements reading "Orders" now differ
visibly by their subtree.

Combined with (a), an unchanged subtree collapses to a single line:

```
0.1.1  nav -- 122 items, unchanged
0.2.3  table -- 20 rows, NEW
```

**c. Remember what is chrome, per site.** 43 distinct strings appear on >=80% of
shopping pages; 122 on shopping_admin; 10 on reddit -- 32-34% of Magento page
text, and it lines up with cost, since reddit has the fewest and is both the
cheapest site per task and the highest scoring.

Key this on *content*, not on path. Paths are not stable across pages: `0.1.1`
is the nav on one Magento page and something else on the next, so a mute keyed
to a path would start hiding real content after a navigation -- and the agent
could not tell. Depth-based truncation fails the same way: shallow text includes
`records found`, counts and titles, so a filter tuned to skip chrome throws away
answers.

The natural home for the learned part is the playbook system already shipped:
"on this host these strings are chrome" is a site-level fact worth persisting
across sessions rather than rediscovering every run. An agent-declared mute is
worth having as an override for what the heuristic misses, with an explicit
unmute as the escape hatch.

### 21. `find` throws away the text it matched

**Status: fixed in 0.4.0.** A match now carries the text it *owns* -- its own
child text nodes, not its descendants' -- plus a form control's live value and
the element's path. Own text rather than `innerText` on purpose: a container
would otherwise drag its whole subtree back, and `innerText` forces a reflow
per candidate on a search that can return a thousand. The path comes from the
same helper the snapshot walk uses, so an address printed by the text track is
the address `find` gives the same node. Empty keys are omitted, so a
structural div still costs one line.


`_SERIALIZE` in `src/abt/ops/read.py` serialises a match as

```js
html: full ? e.outerHTML : e.cloneNode(false).outerHTML,
visible: e.getClientRects().length > 0
```

`cloneNode(false)` drops every child, so in the default `shell` mode the text is
deleted. `find {"text": "Orders"}` matching three spans returns three entries
that are identical apart from their ref:

```
{ref: el_1, html: "<span></span>", visible: true}
{ref: el_2, html: "<span></span>", visible: true}
{ref: el_3, html: "<span></span>", visible: true}
```

**231 of 734 `run_js` scripts (31.5%)** are the agent re-reading with `innerText`
or `textContent` what `find` had just matched and discarded. The alternative,
`mode: "full"`, returns the entire subtree per match, which is unusable on a
table or a container.

Fix is one line: a `text` field carrying trimmed, length-capped visible text.
`innerText` forces layout, so cap it (~120 chars) and fall back to `textContent`.

### 22. Nothing reads what is currently typed into a field

**Status: fixed in 0.4.0.** `get_text` now reads through the snapshot walk
rather than `body.text`, and that walk has always collected form-control
values. So a field's live value arrives with the page, and `level` reads one
form without the rest of the document.


An input's `value` is a property, not an attribute: it does not appear in
`outerHTML` once anything has typed into it. `get_text` returns nothing for
inputs, because they hold no text node. So no op answers "what is in this box
right now".

Agents reach for `run_js`: `document.querySelector('#comment').value`,
`f.querySelector('#name')?.value`. This is a large part of the 250-script
(34.1%) "other DOM" bucket, and it is also why form tasks are hard to verify --
the agent cannot read back what it just wrote without JS.

Fix: serialise `value`, and `checked` for checkboxes and radios, alongside the
text from entry 21.

### 23. A match carries no context, so identical elements cannot be told apart

**Status: half fixed in 0.4.0.** Text now carries positions, so three strings
reading "Orders" are visibly in different subtrees. `find` results still do
not: a match is still a ref plus a stripped shell. And `level` is accepted only
by `get_text` -- an agent that tried `click {"ref": "AEDBAAAAAAAA"}` was
refused, and thought the limitation worth warning its successor about.


There is no ancestry anywhere in a `find` result. When several elements share
text, nothing distinguishes them, and the only op that can walk a parent chain
is `run_js`.

`webarena.64` is the clean example. At turn 22 the agent tried
`find {"css": "a[href='#orders']"}` and `find {"css": "[data-ui-id*='orders']"}`,
both guesses at DOM structure, both empty. Turns 23 to 25 enumerate the spans
reading "Orders", walk each parent chain to find the one inside
`li.admin__page-nav-item` rather than the top menu, and dispatch a click. That
episode ran 26 turns and 1,091,337 tokens and was then scored on a sentence of
narration.

**43 scripts (5.9%) walk ancestors; 16 (2.2%) dispatch clicks `find` could not
reach.** Smaller than the entries above, but it is the difference between one
`find` plus one `click` and five turns of JS.

Fix: a `path` field -- a `parentElement` walk up four or five levels emitting
`tag#id.class`. Cheap, and it needs no layout.

### 24. Reading many pages costs a turn each, so agents write crawlers instead

**194 of 734 scripts (26.4%), averaging 707 characters**, do not touch the
current page at all. They are `XMLHttpRequest` / `fetch` / `DOMParser` loops over
*other* URLs: `/catalogsearch/result/?q=...&p=1..4`, or forty order pages by id,
fetched and parsed inside the page and reduced to a summary.

The agent does this because the alternative is forty `goto` + `get_text` round
trips against a thirty-turn budget. It is not a targeting failure; it is routing
around a missing capability, and it is the main reason admin episodes (47%
`run_js` use, 357k tokens each) cost roughly double shopping's.

A design question rather than a one-line fix. Whatever shape it takes -- a batch
read over a list of URLs, or one selector extracted across pages -- this is where
the token cost concentrates.

### 25. An episode record cannot distinguish "knew it" from "never found it"

Harness-side. When an episode ends without an `ANSWER:` marker the runner falls
back to scoring the whole reply, so `answer_sent` and `reply` become the same
string. Nothing in the record holds what the agent had actually concluded.

Separating the two cases meant grepping 26 trace files for the gold strings.
Nine of those episodes had the complete answer in their own transcript and never
stated it; ten genuinely had not found it. That distinction decides whether a
failure is a prompting problem or a capability problem, and it should be
readable from `episodes.jsonl`.

Fix: record the last reasoning block, or a `final_answer_candidate`, in the
episode record.

### 26. The ops counter goes negative across a server restart

`ops` is a delta against a counter held by the abt server. When the server
restarts mid-episode the counter resets and the delta comes out negative:
`webarena.494` recorded `ops=-15`, `webarena.402` `ops=-35`. Two episodes in 393,
so aggregates barely move, but every percentile and per-task average has to
filter them out, and nothing in the record says why the number is impossible.

Fix: read the counter as a monotonic session-scoped value, or record the session
id on the episode so a reset is detectable rather than silent.

### 27. The harness prompt work lives only on the benchmark host

`benchmarks/browsergym/loop_policy.py` is 438 lines in this repository and 867 on
the VPS. The repo copy has none of the campaign's prompt work: no `_ANSWER_MARK`,
no `_NUDGE`, no `_turn_budget`, no `_playbook_section`, no counts or forms rules.
Every improvement measured above exists on one server and nowhere else.

### 28. A status word read correctly was still summed anyway -- fixed 2026-09-03

Not a reading failure -- the model's own answer named both facts correctly, in
the same sentence:

```
000000149 -- 7/25/22 -- $354.66 (Canceled)
000000167 -- 7/8/22  -- $40.16  (Complete)
Summing the order totals for July 2022: 354.66 + 40.16 = 394.82
```

Gold wanted `40.16` -- the Complete order alone. The lapse happened entirely
inside the model's own reasoning, after every tool call had already returned;
there is no op in between where a toolkit response could have intervened.

`diff.status_hint` now scans the text a response is about to return for a
closed set of past-tense status words -- Canceled, Cancelled, Rejected,
Declined, Deleted, Refunded, Voided -- and, if any appear, adds a one-line
`status_hint` reminding the caller to check status before summing. It cannot
undo a slip that happens after the response is already in hand, so it will not
catch every instance of this failure; it exists for the ordinary case, where
the reminder lands in the same response that showed the status.

Matches only the status form, never the imperative: "Canceled" fires, "Cancel"
does not. That is what keeps it off every Cancel/Delete button on the page --
a status column and a button use different grammatical forms of the same word,
so the distinction costs nothing to check and needs no knowledge of where on
the page the text sat. Wired into both diffed-op responses and `get_text`
(whole page and `level` reads); a selector-targeted `get_text` stays a bare
string on purpose and is not touched, so `get_text {"css": "#total"} == "$40.16"`
keeps holding exactly the value a caller asked for.
