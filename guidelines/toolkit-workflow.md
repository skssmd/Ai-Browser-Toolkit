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
| Interact | `click` `input` `press` `select` `hover` `scroll` `wait_for` |
| Tabs | `tab_new` `tab_switch` `tab_close` `tab_list` |
| Control | `diff` `status` `shutdown` |

## Targeting and refs

- Ops that touch an element take exactly **one** of `css`, `xpath`, `text`
  (exact visible text), or `ref`. An `index` picks the Nth match.
- `find` returns compact element **shells** (tag + attributes, no children) —
  perfect for surveying a page cheaply. `find_full` returns inner content.
- Every match carries a `ref`. Act on it directly:
  `find` then `click {"ref": "el_0"}` — no re-selecting.
- Refs die on navigation or when the element leaves the DOM. A dead ref returns
  `stale_ref`, never silently hits a different element.

## Diffs: your primary feedback loop

Interactive ops (`click input press select hover scroll wait_for run_js`) and
navigation ops (`goto back forward reload`) snapshot the page before/after and
return `dom_diff`. This is how you see what an action *did*, in real time. Two
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

**Rule of thumb:** verify *effects* with the diff, not with screenshots or
external downloads. Downloads and exports lag; the diff is live.

## Types of work

- **Reading a page:** `find` shells → `find_full` the interesting ones →
  `get_text`/`get_html` for specifics. `run_js` for anything the ops don't cover.
- **Typing:** `input` clears then types into a **visible** target (use
  `"clear": false` to append). `press` sends keystrokes to whatever has focus —
  use it when there is no visible input element (see google-docs.md).
- **Press chords:** `press` accepts `ctrl+v`, `ctrl+alt+1`, `shift+enter`, …
  modifiers are `ctrl/control`, `shift`, `alt/option`, `meta/command/cmd/windows`.
- **Waiting:** `wait_for` with `state` = `present|visible|clickable|absent` and
  a `timeout`. Use it before acting on slow-loading content.

## Errors

A closed set of `error.type` values to branch on: `invalid_op`,
`element_not_found`, `stale_ref`, `not_interactable`, `not_a_select`, `timeout`,
`navigation_failed`, `js_error`, `last_tab`, `tab_not_found`, `browser_dead`.

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
  end — huge diffs are noise.
- Tabs you create for downloads/export are often closed by the human operator;
  never assume a tab id survives. Create a fresh tab for each export check and
  read the newest file in the Downloads folder.
- Log everything. If a run goes wrong, `/viewer` shows exactly what happened.
