"""Interaction ops: click, type, select, hover, scroll, wait, key press."""

from __future__ import annotations

import time

from ..browser import BrowserSession
from ..engine import (
    CONTROL,
    DELETE,
    ActionChains,
    ClickIntercepted,
    EngineError,
    InvalidElementState,
    NotInteractable,
    Select,
    Timeout,
    UnexpectedTagName,
    WebDriverWait,
)
from ..engine import KEYS as KEYS
from ..engine import MODIFIERS as _MODIFIERS
from ..errors import OpError
from ..targeting import describe, locator, resolve_one


def _resolve_press_keys(raw: str) -> list[str]:
    """Turn 'ctrl+v', 'shift+enter', or a plain key into a send_keys list.

    A chord is modifiers joined by '+' and one final key: 'ctrl+alt+1'. The
    final key may be a single character or a named key. A bare key behaves as
    before (single character or named key).
    """
    parts = [part.strip() for part in raw.split("+")]
    if len(parts) == 1:
        named = KEYS.get(raw.lower())
        if named is not None:
            return [named]
        if len(raw) != 1:
            raise OpError(
                "invalid_op",
                f"unknown key {raw!r}; use a single character, a named key, or a "
                f"chord like 'ctrl+v' (modifiers: {', '.join(sorted(_MODIFIERS))})",
            )
        return [raw]

    modifiers = []
    for part in parts[:-1]:
        modifier = _MODIFIERS.get(part)
        if modifier is None:
            raise OpError(
                "invalid_op",
                f"unknown modifier {part!r} in chord {raw!r}; use one of "
                f"{', '.join(sorted(_MODIFIERS))}",
            )
        modifiers.append(modifier)

    main = parts[-1]
    main_key = KEYS.get(main) or (main if len(main) == 1 else None)
    if main_key is None:
        raise OpError("invalid_op", f"unknown key {main!r} in chord {raw!r}")
    return modifiers + [main_key]


_VIEWPORT_JS = "return [window.innerWidth, window.innerHeight];"

# Report what is actually under the point. A coordinate click is blind by
# nature, so saying what it landed on is the difference between a result and a
# guess.
_AT_POINT_JS = """
const el = document.elementFromPoint(arguments[0], arguments[1]);
if (!el) { return null; }
return el.tagName.toLowerCase()
  + (el.id ? '#' + el.id : '')
  + (el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
"""


# Selenium judges an element by its own state -- displayed, enabled -- and not
# by what is painted on top of it. When something else is, the click can be
# dispatched and swallowed, and the op reports success having done nothing.
# That is the worst answer an agent can be handed, so hit-test first: whatever
# sits at the element's centre must be the element, an ancestor of it (a label
# wrapping its input), or a descendant (the span inside a button).
_HIT_TEST_JS = """
const el = arguments[0];
const r = el.getBoundingClientRect();
if (!r.width && !r.height) { return {ok: false, reason: 'zero size'}; }
const x = r.left + r.width / 2, y = r.top + r.height / 2;
// Off-screen centres are not this check's business: the caller already scrolled
// the element into view, and a partially visible target is still clickable.
if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) {
  return {ok: true};
}
// `elementFromPoint` answers from the document's point of view, so anything
// inside a shadow root comes back as its *host* -- and a component's own
// button would read as covered by the element it lives in. Descend through
// each root under the point to find what would really be hit.
let top = document.elementFromPoint(x, y);
for (let depth = 0; depth < 10 && top && top.shadowRoot; depth++) {
  const inner = top.shadowRoot.elementFromPoint(x, y);
  if (!inner || inner === top) break;
  top = inner;
}
if (!top || top === el || el.contains(top) || top.contains(el)) { return {ok: true}; }
// `contains` does not cross a shadow boundary either, so ask the composed
// path: if the target is on the way from the hit element to the window, the
// click lands on it.
try {
  if (typeof el.getRootNode === 'function') {
    let node = top;
    while (node) {
      if (node === el) { return {ok: true}; }
      node = node.parentNode || (node.host || null);
    }
  }
} catch (e) {}
// What *kind* of thing is in the way, which is the part a caller can act on.
// A class list is not it: a Radix overlay reports as
// `div.data-[state=open]:animate-in.data-[state=closed]:animate-out`, which
// names the animation and says nothing about a dialog being open.
let kind = '', name = '';
for (let node = top, up = 0; node && up < 6; node = node.parentElement, up++) {
  if (!node.getAttribute) { break; }
  const role = node.getAttribute('role');
  if (role === 'dialog' || role === 'alertdialog'
      || node.getAttribute('aria-modal') === 'true') {
    kind = 'dialog';
    const labelled = node.getAttribute('aria-label');
    if (labelled) { name = labelled; }
    else {
      const heading = node.querySelector('h1,h2,h3,[role=heading]');
      if (heading) { name = (heading.textContent || '').trim().slice(0, 60); }
    }
    break;
  }
}
if (!kind) {
  const cover = top.getBoundingClientRect();
  if (cover.width >= window.innerWidth * 0.9
      && cover.height >= window.innerHeight * 0.9) {
    kind = 'a full-screen overlay';
  }
}
return {ok: false, kind: kind, name: name, hit: top.tagName.toLowerCase()
  + (top.id ? '#' + top.id : '')
  + (top.className && typeof top.className === 'string'
      ? '.' + top.className.trim().split(/\\s+/).slice(0, 2).join('.') : '')};
"""


# How long an obstruction has to persist before it counts as real.
#
# Deliberately shorter than action_timeout. Component libraries animate dialogs
# and popovers in and out, so for a few hundred milliseconds the thing you asked
# for really is behind an overlay -- one that is on its way out. Sampling once
# turned every such transition into a spurious failure; waiting the full action
# timeout would instead double how long a genuinely blocked click takes to
# report. A second covers any animation worth the name.
_HIT_TEST_WINDOW = 1.0
_HIT_TEST_INTERVAL = 0.05


def _blocker(verdict: dict) -> str:
    """What is in the way, named twice over: what kind of thing it is, and
    which element it is. The kind is what a caller acts on; the element is what
    they grep the page for, and dropping it would make an error less useful
    than the one it replaced."""
    hit = verdict.get("hit") or "something"
    kind = verdict.get("kind")
    return f"{kind} ({hit})" if kind else hit


def _require_hit(session: BrowserSession, element, cmd) -> None:
    """Refuse a click that would land on something other than its target.

    Polls rather than sampling: `resolve_one` has just *waited* for the element
    to become clickable, and a check that gives up instantly disagrees with the
    patience of the wait in front of it. Observed against a shadcn dialog, where
    every close animation produced a not_interactable that succeeded on the very
    next identical command.

    Never invents a failure: any trouble running the test is treated as a pass,
    because this exists to catch a silent success, not to add a new way to fail.
    """
    deadline = time.monotonic() + _HIT_TEST_WINDOW
    verdict = None
    while True:
        try:
            verdict = session.driver.execute_script(_HIT_TEST_JS, element)
        except EngineError:
            return
        if not isinstance(verdict, dict) or verdict.get("ok"):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(_HIT_TEST_INTERVAL)

    if verdict.get("reason") == "zero size":
        raise OpError(
            "not_interactable",
            f"{describe(cmd)} has no size on screen, so a click cannot reach it",
        )
    # Name the obstacle in terms the caller can act on. A dialog is both the
    # common case and the actionable one: it almost always means the *previous*
    # command opened it, and that command's diff already reported its controls.
    #
    # Seen in a real session: an agent clicked Approve, which opened a
    # confirmation dialog, then clicked the same ref twice more. The refusal was
    # correct both times -- but it said "covered by
    # div.data-[state=open]:animate-in.data-[state=closed]:animate-out", which
    # names a Tailwind animation and gives a reader nothing to do.
    if verdict.get("kind") == "dialog":
        titled = f" ({verdict.get('name')!r})" if verdict.get("name") else ""
        raise OpError(
            "not_interactable",
            f"{describe(cmd)} is behind an open dialog{titled}, which would "
            "receive the click instead. Act on the dialog or close it first -- "
            "the command that opened it already reported its controls. Pass "
            "force:true only if you mean to click through it.",
        )
    raise OpError(
        "not_interactable",
        f"{describe(cmd)} is still covered by "
        f"{_blocker(verdict)} after "
        f"{_HIT_TEST_WINDOW}s, and it would receive the click instead. Pass "
        "force:true to dispatch it anyway, or new_tab:true if the target is a link",
    )


def click(session: BrowserSession, cmd) -> dict:
    if cmd.at is not None:
        return _click_at(session, cmd)
    if cmd.new_tab:
        return _open_in_new_tab(session, cmd)

    # Without force the element must be genuinely clickable. With force we only
    # require it to exist, because the two cases force exists for -- an overlay
    # covering it, and a custom control that hides the real input -- both fail
    # that gate before a click is ever dispatched.
    element = resolve_one(session, cmd, state="present" if cmd.force else "clickable")

    if cmd.force and not element.is_enabled():
        raise OpError(
            "not_interactable",
            f"{describe(cmd)} is disabled; force defeats occlusion, not intent",
        )

    if not cmd.force:
        # force exists precisely to click through an overlay, so it skips the
        # test rather than being blocked by it.
        _require_hit(session, element, cmd)

    try:
        element.click()
    except (ClickIntercepted, NotInteractable) as exc:
        if not cmd.force:
            raise OpError(
                "not_interactable",
                f"could not click {describe(cmd)}: {exc.msg or exc}",
            ) from exc
        try:
            session.driver.execute_script("arguments[0].click();", element)
        except EngineError as inner:
            raise OpError(
                "not_interactable",
                f"forced click on {describe(cmd)} failed: {inner.msg or inner}",
            ) from inner
        return {"clicked": describe(cmd), "forced": True, **session.location()}
    return {"clicked": describe(cmd), "forced": False, **session.location()}


def _click_at(session: BrowserSession, cmd) -> dict:
    """Click a point with a real mouse event.

    This is the escape hatch for anything the DOM cannot address -- a canvas, a
    closed shadow root, an image map. It is a genuine pointer sequence, not a
    dispatched event, so a page cannot tell it from a person.
    """
    offset_x, offset_y = cmd.at

    if cmd.has_target:
        # Relative to an element: scroll it into view first, so the offset means
        # the same thing no matter where the page is scrolled to.
        element = resolve_one(session, cmd, state="visible")
        box = element.rect
        origin = describe(cmd)
        x = int(box["x"] + offset_x - session.driver.execute_script("return window.scrollX;"))
        y = int(box["y"] + offset_y - session.driver.execute_script("return window.scrollY;"))
    else:
        origin = "viewport"
        x, y = offset_x, offset_y

    width, height = session.driver.execute_script(_VIEWPORT_JS)
    if not (0 <= x < width and 0 <= y < height):
        raise OpError(
            "not_interactable",
            f"({x}, {y}) is outside the {width}x{height} viewport; a mouse click "
            "can only reach what is on screen, so scroll it into view first",
        )

    hit = session.driver.execute_script(_AT_POINT_JS, x, y)
    try:
        chain = ActionChains(session.driver)
        pointer = chain.w3c_actions.pointer_action
        pointer.move_to_location(x, y)
        pointer.click()
        chain.perform()
    except EngineError as exc:
        raise OpError(
            "not_interactable",
            f"could not click ({x}, {y}): {exc.msg or exc}",
        ) from exc

    return {
        "clicked": f"at=({x}, {y})",
        "relative_to": origin,
        "hit": hit,
        "forced": False,
        **session.location(),
    }


def _open_in_new_tab(session: BrowserSession, cmd) -> dict:
    """Open the target's href beside the current page.

    Reading the href beats ctrl-click: no modifier-key timing, no popup blocker,
    and an overlay covering the link is irrelevant because nothing is clicked.
    """
    element = resolve_one(session, cmd)
    href = element.get_attribute("href")
    if not href:
        raise OpError(
            "not_interactable",
            f"{describe(cmd)} is a <{element.tag_name}> with no href, so there is "
            "nothing to open in a new tab",
        )

    origin = session.active_tab
    tab_id = session.new_tab(href, activate=True)
    location = session.location()
    if not cmd.activate:
        session.switch_tab(origin)
    return {"clicked": describe(cmd), "tab_id": tab_id, "forced": False, **location}


# Emptying a field the way a framework will believe. Mirrors _SET_VALUE_JS: the
# prototype's own setter, because an assignment React already knows about is one
# it ignores, then the events it listens on.
_CLEAR_VALUE_JS = """
const el = arguments[0];
const proto = el instanceof HTMLTextAreaElement
  ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
const desc = Object.getOwnPropertyDescriptor(proto, 'value');
if (!desc || !desc.set) { return false; }
desc.set.call(el, '');
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
return true;
"""


def _clear_field(session: BrowserSession, element) -> None:
    """Empty a field, whatever kind of field it is.

    Selenium's clear() only applies to form controls. Rich editors -- Google
    Sheets' cell editor, most WYSIWYGs -- are contenteditable divs, where clear()
    raises and would otherwise leave stale text for send_keys to append to.

    It can also come undone. clear() empties the value, fires `change` alone --
    no `input` -- and blurs the field, so a component that tracks its own text
    reverts to what it last committed. The field reads empty for as long as
    nothing touches it, then the old text is back the moment send_keys takes
    focus, and the typing appends to what was supposed to be gone. Checking here
    cannot catch that; `input` checks afterwards instead.
    """
    try:
        element.clear()
    except (InvalidElementState, NotInteractable):
        _clear_by_keystrokes(session, element)
        return

    # Then say the same thing in the language a component understands. clear()
    # is invisible to one; this write goes through the prototype's setter, which
    # is what makes a framework notice the value changed, and the `input` event
    # is the one it is actually listening for. Either alone leaves a field this
    # op cannot empty; together they cover both kinds.
    try:
        session.driver.execute_script(_CLEAR_VALUE_JS, element)
    except EngineError:
        pass


def _clear_by_keystrokes(session: BrowserSession, element) -> None:
    """Empty a field the way a person would: select all, delete.

    Slower than clear() and it moves focus, but every step is a real event the
    page cannot tell from a user -- which is the point when a component only
    believes `input`.
    """
    ActionChains(session.driver).click(element).key_down(CONTROL).send_keys(
        "a"
    ).key_up(CONTROL).send_keys(DELETE).perform()


# Fields the browser renders as locale-formatted segment boxes rather than as
# text. Typing into them is not a matter of keystrokes.
_SEGMENTED_TYPES = {
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "datetime-local": "YYYY-MM-DDTHH:MM",
    "month": "YYYY-MM",
    "week": "YYYY-Www",
}

# React keeps its own record of the last value it wrote and ignores a plain
# assignment, so the write has to go through the prototype's own setter for the
# framework to notice it changed.
_SET_VALUE_JS = """
const el = arguments[0], value = arguments[1];
const proto = el instanceof HTMLTextAreaElement
  ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
return el.value;
"""


# chromedriver refuses send_keys to an element with no size, file input or not,
# so the input has to exist on screen for the instant the path is written. It is
# given a 5px corner at 1% opacity, then put back exactly as it was -- a page
# left mutated would show up as a phantom change in the next diff.
UNHIDE_FILE_INPUT_JS = """
const el = arguments[0];
const previous = el.style.cssText;
el.style.cssText = 'display:block !important; visibility:visible !important;'
  + 'opacity:0.01 !important; position:fixed !important; top:0; left:0;'
  + 'width:5px; height:5px; z-index:99999;';
return previous;
"""

_RESTORE_STYLE_JS = "arguments[0].style.cssText = arguments[1] || '';"


def _write_hidden_file(session: BrowserSession, cmd, element) -> dict:
    """Write a path to a file input that is hidden by design."""
    try:
        previous = session.driver.execute_script(UNHIDE_FILE_INPUT_JS, element)
    except EngineError:
        previous = ""
    try:
        element.send_keys(cmd.value)
    except EngineError as exc:
        raise OpError(
            "not_interactable",
            f"could not stage {cmd.value!r} on {describe(cmd)}: {exc.msg or exc}",
        ) from exc
    finally:
        try:
            session.driver.execute_script(_RESTORE_STYLE_JS, element, previous)
        except EngineError:
            pass
    return {"target": describe(cmd), "value": _field_value(element), "staged": True}


def _hidden_file_input(session: BrowserSession, cmd, original: OpError):
    """Recover a file input that failed the visibility gate.

    Uploads are the one control the web hides on purpose: the standard pattern
    styles a custom button and keeps the real `<input type=file>` at
    display:none, so requiring it to be visible means it can never be used. A
    path can be written to it hidden -- nothing else can, so nothing else gets
    this exemption, and anything that is not a file input re-raises untouched.
    """
    try:
        element = resolve_one(session, cmd, state="present")
        if (element.get_attribute("type") or "").lower() == "file":
            return element
    except (OpError, EngineError):
        pass
    raise original


def input(session: BrowserSession, cmd) -> dict:
    try:
        element = resolve_one(session, cmd, state="visible")
    except OpError as exc:
        return _write_hidden_file(session, cmd, _hidden_file_input(session, cmd, exc))

    field_type = ""
    try:
        field_type = (element.get_attribute("type") or "").lower()
    except EngineError:
        pass

    # Every file input goes through the staged writer, however it was targeted.
    # A `ref` resolves straight out of the cache without a visibility check, so
    # a hidden upload reaches here rather than raising -- which meant the ref
    # the actionable track hands out for an upload was the one way of reaching
    # it that did not work.
    if field_type == "file":
        return _write_hidden_file(session, cmd, element)

    if field_type in _SEGMENTED_TYPES:
        return _set_segmented(session, cmd, element, field_type)

    previous = _field_value(element) or "" if cmd.clear else ""
    try:
        if cmd.clear:
            _clear_field(session, element)
        element.send_keys(cmd.value)

        # A framework-controlled field can put its old text back between the
        # clear and the first keystroke, leaving exactly old+new behind. That
        # concatenation is the signature, and it is worth one retry through
        # keystrokes, which such a field does listen to. Left alone it is
        # invisible: the op reports the corrupted value as the one it wrote, and
        # the next thing to read the field -- a typeahead, a form submit -- acts
        # on nonsense. Traced on LinkedIn's profile form, where it silently
        # poisoned every retry.
        if previous and _field_value(element) == previous + cmd.value:
            _clear_by_keystrokes(session, element)
            element.send_keys(cmd.value)
    except NotInteractable as exc:
        raise OpError(
            "not_interactable",
            f"could not type into {describe(cmd)}: {exc.msg or exc}",
        ) from exc
    return {"target": describe(cmd), "value": _field_value(element)}


def _set_segmented(session: BrowserSession, cmd, element, field_type: str) -> dict:
    """Write a date/time field instead of typing into it.

    `send_keys` feeds the browser's *locale* segments, not the ISO value: on an
    en-US date input "2026-08-03" arrives as 60803-02-20, because the dashes are
    consumed as segment separators and the digits shift. The field then submits
    silently wrong. Setting the value is the only reliable route.
    """
    try:
        landed = session.driver.execute_script(_SET_VALUE_JS, element, cmd.value)
    except EngineError as exc:
        raise OpError(
            "not_interactable",
            f"could not set {describe(cmd)}: {exc.msg or exc}",
        ) from exc

    if landed != cmd.value:
        # An <input type=date> silently empties itself when handed something it
        # cannot parse, which would otherwise look like a successful write.
        raise OpError(
            "not_interactable",
            f"{describe(cmd)} is a {field_type} input and rejected "
            f"{cmd.value!r} (it now holds {landed!r}); it needs the format "
            f"{_SEGMENTED_TYPES[field_type]}",
        )
    return {"target": describe(cmd), "value": landed, "set_directly": True}


def _field_value(element) -> str | None:
    """What the field now holds.

    Form controls answer to the value attribute; contenteditable elements have
    no such attribute and would report null, making a successful write look
    like it did nothing.
    """
    value = element.get_attribute("value")
    if value is not None:
        return value
    if element.get_attribute("contenteditable") in ("", "true", "plaintext-only"):
        return element.get_attribute("textContent")
    return None


def select(session: BrowserSession, cmd) -> dict:
    element = resolve_one(session, cmd, state="visible")
    try:
        dropdown = Select(element)
    except UnexpectedTagName as exc:
        raise OpError(
            "not_a_select",
            f"{describe(cmd)} is a <{element.tag_name}>, not a <select>; "
            "for custom dropdowns use hover then click",
        ) from exc

    try:
        if cmd.by_text is not None:
            dropdown.select_by_visible_text(cmd.by_text)
        elif cmd.value is not None:
            dropdown.select_by_value(cmd.value)
        else:
            dropdown.select_by_index(cmd.option_index)
    except Exception as exc:  # selenium raises NoSuchElementException here
        raise OpError(
            "element_not_found",
            f"no matching option in {describe(cmd)}: {exc}",
        ) from exc

    chosen = dropdown.first_selected_option
    return {"selected": chosen.text, "value": chosen.get_attribute("value")}


def hover(session: BrowserSession, cmd) -> dict:
    element = resolve_one(session, cmd, state="visible")
    ActionChains(session.driver).move_to_element(element).perform()
    return {"hovered": describe(cmd)}


def scroll(session: BrowserSession, cmd) -> dict:
    if cmd.has_target:
        element = resolve_one(session, cmd)
        session.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element
        )
        return {"scrolled_to": describe(cmd)}
    session.driver.execute_script("window.scrollTo(0, arguments[0]);", cmd.y)
    return {"scrolled_to": cmd.y}


def wait_for(session: BrowserSession, cmd) -> dict:
    if cmd.state == "absent":
        if cmd.ref is not None:
            raise OpError(
                "invalid_op", "wait_for state 'absent' needs a selector, not a ref"
            )
        by, selector = locator(cmd)
        try:
            WebDriverWait(session.driver, cmd.timeout).until(
                lambda d: not d.find_elements(by, selector)
            )
        except Timeout as exc:
            raise OpError(
                "timeout",
                f"{describe(cmd)} was still present after {cmd.timeout}s",
            ) from exc
        return {"state": "absent", "target": describe(cmd)}

    resolve_one(session, cmd, state=cmd.state, timeout=cmd.timeout)
    return {"state": cmd.state, "target": describe(cmd)}


def press(session: BrowserSession, cmd) -> dict:
    keys = _resolve_press_keys(cmd.key)

    if cmd.has_target:
        resolve_one(session, cmd, state="visible").send_keys(*keys)
        return {"pressed": cmd.key, "target": describe(cmd)}

    # No target: drive whatever has focus. With modifiers the chord needs each
    # modifier held while the main key goes down, so key_down every modifier,
    # send the main key, then release them in reverse order.
    modifiers, main = keys[:-1], keys[-1]
    if modifiers:
        chain = ActionChains(session.driver)
        for modifier in modifiers:
            chain = chain.key_down(modifier)
        chain = chain.send_keys(main)
        for modifier in reversed(modifiers):
            chain = chain.key_up(modifier)
        chain.perform()
    else:
        ActionChains(session.driver).send_keys(main).perform()
    return {"pressed": cmd.key, "target": "<active element>"}
