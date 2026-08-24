"""Reading ops: page HTML, visible text, element search, screenshots."""

from __future__ import annotations

from itertools import groupby

from .. import shadow
from ..browser import BrowserSession
from ..engine import EngineError
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
    except EngineError:
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
            batch = list(group)
            elements = [element for element, _, _ in batch]
            if not session.enter_frame(home):
                continue
            refs = session.refs.allocate(session.active_tab, elements, home)
            serialized = session.driver.execute_script(
                _SERIALIZE, elements, mode == "full"
            )
            for (_el, _home, in_shadow), ref, item in zip(batch, refs, serialized):
                found = {
                    "ref": ref,
                    "html": item["html"],
                    "visible": bool(item["visible"]),
                }
                # Only worth saying when it is true: it tells the caller this
                # one was out of reach of an ordinary search.
                if in_shadow:
                    found["shadow"] = True
                matches.append(found)
    finally:
        session.leave_frames()

    result = {"count": len(matches), "truncated": truncated, "matches": matches}

    # Nothing found is the moment an agent decides to give up, so it is the one
    # moment it has to know where nobody looked. A bare zero is what sent a live
    # agent through fifteen commands of escalating run_js scans; with the count
    # attached, zero is either an answer or an instruction, and it says which.
    if not matches and not getattr(cmd, "shadow", False):
        hosts = shadow.host_count(session.driver)
        if hosts:
            result["shadow_hosts"] = hosts
            result["note"] = (
                f"nothing matched, but this page has {hosts} shadow root(s) that "
                f"an ordinary search cannot see into; retry with \"shadow\": true"
            )
    return result


def find_full(session: BrowserSession, cmd) -> dict:
    return find(session, cmd)


def screenshot(session: BrowserSession, cmd) -> dict:
    """A frame of the page. Returns a path by default, base64 on request.

    The server already writes a frame to the session log for every command,
    so this op has nothing to save: it names the file that was written for
    it, and the caller opens it like any other image.

    Base64 was the only option here, and it made the op useless to exactly
    the callers most likely to reach for it. An agent reading tool output as
    text cannot see an inlined image, and the blob -- a viewport PNG is
    100KB-1MB before base64 adds a third -- buries the rest of its context.
    One observed session spent six minutes chewing through a single frame and
    ended with the agent trying to save the image itself.

    The path is filled in by the server, which is what owns the recorder; a
    target only sets where the frame is annotated, since the recorded frame
    is the whole viewport.
    """
    if cmd.base64:
        if not cmd.has_target:
            data = session.driver.get_screenshot_as_base64()
        else:
            data = resolve_one(session, cmd, state="visible").screenshot_as_base64
        return {"format": "png", "base64": data}
    if cmd.has_target:
        # Resolved for its side effect: it scrolls the element into view and
        # sets last_target, so the recorded frame both shows the element and
        # carries a box saying where in the frame it is.
        resolve_one(session, cmd, state="visible")
    return {"format": "jpeg"}
