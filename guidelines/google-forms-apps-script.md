# Google Forms via Apps Script

Building a Google Form of any real size through the Forms UI is a trap: every
question costs a click to add, a click to pick its type, a typed title, and one
click plus one typed string per choice. A 30-item hiring form is several hundred
ordering-sensitive operations, and a single mis-click silently produces the wrong
question type.

**Drive `script.google.com` instead.** One Apps Script run creates the whole
form — sections, every question type, quiz points, the answer key, *and* the
linked response spreadsheet — and returns the URLs. This file is the route that
works, including the four places it bites.

Read [`toolkit-workflow.md`](toolkit-workflow.md) first; this is an addition to
it, not a replacement.

## The shape of the run

1. `goto https://script.google.com/create` — creates a project and lands in the
   editor. The URL that comes back contains the project id; keep it.
2. Inject the code into the Monaco model (see below).
3. `press ctrl+s` to save. The diff shows `Unsaved changes` → `Saving...`.
4. `wait_for` the function name as **text** — it appears in the toolbar's
   function picker once the save has parsed the file. That is your signal the
   code compiled well enough to run.
5. `click text:"Run"`.
6. First run only: the authorization gauntlet (see below).
7. `wait_for text:"Execution completed"`, then read the log.

## Getting code into the Monaco editor

`window.monaco` **is** exposed on the Apps Script IDE, so you do not need the
clipboard. But two obvious approaches fail:

| Approach | Result |
|---|---|
| `model.setValue(code)` | throws `j.create is not a function` — content unchanged |
| `model.applyEdits([...])` with the whole file at once | throws `Cannot read properties of undefined (reading 'lineFeedCnt')` |

`applyEdits` **does** work in small chunks. Clear the model, then append ~1500
characters at a time at the end of the current range:

```js
// clear
var m = monaco.editor.getModels()[0];
m.applyEdits([{range: m.getFullModelRange(), text: ""}]);

// append one chunk
var m = monaco.editor.getModels()[0], r = m.getFullModelRange();
m.applyEdits([{range: {startLineNumber: r.endLineNumber, startColumn: r.endColumn,
                       endLineNumber: r.endLineNumber, endColumn: r.endColumn},
               text: CHUNK}]);
```

Normalise CRLF to LF before chunking. Verify by comparing
`m.getValue().length` against the source length — an exact match means every
chunk landed and nothing was auto-indented or bracket-completed on the way in.
That length check is the whole verification; you do not need to read the code
back.

`applyEdits` fires the model's change events, so the IDE marks the file dirty
and `ctrl+s` saves normally.

> Do not try to read the code back with `get_text`. Monaco renders runs of
> spaces as `U+00A0`, so the text you get out is not byte-identical to what you
> put in even when the model is perfect. Trust the length.

## The authorization gauntlet (first run of a project)

A new project has no OAuth grant, so the first `Run` stops at
`Authorization required`. The full path:

1. `click text:"Review permissions"` — opens the consent flow **as a new tab**,
   which `status` lists normally. `tab_switch` to it.
2. Unverified-app warning: `click text:"Advanced"`, then click the
   `Go to <project name> (unsafe)` link that appears in `actionable.added`.
3. The consent summary page: tick the scopes, then Continue.

**The consent page lives in an iframe.** This matters:

- `find` reads into frames, so it locates the checkboxes and buttons fine.
- `run_js` does **not** — `document.querySelectorAll('input[type=checkbox]')`
  returns an empty list, so you cannot inspect or set `.checked` that way.
- `click text:"Select all"` does not match, because `find` returns element
  *shells* and these Material buttons carry no text in the shell.

So: `find css:"input[type=checkbox], button"`, click the first checkbox by
**ref** (it is "Select all"), and take a `screenshot` to confirm the ticks. A
checkbox toggle is an attribute-only change, so the text diff is empty either
way and the screenshot is the only honest check here.

If you click Continue with nothing ticked you get a *You did not allow any
access* modal. Its two buttons are the last two in the `find` results — go back,
tick, continue.

### The one that will bite you: the popup closes itself

**After you grant access, the OAuth tab closes itself. If it was the active
tab, that kills the WebDriver session** — every later call returns
`browser_dead` / `no such window: target window already closed`, and the session
cannot recover on its own. `tab_switch` and `tab_list` fail too.

Recovery:

```
POST /command {"op":"shutdown"}     # still works with a dead browser
./start-server.sh                   # or start-server.bat
```

Before restarting, check that no Chrome is still holding the toolkit profile:

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -like "*aibrowsertoolkit\profile*" }
```

If one survives, the fresh Chrome hands off to it and the *new* session dies
immediately with `invalid session id`. Never blanket-kill `chrome.exe` — filter
on the profile path, or you close the human's own browser.

### The run does not resume

The grant succeeds, but **the function does not re-run afterwards** — the
project's Executions page shows `Showing 0 executions`. Check it before doing
anything else: it is how you know whether to re-run or whether you are about to
create a duplicate form.

After the restart, reopen the editor, confirm the code survived the save
(`m.getValue().length`), and click `Run` again. The second run goes straight
through with no consent prompts.

## Getting results back out

Apps Script gives you no return channel, so `Logger.log` a block with markers
you can find in the log pane:

```js
Logger.log([
  'FORM_LIVE_URL: ' + form.getPublishedUrl(),
  'FORM_EDIT_URL: ' + form.getEditUrl(),
  'SHEET_URL: '     + ss.getUrl(),
  'ITEM_COUNT: '    + form.getItems().length
].join('\n'));
```

Then read them with a marker search rather than dumping the page — the editor's
own source text is in `body.innerText` and will drown the log:

```js
var t = document.body.innerText || "";
var i = t.indexOf("FORM_LIVE_URL");
return i < 0 ? "NOT_FOUND" : t.slice(i, i + 900);
```

## FormApp notes worth knowing up front

- `form.setIsQuiz(true)` must be set **before** any `setPoints`, or the call
  throws.
- Correct answers come from the choice, not the item:
  `item.createChoice(text, isCorrect)`, collected into `item.setChoices([...])`.
- `setFeedbackForCorrect` / `setFeedbackForIncorrect` take a built object:
  `FormApp.createFeedback().setText(s).build()`.
- **There is no `addFileUploadItem`.** Apps Script cannot create file-upload
  questions at all. Ask for a shareable link in a text item instead, or add the
  upload question by hand in the UI afterwards.
- `setCollectEmail(true)` is deprecated in favour of `setEmailCollectionType`
  but still works; wrap it in `try/catch` so a runtime change cannot fail the
  whole build.
- Sheets integration is two lines and needs no UI work at all:

  ```js
  var ss = SpreadsheetApp.create('My Form - Responses');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  ```

  This creates the sheet and links it; a `Form Responses 1` tab with a
  `Timestamp` header appears immediately. In quiz mode a `Score` column is added
  once the first response arrives.

## Verifying without re-reading everything

Three cheap checks that together are conclusive:

1. **`ITEM_COUNT` arithmetic.** Count what you expect — section headers and page
   breaks are items too. An exact match means every `add*Item` call landed.
2. **`goto` the published URL.** The navigation diff hands back the entire
   rendered form as `text.added`, so one call shows every question, choice and
   help string. This is the real check, and it costs one round trip.
3. **Quiz mode:** on the edit page, regex `body.innerText` for `/(\d+)\s*point/`.
   You should see one `N point` per graded question plus the total. Do **not**
   look for the string `Answer key` — that panel only renders after you click
   into a question, so its absence proves nothing.

## Op-signature gotchas hit while doing this

Cheap to get wrong, and the error messages are the only documentation:

| Op | Correct | Wrong |
|---|---|---|
| `run_js` | `script` | `code` |
| `press` | `key` | `keys` |
| `wait_for` | `timeout` in **seconds**, max 300 | milliseconds |
| `find` | no `diff` key accepted | `diff: false` |
| `screenshot` | returns `base64`; no `path` | `path` |

Building these JSON bodies with `curl` from a shell is where the time goes —
Apps Script sources are full of quotes, apostrophes and newlines. Build the
payload in a language with a real JSON encoder (PowerShell `ConvertTo-Json`,
Python `json.dumps`) and POST that. A JS string literal is just the source text
run through the same encoder.
