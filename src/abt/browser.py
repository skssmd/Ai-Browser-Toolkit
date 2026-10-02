"""Browser lifecycle, persistent profile, and the stable tab registry."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import diff as diff_util
from . import frames as frame_util
from . import trace as trace_util
from .engine import EngineError
from .errors import OpError
from .launch import LaunchConfig
from .policy import Policy, from_settings
from .tabs import TabGate

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

# How long `claim_tab` waits for a claimed tab to reach this session's own
# connection. See the comment there.
CLAIM_VISIBLE_TIMEOUT = 2.0


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


def open_in_file_manager(folder: Path) -> bool:
    """Show a folder in Explorer, Finder or the desktop's file manager."""
    import os
    import subprocess
    import sys

    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # noqa: S606 -- a folder the toolkit made
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return True
    except Exception:
        return False


@dataclass
class Attach:
    """How a session reaches a browser it shares rather than owns.

    Supplied by the SessionRegistry. `connect` makes sure the profile's Chrome
    is running and returns its CDP URL; `disconnect` says this session is
    finished with it; `list_targets` is every page in that Chrome.
    """

    connect: Callable[[], str]
    disconnect: Callable[[], None]
    list_targets: Callable[[], list[dict]]
    gate: TabGate

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
        attach: Attach | None = None,
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
        # What `abt serve` said, so a session's own setting can be undone.
        self._run_js_default = run_js_enabled
        # This session's URL rules. Empty for a session that has none, and
        # always empty outside shared mode -- see `apply_settings`.
        self.policy = Policy()
        # Where this session's files live, when it has a folder at all (a
        # session in a registry does; a bare BrowserSession does not). With
        # uploads_only, a file input takes nothing from outside `uploads_dir`.
        self.uploads_dir: Path | None = None
        self.downloads_dir: Path | None = None
        self.uploads_only_default = False
        self.uploads_only = False
        self._guard = None
        self._cdp_port: int | None = None
        self.max_frames = max_frames
        self.max_frame_depth = max_frame_depth
        self.diff_enabled = diff_enabled
        self.diff_max_tokens = diff_max_tokens
        # Which driver backs this session. Deliberately not on LaunchConfig:
        # that object is serialised into /browser and /status, and the engine is
        # an implementation detail no caller should be branching on. See
        # docs/playwright-spike-2026-08-19.md.
        if engine != "playwright":
            raise ValueError(f"unknown engine {engine!r}: only playwright is supported")
        self._engine = engine
        # Set when this session is one of several on a profile's browser.
        # Everything that differs between owning a browser and sharing one
        # branches on this.
        self._attach = attach
        self._baselines: dict[str, dict] = {}  # tab_id -> {"url", "dom"}
        self._driver: Any = None
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

    @property
    def is_dead(self) -> bool:
        """The browser may be fine but this session's connection to it is gone."""
        return self._driver is not None and bool(getattr(self._driver, "is_dead", False))

    def reconnect(self) -> None:
        """A new connection to the same browser, for a session whose own died.

        A call that gets no answer ends the connection (see `PlaywrightDriver`),
        and every call after it failed with browser_dead -- for good: `status`
        still said running, `browser_start` said a browser was already running,
        and nothing the session was told to try could end it. Seen live: an
        agent sat in that state for twenty minutes, one command every five.

        But Chrome and the session's tabs are untouched, so a restart -- which
        closes them -- is the wrong remedy. This opens a fresh connection, takes
        the session's tabs back, and goes on.
        """
        if self._attach is None:
            raise OpError(
                "browser_dead",
                "the browser connection stopped answering; restart the browser",
            )
        config = self.config
        with trace_util.span("browser.reconnect", config.browser, session=self._attach.gate.session):
            print(
                f"[abt] {time.strftime('%Y-%m-%d %H:%M:%S')} reconnecting "
                f"session {self._attach.gate.session!r} to its browser",
                file=sys.stderr, flush=True,
            )
            # Where the agent was, read from what the dead driver last knew --
            # no round trip. A fresh connection starts on its first tab, and
            # the agent's next click must land where its last one did.
            was_on = self.active_target_hint()
            old, self._driver = self._driver, None
            try:
                if old is not None:
                    old.quit()
            except Exception:
                pass  # it is dead; there is nothing in it to close
            self._reset_state()
            try:
                self._driver = self._launch_driver(config)
                self._driver.implicitly_wait(0)
                self._verify_session()
                if was_on and was_on in self._driver.window_handles:
                    self._driver.switch_to.window(was_on)
                self._install_console_capture()
                self._sync_tabs()
                self.sync_guard()
            except Exception as exc:
                # Leave it stopped, cleanly, rather than half-built: the next
                # call then says there is no browser, and browser_start works.
                self._driver = None
                self._reset_state()
                if isinstance(exc, OpError):
                    raise
                raise OpError(
                    "browser_dead",
                    f"could not reconnect to the browser: {exc}",
                ) from exc

    @property
    def shared(self) -> bool:
        return self._attach is not None

    def refuse_other_profile(self, profile) -> None:
        """A session's profile changes through `abt session set`, never from
        inside it: `browser_start {"profile": ...}` would otherwise walk an
        agent out of the profile it was given."""
        if self._attach is None or profile is None:
            return
        if Path(profile).expanduser().resolve() != self.defaults.profile:
            raise OpError(
                "invalid_op",
                "this session's profile is fixed; change it with "
                "`abt session set NAME --profile P`, not from inside the session",
            )

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
        self.refuse_other_profile(profile)
        if self.is_dead:
            # "Already running" is true of the browser and false of this
            # session's hold on it: say so by mending it.
            if self._attach is not None:
                self.reconnect()
                return {
                    "running": True,
                    "reconnected": True,
                    "config": self.config.to_dict(),
                    "active_tab": self.active_tab,
                }
            self.stop()
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
        try:
            # Implicit waits interact badly with explicit waits and make every
            # failed lookup cost the full timeout. All waiting here is explicit.
            self._driver.implicitly_wait(0)
            self._verify_session()
            self._install_console_capture()
            self._sync_tabs()
            self.sync_guard()
            self._restore_pages()
        except Exception:
            # A shared start that fails part way must let go of the profile,
            # or the connection leaks and the session stays counted on it.
            if self._attach is not None and self._driver is not None:
                self.stop()
            raise
        return {
            "running": True,
            "config": config.to_dict(),
            "active_tab": self.active_tab,
        }

    def _launch_driver(self, config: LaunchConfig):
        from .pwdriver import PlaywrightDriver

        if self._attach is not None:
            url = self._attach.connect()
            self._cdp_port = int(url.rsplit(":", 1)[1].split("/")[0])
            try:
                return PlaywrightDriver(
                    config,
                    action_timeout=self.action_timeout,
                    cdp_url=url,
                    gate=self._attach.gate,
                    downloads=self.downloads_dir,
                )
            except Exception:
                self._attach.disconnect()
                raise
        return PlaywrightDriver(config, action_timeout=self.action_timeout)

    # How many pages a start reopens, at most. Each one is a full page load
    # before the start answers.
    RESTORE_LIMIT = 6

    def active_target_hint(self) -> str | None:
        """Chrome's id for the tab this session is on, without asking Chrome.

        Read from what the driver already knows, so a watcher can find the
        tab while a command is still running -- no lock, no round trip.
        """
        driver = self._driver
        page = getattr(driver, "_page", None) if driver is not None else None
        return getattr(page, "_abt_target_id", None) if page is not None else None

    def page_snapshot(self) -> dict | None:
        """This session's open web pages, in tab order, and which is active.

        Read from Chrome's own list of pages -- no switching tabs, no page
        loads -- so it is cheap enough to take after every command.
        """
        if self._attach is None or not self.is_running:
            return None
        try:
            gate = self._attach.gate
            rows = [r for r in self._attach.list_targets() if gate.owns(r.get("id", ""))]
            active_url = self._driver.current_url
        except Exception:
            return None

        def order(row):
            label = gate.label(row["id"])
            return int(label.split("_")[-1]) if label.split("_")[-1].isdigit() else 0

        urls = [r.get("url", "") for r in sorted(rows, key=order)]
        urls = [u for u in urls if u.startswith(("http://", "https://"))]
        active = urls.index(active_url) if active_url in urls else len(urls) - 1
        return {"urls": urls, "active": max(active, 0)}

    def _restore_pages(self) -> None:
        """Reopen the pages this session had open when its browser last ran.

        Each one still goes through `goto`, so the session's site rules apply;
        a page that is now blocked, or will not load, is skipped rather than
        failing the start.
        """
        source = getattr(self, "pages_to_restore", None)
        if self._attach is None or source is None:
            return
        # Its tabs were still open, and it took them back: nothing to reopen.
        if getattr(self._driver, "reused_tabs", False):
            return
        pages = source() or {}
        urls = [u for u in pages.get("urls") or [] if str(u).startswith(("http://", "https://"))]
        active = pages.get("active")
        active_url = urls[active] if isinstance(active, int) and 0 <= active < len(urls) else None
        # Once each: a page open twice was a duplicate, not a choice.
        urls = list(dict.fromkeys(urls))[: self.RESTORE_LIMIT]
        pages = {"active": urls.index(active_url) if active_url in urls else len(urls) - 1}
        if not urls:
            return
        tabs: list[str | None] = []
        for index, url in enumerate(urls):
            try:
                if index == 0:
                    self.goto(url)
                    tabs.append(self.active_tab)
                else:
                    tabs.append(self.new_tab(url, activate=False))
            except Exception:
                tabs.append(None)
        want = pages.get("active", len(urls) - 1)
        target = tabs[want] if isinstance(want, int) and 0 <= want < len(tabs) else None
        if target:
            try:
                self.switch_tab(target)
            except Exception:
                pass

    def stop(self) -> dict:
        """Quit the browser and forget everything tied to it.

        Safe when nothing is running. A shared session only closes its own tabs
        and lets go; the profile's browser outlives it while anyone else is on
        it. See `_wait_for_profile_release` for why the owning case does more
        than call quit().
        """
        was_running = self.is_running
        if self._guard is not None:
            self._guard.stop()
            self._guard = None
        if self._driver is not None:
            try:
                self._driver.quit()
            except EngineError:
                pass
            except Exception:
                # A shared browser that died under us raises Playwright's own
                # errors on the way out. Letting go must still succeed.
                if self._attach is None:
                    raise
            self._driver = None
        if self._attach is not None:
            if was_running:
                self._attach.disconnect()
            self._reset_state()
            return {"stopped": was_running, "profile_released": True}
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
        self.refuse_other_profile(profile)
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
        except EngineError as exc:
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
        background job all open one. Install per tab, once each:
        registering twice on the same target stacks duplicate scripts.

        Best effort throughout: a browser without CDP still works, just without
        a console.
        """
        try:
            handle = self._driver.current_window_handle
        except EngineError:
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

    def quit(self) -> None:
        """Alias for `stop`, kept because conftest and server teardown call it."""
        self.stop()

    @property
    def driver(self) -> Any:
        if self._driver is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        return self._driver

    def health_check(self) -> None:
        """Raise browser_dead rather than hanging on a driver that has gone away."""
        if self._driver is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        if self.is_dead:
            self.reconnect()
        try:
            self._driver.window_handles
        except EngineError as exc:
            raise OpError(
                "browser_dead",
                f"browser is no longer reachable: {exc.msg or exc}; "
                'relaunch it with {"op": "browser_restart"} '
                "or POST /browser/restart",
            ) from exc

    # --- tabs -----------------------------------------------------------------

    def _new_tab_id(self, handle: str | None = None) -> str:
        # Shared: the profile's registry numbers tabs, so every session and
        # the GUI agree on which one `tab_3` is.
        if self._attach is not None and handle is not None:
            return self._attach.gate.label(handle)
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
                tab_id = self._new_tab_id(handle)
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
        # The browser is fine; this session's current tab is not one it owns --
        # closed, or handed to another session. Restarting would lose every tab.
        raise OpError(
            "tab_not_found",
            "this session's current tab is not one it owns (it was closed, or "
            "given to another session)",
            hint="Open one with tab_new, or tab_claim an unowned tab from tab_list.",
        )

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
        self.check_url(url)
        before = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")
        self._install_console_capture()  # before anything loads in it
        self._sync_tabs()
        # Guarded before it loads anything, not a poll later.
        if self.policy:
            self.sync_guard()
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

    # --- policy -----------------------------------------------------------------

    def apply_settings(self, settings: dict | None) -> None:
        """Take a session's settings: its URL rules and its run_js switch.

        Applies at once -- the network guard picks up new rules on its next
        request, and the next command sees the rest.
        """
        settings = settings or {}
        self.policy = from_settings(settings)
        run_js = settings.get("run_js")
        self.run_js_enabled = self._run_js_default if run_js is None else bool(run_js)
        only = settings.get("uploads_only")
        self.uploads_only = self.uploads_only_default if only is None else bool(only)
        if self.is_running:
            self.sync_guard()

    def sync_guard(self) -> None:
        """Start, stop or refresh the network guard to match the rules."""
        if self._attach is None or self._cdp_port is None:
            return
        if not self.policy:
            if self._guard is not None:
                self._guard.stop()
                self._guard = None
            return
        if self._guard is None:
            from .guard import Guard

            gate = self._attach.gate
            self._guard = Guard(
                self._cdp_port,
                policy=lambda: self.policy,
                owned=lambda: set(gate.registry.owned_by(gate.session)),
            )
        self._guard.sync()

    def check_upload(self, value: str, strict: bool = False) -> str:
        """The file path(s) a file input may be given, or `file_blocked`.

        Each path is resolved -- `..` walked, links followed -- before it is
        compared, so no spelling reaches outside the uploads folder. Several
        files arrive newline-separated, as a file input takes them.
        """
        if not (self.uploads_only or strict):
            return value
        if self.uploads_dir is None:
            raise OpError("file_blocked", "this session has no uploads folder")
        base = self.uploads_dir.resolve()
        accepted = []
        for raw in str(value).split("\n"):
            raw = raw.strip()
            if not raw:
                continue
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = base / path
            path = path.resolve()
            if base not in path.parents:
                raise OpError(
                    "file_blocked",
                    f"{raw} is not in this profile's uploads folder ({base})",
                )
            if not path.is_file():
                raise OpError("file_blocked", f"there is no file {path.name!r} in {base}")
            accepted.append(str(path))
        if not accepted:
            raise OpError("file_blocked", "no file was named")
        return "\n".join(accepted)

    def files(self, open_folder: bool = False) -> dict:
        """What is in this profile's uploads and downloads folders.

        Names, sizes and paths -- never contents. `open_folder` shows the
        uploads folder in the system file manager so a person can add to it.
        """
        if self.uploads_dir is None or self.downloads_dir is None:
            raise OpError("invalid_op", "files needs sessions: run `abt serve` on the playwright engine")
        if self._driver is not None:
            # A finished download is saved by an event, and a sync Playwright
            # connection only hands events over during a call to the browser.
            # One cheap call first, so a download that already landed is
            # listed. It must be a real round trip: `current_url` is answered
            # from Playwright's own cache and delivers nothing.
            try:
                self._driver.title
            except Exception:
                pass

        def listing(folder: Path) -> dict:
            folder.mkdir(parents=True, exist_ok=True)
            rows = [
                {"name": p.name, "path": str(p.resolve()), "size": p.stat().st_size}
                for p in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                if p.is_file()
            ]
            return {"folder": str(folder.resolve()), "files": rows}

        out = {"uploads": listing(self.uploads_dir), "downloads": listing(self.downloads_dir)}
        if open_folder:
            out["opened"] = open_in_file_manager(self.uploads_dir)
        return out

    # What save_file writes: documents, never programs or anything a double
    # click would run.
    SAVE_EXTENSIONS = frozenset(
        {".md", ".txt", ".csv", ".json", ".html", ".xml", ".yaml", ".yml", ".log"}
    )
    SAVE_MAX_BYTES = 2 * 1024 * 1024

    def save_file(self, name: str, content: str, overwrite: bool = False) -> dict:
        """Save a document the caller wrote into this profile's downloads folder.

        `name` must be a bare file name with a text extension: no folders, so
        nothing lands outside the folder, and nothing executable. An existing
        file is left alone -- the new one gets " (2)", " (3)"... -- unless
        `overwrite`.
        """
        if self.downloads_dir is None:
            raise OpError("invalid_op", "save_file needs sessions: run `abt serve` on the playwright engine")
        raw = str(name or "").strip()
        if not raw or raw != Path(raw).name or raw in (".", "..") or any(c in raw for c in '<>:"|?*\\/'):
            raise OpError("file_blocked", f"{name!r} is not a plain file name; give a name like notes.md, no folders")
        suffix = Path(raw).suffix.lower()
        if suffix not in self.SAVE_EXTENSIONS:
            allowed = " ".join(sorted(self.SAVE_EXTENSIONS))
            raise OpError("file_blocked", f"{raw!r}: only text documents can be saved ({allowed})")
        data = str(content).encode("utf-8")
        if len(data) > self.SAVE_MAX_BYTES:
            raise OpError("invalid_op", f"{len(data)} bytes is over the {self.SAVE_MAX_BYTES} byte limit; split it into parts")
        folder = self.downloads_dir
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / raw
        if target.exists() and not overwrite:
            stem, n = Path(raw).stem, 2
            while (folder / f"{stem} ({n}){suffix}").exists():
                n += 1
            target = folder / f"{stem} ({n}){suffix}"
        target.write_bytes(data)
        return {"saved": target.name, "path": str(target.resolve()), "size": len(data),
                "folder": str(folder.resolve())}

    def check_url(self, url: str | None) -> None:
        if url:
            self.policy.check(url)

    # --- sharing ----------------------------------------------------------------

    def _gate(self, op: str) -> TabGate:
        if self._attach is None:
            raise OpError(
                "invalid_op",
                f"{op} needs sessions: run `abt serve` on the playwright engine",
            )
        return self._attach.gate

    def check_tab(self, tab_id: str) -> None:
        """Refuse another session's tab before looking it up. No-op unshared."""
        if self._attach is not None:
            self._attach.gate.check(tab_id)

    def foreign_tabs(self) -> list[dict]:
        """Tabs on this profile that are not this session's.

        Another session's tab is named with its owner and nothing else: what is
        on it is that session's business. An unowned tab shows its page, since
        claiming it is the only thing to do with it.
        """
        if self._attach is None or not self.is_running:
            return []
        own = set(self._handles.values())
        gate = self._attach.gate
        rows = []
        for target in self._attach.list_targets():
            tid = target.get("id")
            if not tid or tid in own:
                continue
            label = gate.label(tid)
            if not gate.placed(tid):
                # No connection has worked out whose it is yet -- it may be a
                # sealed session's popup, carrying an OAuth code in its URL.
                # Say it exists and nothing more until it is placed.
                rows.append({"tab_id": label, "pending": True})
                continue
            owner = gate.owner(tid)
            if owner is None:
                rows.append({
                    "tab_id": label,
                    "url": target.get("url"),
                    "title": target.get("title"),
                    "unowned": True,
                })
            else:
                rows.append({"tab_id": label, "locked": owner})
        return rows

    def claim_tab(self, tab_id: str) -> str:
        gate = self._gate("tab_claim")
        target = gate.target_of(tab_id)
        if target is None:
            # An id straight from the GUI may not have been numbered on this
            # connection yet; listing numbers every page.
            self.foreign_tabs()
            target = gate.target_of(tab_id)
        if target is None:
            raise OpError("tab_not_found", f"no tab {tab_id!r}")
        # A page is claimable only once it has been placed -- given to its
        # opener's owner if it is a popup. Claiming before that would let any
        # session take someone else's popup in the moment before its owner's
        # connection noticed it.
        deadline = time.monotonic() + CLAIM_VISIBLE_TIMEOUT
        while not gate.placed(target):
            if time.monotonic() >= deadline:
                raise OpError(
                    "tab_not_found",
                    f"{tab_id} is not ready to claim yet; list tabs and try again",
                )
            time.sleep(0.05)
            self._sync_tabs()
        gate.claim(target, self.driver.opener_of(target))
        # Each session has its own connection, and a page another connection
        # opened reaches this one's page list a moment after the registry knew
        # of it. Returning before it lands would report a claim whose tab this
        # session cannot yet see.
        deadline = time.monotonic() + CLAIM_VISIBLE_TIMEOUT
        while True:
            self._sync_tabs()
            if target in self._handles.values() or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        return tab_id

    def release_tab(self, tab_id: str | None) -> str:
        gate = self._gate("tab_release")
        self._sync_tabs()
        label = tab_id or self.active_tab
        handle = self._handles.get(label)
        if handle is None:
            self.check_tab(label)
            raise OpError("tab_not_found", f"no tab {label!r}")
        if len(self._order) == 1:
            # Same rule as close_tab: a session with no tab has no active page,
            # and every command after this would fail for a reason nobody
            # would guess.
            raise OpError(
                "last_tab",
                "refusing to release your last tab; open another with tab_new first",
            )
        gate.release(handle)
        self._sync_tabs()
        return label

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
        except EngineError:
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
        except EngineError:
            pass

        overran = False
        try:
            self.driver.get(url)
        except EngineError as exc:
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
        except EngineError:
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
            except EngineError:
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
