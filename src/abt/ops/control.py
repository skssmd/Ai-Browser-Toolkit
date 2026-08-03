"""Control ops: arbitrary JS, session status, shutdown."""

from __future__ import annotations

from selenium.common.exceptions import JavascriptException, WebDriverException

from ..diff import diff_html, page_key
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


def diff(session: BrowserSession, cmd) -> dict:
    """Diff the current DOM against the last known state, or re-baseline."""
    tab_id = session.active_tab
    entry = session.baseline()

    if cmd.reset or entry is None:
        session.set_baseline()
        return {
            "baseline": "set",
            "tab_id": tab_id,
            "url": session.driver.current_url,
            "note": "baseline is now the current DOM",
        }

    after = session.snapshot()
    session.set_baseline(after)
    url_after = session.driver.current_url
    payload = {
        "baseline": "present",
        "tab_id": tab_id,
        "url_before": entry["url"],
        "url_after": url_after,
    }
    if page_key(entry["url"]) != page_key(url_after):
        payload["navigation"] = True
        payload["note"] = (
            "the page changed since the baseline; the two DOMs are different documents"
        )
    else:
        payload.update(diff_html(entry["dom"], after, cmd.max_tokens))
    return payload


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
