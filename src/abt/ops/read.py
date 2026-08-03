"""Reading ops: page HTML, visible text, element search, screenshots."""

from __future__ import annotations

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


def get_text(session: BrowserSession, cmd) -> str:
    if not cmd.has_target:
        return session.driver.find_element("tag name", "body").text
    return resolve_one(session, cmd).text


def find(session: BrowserSession, cmd) -> dict:
    mode = getattr(cmd, "mode", "full" if cmd.op == "find_full" else "shell")
    elements, truncated = resolve_many(session, cmd, cmd.limit, cmd.visible_only)
    refs = session.refs.allocate(session.active_tab, elements)

    serialized = (
        session.driver.execute_script(_SERIALIZE, elements, mode == "full")
        if elements
        else []
    )
    matches = [
        {"ref": ref, "html": item["html"], "visible": bool(item["visible"])}
        for ref, item in zip(refs, serialized)
    ]
    return {"count": len(matches), "truncated": truncated, "matches": matches}


def find_full(session: BrowserSession, cmd) -> dict:
    return find(session, cmd)


def screenshot(session: BrowserSession, cmd) -> dict:
    if not cmd.has_target:
        data = session.driver.get_screenshot_as_base64()
    else:
        data = resolve_one(session, cmd, state="visible").screenshot_as_base64
    return {"format": "png", "base64": data}
