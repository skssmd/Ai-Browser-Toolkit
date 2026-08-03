"""Op registry: maps an op name to the handler that runs it."""

from __future__ import annotations

from typing import Any, Callable

from ..browser import BrowserSession
from ..diff import diff_html, diff_text, page_key, page_text
from ..errors import OpError
from . import control, interact, navigate, read, tabs

Handler = Callable[[BrowserSession, Any], Any]

REGISTRY: dict[str, Handler] = {
    "goto": navigate.goto,
    "back": navigate.back,
    "forward": navigate.forward,
    "reload": navigate.reload,
    "current_url": navigate.current_url,
    "get_html": read.get_html,
    "get_text": read.get_text,
    "find": read.find,
    "find_full": read.find_full,
    "screenshot": read.screenshot,
    "click": interact.click,
    "input": interact.input,
    "select": interact.select,
    "hover": interact.hover,
    "scroll": interact.scroll,
    "wait_for": interact.wait_for,
    "press": interact.press,
    "tab_new": tabs.tab_new,
    "tab_list": tabs.tab_list,
    "tab_switch": tabs.tab_switch,
    "tab_close": tabs.tab_close,
    "run_js": control.run_js,
    "alert": control.alert,
    "diff": control.diff,
    "status": control.status,
    "shutdown": control.shutdown,
}

# Ops that change the page in place and therefore get a before/after diff
# attached to their response when diffing is on.
DIFFABLE_OPS = frozenset(
    {"click", "input", "select", "hover", "scroll", "press", "wait_for", "run_js"}
)

# Ops whose whole purpose is to land somewhere else. Diffing two unrelated
# documents is noise, so these report the page they arrived at instead.
NAVIGATION_OPS = frozenset({"goto", "back", "forward", "reload"})

# Ops that can change the DOM. Their post-command state becomes the baseline for
# the next manual `diff`.
DOM_TOUCHING_OPS = DIFFABLE_OPS | NAVIGATION_OPS | {"tab_new", "tab_close"}


def dispatch(session: BrowserSession, cmd) -> Any:
    handler = REGISTRY.get(cmd.op)
    if handler is None:
        raise OpError("invalid_op", f"no handler registered for op {cmd.op!r}")
    session.health_check()

    want_diff = session.diff_enabled if getattr(cmd, "diff", None) is None else cmd.diff
    if cmd.op in DIFFABLE_OPS and want_diff:
        return _run_with_diff(session, cmd, handler)
    if cmd.op in NAVIGATION_OPS and want_diff:
        return _run_with_page_text(session, cmd, handler)

    result = handler(session, cmd)
    if cmd.op in DOM_TOUCHING_OPS:
        session.set_baseline()
    return result


def _run_with_diff(session: BrowserSession, cmd, handler) -> Any:
    """Run an interactive op, then report what it changed on the page.

    Text always; elements only when asked. The text diff is what an agent reads
    to decide its next move, and it carries no markup, so it stays cheap enough
    to be unconditional.
    """
    before = session.snapshot()
    url_before = session.driver.current_url
    try:
        result = handler(session, cmd)
    except OpError:
        after = session.snapshot()
        session.set_baseline(after)
        raise

    after = session.snapshot()
    session.set_baseline(after)
    if not isinstance(result, dict):
        return result

    url_after = session.driver.current_url
    info = {"url_before": url_before, "url_after": url_after}
    if page_key(url_before) != page_key(url_after):
        # The click redirected. The old document is gone, so there is nothing to
        # diff -- but the question the caller was asking ("what am I looking at
        # now?") still has an answer, and it is the new page's text.
        info["navigation"] = True
        info["note"] = (
            "the page navigated; text is the new page in full, not a diff, and "
            "the element track is skipped because the two documents are unrelated"
        )
        info["text"] = page_text(after["text"], before["text"], cmd.include_removed)
    else:
        info["text"] = diff_text(
            before["text"], after["text"], include_removed=cmd.include_removed
        )
        if cmd.element_diff:
            budget = cmd.diff_max_tokens or session.diff_max_tokens
            info["elements"] = diff_html(before["dom"], after["dom"], budget)
    result["dom_diff"] = info
    return result


def _run_with_page_text(session: BrowserSession, cmd, handler) -> Any:
    """Run a navigation op, then hand back the text of the page it landed on.

    No diff: goto/back/forward/reload exist to replace the document, so the
    before and after have nothing in common worth aligning. What the caller
    wants is the destination's content, which they would otherwise have to ask
    for in a second round trip.
    """
    before = session.snapshot()
    try:
        result = handler(session, cmd)
    except OpError:
        session.set_baseline()
        raise

    after = session.snapshot()
    session.set_baseline(after)
    if not isinstance(result, dict):
        return result

    result["dom_diff"] = {
        "url_after": session.driver.current_url,
        "navigation": True,
        "note": "text is the full page you landed on, not a diff",
        "text": page_text(after["text"], before["text"], cmd.include_removed),
    }
    return result
