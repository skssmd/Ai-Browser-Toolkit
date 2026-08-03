"""Interaction ops: click, type, select, hover, scroll, wait, key press."""

from __future__ import annotations

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    InvalidElementStateException,
    TimeoutException,
    UnexpectedTagNameException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select as SeleniumSelect
from selenium.webdriver.support.ui import WebDriverWait

from ..browser import BrowserSession
from ..errors import OpError
from ..targeting import describe, locator, resolve_one

KEYS = {
    name.lower(): getattr(Keys, name)
    for name in dir(Keys)
    if name.isupper() and not name.startswith("_")
}

# Modifier names accepted inside a key chord like "ctrl+v" or "shift+enter".
_MODIFIERS = {
    "alt": Keys.ALT,
    "cmd": Keys.META,
    "command": Keys.META,
    "control": Keys.CONTROL,
    "ctrl": Keys.CONTROL,
    "meta": Keys.META,
    "option": Keys.ALT,
    "shift": Keys.SHIFT,
    "windows": Keys.META,
}


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


def click(session: BrowserSession, cmd) -> dict:
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

    try:
        element.click()
    except (ElementClickInterceptedException, ElementNotInteractableException) as exc:
        if not cmd.force:
            raise OpError(
                "not_interactable",
                f"could not click {describe(cmd)}: {exc.msg or exc}",
            ) from exc
        try:
            session.driver.execute_script("arguments[0].click();", element)
        except WebDriverException as inner:
            raise OpError(
                "not_interactable",
                f"forced click on {describe(cmd)} failed: {inner.msg or inner}",
            ) from inner
        return {"clicked": describe(cmd), "forced": True, **session.location()}
    return {"clicked": describe(cmd), "forced": False, **session.location()}


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


def _clear_field(session: BrowserSession, element) -> None:
    """Empty a field, whatever kind of field it is.

    Selenium's clear() only applies to form controls. Rich editors -- Google
    Sheets' cell editor, most WYSIWYGs -- are contenteditable divs, where clear()
    raises and would otherwise leave stale text for send_keys to append to.
    """
    try:
        element.clear()
        return
    except (InvalidElementStateException, ElementNotInteractableException):
        pass
    ActionChains(session.driver).click(element).key_down(Keys.CONTROL).send_keys(
        "a"
    ).key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()


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


def input(session: BrowserSession, cmd) -> dict:
    element = resolve_one(session, cmd, state="visible")

    field_type = ""
    try:
        field_type = (element.get_attribute("type") or "").lower()
    except WebDriverException:
        pass
    if field_type in _SEGMENTED_TYPES:
        return _set_segmented(session, cmd, element, field_type)

    try:
        if cmd.clear:
            _clear_field(session, element)
        element.send_keys(cmd.value)
    except ElementNotInteractableException as exc:
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
    except WebDriverException as exc:
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
        dropdown = SeleniumSelect(element)
    except UnexpectedTagNameException as exc:
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
        except TimeoutException as exc:
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
