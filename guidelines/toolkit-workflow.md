# Toolkit workflow

Concepts for driving the AI Browser Toolkit well. Read this before touching any
site. These are the lessons that took the longest to learn.

## The mental model

A long-running server owns a real Chrome window, and **`abt` drives it**. You
do not write WebDriver code; you run small commands and read JSON back. The
browser stays up between commands, so tabs, logins and focus persist.

```bash
abt status                            # a server up? usually yes. URL, tabs, refs
abt up                                # start one if not; returns immediately
abt goto https://example.com
abt find --text "Sign in"
abt click --ref el_3
abt input --css "#email" --value "someone@example.com"
abt ops                               # every op and its exact parameters
abt exec '{"op":"scroll","y":4000}'             # any op, raw
abt exec-batch '[{"op":"click","text":"Edit"},{"op":"get_text","css":"h1"}]'
abt guidelines show toolkit-workflow  # this document
abt guidelines search <domain>        # a playbook for the site you are on?
```

`abt exec` reaches **every** op, including those with no named subcommand — so
the op tables below are the real vocabulary. `abt --help` lists subcommands;
`abt <command> --help` lists flags. On PowerShell, pipe JSON rather than
quoting it inline: `'{"op":"press","key":"Enter"}' | abt exec -`.

**Never run `abt serve` from a tool call.** That is the command loop itself: it
never returns, so whatever launched it hangs until killed. `abt up` is the one
you want — safe at any time, no-ops when a server already answers, and spawns
the server outside your job object so your call returns while it keeps running.
The server usually *is* already running, holding tabs and logins that must not
be thrown away, so check before starting anything.

**Batch what you already know.** `abt exec-batch` runs a list in order and stops
at the first error. Two round trips become one, and you stop guessing between
them.

**The viewer.** `/viewer` in a browser tab replays every command and response as
it happens — the best debugging tool here. Open it beside your work.

**Underneath is HTTP**, and that surface is supported: `POST /command`,
`POST /commands`, `GET /status`, `GET /ops`. Every `abt` subcommand except
`serve` is one of those requests. Use it directly when you are already making
HTTP calls and want to avoid a process launch per command; otherwise prefer
`abt`.

## The op groups

| Group | Ops |
|---|---|
| Navigate | `goto` `back` `forward` `reload` `current_url` |
| Read | `find` `find_full` `get_text` `get_html` `run_js` `screenshot` |
| Inspect | `read_console` `read_network` |
| Interact | `click` `input` `press` `select` `hover` `scroll` `wait_for` |
| Tabs | `tab_new` `tab_switch` `tab_close` `tab_list` |
| Control | `diff` `status` `shutdown` |

A few sites have sequences that always run together, and those are packaged as
shortcuts of their own. They are shortcuts over these same ops, never a
replacement: when one does not fit what you need, drive the page with the ops
directly. Which sites have them, and what they do, belongs in that site's
playbook — `abt guidelines search <domain>`.

## Targeting and refs

- **`near` qualifies a selector that matches too much.** A table whose every
  row has an `Edit` button is the case: `text` alone matches all of them, and
  an `index` is a guess that breaks the moment a row is added.

  ```json
  {"op": "click", "text": "Edit", "near": "Medication"}
  ```

  It picks the match sharing the *smallest* container with that text — the row
  on a table, the section on a card. **Do not reach for `run_js` to stamp an
  attribute on the right row and click that.** An agent doing exactly that
  spent 14 of its 33 `run_js` calls on it, and when one stamp failed it left a
  selector matching nothing and retried the same click ten times.

  A `near` that matches nothing lists the qualifiers that do exist, so a miss
  tells you what to ask for instead.

- Ops that touch an element take exactly **one** of `css`, `xpath`, `text`
  (exact visible text), or `ref`. An `index` picks the Nth match.
- `find` returns compact element **shells** (tag + attributes, no children) —
  perfect for surveying a page cheaply. `find_full` returns inner content.
- Every match carries a `ref`. Act on it directly:
  `find` then `click {"ref": "el_0"}` — no re-selecting.
- Refs die on navigation or when the element leaves the DOM. A dead ref returns
  `stale_ref`, never silently hits a different element.
- Numbering never restarts, so ref numbers climb through a session. That is
  deliberate: a reused name would let a new page's `el_0` answer to a handle you
  were holding for the old one. Do not read meaning into the numbers.
- The `actionable` track on a diff also hands out refs — see below. Reaching for
  `find` right after a click is usually a wasted round trip.

## Diffs: your primary feedback loop

> **Trust the diff. Do not re-read the page to check what a command did.**
>
> This is the most common and most expensive mistake made with this toolkit. A
> click succeeds, returns a `dom_diff` saying exactly what changed — and the
> agent fires `get_text {"css": "body"}` to "see what happened". You already
> have what happened. That follow-up costs a round trip and can cost tens of
> thousands of tokens, to learn what was in the response you just received.
>
> The diff is snapshotted from the live DOM either side of the command. It is
> not a hint to be confirmed. **Read it and act.** (It was once worth
> distrusting — navigations snapshotted before an SPA had rendered. Navigation
> now waits for network idle and a still DOM. A `Loading…` in a diff today is a
> bug to report, not a reason to re-read.)

Interactive ops (`click input press select hover scroll wait_for run_js`) and
navigation ops (`goto back forward reload`) snapshot before/after and return
`dom_diff`. Three tracks:

**`text` — always on, no budget.** Strings that appeared on screen, one entry
per element, plus form-control values. Read this first; on most pages it is the
whole answer.

```json
"text": {"added": ["Widgets", "Gadgets"], "removed_count": 1, "truncated": false}
```

Only *rendered* text counts, so a hover that reveals a menu reads as its items
appearing, and an attribute-only change (`aria-expanded`, a class flip) shows as
an empty diff. That is the trade: text stays clean because it drops that churn.
Removals are counted, not listed — on a page that rewrites itself they are the
whole old document. Add `"include_removed": true` when the count says it matters.

**After a navigation, `added` is the whole destination page.** `goto` `back`
`forward` `reload`, and any click that redirected, return the text of the page
they landed on. So you never need a `find` or `get_text` merely to see what is
on a page you just opened. The element track is skipped there.

**`actionable` — on by default.** The controls among those additions, each with
a **ref you can act on immediately**. This is the shortest path in the toolkit:
click, read what appeared, click what appeared — no `find` in between.

```json
{"op": "click", "css": "#insert-menu"}
→ "text":       {"added": ["Chart", "Pivot table", "Macro"]},
  "actionable": {"added": [
     {"ref": "el_7", "role": "menuitem", "name": "Chart"},
     {"ref": "el_9", "role": "button",   "name": "Macro", "disabled": true}]}

{"op": "click", "ref": "el_7"}
```

Every `name` is also a string in `text.added`, so the two line up: read the text
to decide, use the ref to act. `role` disambiguates, `disabled` warns you off.

When several controls share a name each carries `near` — the nearest text that
is not its own label, so a row of identical `Edit` buttons tells you which row
it belongs to: `{"ref": "el_9", "name": "Edit", "near": "Medication"}`. **This
exists so you do not reach for `run_js` to match a button to its row.** That
DOM-walking is expensive and wrong more often than it looks — it has opened the
wrong row's dialog and returned `ok: true`.

It skips navigations (on a new page every control is "new") and drops controls
with no accessible name, so you never get a ref you cannot tie to something you
read. **Exception: file inputs are reported even when invisible**, because sites
hide the real `<input type=file>` behind a custom uploader. Look for
`role: "file"` and write the path straight to it — `input` handles the hiding:

```json
{"op": "input", "ref": "el_4", "value": "C:/shots/page.png"}
```

Unlike the text track this one is not free — roughly a quarter again on a diffed
op. Pass `"actionable": false` on batch steps whose new controls you will never
click.

**`elements` — pass `element_diff: true`.** A line-per-element unified diff with
tags, ids, classes and attributes. For a change with no visible text, or when
you need a selector for something the text track reported. Budget it with
`diff_max_tokens`; passing a budget implies `element_diff: true`.

- Navigation and tab ops reset the baseline automatically.
- Suppress noise on one command with `"diff": false`; disable entirely with
  `--no-diff`.
- Set a manual baseline with `{"op": "diff", "reset": true}`, then re-check with
  `{"op": "diff"}` to catch async SPA updates. The manual `diff` is explicit, so
  it returns everything: both tracks, removals listed.

### When the diff looks empty

The one case that tempts you back into re-reading the page. Don't — there are
three causes and each has a cheaper answer:

1. **No visible text changed** — a class flip, `aria-expanded`, a `data-`
   attribute. Ask for the element track:
   `{"op": "click", "css": "…", "element_diff": true}`.
2. **It has not landed yet** — an SPA updating after the command returned. Take
   a second look with `{"op": "diff"}`, which compares against the state the
   last command left. That is what it is for.
3. **Nothing happened** — a real outcome, and worth knowing. `click` hit-tests
   first and raises `not_interactable` naming what covered it, so `ok: true`
   with an empty diff genuinely means the click landed and the page did not
   react.

`get_text {"css": "body"}` answers none of these better, and costs more than all
three together. There used to be a fourth cause — a change inside an iframe,
invisible to every selector. All three tracks now read into frames and refs from
inside them act normally; you never switch frames yourself.

**Verify effects with the diff, not with screenshots or downloads.** Downloads
and exports lag; the diff is live.

**The loop, in one line:** act, read `dom_diff.text.added` to see what appeared,
act on `dom_diff.actionable.added[].ref` to use it. A `find` between those steps
is usually a round trip you did not need.

## Searching for something that should be there

The rule above is about *verifying what a command did*. This one is about
*looking for something*, and its failure mode is the opposite: a search comes
back empty, the agent reads that as "my selector was wrong", and starts
guessing. On a live LinkedIn profile an agent searched for `input[type=file]`,
got `count: 0`, and spent **fifteen commands and six minutes** widening
`run_js` scans. There was no file input — the page creates it when you engage
the drop zone.

**A search that finds nothing is an answer.** Climb this ladder once, then
believe it:

| | step | what it covers |
|---|---|---|
| 1 | **Re-read the response you have** | A navigation already returned the whole page in `text.added` |
| 2 | **`find`** — `css`, then `text` | The document and every frame |
| 3 | **`get_text`** | Rendered text, *including open shadow roots* |
| 4 | **`find` with `"shadow": true`** | Turns shadow content into a ref you can act on |
| 5 | **Stop** | It is not there |

Step 3 follows the composed tree, so a component's internals are in it with no
flag — discovery is free. Step 4 exists because reading a label is not the same
as being able to click it.

**You are told when step 4 is worth taking.** Shadow roots are counted on every
snapshot but never walked:

```json
{"op": "find", "css": "#resume"}
→ {"count": 0, "shadow_hosts": 2,
   "note": "nothing matched, but this page has 2 shadow root(s) … retry with \"shadow\": true"}
```

No hosts, no note — so on most pages this costs and says nothing.

**Do not `run_js` a `querySelectorAll` to "look harder".** Steps 2–4 already
searched the document, its frames and its open shadow roots. JavaScript finds
the same nothing, a round trip and a few thousand tokens later.

**The usual real cause:** the page has not created the control yet. Hidden file
inputs are the classic — mounted when you click the visible upload button or
drop zone. Act on what the page is showing you, then look again.

**The one honest limit:** a `mode: "closed"` shadow root returns `null` from
`.shadowRoot`, so no JavaScript can read it or prove it exists, and neither can
this. "Not there" means *nothing reachable has it*. Closed roots are rare
outside browser internals like `<video>` controls.

## Types of work

- **Reading a page:** `find` shells → `find_full` the interesting ones →
  `get_text`/`get_html` for specifics. `run_js` for anything the ops don't cover.
- **Typing:** `input` clears then types into a **visible** target (use
  `"clear": false` to append). The one exception is `<input type=file>`, which
  sites hide on purpose — `input` writes a path to it anyway. `press` sends keystrokes to whatever has focus —
  use it when there is no visible input element (see google-docs.md).
- **Press chords:** `press` accepts `ctrl+v`, `ctrl+alt+1`, `shift+enter`, …
  modifiers are `ctrl/control`, `shift`, `alt/option`, `meta/command/cmd/windows`.
- **Waiting:** `wait_for` with `state` = `present|visible|clickable|absent` and
  a `timeout`. Use it before acting on slow-loading content.

## Clicking what the DOM cannot address

`click` takes `at: [x, y]` for a canvas, a closed shadow root, an image map —
anything a selector cannot reach. It is a real synthesized pointer sequence, so
`event.isTrusted` is true and a page cannot tell it from a person.

```json
{"op": "click", "css": "canvas#pad", "at": [120, 80]}   // inside that element
{"op": "click", "at": [640, 400]}                        // in the viewport
```

**Prefer the element-relative form.** With a target, `at` is an offset from the
element's top-left and the element is scrolled into view first, so the numbers
mean the same thing however the page is scrolled. A bare viewport point is
whole-pixel while layout is fractional, so it is only good to about a pixel.

The response reports `hit` — what `elementFromPoint` found there. A coordinate
click is blind by nature; check `hit` rather than assume. A point off screen
raises `not_interactable` instead of clicking nothing.

Reach for this only when targeting genuinely cannot work. A `css` selector
survives a redesign; a coordinate does not.

## When the page won't say what went wrong

The DOM tells you what a page *is*. `read_console` and `read_network` tell you
what it *did* — and a failed request usually leaves nothing in the DOM at all.

- `read_console` — everything the page logged, plus uncaught errors and
  unhandled rejections. Captured from **document start**, so a reload gives you
  what a page said while loading, which is where the useful errors are. Filter
  with `pattern` (regex on the text) and `levels`.
- `read_network` — every request with its status, duration, and size.
  `failures_only: true` is the one you want: it keeps 4xx/5xx and anything the
  browser refused to disclose. `pattern` filters on URL.

A real case: a site showed "Failed to load PDF" and nothing else. The DOM had no
more to give. `read_network` with `failures_only` showed a 404 on a storage key
— the whole diagnosis in one call.

Statuses and URLs, not bodies. A cross-origin response without
`Timing-Allow-Origin` reports `status: null` and `opaque: true`; the browser
genuinely will not say, so neither does this.

## A field that suggests is a field that must be chosen from

**If typing into a field makes suggestions appear in the diff, typing is not
finished — you have to pick one.**

This is the most expensive silent failure on the web, because every signal
says you succeeded. `input` returns `ok`, and the value it reports is exactly
the value you asked for. The form disagrees: many of these fields validate the
raw text against the suggestion list and accept nothing else, so `ACV` is
rejected where `Arcata, CA (ACV)` is accepted. Nothing announces the
rejection. A red outline appears, the submit quietly does nothing, and the
next thing you do is retype the value that was never the problem.

The diff is what tells you, and it tells you immediately:

```
abt input --css '#flight-from' --value 'ACV'
```
```json
"text": {"added": ["ACV", "Arcata, CA (ACV)", "Eureka/Arcata, CA (ACV)",
                   "2 results are available, use up and down arrow keys..."]}
```

Suggestions in `text.added` after typing means the field is a chooser. Click
the one you want — it is in `actionable` with a ref — or press `Down` then
`Enter`. Then check that the field holds the *full* suggestion text, not what
you typed.

Two suggestions that both contain your text is the case worth slowing down
for: above, `Arcata, CA (ACV)` and `Eureka/Arcata, CA (ACV)` both match, and
only one is right. Read them before clicking rather than taking the first.

## Typing into dates

`input` on `<input type="date|time|month|week|datetime-local">` sets the value
directly rather than typing, and fires the events a framework listens for.
Typing into these is a trap: the browser feeds keystrokes to *locale* segment
boxes, so `2026-08-03` on an en-US date input lands as `60803-02-20` and the
form submits silently wrong.

Use the field's own format — `YYYY-MM-DD`, `HH:MM`, `YYYY-MM`, `YYYY-Www`,
`YYYY-MM-DDTHH:MM` — and anything the field rejects raises `not_interactable`
instead of quietly emptying itself.

**A readonly date field is a different animal.** Most date fields on the web
are plain text inputs marked `readonly` and driven by a JavaScript calendar.
Nothing can be typed into one, and `input` says so: *"is readonly, so nothing
can be typed into it"*. Click it instead, and the calendar's controls arrive
in `dom_diff.actionable` with refs.

Then **read the calendar's header before clicking anything in it**. It tells
you which month is showing, and that decides which of three routes is right:

1. **Already the month you want.** Common, because a form that expects a date
   in a range often opens the calendar inside that range. Click the day.
2. **A month or two away.** Click the previous/next arrow that many times.
3. **Years away.** Look for month and year `<select>`s in the header and use
   them. If there are none — and many calendars ship without them, jQuery UI
   among them by default — the arrows are the only route, one click per
   month. At that point check whether the field will take a value directly
   through `run_js` instead.

The mistake is clicking the arrow before reading the header, because the
number of clicks needed is the one thing the header tells you and guessing
it costs a click each time you guess low.

## Errors

A closed set of `error.type` values to branch on: `invalid_op`,
`element_not_found`, `stale_ref`, `not_interactable`, `not_a_select`, `timeout`,
`navigation_failed`, `js_error`, `last_tab`, `tab_not_found`, `browser_dead`,
`bad_browser`.

Failed ops never quietly continue: batches stop unless `continue_on_error`.

### A tab that closes itself takes the session with it

OAuth popups, payment frames and "you may close this window" tabs close
themselves when they finish. **If such a tab was the active one, the session
dies** — every later call returns `browser_dead` with `no such window: target
window already closed`, and neither `tab_switch` nor `tab_list` can recover it,
even though the other windows are still on screen.

Avoid it by not standing there: `tab_switch` back to the tab you came from
*before* clicking the control that completes the flow, when the flow allows it.

Once it has happened, send `{"op": "browser_restart"}`. Like `status` and
`shutdown` it skips the health check, so it works precisely when everything else
returns `browser_dead`. The server stays up, the session log continues, and you
get a fresh browser on the same profile — so you are still logged in, but
**every tab and every ref is gone** and you must navigate back.

You no longer have to check by hand that nothing else holds the profile: `stop`
waits for the old browser to release it, and `start` probes the new session and
fails loudly rather than handing you one that dies on first use.

Still worth fixing properly: falling back to a surviving window handle on
`NoSuchWindowException` would keep the tabs, which `browser_restart` cannot.

## Site traps to remember

- **Canvas-rendered editors** (Google Docs, Figma, Excalidraw) put the text on
  a `<canvas>`, not in the DOM. `find`/`get_text`/diff cannot see the typed
  text — the diff still catches structural and save-indicator changes.
- **Offscreen focus targets** (`input` on a hidden editor iframe) fail with
  "not visible within Ns" even though the element exists and has focus.
  Drive them with `press` instead.
- **Exports/downloads can be stale** — a doc's export endpoint may serve old
  content while the live editor is ahead. Cache-bust the URL and wait for save.

## Hygiene

- Keep bulk operations on `"diff": false` and do one verification pass at the
  end — huge diffs are noise. **Except across a form fill:** the text track
  captures input values, so a diff after typing is the cheapest way to catch a
  field that took something other than what you sent. A whole form filled on
  `"diff": false` once hid a mangled date until the server rejected it twice.
- Tabs you create for downloads/export are often closed by the human operator;
  never assume a tab id survives. Create a fresh tab for each export check and
  read the newest file in the Downloads folder.
- Log everything. If a run goes wrong, `/viewer` shows exactly what happened.
