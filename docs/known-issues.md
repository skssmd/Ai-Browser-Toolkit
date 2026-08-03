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

### 6. `_choose_browser` prompted, breaking detached launches — fixed 2026-08-03

`typer.prompt` needs a TTY, and `abt serve` is routinely started detached, where
there is no stdin to answer with. It now defaults to chrome when
`sys.stdin.isatty()` is false, and still prompts for a human.

## Open

### 7. A click can report `ok: true` and do nothing

Seen on `hr.dataclans.com`: with the site's own error dialog open, a
`click {"text": "Create Employee"}` returned `ok: true`, made no request, and
changed nothing.

**Not diagnosed** — this is an observation, not a root cause, and issue 3 above
may have been part of it. Worth reproducing deliberately: does
`element_to_be_clickable` actually reject an element covered by an overlay, and
what does a click dispatched on a covered element report?

"Succeeded and changed nothing" is the worst failure an agent can be handed, so
this matters more than its size suggests.

### 8. No coordinate click

Every interactive op targets by `css`/`xpath`/`text`/`ref`. A control with no
addressable DOM node — canvas, closed shadow DOM, an image map — can be seen in
a `screenshot` and then not acted on.

Hit while annotating a canvas PDF editor: the only available move was to click
the canvas centre, with no way to place a mark anywhere specific.

`ActionChains.move_by_offset(...).click()` already exists in Selenium and
`document.elementFromPoint(x, y)` works through `run_js` today; this is about
making it a first-class op, e.g. `click {"at": [x, y]}`.
