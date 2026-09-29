"""The engine seam: everything the page layer needs from a browser driver.

Nothing above this module names a driver library. `ops/`, `targeting`,
`frames`, `shadow` and `refs` import their exceptions, locator
strategies, key names and waits from here; `pwdriver` raises these exceptions
and speaks this vocabulary.

The names were first re-exports of Selenium's, so the move to Playwright could
be a rename rather than a rewrite. Selenium is retired now (0.7.0) and this
module defines them itself, with the same names, roles and values -- nothing
above it changed. The Selenium version is kept, unimported, in
`reference/selenium/` at the repository root.

## What each group is for

**Exceptions.** Every module catches driver failures. `EngineError` is the
root, so a bare `except EngineError` means "the driver could not do that".

**Locators.** `By.CSS` and friends carry the wire strings the page layer has
always used; `pwdriver` translates them to Playwright selectors.

**Keys.** The named keys an agent can send, as the private-use codepoints the
WebDriver protocol defined. `pwdriver` maps each to Playwright's key name.
"""

from __future__ import annotations

import time
from typing import Any, Callable

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class EngineError(Exception):
    """The driver could not do that. The root of every exception here.

    `msg` is the bare message, which is what error text across the toolkit
    quotes (`exc.msg or exc`).
    """

    def __init__(self, msg: str | None = None, *args: Any) -> None:
        super().__init__(msg, *args)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg or self.__class__.__name__


class Timeout(EngineError):
    """A wait ran out."""


class StaleElement(EngineError):
    """The element was removed from the page after it was found."""


class NoSuchElement(EngineError):
    """Nothing matched."""


class NotInteractable(EngineError):
    """The element exists but cannot be clicked or typed into."""


class ClickIntercepted(EngineError):
    """Something else is painted over the element."""


class InvalidElementState(EngineError):
    """The element is in a state that forbids the action (e.g. read-only)."""


class UnexpectedTagName(EngineError):
    """An element of the wrong kind, e.g. `Select` on a non-select."""


class NoSuchFrame(EngineError):
    """The frame to switch into does not exist."""


class NoSuchWindow(EngineError):
    """The tab or window is gone."""


class NoAlert(EngineError):
    """No dialog is open."""


class UnexpectedAlert(EngineError):
    """A dialog is open and blocks the action."""


class DeadSession(EngineError):
    """The browser behind the driver is gone."""


class ScriptError(EngineError):
    """The page's JavaScript threw."""


# The type a resolved element has. The Playwright driver's element; typed
# loosely so this module imports nothing from the driver.
Element = Any

# Every exception above, for the `except` clauses that mean "anything the driver
# can raise".
ENGINE_ERRORS: tuple[type[BaseException], ...] = (
    EngineError,
    Timeout,
    StaleElement,
    NoSuchElement,
    NotInteractable,
    ClickIntercepted,
    InvalidElementState,
    UnexpectedTagName,
    NoSuchFrame,
    NoSuchWindow,
    NoAlert,
    UnexpectedAlert,
    DeadSession,
    ScriptError,
)


class By:
    """Locator strategies, as the WebDriver wire strings. `pwdriver` translates
    them to Playwright selectors at its boundary."""

    CSS = "css selector"
    XPATH = "xpath"
    TAG = "tag name"


# --------------------------------------------------------------------------- #
# Keys
#
# Callers ask for `KEYS["ctrl"]`-style names and never see how the driver
# spells them. Frozen from Selenium's `Keys` class when it was retired, so the
# accepted spellings are exactly the ones that always worked -- including the
# ones nobody thinks to list (f1-f12, numpad0-9, semicolon, separator) and the
# underscored ones (`arrow_down`). A test pins the table.
# --------------------------------------------------------------------------- #

KEYS: dict[str, str] = {
    'null': '\ue000',
    'cancel': '\ue001',
    'help': '\ue002',
    'back_space': '\ue003',
    'backspace': '\ue003',
    'tab': '\ue004',
    'clear': '\ue005',
    'return': '\ue006',
    'enter': '\ue007',
    'left_shift': '\ue008',
    'shift': '\ue008',
    'control': '\ue009',
    'left_control': '\ue009',
    'alt': '\ue00a',
    'left_alt': '\ue00a',
    'left_option': '\ue00a',
    'pause': '\ue00b',
    'escape': '\ue00c',
    'space': '\ue00d',
    'page_up': '\ue00e',
    'page_down': '\ue00f',
    'end': '\ue010',
    'home': '\ue011',
    'arrow_left': '\ue012',
    'left': '\ue012',
    'arrow_up': '\ue013',
    'up': '\ue013',
    'arrow_right': '\ue014',
    'right': '\ue014',
    'arrow_down': '\ue015',
    'down': '\ue015',
    'insert': '\ue016',
    'delete': '\ue017',
    'semicolon': '\ue018',
    'equals': '\ue019',
    'numpad0': '\ue01a',
    'numpad1': '\ue01b',
    'numpad2': '\ue01c',
    'numpad3': '\ue01d',
    'numpad4': '\ue01e',
    'numpad5': '\ue01f',
    'numpad6': '\ue020',
    'numpad7': '\ue021',
    'numpad8': '\ue022',
    'numpad9': '\ue023',
    'multiply': '\ue024',
    'add': '\ue025',
    'separator': '\ue026',
    'subtract': '\ue027',
    'decimal': '\ue028',
    'divide': '\ue029',
    'f1': '\ue031',
    'f2': '\ue032',
    'f3': '\ue033',
    'f4': '\ue034',
    'f5': '\ue035',
    'f6': '\ue036',
    'f7': '\ue037',
    'f8': '\ue038',
    'f9': '\ue039',
    'f10': '\ue03a',
    'f11': '\ue03b',
    'f12': '\ue03c',
    'command': '\ue03d',
    'left_command': '\ue03d',
    'left_meta': '\ue03d',
    'meta': '\ue03d',
    'zenkaku_hankaku': '\ue040',
    'right_shift': '\ue050',
    'right_control': '\ue051',
    'right_alt': '\ue052',
    'right_option': '\ue052',
    'right_meta': '\ue053',
}

# Modifier names accepted inside a chord like "ctrl+v" or "shift+enter". A
# strict subset of KEYS by intent: these are the only ones that may appear
# before the '+', and the error message lists them.
MODIFIERS: dict[str, str] = {
    "alt": KEYS["alt"],
    "cmd": KEYS["meta"],
    "command": KEYS["meta"],
    "control": KEYS["control"],
    "ctrl": KEYS["control"],
    "meta": KEYS["meta"],
    "option": KEYS["alt"],
    "shift": KEYS["shift"],
    "windows": KEYS["meta"],
}

# Individual keys named at their use sites rather than looked up by string.
BACKSPACE = KEYS["backspace"]
CONTROL = KEYS["control"]
DELETE = KEYS["delete"]
ENTER = KEYS["enter"]


def ActionChains(driver):
    """Chorded input (hold a modifier, press, release) for this driver."""
    from .pwdriver import PlaywrightActionChains

    return PlaywrightActionChains(driver)


def Select(element):
    """A <select> helper: pick by label, value or index."""
    from .pwdriver import PlaywrightSelect

    return PlaywrightSelect(element)


# --------------------------------------------------------------------------- #
# Waits
#
# The polling wait the page layer has always used: call the condition until it
# returns something truthy, treating "not found yet" as "not yet", and raise
# `Timeout` when time runs out. Same defaults as the WebDriver one it replaces:
# a 0.5s poll, and at least one try however short the timeout.
# --------------------------------------------------------------------------- #

POLL_SECONDS = 0.5


class WebDriverWait:
    def __init__(
        self,
        driver: Any,
        timeout: float,
        poll_frequency: float = POLL_SECONDS,
        ignored_exceptions: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        self._driver = driver
        self._timeout = float(timeout)
        self._poll = poll_frequency if poll_frequency > 0 else POLL_SECONDS
        self._ignored = (NoSuchElement,) + tuple(ignored_exceptions or ())

    def until(self, method: Callable[[Any], Any], message: str = "") -> Any:
        end = time.monotonic() + self._timeout
        while True:
            try:
                value = method(self._driver)
                if value:
                    return value
            except self._ignored:
                pass
            if time.monotonic() > end:
                break
            time.sleep(self._poll)
        raise Timeout(message or f"condition not met after {self._timeout}s")


class EC:
    """The element conditions `targeting` waits on."""

    @staticmethod
    def presence_of_element_located(locator: tuple[str, str]):
        def condition(driver):
            return driver.find_element(*locator)

        return condition

    @staticmethod
    def visibility_of_element_located(locator: tuple[str, str]):
        def condition(driver):
            try:
                element = driver.find_element(*locator)
                return element if element.is_displayed() else False
            except StaleElement:
                return False

        return condition

    @staticmethod
    def element_to_be_clickable(locator: tuple[str, str]):
        def condition(driver):
            element = driver.find_element(*locator)
            return element if element.is_displayed() and element.is_enabled() else False

        return condition


__all__ = [
    "ActionChains",
    "BACKSPACE",
    "By",
    "ClickIntercepted",
    "CONTROL",
    "DeadSession",
    "DELETE",
    "EC",
    "Element",
    "ENGINE_ERRORS",
    "EngineError",
    "ENTER",
    "InvalidElementState",
    "KEYS",
    "MODIFIERS",
    "NoAlert",
    "NoSuchElement",
    "NoSuchFrame",
    "NoSuchWindow",
    "NotInteractable",
    "ScriptError",
    "Select",
    "StaleElement",
    "Timeout",
    "UnexpectedAlert",
    "UnexpectedTagName",
    "WebDriverWait",
]
