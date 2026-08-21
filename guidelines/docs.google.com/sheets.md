# Google Sheets playbook

How to read and write a Google Sheet with the toolkit. Everything here was
verified against a live sheet; follow it and skip the trial-and-error.

## The fundamental trap: the grid is a canvas

The cell grid is painted onto a single `<canvas>`. Verified on a live sheet:

```json
{"canvases": 1, "gridCanvases": 1, "cellDivs": 0}   // [role=gridcell] → zero
```

So the core reading ops **cannot see cell values**:

- `find`, `find_full`, `get_text`, `get_html` never return cell contents.
- `find {"text": "Hello"}` matches only the formula bar, never the grid — a
  useful tell that you are looking at painted pixels, not DOM.
- `click {"css": …}` cannot target a cell, because no cell is an element.
- `dom_diff` will not show a value change inside the grid.

Everything below works *around* the canvas through the three DOM controls that
Sheets does expose.

## The three handles that make Sheets drivable

| Selector | What it is | Use it for |
|---|---|---|
| `#t-name-box` | Real `<input>` | Navigating to any cell or range |
| `.cell-input` | contenteditable `<div>` | Typing a value or formula |
| `#t-formula-bar-input` | `<div>` | Reading the selected cell back |

The menu bar is also real DOM: `#docs-file-menu`, `#docs-edit-menu`,
`#docs-view-menu`, `#docs-insert-menu`, `#docs-format-menu`, `#docs-tools-menu`.

## Reading a cell

Navigate, then read the formula bar. This returns the **formula** for formula
cells (`=SUM(D2:D6)`), not the computed value.

```json
[{"op": "input",    "css": "#t-name-box", "value": "D8"},
 {"op": "press",    "css": "#t-name-box", "key": "Enter"},
 {"op": "get_text", "css": "#t-formula-bar-input"}]
```

To read a *computed* value instead, put `=D8` in a scratch cell and read that,
or use the Sheets API.

## Writing a cell

Always `Delete` first. `.cell-input` is a persistent contenteditable div that
retains content between cells — without clearing, the previous cell's text (and
even the name-box text) gets prepended. This bug produced
`D8=COUNTIF(C2:C6,"Done")=COUNTIF(C2:C6,"Done")` before it was understood.

```json
[{"op": "input", "css": "#t-name-box", "value": "D8"},
 {"op": "press", "css": "#t-name-box", "key": "Enter"},
 {"op": "press", "key": "Delete"},
 {"op": "input", "css": ".cell-input", "value": "=SUM(D2:D6)"},
 {"op": "press", "css": ".cell-input", "key": "Enter"}]
```

`input` with the default `clear: true` now handles contenteditable (it falls
back to select-all + delete), and reports the text it wrote. Keep the explicit
`Delete` anyway — it clears the *cell*, not just the editor.

Formulas can be typed in full, closing paren included; Sheets' auto-close does
not double it up. Verified with `=SUM(D2:D6)` and `=COUNTIF(C2:C6,"Done")`.

## Filling a row: type, then Tab

Far faster than navigating per cell. `Tab` moves right and stays in entry mode;
`Enter` on the last cell returns to the starting column of the next row.

```json
[{"op": "input", "css": "#t-name-box",  "value": "A1"},
 {"op": "press", "css": "#t-name-box",  "key": "Enter"},
 {"op": "input", "css": ".cell-input",  "value": "Task"},   {"op": "press", "css": ".cell-input", "key": "Tab"},
 {"op": "input", "css": ".cell-input",  "value": "Owner"},  {"op": "press", "css": ".cell-input", "key": "Tab"},
 {"op": "input", "css": ".cell-input",  "value": "Status"}, {"op": "press", "css": ".cell-input", "key": "Tab"},
 {"op": "input", "css": ".cell-input",  "value": "Hours"},  {"op": "press", "css": ".cell-input", "key": "Enter"}]
```

**Blank cells break the chain.** Do not "skip" a cell by pressing Tab against a
different element — that desynchronises the sequence and the rest of the row
lands in the wrong columns, silently. If a row has gaps, either type a space, or
abandon the Tab chain and address those cells individually by name box.

## Menus, and how to tell whether one opened

A plain `click` on `#docs-insert-menu` does open the menu. It does not always
*look* like it did, so confirm rather than assume — just read the `dom_diff` the
click already returns. The text track alone answers it, because an open menu is
a list of words that were not on screen a moment ago:

```json
"text": {"added": ["Cells", "Rows", "Columns", "Sheet", "Chart", "Pivot table", …],
         "removed_count": 0, "truncated": false}
```

That is also your menu inventory — you do not need a separate `find` to learn
what the menu contains. If you want the structural confirmation too, add
`"element_diff": true`:

```
-div#docs-insert-menu … [aria-expanded="false" aria-haspopup="false"] "Insert"
+div#docs-insert-menu … [aria-expanded="true"  aria-haspopup="true" ] "Insert"
+div.goog-menu.goog-menu-vertical … [role="menu"]        ← 118 items appear
```

This is the single best use of `dom_diff` on Sheets: the grid is invisible to it,
but every menu, dialog, and sidebar is fully visible.

If a menu genuinely refuses to open (focus stuck in the grid), dispatch the
events directly:

```js
var m = document.querySelector('#docs-insert-menu');
['mouseover','mousedown','mouseup'].forEach(function (t) {
  m.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}));
});
return m.getAttribute('aria-expanded');
```

Menu items are `.goog-menuitem`; filter to `getClientRects().length > 0` for the
open menu, since ~116 hidden ones exist at all times. Match on text
(`/^Chart/`), because their ids are generated (`#b7rucc:15s`).

## Charts

Select the range with the name box first (`A1:D6`), then Insert → Chart. The
Insert menu contains: Cells, Rows, Columns, Sheet, Pre-built tables, **Chart**,
Pivot table, Image, Drawing, Function, Link, Checkbox, Dropdown, Emoji, Smart
chips, Comment.

The chart itself renders into the canvas, so verify with a `screenshot`, not
with `find`.

## Traps

- **Onboarding popups steal your keystrokes.** A "Save time with tables" dialog
  and a Tables side panel appeared unprompted mid-run and swallowed input, which
  left a stray `add` in a cell. Dismiss with `press Escape` and by clicking
  `Got it`, then re-verify the cell you were writing.
- **`get_text` on the formula bar returns `"\n"` for an empty cell**, not `""`.
  Strip before comparing.
- **Screenshot after any multi-step write.** The formula bar can read correctly
  while the sheet is in an unexpected state; only the screenshot showed the
  stray `add` and the cell still in edit mode.
- **`sheets.new`** creates a blank sheet and redirects to its real URL — capture
  that URL from `current_url`, since you will need it after any server restart.
- Login persists across `abt serve` restarts via the profile, so a restart to
  pick up new toolkit code does not cost you the session.

## When not to use the browser at all

For bulk reads, bulk writes, or anything scheduled, use the **Sheets API** with
a service account. It addresses cells directly, has no canvas problem, no
onboarding popups, and does not break when Google reships their frontend. This
playbook is for when the browser is genuinely the only option — a sheet you can
only reach interactively, or a flow that must look like a human did it.
