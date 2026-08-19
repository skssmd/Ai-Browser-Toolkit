"""Control ops: arbitrary JS, native dialogs, session status, shutdown."""

from __future__ import annotations

from selenium.common.exceptions import (
    JavascriptException,
    NoAlertPresentException,
    WebDriverException,
)

from ..diff import diff_html, diff_text, page_key, page_text
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


def alert(session: BrowserSession, cmd) -> dict:
    """Inspect or answer a native browser dialog (alert/confirm/prompt)."""
    try:
        dialog = session.driver.switch_to.alert
    except NoAlertPresentException:
        return {"present": False}

    message = None
    try:
        message = dialog.text
    except WebDriverException:
        pass

    if cmd.action == "text":
        return {"present": True, "text": message}
    if cmd.action == "accept":
        dialog.accept()
    elif cmd.action == "dismiss":
        dialog.dismiss()
    else:  # send_text
        dialog.send_keys(cmd.text or "")
        dialog.accept()
    return {"present": True, "text": message, "action": cmd.action}


def diff(session: BrowserSession, cmd) -> dict:
    """Diff the current page against the last known state, or re-baseline."""
    tab_id = session.active_tab
    entry = session.baseline()

    if cmd.reset or entry is None:
        session.set_baseline()
        return {
            "baseline": "set",
            "tab_id": tab_id,
            "url": session.driver.current_url,
            "note": "baseline is now the current page",
        }

    after = session.snapshot()
    session.set_baseline(after)
    url_after = session.driver.current_url
    navigated = page_key(entry["url"]) != page_key(url_after)
    payload = {
        "baseline": "present",
        "tab_id": tab_id,
        "url_before": entry["url"],
        "url_after": url_after,
    }
    if navigated:
        payload["navigation"] = True
        payload["note"] = (
            "the page changed since the baseline; text is the new page in full, "
            "not a diff, and the element track is skipped"
        )
        payload["text"] = page_text(
            after["text"], entry["text"], include_removed=cmd.include_removed
        )
    else:
        payload["text"] = diff_text(
            entry["text"], after["text"], include_removed=cmd.include_removed
        )
        if cmd.element_diff:
            payload["elements"] = diff_html(entry["dom"], after["dom"], cmd.max_tokens)

        # Imported here: the op registry imports this module, so importing
        # the registry at module scope would close the loop.
        from . import actionable_report

        if cmd.actionable:
            controls = actionable_report(session, entry.get("actionable", []), after)
            if controls is not None:
                payload["actionable"] = controls
    return payload


# --- browser lifecycle ------------------------------------------------------


def browser_state(session: BrowserSession) -> dict:
    """Lifecycle state, answerable with no browser present.

    Two configs, because one key cannot answer both questions. `config` is what
    is running now (or ran most recently), which is what a bare browser_restart
    will use. `defaults` is what `abt serve` was given, which is what a bare
    browser_start will use.
    """
    return {
        "running": session.is_running,
        "config": session.config.to_dict(),
        "defaults": session.defaults.to_dict(),
    }


def browser_start(session: BrowserSession, cmd) -> dict:
    return session.start(
        browser=cmd.browser, profile=cmd.profile, headless=cmd.headless
    )


def browser_stop(session: BrowserSession, cmd) -> dict:
    return session.stop()


def browser_restart(session: BrowserSession, cmd) -> dict:
    return session.restart(
        browser=cmd.browser, profile=cmd.profile, headless=cmd.headless
    )


def browser_status(session: BrowserSession, cmd) -> dict:
    return browser_state(session)


def status(session: BrowserSession, cmd) -> dict:
    return session_status(session)


def session_status(session: BrowserSession) -> dict:
    """Where the session is, or that there is no session.

    `running` is always present. Everything else is only meaningful with a
    browser up, and a caller that reads `url` without checking `running` should
    find it missing rather than find a lie.
    """
    if not session.is_running:
        return browser_state(session)
    tabs = session.tabs()
    active = session.active_tab
    return {
        "running": True,
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
