"""The engine seam: everything the page layer needs from a browser driver.

Nothing above this module names Selenium. `ops/`, `targeting`, `frames`,
`shadow`, `refs` and `messenger` import their exceptions, locator strategies and
key names from here, so swapping the driver underneath is a change to this file
and `browser.py` rather than to thirty call sites.

This is deliberately *not* an abstract interface with a Playwright subclass. It
is the set of names the existing code already uses, re-homed. An interface
invented before the second implementation exists gets the abstraction wrong in
ways only the second implementation reveals; re-homing the names is provably
behaviour-preserving today and leaves the shape of the real seam to be settled
by the port rather than guessed at now.

## What each group is for

**Exceptions.** Every module catches driver failures. Selenium's hierarchy is
re-exported under neutral names so a `except EngineError` survives the swap.
Playwright's `Error` and `TimeoutError` map onto the same two roles.

**Locators.** `By.CSS_SELECTOR` is the string `"css selector"` and Playwright
has no equivalent constant, so these become the seam's own vocabulary. The
values are kept identical to Selenium's for now, which is what makes this step
a rename rather than a behaviour change.

**Keys.** The named keys an agent can send. Selenium spells them as private-use
unicode codepoints, Playwright as names like `"Control"`. `KEYS` and
`MODIFIERS` are the only tables that have to change for that.
"""

from __future__ import annotations

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    InvalidElementStateException,
    InvalidSessionIdException,
    JavascriptException,
    NoAlertPresentException,
    NoSuchElementException,
    NoSuchFrameException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
    UnexpectedTagNameException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import (
    ActionChains as _SeleniumActionChains,
)
from selenium.webdriver.common.keys import Keys as _SeleniumKeys
from selenium.webdriver.remote.webelement import WebElement as _SeleniumElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select as _SeleniumSelect
from selenium.webdriver.support.ui import WebDriverWait

# --------------------------------------------------------------------------- #
# Exceptions
#
# `EngineError` is the root every driver failure inherits from, so a bare
# `except EngineError` keeps meaning "the driver could not do that" after the
# swap. The rest are named for the condition rather than the library.
# --------------------------------------------------------------------------- #

EngineError = WebDriverException
Timeout = TimeoutException
StaleElement = StaleElementReferenceException
NoSuchElement = NoSuchElementException
NotInteractable = ElementNotInteractableException
ClickIntercepted = ElementClickInterceptedException
InvalidElementState = InvalidElementStateException
UnexpectedTagName = UnexpectedTagNameException
NoSuchFrame = NoSuchFrameException
NoSuchWindow = NoSuchWindowException
NoAlert = NoAlertPresentException
UnexpectedAlert = UnexpectedAlertPresentException
DeadSession = InvalidSessionIdException
ScriptError = JavascriptException

# The type a resolved element has. Named so annotations across the page layer
# stop reading `WebElement`, which will not be true after the port.
Element = _SeleniumElement

# Every exception above, for the `except` clauses that mean "anything the driver
# can raise" and must not silently stop catching something after the swap.
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
    """Locator strategies.

    The values match Selenium's wire strings exactly, so this class is a rename
    and nothing behaves differently for having gone through it. Playwright takes
    selectors as prefixed strings (`css=`, `xpath=`) and will translate at the
    driver boundary rather than here.
    """

    CSS = "css selector"
    XPATH = "xpath"
    TAG = "tag name"


# --------------------------------------------------------------------------- #
# Keys
#
# The table is the seam. Callers ask for `key("ctrl")` and never see how the
# driver spells it.
# --------------------------------------------------------------------------- #

# Derived from the driver's own key class rather than hand-written, which is
# what `ops.interact` already did and therefore what the accepted spellings
# already are. Writing the table out by hand here looked tidier and was wrong
# twice over: it dropped the keys nobody thinks to list (f1-f12, numpad0-9,
# semicolon, separator, ...), and `.lower()` on `ARROW_DOWN` yields `arrow_down`
# with the underscore kept -- so a hand-written "arrowdown" would have started
# accepting a spelling that never worked and stopped accepting the one that did.
#
# The port has to replace this with an explicit map, because Playwright spells
# keys as names ("Control", "ArrowDown") rather than private-use codepoints.
# That map must be generated from this dict and diffed against it, not typed
# out -- the same trap is waiting there.
KEYS: dict[str, str] = {
    name.lower(): getattr(_SeleniumKeys, name)
    for name in dir(_SeleniumKeys)
    if name.isupper() and not name.startswith("_")
}

# Modifier names accepted inside a chord like "ctrl+v" or "shift+enter". A
# strict subset of KEYS by intent: these are the only ones that may appear
# before the '+', and the error message lists them.
MODIFIERS: dict[str, str] = {
    "alt": _SeleniumKeys.ALT,
    "cmd": _SeleniumKeys.META,
    "command": _SeleniumKeys.META,
    "control": _SeleniumKeys.CONTROL,
    "ctrl": _SeleniumKeys.CONTROL,
    "meta": _SeleniumKeys.META,
    "option": _SeleniumKeys.ALT,
    "shift": _SeleniumKeys.SHIFT,
    "windows": _SeleniumKeys.META,
}

# Individual keys named at their use sites rather than looked up by string.
BACKSPACE = _SeleniumKeys.BACKSPACE
CONTROL = _SeleniumKeys.CONTROL
DELETE = _SeleniumKeys.DELETE
ENTER = _SeleniumKeys.ENTER


def ActionChains(driver):
    """Selenium's ActionChains, or the Playwright equivalent for a Playwright
    driver. A function rather than a class so `ActionChains(session.driver)`
    reads and behaves identically on both engines and no call site has to know
    which one it is on."""
    if driver.__class__.__name__ == "PlaywrightDriver":
        from .pwdriver import PlaywrightActionChains

        return PlaywrightActionChains(driver)
    return _SeleniumActionChains(driver)


def Select(element):
    """As above, dispatched on the element rather than the driver, because that
    is what Selenium's Select takes."""
    if element.__class__.__name__ == "PlaywrightElement":
        from .pwdriver import PlaywrightSelect

        return PlaywrightSelect(element)
    return _SeleniumSelect(element)


# --------------------------------------------------------------------------- #
# The four that are not renames
#
# Everything above this line is a name with an identical replacement waiting on
# the other side. These four are Selenium *mechanisms* with no direct Playwright
# analogue, and re-exporting them here is not pretending otherwise -- it is so
# that this file is the complete inventory of what the port has to replace,
# rather than that inventory being spread across `interact`, `targeting` and
# `messenger` where it is easy to miss one.
#
#   ActionChains   -> Playwright drives modifiers through `page.keyboard.down`
#                     / `up` and per-action `modifiers=[...]`. The chord builder
#                     in `ops.interact` is the only caller that needs the
#                     sequencing; `messenger` uses it for select-all-and-delete.
#   Select         -> `locator.select_option()`, which takes label/value/index
#                     directly and needs no wrapper object.
#   WebDriverWait  -> mostly *deleted*: Playwright locators auto-wait, which is
#     + EC           what makes `_CONDITIONS` and the scroll-then-check dance in
#                     `targeting._resolve_one` unnecessary rather than portable.
#
# The `WebDriverWait(..).until(lambda d: ...)` form in `targeting` that waits on
# a match *count* is the one with no locator equivalent and will need
# `expect(locator).to_have_count()` or an explicit poll.
# --------------------------------------------------------------------------- #

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
