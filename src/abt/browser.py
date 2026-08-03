"""Browser lifecycle, persistent profile, and the stable tab registry."""

from __future__ import annotations

from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions

from . import diff as diff_util
from .errors import OpError
from .refs import RefCache

_SUPPORTED_BROWSERS = ("chrome", "edge")


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
    ) -> None:
        browser = browser.lower()
        if browser not in _SUPPORTED_BROWSERS:
            raise OpError(
                "bad_browser",
                f"unsupported browser {browser!r}; choose from {', '.join(_SUPPORTED_BROWSERS)}",
            )
        self.browser = browser
        self.profile = Path(profile).expanduser().resolve()
        self.headless = headless
        self.action_timeout = action_timeout
        self.diff_enabled = diff_enabled
        self.diff_max_tokens = diff_max_tokens
        self.refs = RefCache()
        self._baselines: dict[str, dict] = {}  # tab_id -> {"url", "dom"}
        self._driver: webdriver.Chrome | webdriver.Edge | None = None
        self._handles: dict[str, str] = {}  # tab_id -> window handle
        self._order: list[str] = []
        self._counter = 0
        self._captured: set[str] = set()  # handles already armed for console

    # --- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self.profile.mkdir(parents=True, exist_ok=True)
        options = self._make_options()
        if self.browser == "edge":
            self._driver = webdriver.Edge(options=options)
        else:
            self._driver = webdriver.Chrome(options=options)
        # Implicit waits interact badly with explicit waits and make every failed
        # lookup cost the full timeout. All waiting here is explicit.
        self._driver.implicitly_wait(0)
        self._install_console_capture()
        self._sync_tabs()

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
            self._driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": self._CONSOLE_CAPTURE},
            )
            # The init script only fires on the *next* document, so seed the
            # page already loaded. It misses whatever was logged before now.
            self._driver.execute_script(self._CONSOLE_CAPTURE)
            self._captured.add(handle)
        except Exception:
            pass

    def _make_options(self):
        if self.browser == "edge":
            options = EdgeOptions()
        else:
            options = ChromeOptions()
        options.add_argument(f"--user-data-dir={self.profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,900")
        return options

    def quit(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            self._driver = None

    @property
    def driver(self) -> webdriver.Chrome | webdriver.Edge:
        if self._driver is None:
            raise OpError("browser_dead", "browser is not running")
        return self._driver

    def health_check(self) -> None:
        """Raise browser_dead rather than hanging on a driver that has gone away."""
        if self._driver is None:
            raise OpError("browser_dead", "browser is not running")
        try:
            self._driver.window_handles
        except WebDriverException as exc:
            raise OpError(
                "browser_dead", f"browser is no longer reachable: {exc.msg or exc}"
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

    def location(self) -> dict:
        return {"url": self.driver.current_url, "title": self.driver.title}

    # --- DOM diff baselines ----------------------------------------------------

    def snapshot(self) -> dict:
        """The active tab's state as {"dom": [element lines], "text": [strings]}."""
        return diff_util.snapshot(self.driver)

    def baseline(self) -> dict | None:
        """The stored (url, dom, text) state for the active tab, or None."""
        return self._baselines.get(self.active_tab)

    def set_baseline(self, state: dict | None = None) -> dict:
        """Record the current page as the state to diff the next command against."""
        if state is None:
            state = self.snapshot()
        entry = {"url": self.driver.current_url, **state}
        self._baselines[self.active_tab] = entry
        return entry
