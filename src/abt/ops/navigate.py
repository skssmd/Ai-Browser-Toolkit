"""Navigation ops. Each one invalidates the active tab's refs."""

from __future__ import annotations

from pathlib import Path

from ..browser import BrowserSession
from ..engine import EngineError
from ..errors import OpError


def goto(session: BrowserSession, cmd) -> dict:
    settled = session.goto(cmd.url)
    result = session.location()
    if not settled:
        # Landed, but the redirect chain overran the navigation budget. Said
        # out loud rather than swallowed: the page is usable, and a caller
        # that cares can raise --action-timeout.
        result["navigation_slow"] = True
    found = _playbook_for(result.get("url") or cmd.url)
    if found is not None:
        result["guideline"] = found
    return result


def _playbook_for(url: str) -> dict | None:
    """What is known about a playbook for the site just landed on.

    Reports; never fetches into use. The server cannot prompt -- it is HTTP --
    so the answer rides along in the response and the caller decides whether
    to pull. Never raises: a site visit must not fail because a playbook
    lookup did.

    Only the *first* visit to a domain in a session says anything, because a
    line repeated on every navigation is a line people stop reading.
    """
    from .. import guidelines

    try:
        domain = guidelines.domain_of(url)
        if domain is None or domain in _ANNOUNCED:
            return None

        held = guidelines.installed().get(domain)
        if held is not None and held["trusted"]:
            _ANNOUNCED.add(domain)
            return {
                "domain": domain,
                "state": "held",
                "source": held["source"],
                "version": held["version"],
                "files": held["files"],
                "read": f"abt guidelines show {domain}/{Path(held['files'][0]).stem}"
                if held["files"]
                else None,
            }

        found = guidelines.lookup(domain)
        if found is None:
            return None

        _ANNOUNCED.add(domain)
        return {
            "domain": domain,
            "state": "pending" if held is not None else "available",
            "version": found["available_version"],
            "files": found["files"],
            "trusted": False,
            "hint": (
                f"A playbook for {domain} exists but is not installed. "
                f"`abt guidelines pull {domain}` shows it and asks before "
                f"anything is trusted."
            ),
        }
    except Exception:
        return None


# Per-process, and deliberately not persisted: it is about not repeating
# yourself within a session, not a record of anything.
_ANNOUNCED: set[str] = set()


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
    except EngineError as exc:
        raise OpError("navigation_failed", f"{action} failed: {exc.msg or exc}") from exc
    session.refs.invalidate(session.active_tab)
    code = session.error_page_code()
    if code:
        raise OpError("navigation_failed", f"{action} landed on a chrome error: {code}")
    session.settle()
    return session.location()
