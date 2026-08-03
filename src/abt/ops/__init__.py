"""Op registry: maps an op name to the handler that runs it."""

from __future__ import annotations

from typing import Any, Callable

from ..browser import BrowserSession
from ..diff import diff_html, page_key
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
    "diff": control.diff,
    "status": control.status,
    "shutdown": control.shutdown,
}

# Ops that change the page and therefore get a before/after DOM diff attached to
# their response when diffing is on.
DIFFABLE_OPS = frozenset(
    {"click", "input", "select", "hover", "scroll", "press", "wait_for", "run_js"}
)

# Ops that can change the DOM. Their post-command state becomes the baseline for
# the next manual `diff`.
DOM_TOUCHING_OPS = DIFFABLE_OPS | {
    "goto",
    "back",
    "forward",
    "reload",
    "tab_new",
    "tab_close",
}


def dispatch(session: BrowserSession, cmd) -> Any:
    handler = REGISTRY.get(cmd.op)
    if handler is None:
        raise OpError("invalid_op", f"no handler registered for op {cmd.op!r}")
    session.health_check()

    want_diff = session.diff_enabled if getattr(cmd, "diff", None) is None else cmd.diff
    if cmd.op in DIFFABLE_OPS and want_diff:
        return _run_with_diff(session, cmd, handler)

    result = handler(session, cmd)
    if cmd.op in DOM_TOUCHING_OPS:
        session.set_baseline()
    return result


def _run_with_diff(session: BrowserSession, cmd, handler) -> Any:
    """Run an interactive op, then report what it changed in the DOM."""
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
        info["navigation"] = True
        info["note"] = (
            "the page navigated; the before/after DOMs are different documents"
        )
    else:
        info.update(diff_html(before, after, session.diff_max_tokens))
    result["dom_diff"] = info
    return result
