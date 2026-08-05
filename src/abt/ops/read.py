"""Reading ops: page HTML, visible text, element search, screenshots."""

from __future__ import annotations

from itertools import groupby

from selenium.common.exceptions import WebDriverException

from ..browser import BrowserSession
from ..targeting import resolve_many, resolve_one

# One round trip for the whole match list. `cloneNode(false)` drops children and
# text, leaving the element's own tag and attributes -- the "shell" form.
_SERIALIZE = """
var els = arguments[0], full = arguments[1];
return els.map(function (e) {
  return {
    html: full ? e.outerHTML : e.cloneNode(false).outerHTML,
    visible: e.getClientRects().length > 0
  };
});
"""


def get_html(session: BrowserSession, cmd) -> str:
    if not cmd.has_target:
        return session.driver.page_source
    return resolve_one(session, cmd).get_attribute("outerHTML")


def _body_text(session: BrowserSession) -> str:
    try:
        return session.driver.find_element("tag name", "body").text
    except WebDriverException:
        return ""


def get_text(session: BrowserSession, cmd) -> str:
    """The visible text of the page, frames included.

    A frame's content is on the page, so it belongs in the answer -- and it is
    appended plain, with no marker saying where the boundary was. Whose
    document a string came from is not something a reader needs to know, and
    inventing a divider would put text on screen that nobody can see.
    """
    if cmd.has_target:
        return resolve_one(session, cmd).text

    session.leave_frames()
    parts = [_body_text(session)]
    try:
        for path in session.frame_paths():
            if not session.enter_frame(path):
                continue
            inner = _body_text(session)
            if inner:
                parts.append(inner)
    finally:
        session.leave_frames()
    return "\n".join(part for part in parts if part)


def find(session: BrowserSession, cmd) -> dict:
    """Matches anywhere on the page, each with a ref that acts where it lives.

    Serialisation and ref allocation happen inside the document each group came
    from: a WebElement only answers from its own frame, so both have to be done
    before moving on to the next one.
    """
    mode = getattr(cmd, "mode", "full" if cmd.op == "find_full" else "shell")
    pairs, truncated = resolve_many(session, cmd, cmd.limit, cmd.visible_only)

    matches: list[dict] = []
    try:
        for home, group in groupby(pairs, key=lambda pair: pair[1]):
            elements = [element for element, _ in group]
            if not session.enter_frame(home):
                continue
            refs = session.refs.allocate(session.active_tab, elements, home)
            serialized = session.driver.execute_script(
                _SERIALIZE, elements, mode == "full"
            )
            matches.extend(
                {"ref": ref, "html": item["html"], "visible": bool(item["visible"])}
                for ref, item in zip(refs, serialized)
            )
    finally:
        session.leave_frames()
    return {"count": len(matches), "truncated": truncated, "matches": matches}


def find_full(session: BrowserSession, cmd) -> dict:
    return find(session, cmd)


def screenshot(session: BrowserSession, cmd) -> dict:
    if not cmd.has_target:
        data = session.driver.get_screenshot_as_base64()
    else:
        data = resolve_one(session, cmd, state="visible").screenshot_as_base64
    return {"format": "png", "base64": data}
