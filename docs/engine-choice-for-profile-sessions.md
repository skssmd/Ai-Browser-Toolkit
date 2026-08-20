# Which engine for profile sessions?

Date: 2026-08-20
Question: for the multi-agent / multi-profile / tab-ownership design in
`docs/superpowers/specs/2026-08-19-profile-sessions-design.md`, is Selenium or
Playwright the better base?

Short answer: **Selenium if the feature ships as written. Playwright only if
you intend to remove the limitation the spec currently accepts — and that
removal is an API change, not a driver change.**

## The spec's central constraint, and where it comes from

> A Selenium `WebDriver` has one *current window* and one *current frame*, held
> as state on the driver rather than passed per call. Two threads interleaving
> `switch_to.window` retarget each other's clicks, and — worse than failing —
> both report success.

That is correct, and it is what forces:

- one lock per browser (`BrowserPool: name -> (BrowserSession, Lock)`);
- "same profile: serialized" as a stated non-goal;
- most of `TabOwnership` — claims, TTLs, `tab_locked` — whose sharpest warning
  is that *"an agent's `tab_switch` moves where the other agent's next click
  lands"*.

So a meaningful part of the design is machinery built to contain a hazard the
**engine** creates, not one the problem domain requires.

## What each engine actually offers this design

### Selenium

**Strengths**

- **No marshalling.** The driver can be called from any thread, so
  `run_in_threadpool` -> `pool.get(profile)` -> `lock` -> `dispatch` works
  exactly as the spec draws it. Nothing extra to build.
- **Cheap browser start: 3.1s** against Playwright's 7.2s on the 1.2GB profile
  (measured). With `max_browsers` defaulting to 4 and explicit `browser_start`,
  warming a full pool is ~12s versus ~29s. For a design whose whole point is
  several profiles live at once, that is the most user-visible number here.
- **The lifecycle work is already tuned to it** — singleton-lock probing,
  `PROFILE_RELEASE_TIMEOUT`, the WMI/Task Scheduler spawn. All of that was
  built and debugged against Selenium's process model.

**Weaknesses**

- **Intra-profile concurrency is impossible, not merely unimplemented.** The
  ambient current-window is a property of the driver; no locking granularity
  below one-lock-per-driver is safe.
- **`tabs()` is O(n) round trips and mutates shared state.** It
  `switch_to.window`s to each tab, reads `current_url` and `title`, then
  switches back — so listing tabs is itself an operation that cannot overlap
  with anything, and it is one an orchestrator will call constantly.
- The tab-ownership subsystem is comparatively expensive to build and to
  explain, and it exists mostly to fence off this hazard.

### Playwright

**Strengths**

- **`Page` and `Frame` are addressed, not switched into.** Two agents holding
  two pages of one browser cannot retarget each other, by construction. The
  spec's worst failure mode — a `tab_switch` silently moving where someone
  else's click lands — stops being expressible.
- **`tabs()` becomes a pure read** over `context.pages`, with no switching and
  no mutation, so it is safe to call concurrently and costs one round trip
  instead of 3n.
- **`BrowserContext` is a third isolation level** the spec does not currently
  consider. Its non-goals say *"Chrome's incognito-style contexts are not used;
  isolation comes from separate user-data-dirs"* — a reasonable call on
  Selenium, where contexts are awkward. On Playwright a context is cheap and
  cookie-isolated, which gives you "separate identity, shared browser process"
  without a second 1.2GB profile directory on disk. Worth revisiting for roles
  that need isolation but not a distinct persistent login.
- **25-35% faster per command** (measured across six operations on the live
  app).

**Weaknesses**

- **The sync API is thread-affine, and that is not a detail.** `pwdriver.py`
  marshals every call onto a single owner thread
  (`ThreadPoolExecutor(max_workers=1)`) precisely because a `sync_playwright`
  object may only be driven from its creating thread. **This reintroduces the
  serialization the design was trying to escape.** As implemented today,
  Playwright gives *no* intra-profile parallelism either — one lock per driver
  simply became one thread per driver.
- **Slower cold start** (7.2s), which the pool multiplies.
- The Windows profile-lifecycle work needs revalidating against a different
  process model.

## The finding that decides it

**Today, both engines are equally serialized within a profile.** Selenium
because of ambient driver state; Playwright because of my owner-thread
marshalling. Anyone choosing Playwright *for the concurrency* would be buying a
promise, not a capability.

Worse, cashing that promise is **not** a driver-layer change:

- `pwdriver.py` deliberately reproduces the ambient model — `self._frame`,
  `self._active`, `_SwitchTo` — so the page layer runs unchanged. Removing it
  changes behaviour for every op.
- The spec itself notes that *"almost no command names a tab: `click`, `input`,
  `get_text` and the rest act on whatever the session's **active** tab is."*
  For two agents to work the same browser at once, commands must **name their
  page** — i.e. a `tab:` field on `schema.Base`, alongside `profile:` and
  `agent:`.

That is an API-layer change, and it was out of scope for the engine swap. It is
a *feature* decision, not a migration detail.

**Correction after reading the spec in full.** An earlier draft of this note
implied `tab:` would be an expensive change. It would not: the Architecture
section's whole point is that `profile:` and `agent:` are *one* edit to
`schema.Base` rather than thirty op signatures, and `tab:` rides the same rail.
The spec explicitly rejects "teaching every op about profiles" — and adding a
field to `Base` is not that. So the cost is small; it is the *semantics* that
are the decision, not the diff size.

**The stronger argument for Playwright, which the first draft missed.** On
Selenium the ambient current-window lives in the *remote* WebDriver session, so
it is global to the browser and no amount of Python-side cleverness makes it
per-agent. On Playwright the equivalent state is a Python-side pointer — in
`pwdriver.py` it is literally `self._frame` and `self._active`. That state
*could* be made **thread-local**, giving each agent its own current page inside
one browser, with no op signature changes at all. Selenium structurally cannot
do this; Playwright can.

What blocks it today is the sync API's thread affinity: every call funnels
through one owner thread, so a per-thread current page has no threads to be
per. `playwright.async_api` removes that (current page becomes per-task), which
is why async is the real unlock rather than a stylistic preference.

**A wrinkle worth noting.** On Playwright the pool's `threading.Lock` and the
driver's single owner thread are two serialization mechanisms stacked on the
same browser. Harmless, but the lock stops being what enforces safety — the
owner thread already did — and that should be understood rather than
discovered.

## Recommendation

**Ship profile sessions on Selenium, as specified.** The design's accepted
limitation costs nothing extra there, the pool warms in a third of the time,
and no marshalling layer is needed. Playwright's per-command speed does not
change the shape of anything.

**Then, separately, decide whether intra-profile concurrency is a real
requirement.** If it is:

1. move to `playwright.async_api`, or prove one-owner-thread-per-page on the
   sync API;
2. add `tab:` to `schema.Base` so a command names its page;
3. delete `leave_frames()`, the top-document reset in `dispatch()`, and most of
   `TabOwnership`;
4. rewrite "What is actually parallel" — on that footing it is wrong.

Doing (2)–(4) is what actually buys the feature. Swapping the engine alone
buys nothing for it.

## One correction the spec needs either way

Its migration step is guarded by the singleton-lock check, which
**never fires on Windows** (`Singleton*` are POSIX-only; see
`docs/known-issues.md`). On Windows that guard would let `profile/` ->
`profiles/default/` run against a live browser and corrupt a logged-in profile.
Fix that before implementing the migration, on whichever engine.
