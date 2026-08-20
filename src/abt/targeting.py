"""Turn a command's targeting fields into live Elements."""

from __future__ import annotations

from . import shadow
from .browser import BrowserSession
from .engine import (
    EC,
    By,
    Element,
    EngineError,
    NoSuchElement,
    StaleElement,
    Timeout,
    WebDriverWait,
)
from .errors import OpError


def xpath_literal(value: str) -> str:
    """Quote a string for XPath, which has no escape character."""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    # Both quote characters present: stitch the pieces together with concat().
    pieces = ", \"'\", ".join(f"'{p}'" for p in value.split("'"))
    return f"concat({pieces})"


def locator(cmd) -> tuple[str, str]:
    if cmd.css is not None:
        return (By.CSS, cmd.css)
    if cmd.xpath is not None:
        return (By.XPATH, cmd.xpath)
    if cmd.text is not None:
        return (By.XPATH, f"//*[normalize-space(.)={xpath_literal(cmd.text)}]")
    raise OpError("invalid_op", "no selector on this command")


def describe(cmd) -> str:
    for field in ("ref", "css", "xpath", "text"):
        value = getattr(cmd, field, None)
        if value is not None:
            return f"{field}={value!r}"
    return "<no target>"


_CONDITIONS = {
    "present": EC.presence_of_element_located,
    "visible": EC.visibility_of_element_located,
    "clickable": EC.element_to_be_clickable,
}

# States that mean "a person could act on this". Only these need the element on
# screen; "present" deliberately does not, so you can assert something exists
# without disturbing the scroll position.
_NEEDS_VIEWPORT = frozenset({"visible", "clickable"})


def scroll_into_view(session: BrowserSession, element: Element) -> None:
    """Centre an element in the viewport. Never fails a command."""
    try:
        session.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element
        )
    except EngineError:
        pass


def _aim_at_frame(session: BrowserSession, by: str, selector: str) -> None:
    """Point the driver at whichever document holds a match, if not this one.

    A selector only ever searches the frame the driver is switched into, so a
    control inside an embedded widget is unreachable by css, xpath or text no
    matter how long you wait for it. Finding it first means the wait below runs
    where the element actually is.

    The probe is a single unwaited lookup on the top document, which is where
    the answer is on nearly every page, and only a miss pays to look further.
    A miss everywhere leaves the driver at the top so the ordinary wait and the
    ordinary "nothing matched" error still happen, unchanged.
    """
    session.leave_frames()
    if not session.frames_enabled:
        return
    try:
        if session.driver.find_elements(by, selector):
            return
    except EngineError:
        return
    for path in session.frame_paths():
        if not session.enter_frame(path):
            continue
        try:
            if session.driver.find_elements(by, selector):
                return
        except EngineError:
            continue
    session.leave_frames()


# How near each candidate is to the qualifying text, and what sits beside it.
#
# For every candidate: climb its ancestors until one contains `near`, and
# report how *tight* that ancestor is -- the length of its text -- rather than
# how many levels up it was.
#
# Depth alone is the obvious metric and it is wrong. A button sitting directly
# in <body> has its match at depth 0, because body contains every string on the
# page, so it beats the button actually inside the Billing card two levels up.
# The suite caught it: `css: "button", near: "Billing"` selected the page's
# "Show documents" button. The smallest container holding both the candidate
# and the text is the one a person would point at -- on a table that is its
# row, on a card its section. Nothing here knows what a row or a card is.
#
# `label` comes back regardless, so a miss can say what *was* there instead of
# only that nothing matched.
#
# Written without a backslash. The JS in this project has been broken three
# separate times by an escape being eaten between here and the browser, and the
# browser reports it as a syntax error naming neither the file nor the cause.
_NEAR_JS = """
var els = arguments[0], want = String(arguments[1]).toLowerCase();
var NL = String.fromCharCode(10), TAB = String.fromCharCode(9);
function flat(s) {
  return (s || '').split(NL).join(' ').split(TAB).join(' ').toLowerCase();
}
function label(el) {
  var node = el.parentElement, depth = 0;
  while (node && depth < 6) {
    var own = flat(el.innerText || el.textContent);
    var all = flat(node.innerText || node.textContent);
    var rest = all.split(own).join(' ').trim();
    if (rest) { return rest.slice(0, 60); }
    node = node.parentElement; depth += 1;
  }
  return '';
}
return els.map(function (el) {
  var node = el.parentElement, depth = 0;
  while (node && depth < 8) {
    var text = flat(node.innerText || node.textContent);
    if (text.indexOf(want) !== -1) {
      return {depth: depth, size: text.length, label: label(el)};
    }
    node = node.parentElement; depth += 1;
  }
  return {depth: -1, size: -1, label: label(el)};
});
"""


def score_near(session, elements: list, near: str) -> list[dict]:
    """`{depth, label}` per element. Never raises: a failure to score is a
    failure to disambiguate, which the caller reports far better than a
    traceback would."""
    if not elements:
        return []
    try:
        found = session.driver.execute_script(_NEAR_JS, elements, near)
    except EngineError:
        return [{"depth": -1, "size": -1, "label": ""} for _ in elements]
    if not isinstance(found, list) or len(found) != len(elements):
        return [{"depth": -1, "size": -1, "label": ""} for _ in elements]
    return found


def pick_near(session, elements: list, cmd):
    """The match closest to `cmd.near`, or an error naming what was there.

    Ties break on document order, which is what "the first Edit in the
    Medication row" means when a row holds two of them.
    """
    scores = score_near(session, elements, cmd.near)
    # Tightest container first, then closest, then document order.
    ranked = [
        (score.get("size", -1), score.get("depth", -1), position)
        for position, score in enumerate(scores)
        if score.get("depth", -1) >= 0
    ]
    if not ranked:
        seen = [s.get("label") or "?" for s in scores][:6]
        raise OpError(
            "element_not_found",
            f"{len(elements)} element(s) matched {describe(cmd)}, but none is "
            f"near {cmd.near!r}. Found near: {', '.join(seen)}",
        )
    ranked.sort()
    return elements[ranked[0][2]]


def resolve_one(
    session: BrowserSession,
    cmd,
    state: str = "present",
    timeout: float | None = None,
) -> Element:
    """Resolve a single element, waiting up to `timeout` for it to reach `state`.

    Also remembers the element as the command's target, so a recorded frame can
    draw a box around whatever was acted on. Kept here rather than in each op
    because this is the one place every targeted op passes through.
    """
    element = _resolve_one(session, cmd, state, timeout)
    session.last_target = element
    return element


def _resolve_one(
    session: BrowserSession,
    cmd,
    state: str = "present",
    timeout: float | None = None,
) -> Element:
    if getattr(cmd, "ref", None) is not None:
        element = session.resolve_ref(cmd.ref)
        if state in _NEEDS_VIEWPORT:
            scroll_into_view(session, element)
        return element

    wait_for = timeout if timeout is not None else session.action_timeout
    by, selector = locator(cmd)
    index = getattr(cmd, "index", 0)
    _aim_at_frame(session, by, selector)

    # `near` needs the whole match set to choose from, so it takes the same
    # path an index past the first does: wait for the set, then pick. This is
    # the case that used to force an agent into `run_js` -- stamping an
    # attribute on the right row and clicking that -- which is both slower and
    # wrong more often than it looks.
    if getattr(cmd, "near", None) is not None:
        try:
            WebDriverWait(session.driver, wait_for).until(
                lambda d: d.find_elements(by, selector)
            )
        except Timeout as exc:
            raise _miss(session, by, selector, cmd, state, wait_for) from exc
        element = pick_near(session, session.driver.find_elements(by, selector), cmd)
        if state in _NEEDS_VIEWPORT:
            scroll_into_view(session, element)
        return element

    if index == 0:
        try:
            if state in _NEEDS_VIEWPORT:
                # Selenium judges an element where it currently sits, so
                # anything below the fold fails as "not interactable" even
                # though a real user would just scroll to it. Bring it into
                # view first, then ask whether it is interactable.
                scroll_into_view(
                    session,
                    WebDriverWait(session.driver, wait_for).until(
                        EC.presence_of_element_located((by, selector))
                    ),
                )
            return WebDriverWait(session.driver, wait_for).until(
                _CONDITIONS[state]((by, selector))
            )
        except Timeout as exc:
            raise _miss(session, by, selector, cmd, state, wait_for) from exc

    # An index past the first needs the whole match list, so wait for presence
    # of the set rather than a single element.
    try:
        WebDriverWait(session.driver, wait_for).until(
            lambda d: len(d.find_elements(by, selector)) > index
        )
    except Timeout as exc:
        raise OpError(
            "element_not_found",
            f"fewer than {index + 1} elements matched {describe(cmd)} "
            f"after {wait_for}s",
        ) from exc
    return session.driver.find_elements(by, selector)[index]


def _miss(session, by, selector, cmd, state, waited) -> OpError:
    """Distinguish 'nothing matched' from 'matched but not interactable'."""
    try:
        found = session.driver.find_elements(by, selector)
    except (NoSuchElement, StaleElement):
        found = []
    if found and state in ("visible", "clickable"):
        return OpError(
            "not_interactable",
            f"{len(found)} element(s) matched {describe(cmd)} but none became "
            f"{state} within {waited}s (hidden, disabled, or covered)",
        )
    return OpError(
        "element_not_found", f"nothing matched {describe(cmd)} within {waited}s"
    )


def resolve_many(
    session: BrowserSession,
    cmd,
    limit: int,
    visible_only: bool,
) -> tuple[list[tuple[Element, tuple[int, ...], bool]], bool]:
    """Every match on the page, each with where it was found.

    Returns `(element, frame, in_shadow)`. The host document first, then each
    frame in reading order -- so results arrive in the order a person would come
    across them, and the caller knows which document to switch into before
    touching any of them.

    With `shadow: true` the search in each document also descends its open
    shadow roots, so "the whole page" means every tree reachable from it. That
    is what lets an empty result be reported as an answer instead of a shrug.
    """
    if getattr(cmd, "ref", None) is not None:
        home = session.refs.frame_of(session.active_tab, cmd.ref)
        return [(session.resolve_ref(cmd.ref), home, False)], False

    pierce = bool(getattr(cmd, "shadow", False))
    by, selector = locator(cmd)
    homes = [()] + session.frame_paths()
    found: list[tuple[Element, tuple[int, ...], bool]] = []
    try:
        for home in homes:
            if not session.enter_frame(home):
                continue
            try:
                elements = session.driver.find_elements(by, selector)
            except EngineError:
                elements = []
            if visible_only:
                elements = [e for e in elements if _is_displayed(e)]
            found.extend((element, home, False) for element in elements)

            if pierce:
                light = set(elements)
                mode = "css" if cmd.css is not None else "text"
                value = cmd.css if cmd.css is not None else cmd.text
                for element in shadow.search(session.driver, value, mode, limit + 1):
                    # The walk starts at the document, so it re-finds what the
                    # ordinary search already returned. Report each once, and
                    # mark only the ones that were genuinely out of reach.
                    if element in light:
                        continue
                    if visible_only and not _is_displayed(element):
                        continue
                    found.append((element, home, True))

            if len(found) > limit:
                break
    finally:
        session.leave_frames()

    truncated = len(found) > limit
    return found[:limit], truncated


def _is_displayed(element: Element) -> bool:
    try:
        return element.is_displayed()
    except StaleElement:
        return False
