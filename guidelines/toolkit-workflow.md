# Toolkit workflow

Concepts for driving the AI Browser Toolkit well. Read this before touching any
site. These are the lessons that took the longest to learn.

## The mental model

The toolkit is a JSON-over-HTTP server that *owns* a real Chrome window. You do
not write WebDriver code; you POST small JSON commands and read JSON responses.
The server keeps the browser up between calls, so state (tabs, logins, focus)
persists across commands.

- `POST /command` — run one command, wait for its result.
- `POST /commands` — run a batch in order. Stops on first error unless you send
  `{"commands": [...], "continue_on_error": true}`.
- `GET /status` — current URL, tabs, live refs. Safe to call mid-flight.
- `GET /ops` — the live op list.
- `/viewer` — a web UI that replays every command and response as they happen.
  Open it in a second tab and watch yourself work; it is the best debugging tool.

## The op groups

| Group | Ops |
|---|---|
| Navigate | `goto` `back` `forward` `reload` `current_url` |
| Read | `find` `find_full` `get_text` `get_html` `run_js` `screenshot` |
| Inspect | `read_console` `read_network` |
| Interact | `click` `input` `press` `select` `hover` `scroll` `wait_for` |
| Tabs | `tab_new` `tab_switch` `tab_close` `tab_list` |
| Control | `diff` `status` `shutdown` |

Some sequences that always run together are also packaged as their own
endpoints — see `/messenger/*` in [messenger.md](messenger.md). They are
shortcuts over these same ops, never a replacement: when one does not fit what
you need, drive the page with the ops directly.

## Targeting and refs

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
> This is the most common and most expensive mistake made with this toolkit: a
> click succeeds, returns a `dom_diff` saying exactly what changed — and the
> agent then fires `get_text {"css": "body"}` or a broad `find_full` to "see
> what happened". You already have what happened. That follow-up costs a round
> trip and can cost tens of thousands of tokens on a real page, to learn what
> was in the response you just received.
>
> The diff is the designed answer to "what did that do", it is snapshotted from
> the live DOM either side of the command, and it is the most heavily tested
> part of this codebase. It is not a hint to be confirmed. **Read it and act.**
>
> This is worth stating plainly because it was once untrue: navigations used to
> snapshot before a single-page app had rendered, so the diff came back holding
> a spinner and agents learned, correctly, to re-read the page. Navigation now
> waits for the network to go idle and the DOM to stop moving before it looks.
> If you still see `Loading…` in a diff, that is a bug worth reporting, not a
> reason to go back to reading the body.

Interactive ops (`click input press select hover scroll wait_for run_js`) and
navigation ops (`goto back forward reload`) snapshot the page before/after and
return `dom_diff`. This is how you see what an action *did*, in real time. Three
tracks:

**`text` — always on, no budget.** The strings that appeared on screen, one
entry per element, plus form-control values. Read this first; on most pages it
is the whole answer and it costs almost nothing.

```json
"text": {"added": ["Widgets", "Gadgets"], "removed_count": 1, "truncated": false}
```

Only rendered text counts, so a hover that reveals a menu reads as its items
being added. An attribute-only change — `aria-expanded`, a class flip — has no
text and shows up as an empty diff. That is the trade: text is clean because it
drops exactly that state churn.

Text that *left* the screen is counted, not listed — on a page that rewrites
itself the removals are the whole old document. `removed_count` tells you
whether it is worth asking; add `"include_removed": true` when it is.

**When you navigate, `added` is the whole destination page.** `goto` `back`
`forward` `reload`, and any click that redirected, hand back the text of the
page they landed on — there is no diff to take against a document that is gone.
So you do **not** need a `find` or `get_text` just to see what is on a page you
just opened; read `dom_diff.text.added` and act. The element track is skipped
here.

**`actionable` — on by default.** The controls among those additions, each with
a **ref you can act on immediately**. This is the shortest path in the toolkit:
click, read what appeared, click the thing that appeared — no `find` in between.

```json
{"op": "click", "css": "#insert-menu"}
→ "text":       {"added": ["Chart", "Pivot table", "Macro"]},
  "actionable": {"added": [
     {"ref": "el_7", "role": "menuitem", "name": "Chart"},
     {"ref": "el_9", "role": "button",   "name": "Macro", "disabled": true}]}

{"op": "click", "ref": "el_7"}
```

Every `name` here is also a string in `text.added`, so the two line up — read
the text to decide, use the ref to act. `role` tells you what a thing is when
the label alone is ambiguous, and `disabled` warns you off a control that has
appeared but is not ready.

Two things it deliberately does not do. It **skips navigations**, because on a
new page every control is "new" and the list would just be the page again — use
`find` after you land. And it **drops controls with no accessible name**, so you
never get a ref you cannot tie to something you read.

The exception worth knowing: **file inputs are reported even when invisible**.
Sites hide the real `<input type=file>` behind a custom uploader, so the element
you must send a path to is never the one on screen. Look for `role: "file"`,
then write the path straight to it — `input` handles the hiding for you:

```json
{"op": "input", "ref": "el_4", "value": "C:/shots/page.png"}
```

Unlike the text track this one is not free — roughly a quarter again on a diffed
op. Pass `"actionable": false` on batch steps whose new controls you will never
click.

**`elements` — pass `element_diff: true`.** The line-per-element unified diff
with tags, ids, classes, and attributes. Reach for it when the change was an
attribute with no visible text, or when you need a selector for something the
text track told you appeared. Budget it with `diff_max_tokens` (per command) or
`--diff-max-tokens` (server); passing a budget implies `element_diff: true`.

- Navigation and tab ops reset the baseline automatically.
- Reading a page is often free: `goto` already returned its text. Reach for
  `find`/`find_full` when you need selectors or refs, not to see the content.
- Suppress noise on a single command with `"diff": false`; disable entirely with
  `--no-diff`.
- Set a manual baseline with `{"op": "diff", "reset": true}`, then re-check with
  `{"op": "diff"}` to catch async SPA updates. The manual `diff` is explicit, so
  it returns everything by default: both tracks, removals listed.

### When the diff looks empty

An empty diff is the one case that tempts you back into re-reading the page.
Do not. An empty `text.added` has three possible causes, and each has a cheaper
answer than dumping the body:

1. **The change had no visible text** — a class flip, `aria-expanded`, a
   `data-` attribute. The text track drops exactly that churn on purpose, which
   is why it stays clean. Ask for the element track instead:
   `{"op": "click", "css": "…", "element_diff": true}`.
2. **The change has not landed yet** — an SPA that updates after the command
   returned. Take a second look with `{"op": "diff"}`, which compares against
   the state the last command left behind. That is what it is for.
3. **Nothing actually happened** — a real outcome, and worth knowing. Before
   this was reported honestly, a click could be swallowed by an overlay and
   still return `ok: true`; `click` now hit-tests first and raises
   `not_interactable` naming what covered it. So `ok: true` with an empty diff
   now genuinely means the click landed and the page did not react.

`get_text {"css": "body"}` answers none of these better than the three commands
above, and costs more than all of them together.

**Rule of thumb:** verify *effects* with the diff, not with screenshots or
external downloads. Downloads and exports lag; the diff is live.

**The loop, in one line:** act, read `dom_diff.text.added` to see what appeared,
act on `dom_diff.actionable.added[].ref` to use it. A `find` between those steps
is usually a round trip you did not need.

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

## Typing into dates

`input` on `<input type="date|time|month|week|datetime-local">` sets the value
directly rather than typing, and fires the events a framework listens for.
Typing into these is a trap: the browser feeds keystrokes to *locale* segment
boxes, so `2026-08-03` on an en-US date input lands as `60803-02-20` and the
form submits silently wrong.

Use the field's own format — `YYYY-MM-DD`, `HH:MM`, `YYYY-MM`, `YYYY-Www`,
`YYYY-MM-DDTHH:MM` — and anything the field rejects raises `not_interactable`
instead of quietly emptying itself.

## Errors

A closed set of `error.type` values to branch on: `invalid_op`,
`element_not_found`, `stale_ref`, `not_interactable`, `not_a_select`, `timeout`,
`navigation_failed`, `js_error`, `last_tab`, `tab_not_found`, `browser_dead`,
`bad_browser`.

Failed ops never quietly continue: batches stop unless `continue_on_error`.

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
