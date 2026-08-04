"""Navigation ops. Each one invalidates the active tab's refs."""

from __future__ import annotations

from selenium.common.exceptions import WebDriverException

from ..browser import BrowserSession
from ..errors import OpError


def goto(session: BrowserSession, cmd) -> dict:
    session.goto(cmd.url)
    return session.location()


def back(session: BrowserSession, cmd) -> dict:
    return _history(session, "back")


def forward(session: BrowserSession, cmd) -> dict:
    return _history(session, "forward")


def reload(session: BrowserSession, cmd) -> dict:
    return _history(session, "refresh")


def current_url(session: BrowserSession, cmd) -> dict:
    return session.location()


def _history(session: BrowserSession, action: str) -> dict:
    try:
        getattr(session.driver, action)()
    except WebDriverException as exc:
        raise OpError("navigation_failed", f"{action} failed: {exc.msg or exc}") from exc
    session.refs.invalidate(session.active_tab)
    code = session.error_page_code()
    if code:
        raise OpError("navigation_failed", f"{action} landed on a chrome error: {code}")
    session.settle()
    return session.location()
