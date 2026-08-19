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
from .refs import RefCache

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
        frames_enabled: bool = True,
        max_frames: int = frame_util.MAX_FRAMES,
        max_frame_depth: int = frame_util.MAX_FRAME_DEPTH,
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
        self.frames_enabled = frames_enabled
        self.max_frames = max_frames
        self.max_frame_depth = max_frame_depth
        self.diff_enabled = diff_enabled
        self.diff_max_tokens = diff_max_tokens
        self.refs = RefCache()
        self._baselines: dict[str, dict] = {}  # tab_id -> {"url", "dom"}
        self._driver: webdriver.Chrome | webdriver.Edge | None = None
        self._handles: dict[str, str] = {}  # tab_id -> window handle
        self._order: list[str] = []
        self._counter = 0
        self._captured: set[str] = set()  # handles already armed for console
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
        self.refs = RefCache()
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
            self.refs.drop_tab(tab_id)
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
        self.refs.drop_tab(target)
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

    def goto(self, url: str) -> None:
        try:
            self.driver.get(url)
        except WebDriverException as exc:
            raise OpError(
                "navigation_failed", f"could not load {url!r}: {exc.msg or exc}"
            ) from exc
        self.refs.invalidate(self.active_tab)
        code = self.error_page_code()
        if code:
            raise OpError(
                "navigation_failed", f"could not load {url!r}: chrome reported {code}"
            )
        self.settle()

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

    def resolve_ref(self, ref: str):
        """A ref's element, with the driver switched into the document holding it.

        Both halves matter and in this order: the staleness check inside the
        cache asks the element a question, and asking it from the wrong document
        answers "stale" for an element that is perfectly alive.
        """
        self.enter_frame(self.refs.frame_of(self.active_tab, ref))
        return self.refs.get(self.active_tab, ref)

    # --- DOM diff baselines ----------------------------------------------------

    def snapshot(self) -> dict:
        """The active tab's state as its dom, text, and actionable tracks.

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

    def actionable_elements(self, entries: list[dict], indices: list[int]) -> list:
        """Live handles for the entries a diff picked, in the order it picked them.

        Entries carry the frame they were collected in, so the picks are grouped
        by document and each group fetched from inside its own -- the array the
        walk parked belongs to that document's window and exists nowhere else.
        """
        if not indices:
            return []
        groups: dict[tuple[int, ...], list[tuple[int, int]]] = {}
        for position, index in enumerate(indices):
            if index >= len(entries):
                return []
            entry = entries[index]
            home = tuple(entry.get("frame") or ())
            groups.setdefault(home, []).append((entry.get("slot", index), position))

        found: list = [None] * len(indices)
        try:
            for home, picks in groups.items():
                if not self.enter_frame(home):
                    return []
                handles = diff_util.actionable_elements(
                    self.driver, [slot for slot, _ in picks]
                )
                if len(handles) != len(picks):
                    return []
                for (_slot, position), handle in zip(picks, handles):
                    found[position] = handle
        finally:
            self.leave_frames()
        if any(handle is None for handle in found):
            return []
        return found

    def baseline(self) -> dict | None:
        """The stored (url, dom, text, actionable) state for the active tab."""
        return self._baselines.get(self.active_tab)

    def set_baseline(self, state: dict | None = None) -> dict:
        """Record the current page as the state to diff the next command against.

        Keys only, never live elements: a baseline outlives the command that set
        it, and a WebElement held that long is a stale handle waiting to happen.
        Keys are all a diff needs, and the handles can be fetched later for the
        few entries that turn out to matter.
        """
        if state is None:
            state = self.snapshot()
        entry = {
            "url": self.driver.current_url,
            "dom": state.get("dom", []),
            "text": state.get("text", []),
            "actionable": state.get("actionable", []),
        }
        self._baselines[self.active_tab] = entry
        return entry
