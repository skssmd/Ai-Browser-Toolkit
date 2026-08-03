# Google Docs playbook

How to build content into a Google Docs document with the toolkit. Everything
here was learned the hard way; follow it and skip the trial-and-error.

## The fundamental trap: the editor is a canvas

The document body is drawn onto a `<canvas>`. The text you type does **not**
exist as DOM text, so:

- `find`, `get_text`, `get_html`, and `dom_diff` **cannot see the body text**.
- The diff *does* catch structural changes and the save indicator
  (`div#docs-save-indicator-badge`: "Saving…" / "Saved to Drive") — use that as
  the live "an action registered" signal.
- After a `click` on `.kix-page-paginated`, focus lands in an offscreen
  `iframe.docs-texteventtarget-iframe`. The `input` op fails on it
  ("not visible within Ns"); drive it with `press` instead.

## The reliable way to enter content: rich HTML paste

Typing character-by-character with `press` works but is brutally slow. The
fast, lossless route is to write rich HTML to the clipboard and paste it:

1. Build HTML with the tags Docs understands: `h1`, `h2`, `p`, `b`, `i`,
   `ul/li`, `table/tr/td`.
2. Write it to the clipboard with `run_js`:
   ```js
   const blob = new Blob([html], {type: 'text/html'});
   navigator.clipboard.write([new ClipboardItem({'text/html': blob})]);
   ```
   (Verify it landed by setting a marker attribute in the `.then()`, then
   reading it back with a second `run_js` ~1–2s later.)
3. Click into the editor, then `press {"key": "ctrl+v"}`.

### Clean paragraph boundaries are everything

An `<h1>` pasted at the start of an **empty paragraph** becomes a real Heading 1
(with an outline id). An `<h1>` pasted in the middle of text becomes a big-bold
*span* glued into that paragraph — not a heading. Same rule applies to `h2`.

So end every pasted block with an empty `<p></p>`. The next block's `<h1>`/
`<h2>` lands on that empty paragraph → real heading. Structure:

```html
<h1>Section</h1>
<p>Body text with <b>bold</b> and <i>italic</i>.</p>
<ul><li>point</li><li>point</li></ul>
<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>
<p></p>
```

Verified mappings: `h1`/`h2` → real headings, `b`/`i` → real bold/italic,
`ul/li` → real list, `table` → real table. Plain paragraphs → Normal text.
There is no inline "code" style — put command lines in plain paragraphs.

## Headings while typing

If you must type text instead of pasting, apply styles with `press` chords:
`ctrl+alt+1`/`2`/`3` for Heading 1/2/3 while the cursor is in that paragraph,
then `Enter` for a fresh Normal paragraph.

## Clearing the document

`click` the editor, `press {"key": "ctrl+a"}`, `press {"key": "Backspace"}`.
Verify with the save-indicator diff (a real clear changes a lot of DOM).

## The document title

The title field is `input.docs-title-input` in the **top frame** (not the
canvas). Focus it with `run_js` (`el.focus(); el.select()`), then `input` the
value and `press` `Enter`. This is DOM-addressable and does not need paste.

## Verification: export downloads

The export endpoint is the only way to read the actual document text:

- Text: `https://docs.google.com/document/d/<ID>/export?format=txt`
- Structure (headings/tables): `...export?format=html`

Traps:

- **The export can be stale.** Docs may serve old content while the live editor
  is ahead, so cache-bust with a unique query param each time: `&v=1`, `&v=2`, …
- Wait a few seconds for the document to finish saving before exporting.
- Downloading requires navigating a tab to the export URL. The file lands in the
  Downloads folder as `AI Browser Toolkit - Documentation.txt/.html` (Chrome
  adds `(1)`, `(2)`, … suffixes on collision). Read the **newest** file.
- The human usually closes export tabs after the download. Always create a fresh
  tab per export (`tab_new` with the URL) and never assume old tab ids survive.
- Check structure with the HTML export: count `<h1>`, `<h2>`, `<table>` in the
  file, and eyeball the `<body>` for stray paragraphs.

## Worked flow for building a full document

1. Clear the doc (above).
2. For each section, paste its rich HTML block (above), ending with `<p></p>`.
   All commands on `"diff": false` to keep responses small.
3. After every few pastes, check the save-indicator diff to confirm input.
4. Wait for save, then one final HTML export to verify headings/tables and
   catch stray text. Remove strays with `press` `ctrl+end` + `Backspace`.
