# Playwright migration — phase 1 spike

Date: 2026-08-19
Status: **Phases 1-3 complete.** Both engines pass all 485 tests
(Selenium 416s, Playwright 408s). Phase 4 is the remaining work.

## Why a spike came first

The engine is not the product. `_SNAPSHOT_JS` and `diff.py` are — the three
tracks off one walk that turn a page into the few lines a model needs. So the
migration is only worth doing if the curation layer survives the transplant
unchanged, and only safe to start if a real logged-in profile opens under
Playwright. Both were unknowns, and both are cheap to answer before writing any
migration code.

Constraint the spike was written against: **the engine is swapped underneath
`BrowserSession`, and nothing above it moves.** No change to `schema.py`, the
`REGISTRY`, `dispatch(session, cmd)`, the HTTP routes, the MCP tools, the CLI,
the `dom_diff` shape, `el_N` ref naming, or the error types. If a caller can
tell which engine is underneath, the migration failed.

## A. Persistent profile and logins — PASS

`launch_persistent_context(user_data_dir=..., channel="chrome")` against a copy
of the live 1.2GB profile:

```
cookies visible to the context : 481
distinct domains               : 169
logged-in domains include      : accounts.google.com, docs.google.com,
                                 drive.google.com, facebook.com,
                                 hr.dataclans.com, linkedin-ei.com
```

A profile Playwright had failed to adopt would show ~0 cookies. Logins survive.
`channel="chrome"` uses the installed Chrome, so there is no bundled-Chromium
download and the browser is the same binary Selenium was driving.

## B. Snapshot parity — PASS, 11/11 pages byte-identical

The whole adapter, and the reason the port is small:

```python
WRAP = "(a) => (function(){%s}).apply(null, a)"
page.evaluate(WRAP % script, list(args))
```

`execute_script` takes a statement body using `arguments[0..n]` with a top-level
`return`; `evaluate` takes a function. Calling a real function via `.apply`
gives the body a genuine `arguments` object and a legal `return` — so all 48
script sites port **without editing one line of their JavaScript**. That
includes `_SNAPSHOT_JS`, `_SETTLE_JS`, `_NETWORK_JS`, `_CONSOLE_JS` and
`_VIEWPORT_JS`.

Identical canonicalised JSON out of both engines:

| Page | JSON | tracks |
|---|---|---|
| 8 local fixtures (cards, actionable, shadow, frames, form, inspect, overlay, links) | 218–1312 B | all identical |
| news.ycombinator.com | 51,860 B | dom=808 text=321 act=198 |
| developer.mozilla.org/…/Document | 181,321 B | dom=2625 text=869 act=300 |
| en.wikipedia.org/wiki/Web_browser | 390,559 B | dom=4135 text=1516 act=300 |

**A false negative worth recording.** The first scale run showed Wikipedia and
MDN differing while the track *counts* matched exactly (4135=4135, 1516=1516,
300=300). That was responsive layout, not the engine: Selenium's default
headless window is narrower than Playwright's 1280 default, which puts Vector's
sidebar and MDN's menus on the other side of a CSS breakpoint. Both engines
above the breakpoint produce identical output — and they still do with the
viewports *unequal* (1262x568 vs 1280x720), which is better evidence than
equalising them would have been.

MDN mints a random `uid_<rand>` per load. That is page nondeterminism and is
scrubbed in the comparison, not an engine difference.

## C. The ref path — PASS

`_ACTIONABLE_ELEMENTS_JS` is the one call that returns live elements rather than
JSON — it is how a diff entry becomes an `el_N` ref. Playwright needs
`evaluate_handle` plus `get_properties()` where Selenium returns `WebElement`s
directly. Same element counts on every page that has any (5/5, 3/3, 2/2, 1/1).

This is the one shape needing real adaptation, and it is confined to `refs.py`
and the `resolve_*` path — not spread through `ops/`.

## The one hard problem, unchanged by the spike

Sync Playwright is **thread-affine**: a `sync_playwright()` object may only be
driven from the thread that created it. `server.py` runs commands through
`run_in_threadpool`, which hands out arbitrary pool threads, so a naive port
produces intermittent greenlet errors under load.

The fix is **one owner thread per browser**, with commands marshalled to it over
a queue. Ops stay sync, `dispatch()` keeps its signature, and no route changes.
The pleasing part: the profile-sessions design already wants that exact shape —
`BrowserPool: name -> (BrowserSession, Lock)` becomes
`name -> (BrowserSession, OwnerThread)`.

The alternative — porting to `playwright.async_api` — makes ~30 op handlers plus
`targeting`, `diff` and `frames` async, and is rejected on those grounds.

## What this unlocks in the profile-sessions design

That spec's central limitation is a Selenium artifact:

> A Selenium `WebDriver` has one *current window* and one *current frame*, held
> as state on the driver rather than passed per call.

Playwright addresses `Page` and `Frame` as objects; there is no ambient current
window. So after the migration, same-profile parallelism becomes possible rather
than a documented non-goal, and `leave_frames()` plus the "every command starts
on the top document" reset in `dispatch()` stop being necessary. Implementing
profile sessions on Selenium first would write that limitation into the README,
`AGENTS.md`, the tests and `known-issues.md`, and then require unwriting it.

## Also found

`_profile_locked()` never fires on Windows — see `known-issues.md`. Found while
copying the profile for this spike: eight `chrome.exe` were live on `profile/`
with no `Singleton*` file present, because those are POSIX-only. The
profile-sessions migration names that check as the guard against moving a live
profile, so it must be fixed before that feature ships.

## Reproducing

`scratchpad/spike.py` (A, B, C on local fixtures) and `scratchpad/scale2.py`
(B at real-page scale). Neither touches the repo; both need `playwright`
installed in the venv, which is **not** yet added to `pyproject.toml`.


---

# Outcome (same day)

## Phase 2 — the seam (`fa945dd`)

`src/abt/engine.py`. Nothing outside it and `browser.py` imports Selenium, and
`tests/test_engine.py` enforces that from the import graph rather than by
review. 451 tests before and after, identical set.

## Phase 3 — the swap (`4d91486`)

`src/abt/pwdriver.py`, selected with `--engine playwright`. **485/485 on both
engines.**

**Speed is a wash** — 408s against 416s, 1.7% apart. Worth stating plainly
because the migration is easy to sell on performance and that would be wrong.
The snapshot already costs one round trip no matter how deep the tree, so the
usual Selenium-to-Playwright win was mostly banked before this started. The
case is capability and deletable surface, not throughput.

## The thirteen differences, and why they are the real finding

Every one passed on Selenium and broke on Playwright, and **almost none raised
at the point of the mistake**:

| Difference | How it surfaced |
|---|---|
| `json_value()` returns `"ref: <Node>"` for nodes instead of raising | refs became strings, failing two calls later |
| `css=` pierces open shadow roots; `querySelectorAll` does not | every shadow match found twice |
| Two handles to one node are not `==` and hash differently | `resolve_many` de-duplication silently a no-op |
| `innerText` excludes shadow content | `get_text` dropped what components render |
| `select_option` returns `[]` rather than raising | a bad option would report success |
| `type()` inserts at the caret | `"more"` onto `"preset"` gave `"morepreset"` |
| A held Shift does not shift the character | `shift+a` produced `a` |
| Interception / not-visible arrive inside a `TimeoutError` | `force: true` silently stopped working |
| That check was also case-sensitive across two spellings | same, again |
| `Page.addScriptToEvaluateOnNewDocument` dies with its CDP session | console and network captured nothing; 13 tests |
| `bounding_box()` is viewport-relative, `rect` is document-relative | `_click_at` subtracted the scroll twice |
| Selenium key names collide (`LEFT_SHIFT`/`SHIFT`) | Playwright rejected `"LeftShift"` |
| `ActionChains`/`Select` type-check for Selenium objects | `move_to requires a WebElement` |

Selenium fails loudly; Playwright fails quietly and downstream. This port was
only safe because 485 assertions already existed. **A codebase with thin tests
would have shipped a browser tool that silently mis-clicks and silently drops
text** -- and `force: true` degrading while every ordinary click still passed is
exactly the shape of bug that survives manual testing.

## What phase 4 can now do

- flip `_SELECTOR` to piercing `css=` and delete `shadow.py` (127) and
  `tests/test_shadow.py` (211). **Changes observable behaviour** -- `shadow:
  true` and the `shadowHosts` count stop meaning anything -- so it is a product
  decision, not a refactor.
- drop `browser._captured` per-tab console arming: `add_init_script` is
  context-wide, so known-issues #2 cannot recur on this engine
- replace `_SETTLE_QUIET` / `_SETTLE_NETWORK_GRACE` with real load-state signals
- give `read_network` real status codes and bodies instead of Resource Timing's
  `opaque: true`
- remove `leave_frames` and the top-document reset in `dispatch`

## The caveat for profile sessions

Playwright removes the *reason* that design serialises same-profile commands:
`Page` and `Frame` are addressed, so one agent's `tab_switch` cannot move where
another's click lands. But **this implementation does not deliver parallelism
either** -- sync Playwright is thread-affine, so every call is marshalled onto
one owner thread. One serialisation point replaced another.

Real same-profile concurrency needs `playwright.async_api`, or one owner thread
per page (unproven). Cross-profile parallelism works on either engine.

So the spec should stop citing driver state as a permanent reason for the
limitation. On Playwright it is an artefact of the *sync API* -- a different
constraint, and a fixable one.
