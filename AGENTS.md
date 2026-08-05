# Driving this toolkit

This file exists because pointing at documentation did not work. A capable
model, given only this repository's path, drove a live site for 66 commands
without opening `guidelines/` once — guessing parameter names five times and
hand-rolling `run_js` DOM scans for work the ops already do. So the rules that
matter are written out here rather than linked.

**The full version is [`guidelines/toolkit-workflow.md`](guidelines/toolkit-workflow.md).
Read it.** What follows is the short form.

## What this is

A long-running server that owns a real browser. You send it JSON; it drives the
page and answers. It is a **separate process** that outlives your session.

```bash
curl -s localhost:8765/status          # already running? almost always yes
abt serve --browser chrome             # only if it is not
```

**Check `/status` before starting anything.** The server usually is running,
holding tabs and logins you must not throw away. `abt serve` never returns on
its own — background it or give it its own terminal.

`GET /ops` lists every operation and its parameters. Read it instead of
guessing a parameter name.

## The seven rules

**1. Read the response you already got.** Every command that changes the page
returns `dom_diff`, saying what changed. Do **not** follow a click with
`get_text {"css": "body"}` or a broad `find_full` to "see what happened" — you
were already told. On a real page that follow-up costs tens of thousands of
tokens to learn nothing new.

**2. Navigating hands you the whole page.** `goto`, `back`, `forward`, `reload`
and any click that redirected return the destination's full text in
`dom_diff.text.added`, after waiting for it to finish rendering. No second read
is needed to find out where you landed.

**3. Act on the refs you are given.** `find` returns a `ref` per match. So does
`dom_diff.actionable`, which lists the controls that just appeared with their
role and name. Click those directly. A `find` immediately after a click is
usually a wasted round trip.

```json
{"op": "click", "css": "#menu"}
→ "actionable": {"added": [{"ref": "el_7", "role": "menuitem", "name": "Export"}]}
{"op": "click", "ref": "el_7"}
```

**4. Exactly one target per command.** `ref`, `css`, `xpath` or `text` — never
two. Add `index` to pick the Nth match. Prefer `ref` > `css` > `text`; `text`
matches ancestors too, so it often matches more than you meant.

Selectors and all three tracks reach **inside iframes**, so an embedded sign-in
widget, card field or editor is targetable like anything else and its refs act
normally. You never switch frames yourself.

**5. Batch what you already know.** `POST /commands` takes a list and runs it in
order, in one round trip. Filling a form is one call, not six.

```bash
curl -s localhost:8765/commands -d '[{"op":"input","css":"#a","value":"x"},
                                     {"op":"click","text":"Save"}]'
```

**6. `run_js` is the escape hatch, not the tool.** If you are writing
`document.querySelectorAll` to find something, use `find`. Reach for `run_js`
only when no op covers what you need.

**7. Uploads work through the hidden input.** Sites hide the real
`<input type=file>` behind a custom control. Look for `role: "file"` in
`dom_diff.actionable`, then write the path straight to it — `input` handles the
hiding.

```json
{"op": "input", "ref": "el_4", "value": "C:/docs/passport.pdf"}
```

## Errors are a closed set

`invalid_op` `element_not_found` `stale_ref` `not_interactable` `not_a_select`
`timeout` `navigation_failed` `js_error` `last_tab` `tab_not_found`
`browser_dead`

Branch on `error.type`, never on the message. `invalid_op` means you guessed a
parameter — check `GET /ops`.

## If you speak MCP

`abt mcp` serves these operations as typed tools over stdio, which removes the
guessing entirely. Point your client at it:

```json
{"command": "abt", "args": ["mcp"]}
```

It forwards to the same server, so start `abt serve` first.

## Site playbooks

Some sites break the ordinary rules and have their own notes in
[`guidelines/`](guidelines/README.md) — Google Docs, Google Sheets, Messenger
and others. **Most sites have no playbook, and that is normal.** Finding nothing
for your site means the rules above are enough, not that there is no guidance.

## Working on the toolkit itself

- Tests: `.venv/Scripts/python -m pytest` — needs Chrome, drives real pages.
- After editing anything under `src/abt/`, **restart the server** or it keeps
  serving the old code.
- Found a trap on a live site? Add it to `docs/known-issues.md`. Fixed entries
  are kept, not deleted — the failure is the reason the code looks as it does.
