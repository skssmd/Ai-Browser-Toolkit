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
