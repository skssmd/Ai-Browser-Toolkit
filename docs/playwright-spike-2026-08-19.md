# Playwright migration — phase 1 spike

Date: 2026-08-19
Status: **All three questions PASS.** Phase 2 (the driver seam) is unblocked.

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
