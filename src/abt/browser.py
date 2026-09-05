"""Browser lifecycle, persistent profile, and the stable tab registry."""

from __future__ import annotations

import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions

from . import diff as diff_util
from . import frames as frame_util
from .errors import OpError
from .launch import LaunchConfig

# How long the DOM must hold still before a freshly loaded page counts as
# settled, and how often to look.
#
# The quiet window cannot be short. A page that has not *started* rendering
# looks exactly like one that has *finished* -- both are simply not changing --
# so the only way to tell them apart from the DOM alone is to wait longer than
# the gap between load and first paint. 0.35s bridges a fetch-then-render tick
# on the apps this was built against, and a static page pays it once per
# navigation, against the 1-2s the navigation already cost.
_SETTLE_QUIET = 0.35
_SETTLE_INTERVAL = 0.05

# Chrome single-instances per --user-data-dir. A second launch against a locked
# profile does not open its own browser: it signals the incumbent and exits,
# leaving chromedriver holding a session that dies on first use. driver.quit()
# returns before the Chrome process has exited and released these, so a restart
# that launches immediately lands in that window essentially every time.
# Recovery is explicit-only, so this string is the entire recovery interface.
# "browser is not running" was a dead end: true, and no help at all.
NO_BROWSER_MESSAGE = (
    'no browser is running; start one with {"op": "browser_start"} '
    "or POST /browser/start"
)

PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")
PROFILE_RELEASE_TIMEOUT = 8.0
PROFILE_RELEASE_INTERVAL = 0.2


def _profile_locked(config) -> bool:
    """Whether a browser still appears to hold this profile.

    A heuristic, and treated as one. On POSIX the lock is a symlink encoding
    host and pid which can dangle, so is_symlink matters as much as exists.
    Nothing refuses to act on the answer -- see `_verify_session` for the check
    that actually decides.
    """
    for name in PROFILE_LOCK_FILES:
        path = config.profile / name
        try:
            if path.exists() or path.is_symlink():
                return True
        except OSError:
            continue
    return False

# After the last response lands the app still has to render it, so idle is not
# the same as done. This also has to absorb the *gap* in a chain: fetch a URL,
# parse it, fetch that -- between the two the in-flight count is genuinely zero
# and the DOM is genuinely still, and nothing observable distinguishes that from
# being finished except waiting longer than the gap.
#
# Reported from a live app, where 150ms settled mid-chain and the diff went out
# holding the spinner. No fixed value can be right for every gap; 500ms covers a
# parse-and-refetch and costs a fraction of the 1-2s the navigation already
# spent. Raise it with --settle-network-grace for an app that pauses longer.
_SETTLE_NETWORK_GRACE = 0.5

# A cheap change fingerprint plus the network counter. Element count and text
# length both move sharply when a spinner is replaced by real content, and
# neither forces a reflow the way innerText would.
_SETTLE_JS = """
const b = document.body;
if (!b) { return 'nobody|0|0|0|999999'; }
const net = window.__abtNet;
const inflight = net ? net.inflight : 0;
const quiet = net ? (Date.now() - net.last) : 999999;
return document.readyState + '|' + document.getElementsByTagName('*').length
  + '|' + b.textContent.length + '|' + inflight + '|' + quiet;
"""


class BrowserSession:
    """Owns exactly one browser instance (chrome or edge) for the server's life."""

    def __init__(
        self,
        profile: Path,
        browser: str = "chrome",
        headless: bool = False,
        action_timeout: float = 5.0,
        diff_enabled: bool = True,
        diff_max_tokens: int = 1000,
        settle_timeout: float = 5.0,
        settle_network_grace: float = _SETTLE_NETWORK_GRACE,
        interaction_settle: float = 1.0,
        frames_enabled: bool = True,
        run_js_enabled: bool = True,
        max_frames: int = frame_util.MAX_FRAMES,
        max_frame_depth: int = frame_util.MAX_FRAME_DEPTH,
        engine: str = "playwright",
    ) -> None:
        # Validation lives in LaunchConfig, so an unsupported browser is
        # rejected identically whether it arrived from `abt serve` or from
        # POST /browser/start.
        self.defaults = LaunchConfig(
            browser=browser, profile=profile, headless=headless
        )
        # What is running now, or ran most recently. None until the first start.
        self.launch: LaunchConfig | None = None
        self._profile_release_timeout = PROFILE_RELEASE_TIMEOUT
        self.action_timeout = action_timeout
        self.settle_timeout = settle_timeout
        self.settle_network_grace = settle_network_grace
        # A separate, much shorter budget for an interaction that stayed on the
        # page. A navigation can afford five seconds; a click cannot, because
        # every click pays it. See `_run_with_diff`.
        self.interaction_settle = interaction_settle
        self.frames_enabled = frames_enabled
        # Whether the escape hatch is open. run_js exists for what the ops
        # cannot express, and it is also the thing an agent reaches for instead
        # of learning them -- so it can be closed, and the refusal names what to
        # use instead.
        self.run_js_enabled = run_js_enabled
        self.max_frames = max_frames
        self.max_frame_depth = max_frame_depth
        self.diff_enabled = diff_enabled
        self.diff_max_tokens = diff_max_tokens
        # Which driver backs this session. Deliberately not on LaunchConfig:
        # that object is serialised into /browser and /status, and the engine is
        # an implementation detail no caller should be branching on. See
        # docs/playwright-spike-2026-08-19.md.
        if engine not in ("selenium", "playwright"):
            raise ValueError(f"unknown engine {engine!r}")
        self._engine = engine
        self._baselines: dict[str, dict] = {}  # tab_id -> {"url", "dom"}
        self._driver: webdriver.Chrome | webdriver.Edge | None = None
        self._handles: dict[str, str] = {}  # tab_id -> window handle
        self._order: list[str] = []
        self._counter = 0
        self._captured: set[str] = set()  # handles already armed for console
        # Whether a status_hint has already been shown this session. A status
        # word that survives one warning is not going to be caught by a second
        # identical one -- a line repeated on every page read is a line an
        # agent stops reading, the same reasoning `_ANNOUNCED` uses for
        # playbook announcements. See `diff.status_hint`.
        self.status_warned = False
        # level -> role token, from the last full snapshot of the page. Not
        # from what the diff printed: the diff suppresses what has not changed,
        # and a handle must outlive the turn that first reported it.
        self.level_marks: dict[str, str] = {}
        # Every (level, string) this session has already put in front of the
        # caller. Navigation used to report
        # against the page just left, which is one page deep: go A to B and B's
        # shared furniture is rightly withheld, come back to A and the whole of
        # A returns as "new" though it was read two turns ago. Measured over 61
        # gitlab episodes, 21.6% of everything delivered was a line the agent
        # had already been shown in that same episode.
        #
        # Built from full snapshots rather than from what was printed -- a line
        # withheld from B's report is still on B, so it has to count as seen for
        # C. Same reasoning as `level_marks` above.
        self.seen_text: set[tuple[str, str]] = set()
        # (level, string) -> the URL it was first shown from. A withheld line is
        # only useful to an agent that can find it again, and "you have read
        # this" is not findable -- "you read this on /dashboard/issues" is.
        self.seen_from: dict[tuple[str, str], str] = {}
        # The element the command in flight acted on, for the audit frame's
        # highlight box. Set by `targeting.resolve_one`, cleared per command.
        self.last_target = None
        # Whether the driver may be pointed at a frame rather than the top
        # document. See `leave_frames` for why this is tracked rather than asked.
        self._in_frame = False

    # --- launch configuration -------------------------------------------------

    @property
    def config(self) -> LaunchConfig:
        """The effective config: what is running, or what ran most recently."""
        return self.launch or self.defaults

    @property
    def browser(self) -> str:
        return self.config.browser

    @property
    def profile(self) -> Path:
        return self.config.profile

    @property
    def headless(self) -> bool:
        return self.config.headless

    @property
    def is_running(self) -> bool:
        return self._driver is not None

    # --- lifecycle ------------------------------------------------------------

    def start(
        self,
        browser: str | None = None,
        profile: Path | str | None = None,
        headless: bool | None = None,
    ) -> dict:
        """Launch a browser. Overrides layer over the serve-time defaults.

        Deliberately not idempotent. Silently no-op'ing a start that named a
        different profile would hand back a session on the wrong identity with
        no way to tell -- and the profile is the logins. A caller that wants
        "running, whatever it takes" wants `restart`.
        """
        if self.is_running:
            raise OpError(
                "invalid_op",
                "a browser is already running; use browser_restart to replace "
                "it, or browser_stop first",
            )
        config = self.defaults.merge(
            browser=browser, profile=profile, headless=headless
        )
        config.profile.mkdir(parents=True, exist_ok=True)
        self._driver = self._launch_driver(config)
        self.launch = config
        # Implicit waits interact badly with explicit waits and make every failed
        # lookup cost the full timeout. All waiting here is explicit.
        self._driver.implicitly_wait(0)
        self._verify_session()
        self._install_console_capture()
        self._sync_tabs()
        return {
            "running": True,
            "config": config.to_dict(),
            "active_tab": self.active_tab,
        }

    def _launch_driver(self, config: LaunchConfig):
        if self._engine == "playwright":
            from .pwdriver import PlaywrightDriver

            return PlaywrightDriver(config, action_timeout=self.action_timeout)
        options = self._make_options(config)
        if config.browser == "edge":
            return webdriver.Edge(options=options)
        return webdriver.Chrome(options=options)

    def stop(self) -> dict:
        """Quit the browser and forget everything tied to it.

        Safe when nothing is running. See `_wait_for_profile_release` for why
        this does more than call quit().
        """
        was_running = self.is_running
        if self._driver is not None:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            self._driver = None
        released = self._wait_for_profile_release(self.config) if was_running else True
        self._reset_state()
        return {"stopped": was_running, "profile_released": released}

    def restart(
        self,
        browser: str | None = None,
        profile: Path | str | None = None,
        headless: bool | None = None,
    ) -> dict:
        """Stop and start again.

        Overrides layer over the *effective* config, not the serve-time
        defaults: a session you started headless comes back headless, and one
        on a throwaway profile stays on it. `start` is the one that means
        "fresh". Works as `start` when nothing is running.
        """
        target = self.config.merge(
            browser=browser, profile=profile, headless=headless
        )
        self.stop()
        return self.start(
            browser=target.browser,
            profile=target.profile,
            headless=target.headless,
        )

    def _reset_state(self) -> None:
        """Drop everything that only means something against a live driver.

        Config and the recorder are untouched: the session log spans the
        server's life, and a browser crash plus its recovery is among the more
        interesting things that log can hold.
        """
        self._handles.clear()
        self._order.clear()
        self._counter = 0
        self._captured.clear()
        self._baselines.clear()
        # A new browser is a new conversation: nothing has been read yet, so
        # nothing may be withheld as already read.
        self.seen_text.clear()
        self.seen_from.clear()
        self.last_target = None
        self._in_frame = False

    def _wait_for_profile_release(
        self, config: LaunchConfig, timeout: float | None = None
    ) -> bool:
        """Wait, briefly, for the old browser to let go of the profile.

        Prevention, not a guarantee. A hard-killed Chrome leaves its lock
        behind, so this can spend the whole timeout waiting for a file nobody
        owns -- which is why the answer is only ever *reported*, never enforced.
        """
        budget = self._profile_release_timeout if timeout is None else timeout
        deadline = time.monotonic() + budget
        while True:
            if not _profile_locked(config):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(PROFILE_RELEASE_INTERVAL)

    def _verify_session(self) -> None:
        """Prove the driver we just got is actually driving a browser.

        This is the half that decides. A launch that handed off to an incumbent
        returns a perfectly ordinary-looking driver whose first real command
        fails, so asking it a question is the only way to tell the two apart --
        and unlike checking for a lock file, it cannot false-positive on a
        stale lock left by a crash.
        """
        try:
            self._driver.window_handles
            self._driver.current_url
        except WebDriverException as exc:
            self._driver = None
            self._reset_state()
            raise OpError(
                "browser_dead",
                "the browser exited immediately after starting "
                f"({exc.msg or exc}). Another browser is most likely still "
                f"holding the profile at {self.config.profile} -- close it, "
                "then start again.",
            ) from exc

    # A page's console output is gone by the time anyone thinks to ask for it,
    # so the buffer has to exist before the page does. This runs at document
    # start on every page and every frame, for the browser's whole life.
    _CONSOLE_CAPTURE = """
    (() => {
      if (window.__abtConsole) return;
      const buffer = window.__abtConsole = [];
      const LIMIT = 500;
      const render = (value) => {
        if (typeof value === 'string') return value;
        if (value instanceof Error) return (value.stack || value.message);
        try { return JSON.stringify(value); } catch (e) { return String(value); }
      };
      const push = (level, parts) => {
        try {
          buffer.push({level: level, at: Date.now(),
                       text: Array.from(parts).map(render).join(' ').slice(0, 2000)});
          if (buffer.length > LIMIT) buffer.shift();
        } catch (e) {}
      };
      for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
        const original = console[level];
        console[level] = function (...parts) { push(level, parts); return original.apply(this, parts); };
      }
      addEventListener('error', (e) =>
        push('error', [(e.message || 'error') + ' @ ' + (e.filename || '?') + ':' + (e.lineno || 0)]));
      addEventListener('unhandledrejection', (e) =>
        push('error', ['unhandled rejection: ' + render(e.reason)]));
    })();
    """

    # Counts requests that have started but not finished. A page is not ready
    # while it is still fetching what it intends to display -- and the DOM
    # cannot tell you that, because it holds perfectly still on a spinner while
    # a slow request is in flight.
    #
    # Completion is what counts, not success: a 404, a 500 and a dropped
    # connection all end a request, and treating only 2xx as done would hang
    # here until the timeout on every page that has a failing call.
    _NETWORK_PROBE = """
    (() => {
      if (window.__abtNet) return;
      const state = window.__abtNet = {inflight: 0, last: Date.now()};
      const started = () => { state.inflight++; state.last = Date.now(); };
      const ended = () => {
        state.inflight = Math.max(0, state.inflight - 1);
        state.last = Date.now();
      };
      const originalFetch = window.fetch;
      if (originalFetch) {
        window.fetch = function (...args) {
          started();
          return originalFetch.apply(this, args).then(
            (response) => { ended(); return response; },
            (error) => { ended(); throw error; });
        };
      }
      const send = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.send = function (...args) {
        started();
        try { this.addEventListener('loadend', ended, {once: true}); }
        catch (e) { ended(); }
        return send.apply(this, args);
      };
    })();
    """

    def _install_console_capture(self) -> None:
        """Arm console capture on the tab that is active right now.

        CDP registers the init script against one *target*, so a tab opened
        later gets nothing -- and `tab_new`, a click with `new_tab`, and every
        background Messenger send all open one. Install per tab, once each:
        registering twice on the same target stacks duplicate scripts.

        Best effort throughout: a browser without CDP still works, just without
        a console.
        """
        try:
            handle = self._driver.current_window_handle
        except WebDriverException:
            return
        if handle in self._captured:
            return
        try:
            for source in (self._CONSOLE_CAPTURE, self._NETWORK_PROBE):
                self._driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument", {"source": source}
                )
                # The init script only fires on the *next* document, so seed the
                # page already loaded. It misses whatever happened before now.
                self._driver.execute_script(source)
            self._captured.add(handle)
        except Exception:
            pass

    def _make_options(self, config: LaunchConfig):
        if config.browser == "edge":
            options = EdgeOptions()
        else:
            options = ChromeOptions()
        options.add_argument(f"--user-data-dir={config.profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        if config.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,900")
        return options

    def quit(self) -> None:
        """Alias for `stop`, kept because conftest and server teardown call it."""
        self.stop()

    @property
    def driver(self) -> webdriver.Chrome | webdriver.Edge:
        if self._driver is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        return self._driver

    def health_check(self) -> None:
        """Raise browser_dead rather than hanging on a driver that has gone away."""
        if self._driver is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        try:
            self._driver.window_handles
        except WebDriverException as exc:
            raise OpError(
                "browser_dead",
                f"browser is no longer reachable: {exc.msg or exc}; "
                'relaunch it with {"op": "browser_restart"} '
                "or POST /browser/restart",
            ) from exc

    # --- tabs -----------------------------------------------------------------

    def _new_tab_id(self) -> str:
        tab_id = f"tab_{self._counter}"
        self._counter += 1
        return tab_id

    def _sync_tabs(self) -> None:
        """Reconcile the registry with reality.

        Tabs can appear without us asking (target=_blank) or vanish (user closed
        one). Registered ids keep their handle, so ids stay meaningful.
        """
        live = self.driver.window_handles
        known = set(self._handles.values())
        self._captured &= set(live)  # a closed tab's handle can be reissued
        for tab_id in [t for t, h in self._handles.items() if h not in live]:
            del self._handles[tab_id]
            self._order.remove(tab_id)
            self._baselines.pop(tab_id, None)
        for handle in live:
            if handle not in known:
                tab_id = self._new_tab_id()
                self._handles[tab_id] = handle
                self._order.append(tab_id)

    @property
    def active_tab(self) -> str:
        handle = self.driver.current_window_handle
        for tab_id, known in self._handles.items():
            if known == handle:
                return tab_id
        self._sync_tabs()
        for tab_id, known in self._handles.items():
            if known == handle:
                return tab_id
        raise OpError("browser_dead", "the active window is not in the tab registry")

    def tabs(self) -> list[dict]:
        self._sync_tabs()
        active = self.active_tab
        current = self.driver.current_window_handle
        out = []
        for tab_id in self._order:
            self.driver.switch_to.window(self._handles[tab_id])
            out.append(
                {
                    "tab_id": tab_id,
                    "url": self.driver.current_url,
                    "title": self.driver.title,
                    "active": tab_id == active,
                }
            )
        self.driver.switch_to.window(current)
        return out

    def new_tab(self, url: str | None, activate: bool) -> str:
        before = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")
        self._install_console_capture()  # before anything loads in it
        self._sync_tabs()
        tab_id = self.active_tab
        if url:
            self.goto(url)
        if not activate:
            self.driver.switch_to.window(before)
        return tab_id

    def switch_tab(self, tab_id: str) -> None:
        self._sync_tabs()
        handle = self._handles.get(tab_id)
        if handle is None:
            raise OpError(
                "tab_not_found",
                f"no tab {tab_id!r}; open tabs: {', '.join(self._order) or 'none'}",
            )
        self.driver.switch_to.window(handle)
        # A tab we never opened ourselves (target=_blank) still needs arming.
        self._install_console_capture()

    def close_tab(self, tab_id: str | None) -> None:
        self._sync_tabs()
        target = tab_id or self.active_tab
        if target not in self._handles:
            raise OpError(
                "tab_not_found",
                f"no tab {target!r}; open tabs: {', '.join(self._order) or 'none'}",
            )
        if len(self._order) == 1:
            raise OpError(
                "last_tab", "refusing to close the last tab; use shutdown instead"
            )
        position = self._order.index(target)
        self.driver.switch_to.window(self._handles[target])
        self.driver.close()
        self._baselines.pop(target, None)
        del self._handles[target]
        self._order.remove(target)
        # Activate the nearest surviving tab so the session is never adrift.
        neighbour = self._order[min(position, len(self._order) - 1)]
        self.driver.switch_to.window(self._handles[neighbour])
        self._install_console_capture()

    # --- navigation -----------------------------------------------------------

    # Chrome renders its own error page for a failed load and reports success to
    # the driver. Left alone, an agent would read that page as if it were the
    # site. Detect it and fail loudly instead.
    _ERROR_PAGE = """
    var frame = document.querySelector('#main-frame-error');
    if (!frame) { return null; }
    var code = document.querySelector('.error-code');
    return code ? code.textContent.trim() : 'unknown';
    """

    def error_page_code(self) -> str | None:
        try:
            return self.driver.execute_script(self._ERROR_PAGE)
        except WebDriverException:
            return None

    def goto(self, url: str) -> bool:
        """Navigate. Returns False when it landed but overran the budget.

        A redirect chain can outrun the navigation timeout while the
        navigation itself succeeds -- `https://sheets.new` is the canonical
        case: it 302s to a freshly created document, the wait expires, and the
        page is nevertheless there. Reporting that as `navigation_failed` sends
        a caller off to retry something that already worked.

        So a timeout is only a failure if the browser did not actually move.
        """
        before = None
        try:
            before = self.driver.current_url
        except WebDriverException:
            pass

        overran = False
        try:
            self.driver.get(url)
        except WebDriverException as exc:
            if not self._moved_from(before):
                raise OpError(
                    "navigation_failed", f"could not load {url!r}: {exc.msg or exc}"
                ) from exc
            overran = True
        code = self.error_page_code()
        if code:
            raise OpError(
                "navigation_failed", f"could not load {url!r}: chrome reported {code}"
            )
        self.settle()
        return not overran

    def _moved_from(self, before: str | None) -> bool:
        """Did the browser actually end up somewhere new and usable?

        `about:blank` and a chrome error page both count as not having moved:
        one means nothing happened, the other means something did and failed.
        """
        try:
            after = self.driver.current_url
        except WebDriverException:
            return False
        if not after or after.startswith("about:"):
            return False
        if after == before:
            return False
        return not self.error_page_code()

    def settle(self, timeout: float | None = None) -> bool:
        """Wait for the DOM to stop changing. Returns whether it did.

        `driver.get` returns when the *document* has loaded, which on a
        single-page app is the moment a spinner mounts and nothing else has
        rendered. Snapshotting there produced diffs whose entire content was
        "Loading..." / "Please wait while we process your request" -- so the
        promise that a navigation hands back the page it landed on was false
        exactly where it mattered most.

        Two signals, because neither is sufficient alone:

        * **Network idle.** No request in flight, and none completed in the last
          `_SETTLE_NETWORK_GRACE`. This is the one that matters on a real app:
          while a slow fetch is outstanding the DOM holds *perfectly* still on
          its spinner, so a DOM-only check would call that settled and hand back
          "Please wait" as the page.
        * **A still DOM.** Catches the render that owes nothing to the network --
          a `setTimeout` that swaps in content, an animation that finishes.
          Network idle cannot see those at all.

        A page that never stops -- a poller, a ticking clock, an open
        long-poll -- costs the timeout and then proceeds, because a late diff
        beats no diff. Instrumentation is best effort: without it the network
        term reads as idle and the DOM term carries the check alone.
        """
        deadline = time.monotonic() + (
            self.settle_timeout if timeout is None else timeout
        )
        last = None
        stable_since = 0.0
        while True:
            try:
                fingerprint = self.driver.execute_script(_SETTLE_JS)
            except WebDriverException:
                return False
            now = time.monotonic()
            parts = str(fingerprint).split("|")
            shape, inflight, net_quiet = parts[:3], parts[3:4], parts[4:5]
            busy = inflight != ["0"]
            recent = float(net_quiet[0]) / 1000.0 < self.settle_network_grace if net_quiet else False

            # Only the DOM shape counts as "changed" -- the network figures move
            # on their own and would reset the clock forever.
            if shape != last:
                last = shape
                stable_since = now
            elif (
                parts[0] == "complete"
                and not busy
                and not recent
                and now - stable_since >= _SETTLE_QUIET
            ):
                # "complete" alone is not enough: a document still loading is
                # quiet between resources, and that lull is not readiness.
                return True
            if now >= deadline:
                return False
            time.sleep(_SETTLE_INTERVAL)

    def location(self) -> dict:
        return {"url": self.driver.current_url, "title": self.driver.title}

    # --- frames ----------------------------------------------------------------

    def leave_frames(self) -> None:
        """Put the driver back on the top document.

        Free when it is already there. Every command begins with this call, so
        on the frameless pages that are nearly all of them it must cost nothing:
        only `enter_frame` ever moves the driver off the top document, so a flag
        it sets is enough to know whether there is anything to undo. Erring
        towards "maybe inside" only ever costs one redundant switch; the other
        direction would silently retarget a command, so nothing sets it False
        except actually arriving back.
        """
        if not self._in_frame:
            return
        frame_util.leave(self.driver)
        self._in_frame = False

    def enter_frame(self, path) -> bool:
        """Switch into a frame by path. The top document for an empty path."""
        path = tuple(path)
        if not path:
            self.leave_frames()
            return True
        self._in_frame = True
        entered = frame_util.enter(self.driver, path)
        if not entered:
            self._in_frame = False  # a failed entry leaves the driver at the top
        return entered

    def frame_paths(self) -> list[tuple[int, ...]]:
        """Frames on this page worth walking, in reading order.

        For the callers that are not snapshotting. `snapshot` gets the same
        answer for free out of its own walk and does not come through here.
        """
        if not self.frames_enabled:
            return []
        self.leave_frames()
        found: list[tuple[int, ...]] = []
        pending = [(slot,) for slot in frame_util.child_slots(self.driver)]
        try:
            while pending and len(found) < self.max_frames:
                path = pending.pop(0)
                found.append(path)
                if len(path) < self.max_frame_depth and self.enter_frame(path):
                    pending.extend(
                        path + (slot,) for slot in frame_util.child_slots(self.driver)
                    )
        finally:
            self.leave_frames()
        return found

    def snapshot(self) -> dict:
        """The active tab's state as its dom and text tracks.

        The host document first, then each frame in reading order, folded into
        one set of tracks. A frame is a separate document that no amount of
        walking the parent will reach, so the only way its content reaches the
        diff is to go in and walk it too.

        The driver is returned to the top document afterwards, always: frame
        context is sticky, and a leak would silently retarget every command
        after this one.

        Each document's snapshot reports the frames *it* embeds, so the walk is
        driven by the snapshots themselves and a page with no frames pays
        nothing at all -- no scan, no switch, not one extra request. That
        matters more than it sounds: this runs twice per diffed command, and
        the diff is the reason anyone is here.
        """
        self.leave_frames()
        state = diff_util.snapshot(self.driver, min_frame_px=frame_util.MIN_FRAME_PX)
        if not self.frames_enabled or not state["frames"]:
            return state

        pending = [(slot,) for slot in state["frames"]]
        walked = 0
        try:
            while pending and walked < self.max_frames:
                path = pending.pop(0)
                if not self.enter_frame(path):
                    continue
                inner = diff_util.snapshot(
                    self.driver, min_frame_px=frame_util.MIN_FRAME_PX
                )
                diff_util.merge_frame(state, inner, path)
                walked += 1
                if len(path) < self.max_frame_depth:
                    pending.extend(path + (slot,) for slot in inner["frames"])
        finally:
            self.leave_frames()
        return state

    def baseline(self) -> dict | None:
        """The stored (url, dom, text, actionable) state for the active tab."""
        return self._baselines.get(self.active_tab)

    def remember_seen(self, state: dict) -> None:
        """Fold a page into what this session has already put in front of the caller.

        Deliberately not part of `set_baseline`. The baseline is set as soon as
        the page settles, which is before the diff has been rendered from it --
        so folding there would put the page into the aggregate and then diff the
        page against itself, and every arrival, including the very first, would
        report that nothing was new. That is exactly what happened the first
        time this was wired up.

        Keyed on the level *and* the text, never the text alone. A level is
        positional, so inserting one row renumbers every sibling below it: those
        lines keep their words and move. Matching on words alone would call them
        already-read and withhold them, and the caller would go on holding the
        address they used to sit at -- pointing, now, at whatever moved into
        that slot. Anything that moved in the tree has to show. It also means a
        set will do rather than counts: a level appears once per page, so a
        (level, text) pair cannot repeat within one snapshot.
        """
        try:
            here = self.driver.current_url
        except Exception:
            here = ""
        for pair in state.get("text", []) or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            key = (pair[0], pair[1])
            if not isinstance(key[1], str) or not key[1]:
                continue
            if key not in self.seen_text:
                self.seen_from[key] = here
            self.seen_text.add(key)

    def set_baseline(self, state: dict | None = None) -> dict:
        """Record the current page as the state to diff the next command against.

        Keys only, never live elements: a baseline outlives the command that set
        it, and a WebElement held that long is a stale handle waiting to happen.
        Keys are all a diff needs, and the handles can be fetched later for the
        few entries that turn out to matter.
        """
        if state is None:
            state = self.snapshot()
        # Every control the page holds right now, whether or not the diff will
        # mention it. A handle has to stay usable across the turns where its
        # element sat there unchanged and was rightly left unsaid.
        marks: dict[str, str] = {}
        for pair in state.get("text", []) or []:
            if not pair:
                continue
            path = pair[0] if isinstance(pair, (list, tuple)) else ""
            cut = path.find("#") if isinstance(path, str) else -1
            if cut >= 0:
                token = path[cut + 1 :]
                dash = token.find("-")
                marks[path[:cut]] = token if dash < 0 else token[:dash]
        self.level_marks = marks
        entry = {
            "url": self.driver.current_url,
            "dom": state.get("dom", []),
            "text": state.get("text", []),
            "actionable": state.get("actionable", []),
        }
        self._baselines[self.active_tab] = entry
        return entry
