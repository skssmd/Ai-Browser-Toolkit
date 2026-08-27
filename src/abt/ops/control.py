"""Control ops: arbitrary JS, native dialogs, session status, shutdown."""

from __future__ import annotations

from ..browser import BrowserSession
from ..diff import diff_html, diff_text, page_key, page_text
from ..engine import EngineError, NoAlert, ScriptError
from ..errors import OpError


def run_js(session: BrowserSession, cmd) -> dict:
    """Run a script body and hand back what it returned.

    The script is a function *body*, not an expression, so a value only comes
    back if the script says `return`. That trips people, and silently: a
    watched agent sent `1+1`, got null, concluded "run_js return values aren't
    surfaced", and spent three turns building a workaround that wrote results
    into the DOM and read them back out. Nothing was broken. Nothing in the
    documentation said otherwise either -- the workflow mentions run_js nine
    times and every one of them is telling you not to use it.

    So when a script returns nothing and contains no `return` at all, the
    reply says why. The check is deliberately conservative: a script that does
    contain `return` may still legitimately produce null, and guessing at that
    would be worse than staying quiet.
    """
    try:
        value = session.driver.execute_script(cmd.script, *cmd.args)
    except ScriptError as exc:
        raise OpError("js_error", f"script threw: {exc.msg or exc}") from exc
    except EngineError as exc:
        raise OpError("js_error", f"script failed: {exc.msg or exc}") from exc

    result = {"value": value}
    if value is None and not "return" in (cmd.script or ""):
        result["hint"] = (
            "value is null because this script has no `return`. The script is "
            "a function body, not an expression: `1+1` evaluates and discards, "
            "`return 1+1;` hands back 2. Add `return` to whatever you want to "
            "read. Do not write results into the DOM to read them back -- that "
            "is two round trips for something already returned."
        )
    return result


def alert(session: BrowserSession, cmd) -> dict:
    """Inspect or answer a native browser dialog (alert/confirm/prompt)."""
    try:
        dialog = session.driver.switch_to.alert
    except NoAlert:
        return {"present": False}

    message = None
    try:
        message = dialog.text
    except EngineError:
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


# --- playbooks ----------------------------------------------------------------
#
# Reachable from an agent for the first time here. They were CLI-only and
# read-only over HTTP, so the one feature meant to compound across runs never
# accumulated anything: every agent rediscovered every site.


def guidelines_search(session: BrowserSession, cmd) -> dict:
    from .. import guidelines

    found = guidelines.search(cmd.query, limit=cmd.limit)
    if not found.get("matches"):
        found["note"] = (
            "No playbook for this site. That is normal and is an answer -- most "
            "sites have none. Drive it with the ordinary workflow."
        )
    return found


def guidelines_read(session: BrowserSession, cmd) -> dict:
    from .. import guidelines

    try:
        return {"name": cmd.name, "text": guidelines.read(cmd.name)}
    except KeyError as exc:
        raise OpError(
            "element_not_found",
            f"no playbook named {cmd.name!r}",
            hint="Run guidelines_search first; it returns the exact names.",
        ) from exc


_NOTE = """
## {title}
- **URL:** {url}
- **What happened:** {problem}
- **Tried and learned:** {tried}
- **Solution:** {solution}
- *recorded {when} by an agent*
"""


def guidelines_note(session: BrowserSession, cmd) -> dict:
    """Append an entry to this domain's playbook, creating it if needed.

    Appends rather than replaces: a playbook is a list that grows, and an
    agent that overwrote it would erase the work of every run before it.
    """
    from datetime import date

    from .. import guidelines

    name = f"{cmd.domain}/learned.md"
    try:
        existing = guidelines.read(name)
    except KeyError:
        existing = f"# {cmd.domain}\n\nWhat agents have had to work out here.\n"

    entry = _NOTE.format(
        title=cmd.title.strip(),
        url=cmd.url.strip(),
        problem=cmd.problem.strip(),
        tried=cmd.tried.strip(),
        solution=cmd.solution.strip(),
        when=date.today().isoformat(),
    )
    try:
        path = guidelines.save(cmd.domain, "learned.md", existing.rstrip() + "\n" + entry)
    except (KeyError, OSError) as exc:
        raise OpError("invalid_op", f"could not save a note for {cmd.domain!r}: {exc}") from exc

    return {
        "saved": str(path),
        "domain": cmd.domain,
        "entries": existing.count("\n## ") + 1,
        "note": (
            "Stored locally. A pull will not overwrite it and it is not shared "
            "-- `abt guidelines submit` is the separate step for that."
        ),
    }
