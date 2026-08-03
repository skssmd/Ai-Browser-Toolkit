"""Chrome lifecycle, persistent profile, and the stable tab registry."""

from __future__ import annotations

from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options

from .errors import OpError
from .refs import RefCache


class BrowserSession:
    """Owns exactly one Chrome instance for the lifetime of the server."""

    def __init__(
        self,
        profile: Path,
        headless: bool = False,
        action_timeout: float = 5.0,
    ) -> None:
        self.profile = Path(profile).expanduser().resolve()
        self.headless = headless
        self.action_timeout = action_timeout
        self.refs = RefCache()
        self._driver: webdriver.Chrome | None = None
        self._handles: dict[str, str] = {}  # tab_id -> window handle
        self._order: list[str] = []
        self._counter = 0

    # --- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self.profile.mkdir(parents=True, exist_ok=True)
        options = Options()
        options.add_argument(f"--user-data-dir={self.profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,900")
        self._driver = webdriver.Chrome(options=options)
        # Implicit waits interact badly with explicit waits and make every failed
        # lookup cost the full timeout. All waiting here is explicit.
        self._driver.implicitly_wait(0)
        self._sync_tabs()

    def quit(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            self._driver = None

    @property
    def driver(self) -> webdriver.Chrome:
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
        for tab_id in [t for t, h in self._handles.items() if h not in live]:
            del self._handles[tab_id]
            self._order.remove(tab_id)
            self.refs.drop_tab(tab_id)
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
        del self._handles[target]
        self._order.remove(target)
        # Activate the nearest surviving tab so the session is never adrift.
        neighbour = self._order[min(position, len(self._order) - 1)]
        self.driver.switch_to.window(self._handles[neighbour])

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
