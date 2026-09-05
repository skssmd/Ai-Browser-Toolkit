# Level-tree handles: absorbing the actionables track

Date: 2026-09-05
Status: design, approved for planning

## The problem

The toolkit reports a page on two tracks that do not meet.

The **text track** gives every visible string a positional address, so a table
reads as rows and one part of the page can be re-read with
`get_text {"level": "AEDB"}`. It carries no information about what can be
operated.

The **actionables track** reports controls that just appeared, each as
`{"ref": "el_17", "role": "link", "name": "Issues"}`. It carries the role and a
ref that acts, but it is a separate block, and `actionable_report` describes
itself as "a decoration on what the text track already reported".

Three costs follow.

**The same control is paid for twice.** Its text is a line on the text track;
its role and ref are a JSON object beside it. Every turn that reports controls
sends both.

**Elements with no accessible name are dropped entirely.** `diff.py:341`:

> *"A control with no name gives the agent nothing to tie a ref back to, so it
> is noise -- an unlabelled icon, a focusable wrapper div. Dropping it keeps
> this track a decoration on what the text track already reported, never a
> second inventory of the page."*

An icon-only link appears on **neither** track. It is not that the agent cannot
process icons; from its point of view those elements do not exist. Measured
across 180 gitlab episodes, 99 of 641 `find` calls (15%) existed purely to
recover link targets the agent had already seen as text but could not act on,
including blind guesses like `find {'css': 'a[href*="/a11y-syntax-highlighting/issue…"]'}`.

**An input's value is invisible.** The actionables block carries a field's
*name*; the text track carries neither its name nor its value. A field the
agent typed into, or one the page repopulated, produces no observable change.

## The change

The text track absorbs the actionables track. A control's line carries its own
handle and its own key field, and the separate block goes away.

### Line format

```
AEDBa#btn         Save changes
AEDBb#lnk         Issues → /dashboard/issues?assignee_username=byteblaze
AEDBc#inp-q       laptop
AEDBd#sel-country United Kingdom
AEDBe#lnk         → /notifications
```

The mark is `#role` where the control's identity is its text, and `#role-name`
for the three element types whose name and value are different things: `input`,
`select` and `textarea`. For those the line's text is the **value** — what you
want to read back — and the name rides in the mark. Everything else (`#btn`,
`#lnk`, `#chk`, `#rad`, `#opt`, `#file`) takes no name segment; its text is its
identity.

Where an input carries no `name` attribute the mark degrades to bare `#inp`
rather than inventing an identifier.

Role tokens: `#btn` `#lnk` `#inp` `#sel` `#chk` `#rad` `#txt` (textarea)
`#file` `#opt`. Short enough to be cheap, long enough to be unambiguous.

The last line is an icon-only link: no text, so its href is all it has to say,
and today it says nothing at all.

### Controls are edges on the tree

A control absorbs every string inside it onto its own line and does not branch
further. `<button><span>Save</span> <b>now</b></button>` is one line —
`AEDBa#btn Save now` — not three.

This changes the walk. Today `ownText` gives an element only its own child text
nodes, so that button's text lands on the span and the button itself is
textless. Under the edge rule the thing that carries the text is the thing you
can click, which is both fewer lines and a truer description of the page.

### The address is everything before `#`

`AEDBa`, `AEDBa#`, `AEDBa#btn`, `AEDBa#lnk` and `AEDBa#inp-q` all resolve to
the same element. The server strips from `#` onward when resolving; the path
alone is already unique.

The role token is therefore a reading aid, never part of the address. If the
model writes `#btn` on something that was a link, nothing breaks. A class of
transcription error stops being an error.

### Levels act

`{"op": "click", "level": "AEDBa"}` and
`{"op": "input", "level": "AEDBc", "value": "laptop"}` operate directly. One
address for reading and for acting.

### Identity binding, and why the map mirrors the page

A ref is allocated and fails loudly (`stale_ref`) when its element leaves the
DOM. A level is positional and re-resolves against whatever now sits there. For
`get_text` that is harmless. For `click` it is not: after a re-render the level
could address a different control and the click would land silently on the
wrong thing — the failure mode refs exist to prevent.

So the server keeps `level → {role, name/href}` and, on `click`/`input`/`select`,
re-resolves the level and compares against its own record. A mismatch fails
loudly rather than acting.

**The map is built from the full snapshot, not from what the diff printed.**
This matters and is easy to get wrong. The diff suppresses unchanged content,
so a button reported on turn 1 is correctly silent on turn 2. If the map held
only what was emitted, that button would fall out of it and become unusable on
turn 3 — the handle would break precisely when the diff was working properly.
The snapshot walk already visits every element on every diffed op, so the map
mirrors the live page each turn regardless of what was printed. A handle stays
valid while its element is there, and fails only when the element is gone or
something different occupies the position.

### Value changes become visible

The diff compares on the value, so an input whose value is the line's text
gains change detection for free:

- `AEDBc#inp-q laptop` → `AEDBc#inp-q laptop pro` — reported
- an unchanged `Save` button — exact replica, suppressed
- the same button at a new position — same value, treated as unchanged, which
  is correct: it is the same control

A link's href is part of the compared value, so a link whose text stays put
while its target changes is reported. That is the case worth catching: the same
words now pointing somewhere else.

Today a field changing value produces nothing observable.

## What is removed

- The `"actionable": {"added": [...]}` block. Role, name and handle now ride on
  the line that was already being sent.
- The unnamed-control filter at `diff.py:341`. It existed because an unnamed
  control had no text line to decorate; now it has one, and the icon gap closes
  as a consequence of the merge rather than as a separate feature.

## What does not change

- **Still diff-based.** Only what changed is reported. This is not a page
  inventory; the scope of what the diff *covers* widens, its discipline does
  not.
- **`find` and refs stay.** Selector-driven work, `find_full`, and acting on a
  match are untouched.
- **No new control detection.** The snapshot already reads an explicit `role`
  attribute before falling back to the tag, and already catches `tabindex` and
  `contenteditable` — "*the div a framework wired a click handler onto and made
  focusable*". Custom `role="combobox"` widgets and `role="button"` divs are
  detected today.
- **Bare `AEDBa` for a non-control** behaves exactly as now: `get_text {level}`
  reads that subtree. Only the acting ops consult the identity map.

## Deliberately out of scope

**CDP event-listener enumeration.** `DOMDebugger.getEventListeners` could mark
any element carrying a real click listener however it was bound, but it is a
per-element round trip on a path that runs on every diffed op. The cheap
attribute signals already in the walk cover the cases that motivated it
(`role=`, `tabindex`, `contenteditable`). Revisit only if measurement shows
those signals missing controls that matter.

**Nested controls.** A link inside a button, or a card wrapped in an anchor:
under the edge rule the outer control absorbs the text and takes the handle.
The inner remains reachable by selector through `find`. Not worth special
machinery until a task needs it.

## Testing

- **Format**: a button with nested markup renders as one line; an input renders
  `#inp-name` with its value as text; an icon-only link renders with its href
  and no text.
- **Address**: `AEDBa`, `AEDBa#`, and `AEDBa#wrongrole` all resolve to the same
  element; a level with no `#` still reads a subtree.
- **Identity**: a handle still works after an unrelated re-render; a handle
  whose element was replaced fails loudly instead of clicking; a handle
  suppressed by the diff for several turns still works.
- **Diff**: an input value change is reported; an unchanged control is
  suppressed; a control that only moved is not reported as new.
- **Removal**: no response carries an `actionable` block; unnamed controls
  appear on the text track.
- The existing 669-test suite must pass; tests asserting the actionables block
  will need rewriting to assert the merged lines instead.

## Files affected

| file | change |
|---|---|
| `src/abt/diff.py` | walk emits role/name/href per element; edge rule for controls; drop the unnamed filter; render marks; identity map |
| `src/abt/ops/__init__.py` | stop emitting `actionable`; update `_TREE_LEGEND`; `actionable_report` removed |
| `src/abt/targeting.py` | resolve a `level` to an element, stripping from `#` |
| `src/abt/ops/interact.py` | `click`/`input`/`select` accept `level`; identity check and loud failure |
| `docs/reference.md` | document the format, handles, and the removal |
