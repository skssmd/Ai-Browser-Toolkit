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


def input(session: BrowserSession, cmd) -> dict:
    element = resolve_one(session, cmd, state="visible")
    try:
        if cmd.clear:
            _clear_field(session, element)
        element.send_keys(cmd.value)
    except ElementNotInteractableException as exc:
        raise OpError(
            "not_interactable",
            f"could not type into {describe(cmd)}: {exc.msg or exc}",
        ) from exc
    return {"target": describe(cmd), "value": element.get_attribute("value")}


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
    key = KEYS.get(cmd.key.lower())
    if key is None:
        if len(cmd.key) != 1:
            raise OpError(
                "invalid_op",
                f"unknown key {cmd.key!r}; use a single character or one of: "
                + ", ".join(sorted(KEYS)),
            )
        key = cmd.key

    if cmd.has_target:
        resolve_one(session, cmd, state="visible").send_keys(key)
        return {"pressed": cmd.key, "target": describe(cmd)}
    ActionChains(session.driver).send_keys(key).perform()
    return {"pressed": cmd.key, "target": "<active element>"}
