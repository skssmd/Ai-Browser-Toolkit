"""Turn a command's targeting fields into live WebElements."""

from __future__ import annotations

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .browser import BrowserSession
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
        return (By.CSS_SELECTOR, cmd.css)
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


def scroll_into_view(session: BrowserSession, element: WebElement) -> None:
    """Centre an element in the viewport. Never fails a command."""
    try:
        session.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element
        )
    except WebDriverException:
        pass


def resolve_one(
    session: BrowserSession,
    cmd,
    state: str = "present",
    timeout: float | None = None,
) -> WebElement:
    """Resolve a single element, waiting up to `timeout` for it to reach `state`."""
    if getattr(cmd, "ref", None) is not None:
        element = session.refs.get(session.active_tab, cmd.ref)
        if state in _NEEDS_VIEWPORT:
            scroll_into_view(session, element)
        return element

    wait_for = timeout if timeout is not None else session.action_timeout
    by, selector = locator(cmd)
    index = getattr(cmd, "index", 0)

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
        except TimeoutException as exc:
            raise _miss(session, by, selector, cmd, state, wait_for) from exc

    # An index past the first needs the whole match list, so wait for presence
    # of the set rather than a single element.
    try:
        WebDriverWait(session.driver, wait_for).until(
            lambda d: len(d.find_elements(by, selector)) > index
        )
    except TimeoutException as exc:
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
    except (NoSuchElementException, StaleElementReferenceException):
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
) -> tuple[list[WebElement], bool]:
    """Resolve every match. Returns (elements, truncated)."""
    if getattr(cmd, "ref", None) is not None:
        return [session.refs.get(session.active_tab, cmd.ref)], False

    by, selector = locator(cmd)
    elements = session.driver.find_elements(by, selector)
    if visible_only:
        elements = [e for e in elements if _is_displayed(e)]
    truncated = len(elements) > limit
    return elements[:limit], truncated


def _is_displayed(element: WebElement) -> bool:
    try:
        return element.is_displayed()
    except StaleElementReferenceException:
        return False
