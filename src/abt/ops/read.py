"""Reading ops: page HTML, visible text, element search, screenshots."""

from __future__ import annotations

from itertools import groupby

from .. import diff, shadow
from ..browser import BrowserSession
from ..engine import EngineError
from ..errors import OpError
from ..targeting import resolve_many, resolve_one

# One round trip for the whole match list.
# A match used to be its shell and nothing else -- `cloneNode(false)` drops every
# child, so `find {"text": "Orders"}` returned three identical `<span></span>`
# entries and the caller could not tell which was which. Measured across 393
# benchmark episodes, 231 of 734 `run_js` scripts were agents re-reading with
# querySelectorAll the text that `find` had just matched and thrown away.
#
# Now each match carries the text it owns and where it sits. Own text, not
# innerText: a container would otherwise drag its whole subtree back, and
# innerText forces a reflow per candidate on a search that may return a
# thousand.
_SERIALIZE = diff._PATH_JS + """
var els = arguments[0], full = arguments[1];
return els.map(function (e) {
  var tag = e.tagName;
  var value = null;
  if (tag === 'INPUT') {
    var type = (e.type || '').toLowerCase();
    if (type !== 'password' && type !== 'hidden') value = e.value;
  } else if (tag === 'TEXTAREA') {
    value = e.value;
  } else if (tag === 'SELECT') {
    var chosen = e.selectedOptions[0];
    value = chosen ? chosen.textContent : '';
  }
  return {
    html: full ? e.outerHTML : e.cloneNode(false).outerHTML,
    text: ownText(e).slice(0, 200),
    value: value === null ? null : String(value).replace(/\\s+/g, ' ').trim().slice(0, 200),
    path: pathOf(e),
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


def _tree_text(session: BrowserSession, element=None) -> str:
    """Visible text laid out as its tree, the same shape a diff reports.

    A page has one shape however it is read. Before this, a navigation returned
    grouped text with paths and `get_text` returned one flat blob, so an agent
    that re-read what it had just been given got a different -- and worse --
    view of it: a table came back as a wall of cells with no row boundaries,
    which is exactly what sends it to `run_js` with `querySelectorAll`.

    Reads through `text_with_shadow`, not the shared snapshot walk: that walk
    is light-DOM-only because it is paid for on every diffed command, but
    `get_text` is called on request and has always surfaced an open shadow
    root's text for free, the way a browser's own rendered text would.

    Falls back to the element's plain text if the walk finds nothing, so a
    reader is never handed an empty string for a page that has words on it.
    """
    pairs = diff.text_with_shadow(session.driver, root=element)
    if pairs:
        lines = diff.render_text(pairs)
        if not session.status_warned:
            hint = diff.status_hint(lines)
            if hint:
                # Appended as an extra line, the same way the
                # navigation-suppression note is: this is still the page's own
                # text, plus one line that is not, and the two must never be
                # confused for each other.
                lines = [*lines, f"… {hint}"]
                session.status_warned = True
        return "\n".join(lines)
    return element.text if element is not None else _body_text(session)


def get_text(session: BrowserSession, cmd) -> str:
    """The visible text of the page, frames included.

    A frame's content is on the page, so it belongs in the answer -- and it is
    appended plain, with no marker saying where the boundary was. Whose
    document a string came from is not something a reader needs to know, and
    inventing a divider would put text on screen that nobody can see.
    """
    level = getattr(cmd, "level", None)
    if level:
        element = diff.element_at(session.driver, level)
        if element is None:
            # "not_found" is not in the closed error-type set -- OpError's own
            # constructor raises ValueError on an unrecognised type, which the
            # server's catch-all then reports as browser_dead. A stale level
            # told an agent its browser had died; it believed the diagnosis
            # over the message and ran browser_restart, discarding every tab
            # and ref for a level that was simply out of date. element_not_found
            # is the type this already is: a search that found nothing.
            raise OpError(
                "element_not_found",
                f"nothing sits at level {level!r}",
                hint=(
                    "Levels come from the text track and describe one page: a "
                    "navigation renumbers them. Read the page again and use a "
                    "level from the result you were just given."
                ),
            )
        return _tree_text(session, element)

    if cmd.has_target:
        # A selector names one element and the caller wants what it says, so
        # this stays the plain string it has always been. Structure is what
        # `level` is for: a table read by selector would come back as a wall of
        # cells, and the way to avoid that is to ask for its level -- which
        # `find` now hands back with every match.
        return resolve_one(session, cmd).text

    session.leave_frames()
    parts = [_tree_text(session)]
    try:
        for path in session.frame_paths():
            if not session.enter_frame(path):
                continue
            inner = _tree_text(session)
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
                # Only when there is something to say. A structural div owns no
                # text, and an empty key on every match is noise on a search
                # that can return a thousand of them.
                if item.get("text"):
                    found["text"] = item["text"]
                if item.get("value"):
                    found["value"] = item["value"]
                if item.get("path"):
                    found["path"] = item["path"]
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
