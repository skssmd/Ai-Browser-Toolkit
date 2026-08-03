"""Control ops: arbitrary JS, session status, shutdown."""

from __future__ import annotations

from selenium.common.exceptions import JavascriptException, WebDriverException

from ..browser import BrowserSession
from ..errors import OpError


def run_js(session: BrowserSession, cmd) -> dict:
    try:
        value = session.driver.execute_script(cmd.script, *cmd.args)
    except JavascriptException as exc:
        raise OpError("js_error", f"script threw: {exc.msg or exc}") from exc
    except WebDriverException as exc:
        raise OpError("js_error", f"script failed: {exc.msg or exc}") from exc
    return {"value": value}


def status(session: BrowserSession, cmd) -> dict:
    return session_status(session)


def session_status(session: BrowserSession) -> dict:
    tabs = session.tabs()
    active = session.active_tab
    return {
        "url": session.driver.current_url,
        "title": session.driver.title,
        "active_tab": active,
        "tabs": tabs,
        "refs_valid": session.refs.count(active),
        "headless": session.headless,
        "profile": str(session.profile),
    }


def shutdown(session: BrowserSession, cmd) -> dict:
    # The server tears the browser down after the response is sent, so the
    # caller gets confirmation instead of a dropped connection.
    return {"stopping": True}
