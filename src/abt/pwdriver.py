"""A WebDriver-shaped facade over Playwright.

The page layer asks a driver for twelve things and an element for eight. This
implements exactly those, backed by Playwright, so `ops/`, `targeting`,
`frames`, `shadow`, `refs` and `messenger` run unchanged and the existing suite
is the proof. Nothing above `browser.py` learns which engine is underneath --
that is the whole constraint this file exists to satisfy.

## Why a facade rather than a rewrite

The obvious port rewrites the page layer onto locators and deletes the ambient
frame state. That is the better *end* state and it is the wrong *first* step:
it changes the engine and the calling convention at once, so a failing test
cannot tell you which one broke. Emulating WebDriver's shape first means the
485 tests answer one question only -- does Playwright do what Selenium did --
and the calling convention is free to change afterwards, against a suite that
is already green on the new engine.

So the ambient `switch_to` state is deliberately reproduced here, including its
stickiness. Removing it is phase 4, and is what unlocks same-profile
parallelism in the profile-sessions design.

## Thread affinity

A sync Playwright object may only be driven from the thread that created it,
and `server.py` runs commands through `run_in_threadpool`, which hands out
arbitrary pool threads. Every call is therefore marshalled onto one owner
thread -- a `ThreadPoolExecutor(max_workers=1)` that also *creates* the
Playwright objects, so ownership and execution are the same thread by
construction.

Reentrancy is the trap: a marshalled call that marshals again would deadlock on
the single worker. `_call` checks whether it is already on the owner thread and
runs inline if so, which makes nesting safe rather than forbidden.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from .engine import (
    ClickIntercepted,
    DeadSession,
    EngineError,
    NoAlert,
    NoSuchElement,
    NoSuchFrame,
    NoSuchWindow,
    NotInteractable,
    ScriptError,
    StaleElement,
    Timeout,
)
from .errors import OpError

# `execute_script` takes a statement body using `arguments[0..n]` with a
# top-level `return`; `evaluate` takes a function. Calling a real function via
# `.apply` gives the body a genuine `arguments` object and a legal `return`, so
# every script in the codebase runs unedited. Proven byte-identical against
# Selenium on 11 pages up to 390KB -- see docs/playwright-spike-2026-08-19.md.
WRAP = "(a) => (function(){%s}).apply(null, a)"

# Network entries kept per page. A busy SPA makes hundreds; the tail is what
# anyone asks for, and `read_network` already returns the last N.
MAX_NETWORK_ENTRIES = 500

# Whether a script's result has any DOM node in it, answered in the page.
#
# This exists because `json_value()` does NOT fail on nodes -- it silently
# returns the string "ref: <Node>" for each one. Catching an exception around
# it, which is the obvious implementation and was the first one here, therefore
# never fires: `_ACTIONABLE_ELEMENTS_JS` came back as a list of strings, those
# strings were stored as refs, and the failure surfaced two calls later as
# `'str' object has no attribute 'is_enabled'` or, once handed back to a
# script, `e.cloneNode is not a function`. Asking first is the only reliable
# order.
#
# Bounded rather than exhaustive: nodes appear at the top level or in a flat
# array in every script here, and an unbounded walk would traverse the whole
# 8000-line snapshot on the hot path to answer a question about its shape.
_HAS_NODE_JS = """(v) => {
  const look = (x, depth) => {
    if (x === null || typeof x !== 'object' || depth > 2) { return false; }
    if (x instanceof Node) { return true; }
    if (Array.isArray(x)) { return x.some((y) => look(y, depth + 1)); }
    return Object.values(x).some((y) => look(y, depth + 1));
  };
  return look(v, 0);
}"""

# Rendered text with open shadow roots included. See PlaywrightElement.text
# for why innerText is not enough.
#
# Written without a single backslash on purpose. Every layer between here
# and the page -- Python string literals, the shell heredoc that generated
# this file -- gets a vote on what a backslash means, and one of them turned
# a JS newline escape into a real line break inside a string literal. The
# browser reported it as 'SyntaxError: Invalid or unexpected token', which
# names neither the file nor the cause. fromCharCode has no such ambiguity.
_RENDERED_TEXT_JS = """(root) => {
  const NL = String.fromCharCode(10);
  const TAB = String.fromCharCode(9);
  const out = [];
  const walk = (node) => {
    if (node.nodeType === 3) { out.push(node.textContent); return; }
    if (node.nodeType !== 1) { return; }
    const tag = node.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEMPLATE') { return; }
    const style = node.ownerDocument.defaultView.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') { return; }
    if (node.shadowRoot) { node.shadowRoot.childNodes.forEach(walk); }
    node.childNodes.forEach(walk);
    if (style.display !== 'inline') { out.push(NL); }
  };
  walk(root);
  let text = out.join('').split(TAB).join(' ');
  text = text.replace(new RegExp('  +', 'g'), ' ');
  text = text.split(' ' + NL).join(NL).split(NL + ' ').join(NL);
  text = text.replace(new RegExp(NL + '{3,}', 'g'), NL + NL);
  return text.trim();
}"""

# Focus an element and put the caret after any existing content, which is
# where Selenium's send_keys starts from. Covers form controls and
# contenteditable, since the composer in `messenger` is the latter.
_CARET_TO_END_JS = """(e) => {
  e.focus();
  if (typeof e.setSelectionRange === 'function' && typeof e.value === 'string') {
    try { e.setSelectionRange(e.value.length, e.value.length); } catch (err) {}
    return;
  }
  if (e.isContentEditable) {
    const range = e.ownerDocument.createRange();
    range.selectNodeContents(e);
    range.collapse(false);
    const sel = e.ownerDocument.defaultView.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }
}"""

# Selenium locator strategies to Playwright selector syntax. `By` keeps
# Selenium's wire strings so that `engine.By` stays a rename; the translation
# to Playwright's prefixed form happens here, at the driver boundary, exactly
# as engine.py's docstring says it would.
#
# `:light` is load-bearing, not decoration. Playwright's default `css=` engine
# pierces open shadow roots; `document.querySelectorAll`, and therefore
# Selenium, does not. Measured on one host with a matching button inside and
# out: `css=` returns 2, `css:light=` returns 1, raw querySelectorAll returns 1.
#
# Left piercing, every shadow match would be found twice -- once by the
# ordinary search and again by `shadow.search`, whose whole job is to reach
# what the ordinary search cannot. `resolve_many` de-duplicates against the
# light-DOM set precisely because it assumes the two are disjoint. The suite
# caught it as `assert 2 == 1` six times over.
#
# This is parity, not a preference. Flipping to `css=` and deleting `shadow.py`
# is the phase-4 prize, but it changes observable behaviour -- `shadow: true`
# and the `shadowHosts` count both stop meaning anything -- so it is a product
# decision rather than a refactor, and does not belong in the engine swap.
_SELECTOR = {
    "css selector": "css:light=%s",
    "xpath": "xpath=%s",
    "tag name": "css:light=%s",
}


def translate_launch_failure(exc: BaseException, browser: str) -> OpError | None:
    """A missing browser, said in this toolkit's own vocabulary.

    Playwright reports "Chromium distribution 'chrome' is not found at ...",
    which is true and useless: it does not mention that Edge is supported, and
    it does not say what to install. A developer in a checkout can work that
    out. Someone who installed this from winget cannot.

    Returns None for anything else, so an unrelated launch failure keeps its
    own traceback rather than being relabelled as a missing browser.
    """
    text = str(exc).lower()

    # A profile another Chrome already holds. Chrome does not fail loudly: it
    # hands the URL to the running instance, prints "Opening in existing
    # browser session" and exits 0 -- so a window appears, the launcher's
    # handle dies with the process, and the toolkit reports browser_dead while
    # the user is looking at a browser. The real reason is in Playwright's
    # message, buried in two thousand characters of call log, and the stock
    # browser_dead hint then advises `browser restart`, which cannot help:
    # restarting reuses the same locked profile.
    if "already in use" in text or "opening in existing browser session" in text:
        return OpError(
            "browser_dead",
            "that profile is already open in another Chrome, which took the "
            "window and left this toolkit without a handle to it.",
            hint=(
                "Close every Chrome using this profile and start again, or "
                "run a second browser on its own profile: `abt browser start "
                "--profile <dir>` (or `abt serve --profile <dir>`). "
                "`browser restart` will not help -- it reuses the same locked "
                "profile."
            ),
        )

    if "is not found" not in text and "executable doesn't exist" not in text:
        return None
    other = "edge" if browser == "chrome" else "chrome"
    return OpError(
        "browser_dead",
        f"{browser} is not installed, or not where Playwright looks for it. "
        f"This toolkit drives an existing Google Chrome or Microsoft Edge and "
        f"bundles neither. Install one, run `abt doctor` to check, or pass "
        f"--browser {other}.",
    )


def _translate(by: str, selector: str) -> str:
    form = _SELECTOR.get(by)
    if form is None:
        raise EngineError(f"unsupported locator strategy {by!r}")
    return form % selector


def _as_engine_error(exc: BaseException) -> BaseException:
    """Map a Playwright failure onto the exception the page layer catches.

    The page layer branches on these -- `not_interactable` versus
    `element_not_found` is a different message and a different remedy -- so a
    blanket `EngineError` would collapse distinctions the ops rely on.
    Playwright reports the reason in the message rather than the type, which is
    why this reads strings.
    """
    text = str(exc)
    # Matched case-insensitively. Playwright writes the same condition both
    # ways -- "Element is not visible" in a direct error, "element is not
    # visible" in the retry log that a timeout message embeds -- and a
    # capitalised-only check silently missed the second, which is precisely the
    # form the force-click path has to recognise.
    lowered = text.lower()
    # Order matters. Selenium raises ElementClickIntercepted *immediately* when
    # something covers the target; Playwright retries until its timeout and
    # then reports the interception inside a timeout error. Reading the type
    # first would hand `ops.interact` a Timeout, its `except ClickIntercepted`
    # would not fire, and `force: true` -- whose entire job is to click through
    # an overlay -- would stop working while every other click still passed.
    if "intercepts pointer events" in lowered:
        return ClickIntercepted(text)
    if "not attached" in lowered or "node is detached" in lowered:
        return StaleElement(text)
    # Same trap as interception, and for the same reason: Playwright retries an
    # invisible or disabled element until its timeout and then reports *why*
    # inside the timeout message. Reading the type first turned every
    # not-interactable into a Timeout, so `force: true` on a visually hidden
    # control -- which exists precisely to click one -- never reached its
    # fallback.
    if "not visible" in lowered or "not enabled" in lowered or "not stable" in lowered:
        return NotInteractable(text)
    if isinstance(exc, PlaywrightTimeout):
        return Timeout(str(exc))
    if "target closed" in lowered or "browser closed" in lowered:
        return DeadSession(text)
    if isinstance(exc, PlaywrightError):
        return EngineError(text)
    return exc


class PlaywrightElement:
    """The eight element methods the page layer uses.

    Wraps an `ElementHandle` rather than a `Locator` on purpose: a ref is a
    handle to *the element that was found*, and re-resolving a locator could
    silently answer with a different element after the DOM moved. That is the
    exact failure `refs.py` documents as the reason stale refs are an error.
    """

    __slots__ = ("_handle", "_driver", "_ident")

    def __init__(self, driver: PlaywrightDriver, handle) -> None:
        self._driver = driver
        self._handle = handle
        self._ident: int | None = None

    @property
    def _identity(self) -> int:
        """A number that is the same for every handle onto the same node.

        Playwright hands back a *new* ElementHandle per query, and two handles
        onto one node are neither `==` nor equal-hashing -- confirmed, not
        assumed. Selenium's WebElement compares by an id that is stable per
        node, and the page layer leans on that in two places: `resolve_many`
        de-duplicates a shadow search against the light-DOM results with
        `element in light`, and `refs` compares stored elements.

        Comparing handles directly made that de-duplication a no-op, so every
        shadow match was reported twice. The suite said `assert 2 == 1`.

        The stamp is put on the node itself and cached here, so identity costs
        one round trip per element and only when something actually asks.
        """
        if self._ident is None:
            self._ident = self._call(
                lambda: self._handle.evaluate(
                    "e => { const w = e.ownerDocument.defaultView;"
                    " if (!w.__abtIdSeq) { w.__abtIdSeq = 0; }"
                    " if (!e.__abtId) { e.__abtId = ++w.__abtIdSeq; }"
                    " return e.__abtId; }"
                )
            )
        return self._ident

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, PlaywrightElement)
            and self._identity == other._identity
        )

    def __hash__(self) -> int:
        return hash(self._identity)

    @property
    def raw(self):
        return self._handle

    def _call(self, fn, *a, **kw):
        return self._driver._call(fn, *a, **kw)

    @property
    def tag_name(self) -> str:
        return self._call(
            lambda: self._handle.evaluate("e => e.tagName.toLowerCase()")
        )

    @property
    def text(self) -> str:
        """Selenium's rendered text, which descends open shadow roots.

        `innerText` alone does not: measured on a host with a button inside,
        `document.body.innerText` returned only the light-DOM text and the
        shadow button was missing entirely. Selenium's getText uses the
        rendered-text atom, which walks into open roots, and `get_text` is
        documented as seeing shadow content -- so innerText would have quietly
        dropped whatever a page renders inside a component.

        `textContent` is not the alternative: it would pull in `<script>`
        bodies and every hidden node.
        """
        return self._call(lambda: self._handle.evaluate(_RENDERED_TEXT_JS)) or ""

    @property
    def rect(self) -> dict:
        """Position and size in *document* coordinates, as WebDriver reports.

        `bounding_box()` is viewport-relative; WebDriver's Get Element Rect is
        relative to the document. The sole caller, `_click_at`, converts to
        viewport coordinates itself by subtracting `window.scrollX` -- so a
        viewport-relative rect got the scroll taken off twice and the click
        landed above the element it named. Below the fold, that is far enough
        wrong to hit nothing at all.
        """

        def work():
            box = self._handle.bounding_box()
            if box is None:
                return {"x": 0, "y": 0, "width": 0, "height": 0}
            scroll = self._handle.evaluate(
                "e => { const w = e.ownerDocument.defaultView;"
                " return [w.scrollX, w.scrollY]; }"
            )
            return {
                "x": box["x"] + scroll[0],
                "y": box["y"] + scroll[1],
                "width": box["width"],
                "height": box["height"],
            }

        return self._call(work)

    @property
    def screenshot_as_base64(self) -> str:
        """A PNG of just this element, base64'd.

        A property rather than a method because `ops.read.screenshot` chains it
        straight off `resolve_one(...)` -- which is also why the surface survey
        that built this class missed it.
        """
        return base64.b64encode(
            self._call(lambda: self._handle.screenshot(type="png"))
        ).decode("ascii")

    def is_displayed(self) -> bool:
        try:
            return bool(self._call(lambda: self._handle.is_visible()))
        except Exception:
            return False

    def is_enabled(self) -> bool:
        # `refs.get` calls this purely to decide whether the element is still
        # attached, and expects a stale one to raise rather than answer.
        try:
            return bool(self._call(lambda: self._handle.is_enabled()))
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def get_attribute(self, name: str):
        """Selenium's get_attribute, which is mostly *not* getAttribute.

        The property wins over the markup attribute, and the callers depend on
        it: `get_html` asks for `outerHTML`, `_read_value` asks for
        `textContent`, and neither is an attribute at all -- `getAttribute`
        returns null for both. `value` is the same story with worse
        consequences, since the markup attribute holds the default while the
        property holds what was typed, so attribute-first silently reported an
        empty string after every successful `input`.

        Attributes still answer for the names with no property behind them
        (`class` is `className`, `contenteditable` is `contentEditable`), which
        is what the fallback is for. Booleans report Selenium's "true"/None
        rather than JavaScript's true/false.
        """

        def work():
            return self._handle.evaluate(
                "(e, n) => {"
                " const p = e[n];"
                " if (p !== undefined && p !== null &&"
                "     (typeof p === 'string' || typeof p === 'number' ||"
                "      typeof p === 'boolean')) {"
                "   return typeof p === 'boolean' ? (p ? 'true' : null) : String(p);"
                " }"
                " return e.getAttribute(n);"
                "}",
                name,
            )

        return self._call(work)

    def find_elements(self, by: str, selector: str) -> list:
        """Search within this element, as Selenium's element-scoped find does.

        `messenger` narrows to one thread row and then searches inside it, so
        the driver-level search is not a substitute -- it would match rows the
        caller has already excluded.
        """
        target = _translate(by, selector)

        def work():
            return [
                PlaywrightElement(self._driver, h)
                for h in self._handle.query_selector_all(target)
            ]

        try:
            return self._call(work)
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def find_element(self, by: str, selector: str):
        found = self.find_elements(by, selector)
        if not found:
            raise NoSuchElement(f"nothing inside this element matched {selector!r}")
        return found[0]

    def get_dom_attribute(self, name: str):
        """The markup attribute only, with no property fallback.

        The counterpart to `get_attribute`, and the distinction is the whole
        point of having both: Selenium's Select reads `multiple` this way so a
        property shadowing the attribute cannot change the answer.
        """
        return self._call(lambda: self._handle.get_attribute(name))

    def click(self) -> None:
        try:
            self._call(lambda: self._handle.click())
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def clear(self) -> None:
        try:
            self._call(lambda: self._handle.fill(""))
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def send_keys(self, *values) -> None:
        """Type into the element, or hand a file input its paths.

        Selenium overloads send_keys for uploads -- `messenger._attach` and the
        file-input branch of `input` both rely on it -- so the overload has to
        survive here or those paths break in a way no type checker sees.
        """
        text = "".join(str(v) for v in values)
        try:
            if self._call(
                lambda: self._handle.evaluate(
                    "e => e.tagName === 'INPUT' && e.type === 'file'"
                )
            ):
                paths = [p for p in text.split("\n") if p]
                self._call(lambda: self._handle.set_input_files(paths))
                return
            # Selenium appends: send_keys puts the caret at the end of the
            # existing value first. Playwright's type() inserts at whatever
            # position the caret is at, which on a freshly focused field is 0
            # -- so appending "more" to "preset" produced "morepreset".
            self._call(lambda: self._handle.evaluate(_CARET_TO_END_JS))

            # Selenium takes a named key here as readily as literal text --
            # `press` calls send_keys(Keys.ENTER) directly on the element. A
            # named key is a private-use codepoint, so typing it inserts an
            # invisible character and fires no key handler; the test for this
            # showed up as an empty field rather than as a wrong keystroke.
            if any(char in _KEY_NAMES for char in text):
                for chunk, is_key in _split_keys(text):
                    if is_key:
                        self._call(lambda c=chunk: self._handle.press(_KEY_NAMES[c]))
                    else:
                        self._call(lambda c=chunk: self._handle.type(c))
                return
            self._call(lambda: self._handle.type(text))
        except Exception as exc:
            raise _as_engine_error(exc) from exc


class _SwitchTo:
    """WebDriver's ambient frame and window state, reproduced.

    Playwright has none of this -- a `Frame` is addressed, not switched into --
    so the state lives here and every lookup routes through `_context()`. This
    is emulation of a thing worth deleting, kept only so the suite compares one
    variable at a time.
    """

    def __init__(self, driver: PlaywrightDriver) -> None:
        self._driver = driver

    def default_content(self) -> None:
        self._driver._frame = None

    def frame(self, target) -> None:
        driver = self._driver
        try:
            if isinstance(target, PlaywrightElement):
                frame = driver._call(lambda: target.raw.content_frame())
            else:
                frame = None
            if frame is None:
                raise NoSuchFrame(f"cannot switch into {target!r}")
            driver._frame = frame
        except NoSuchFrame:
            raise
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def window(self, handle: str) -> None:
        self._driver._activate(handle)

    def new_window(self, kind: str = "tab") -> None:
        """Open a page and make it current, as WebDriver's does.

        WebDriver distinguishes "tab" from "window"; Playwright's persistent
        context has one notion of page, so the argument is accepted and
        ignored rather than refused -- `browser.new_tab` always passes "tab".
        """
        self._driver._open_page()

    @property
    def alert(self):
        raise NoAlert("no alert open")


class PlaywrightDriver:
    """The twelve driver attributes the page layer uses."""

    def __init__(
        self,
        config,
        console_source: str | None = None,
        action_timeout: float = 5.0,
    ) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abt-pw")
        self._owner: int | None = None
        self._frame = None
        self._console_source = console_source
        self._action_timeout = action_timeout
        self._closed = False
        self._cdp_attached = False
        self._browser = None
        self._cdp: dict[int, object] = {}
        self._net: dict[int, list[dict]] = {}
        self._net_started: dict[int, float] = {}
        # A failure that follows a response annotates that row rather than
        # adding a second one. Matched on url+method, not on the Request
        # object: Playwright hands out a *different* wrapper per event, so
        # keying on identity silently never matched and every ORB-blocked or
        # CORS-blocked request was logged twice -- once with its real status,
        # once with None, the useless row last. Same trap as element handles.
        self._call(self._boot, config)

    # -- thread affinity ---------------------------------------------------
    def _call(self, fn, *a, **kw):
        """Run on the owner thread, or inline when already there.

        The inline branch is what makes nesting safe: a single worker cannot
        service a call submitted from inside itself, so without this any facade
        method that used another would deadlock rather than fail.
        """
        if self._owner is not None and threading.get_ident() == self._owner:
            return fn(*a, **kw)
        return self._pool.submit(self._run, fn, *a, **kw).result()

    def _run(self, fn, *a, **kw):
        self._owner = threading.get_ident()
        return fn(*a, **kw)

    def _boot(self, config) -> None:
        self._pw = sync_playwright().start()
        launcher = self._pw.chromium
        cdp_url = os.environ.get("ABT_CDP_URL")
        if cdp_url:
            # Attach mode: drive a browser this process did not launch,
            # addressed by its CDP endpoint. The point of the mode is sharing --
            # a harness (BrowserGym) owns the launch and the scoring, this
            # toolkit drives the pages, and both must sit on the same browser.
            # Quitting therefore means disconnecting; closing the context or
            # the browser would take the harness down with it (see quit()).
            self._cdp_attached = True
            try:
                self._browser = launcher.connect_over_cdp(cdp_url)
                contexts = self._browser.contexts
                self._context = (
                    contexts[0] if contexts else self._browser.new_context()
                )
            except Exception as exc:
                raise OpError(
                    "browser_dead", f"could not attach to {cdp_url}: {exc}"
                ) from exc
        else:
            self._cdp_attached = False
            self._browser = None
            args = ["--no-first-run", "--no-default-browser-check"]
            try:
                self._context = launcher.launch_persistent_context(
                    user_data_dir=str(config.profile),
                    channel="msedge" if config.browser == "edge" else "chrome",
                    headless=config.headless,
                    viewport=None,
                    args=args,
                )
            except Exception as exc:
                translated = translate_launch_failure(exc, config.browser)
                if translated is None:
                    raise
                raise translated from exc
        if self._console_source:
            # Must exist before the document does, and survive navigation --
            # the same reason the Selenium path uses CDP
            # Page.addScriptToEvaluateOnNewDocument rather than running it once.
            self._context.add_init_script(self._console_source)
        # Playwright's 30s default is an auto-waiting budget; Selenium's raw
        # element calls do not wait at all, and the explicit waits in
        # `targeting` are what the timeouts are supposed to come from. Matching
        # the session's action timeout keeps the failure latency the ops were
        # written against.
        self._context.set_default_timeout(self._action_timeout * 1000)
        self._pages = list(self._context.pages) or [self._context.new_page()]
        self._active = 0
        # Every page, including ones the site opens itself -- a target=_blank
        # popup makes requests too, and it is usually the interesting one.
        self._context.on("page", self._watch)
        for page in self._pages:
            self._watch(page)

    # -- pages -------------------------------------------------------------
    @property
    def _page(self):
        if self._closed:
            raise DeadSession("browser is closed")
        try:
            return self._pages[self._active]
        except IndexError as exc:
            raise NoSuchWindow("no active page") from exc

    def _target(self):
        """Whatever `find`/`evaluate` should run against right now."""
        return self._frame if self._frame is not None else self._page

    # -- network ------------------------------------------------------------
    #
    # The first capability this engine has that the other cannot reach.
    #
    # Resource Timing, which is what `read_network` used on both engines until
    # now, is a *page* API: a cross-origin response without Timing-Allow-Origin
    # reports `status: null` and `opaque: true`, because the browser genuinely
    # will not tell the page. Subscribing to the browser's own events has no
    # such limit -- the status is known for every response, cross-origin or not,
    # and a request that never got a response at all (DNS failure, blocked,
    # aborted) is reported instead of being invisible.
    #
    # Two things it gives up, stated rather than hidden:
    #
    #   `bytes` is best effort. Resource Timing knows `encodedBodySize`
    #   exactly; a response event knows only what the headers say, and
    #   content-length is absent on anything chunked or compressed -- measured,
    #   not assumed. Reading the body to find out costs a round trip per
    #   request and can fail outright on a redirect or a stream.
    #
    #   `ms` is measured here rather than read. `request.timing.responseEnd` is
    #   -1 at the moment the response arrives, because the timing is not
    #   complete yet, so the elapsed time is taken between the request and
    #   response events instead.
    #
    # Scoped per page and cleared when the page navigates, which is what
    # Resource Timing did implicitly. Keeping everything across navigations
    # would quietly change what `read_network` means.

    def _watch(self, page) -> None:
        if id(page) in self._net:
            return
        self._net[id(page)] = []

        def on_request(request) -> None:
            self._net_started[id(request)] = time.monotonic()

        def on_response(response) -> None:
            request = response.request
            started = self._net_started.pop(id(request), None)
            entry = {
                "url": response.url,
                "kind": request.resource_type,
                "method": request.method,
                "status": response.status,
                "ms": _elapsed_ms(started),
                "bytes": _content_length(response),
            }
            self._push(page, entry)

        def on_failed(request) -> None:
            started = self._net_started.pop(id(request), None)
            reason = (request.failure or "request failed")[:200]

            # One request, one row. A cross-origin response the server
            # answered and the browser then blocked fires *both* events -- the
            # real status, then the failure -- and logging each reports one
            # request twice, burying the informative row behind the useless
            # one. Annotate what is already there: the status the server
            # returned, plus why the page never saw it.
            existing = self._recent(page, request.url, request.method)
            if existing is not None:
                existing["error"] = reason
                return

            # No response at all: refused, DNS failure, aborted. Status stays
            # None, which `failures_only` already treats as a failure, so it
            # surfaces where a caller looking for trouble is already looking.
            self._push(
                page,
                {
                    "url": request.url,
                    "kind": request.resource_type,
                    "method": request.method,
                    "status": None,
                    "ms": _elapsed_ms(started),
                    "bytes": None,
                    "error": reason,
                },
            )

        def on_navigated(frame) -> None:
            if frame == page.main_frame:
                self._net[id(page)] = []
                self._net_started.clear()

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_failed)
        page.on("framenavigated", on_navigated)

    def _recent(self, page, url: str, method: str) -> dict | None:
        """The newest row for this request that has not already failed.

        Bounded, because a page that requests one URL hundreds of times should
        not make each failure walk the whole log.
        """
        log = self._net.get(id(page), [])
        for entry in reversed(log[-50:]):
            if (
                entry.get("url") == url
                and entry.get("method") == method
                and "error" not in entry
            ):
                return entry
        return None

    def _push(self, page, entry: dict) -> None:
        log = self._net.setdefault(id(page), [])
        log.append(entry)
        # An unattended agent on a busy SPA would otherwise grow this without
        # bound. The tail is what anyone asks for.
        if len(log) > MAX_NETWORK_ENTRIES:
            del log[: len(log) - MAX_NETWORK_ENTRIES]

    def network_log(self) -> list[dict]:
        """Requests this page has made since it last navigated.

        Presence of this method is what `read_network` probes to decide whether
        the engine can answer natively -- the Selenium driver has no such
        method and falls back to Resource Timing.
        """
        return list(self._call(lambda: self._net.get(id(self._page), [])))

    def _open_page(self):
        def work():
            page = self._context.new_page()
            self._watch(page)
            self._pages.append(page)
            self._active = len(self._pages) - 1
            self._frame = None
            return page

        return self._call(work)

    def _activate(self, handle: str) -> None:
        for index, page in enumerate(self._pages):
            if _handle_of(page) == handle:
                self._active = index
                self._frame = None
                self._call(lambda: page.bring_to_front())
                return
        raise NoSuchWindow(f"no such window handle {handle!r}")

    @property
    def window_handles(self) -> list[str]:
        def work():
            self._pages = [p for p in self._pages if not p.is_closed()]
            for page in self._context.pages:
                if page not in self._pages:
                    self._pages.append(page)
            return [_handle_of(p) for p in self._pages]

        return self._call(work)

    @property
    def current_window_handle(self) -> str:
        return self._call(lambda: _handle_of(self._page))

    # -- navigation --------------------------------------------------------
    def get(self, url: str) -> None:
        def work():
            self._frame = None
            self._page.goto(url, wait_until="load")

        try:
            self._call(work)
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    @property
    def current_url(self) -> str:
        return self._call(lambda: self._page.url)

    @property
    def title(self) -> str:
        return self._call(lambda: self._page.title())

    @property
    def page_source(self) -> str:
        return self._call(lambda: self._page.content())

    def back(self) -> None:
        self._call(lambda: self._page.go_back())

    def forward(self) -> None:
        self._call(lambda: self._page.go_forward())

    def refresh(self) -> None:
        self._call(lambda: self._page.reload())

    def close(self) -> None:
        def work():
            page = self._page
            page.close()
            self._pages = [p for p in self._pages if not p.is_closed()]
            self._active = max(0, min(self._active, len(self._pages) - 1))
            self._frame = None

        self._call(work)

    def quit(self) -> None:
        def work():
            self._closed = True
            try:
                # Attached sessions only drop the connection: the browser was
                # launched by someone else, and its pages are theirs. Closing
                # the adopted context would close every harness page with it.
                if not getattr(self, "_cdp_attached", False):
                    self._context.close()
            finally:
                self._pw.stop()

        try:
            self._call(work)
        finally:
            self._pool.shutdown(wait=False)

    # -- finding -----------------------------------------------------------
    def find_elements(self, by: str, selector: str) -> list[PlaywrightElement]:
        target = _translate(by, selector)

        def work():
            return [
                PlaywrightElement(self, h)
                for h in self._target().query_selector_all(target)
            ]

        try:
            return self._call(work)
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def find_element(self, by: str, selector: str) -> PlaywrightElement:
        found = self.find_elements(by, selector)
        if not found:
            raise NoSuchElement(f"nothing matched {selector!r}")
        return found[0]

    def implicitly_wait(self, seconds: float) -> None:
        # Selenium's implicit wait is set to 0 at startup precisely so it never
        # interferes with the explicit waits. Playwright has no equivalent
        # ambient wait, so honouring "0" means doing nothing.
        if seconds:
            raise EngineError("implicit waits are not supported; use an explicit wait")

    # -- scripting ---------------------------------------------------------
    def execute_script(self, script: str, *args) -> Any:
        """Run a Selenium-style script body and return JSON or elements.

        Selenium returns WebElements from a script transparently; Playwright's
        `evaluate` refuses to serialise a node at all. So everything goes
        through `evaluate_handle` and is converted on the way out -- which is
        what lets `_ACTIONABLE_ELEMENTS_JS` keep handing back the elements that
        become refs.
        """
        payload = [_unwrap(a) for a in args]

        def work():
            handle = self._target().evaluate_handle(WRAP % script, payload)
            return self._convert(handle)

        try:
            return self._call(work)
        except Exception as exc:
            raise _as_script_error(exc) from exc

    def _convert(self, handle) -> Any:
        """A JSHandle to a Python value, wrapping any element it contains."""
        element = handle.as_element()
        if element is not None:
            return PlaywrightElement(self, element)
        if not handle.evaluate(_HAS_NODE_JS):
            # The fast path, and the one the snapshot takes: pure JSON in one
            # hop rather than a round trip per key.
            return handle.json_value()
        converted = {
            name: self._convert(child)
            for name, child in handle.get_properties().items()
        }
        if converted and all(name.isdigit() for name in converted):
            return [converted[k] for k in sorted(converted, key=int)]
        return converted

    def execute_cdp_cmd(self, name: str, params: dict) -> dict:
        """CDP, with the one call that must not go over a temporary session.

        `Page.addScriptToEvaluateOnNewDocument` registers against the *session*,
        so opening a CDP session, registering, and detaching -- which is the
        obvious way to make a one-shot CDP call -- unregisters the script on the
        way out. Console and network capture both come in through here, and both
        silently captured nothing: thirteen tests failed as empty console
        buffers and settle checks that never saw the network probe.

        Playwright has a first-class equivalent that is context-wide and
        survives navigation, so this is not a workaround. It is also the thing
        that makes `browser._captured` per-tab arming unnecessary on this
        engine -- the bug recorded as known-issues #2 cannot happen here --
        though that cleanup belongs to phase 4, not to the swap.
        """
        if name == "Page.addScriptToEvaluateOnNewDocument":
            source = params.get("source", "")

            def register():
                self._context.add_init_script(source)
                return {"identifier": str(len(source))}

            try:
                return self._call(register)
            except Exception as exc:
                raise _as_engine_error(exc) from exc

        def work():
            session = self._cdp_session()
            return session.send(name, params)

        try:
            return self._call(work)
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    def _cdp_session(self):
        """One CDP session per page, kept for the page's life.

        Cached because anything registered on a session dies with it, and
        because attaching per call is a round trip that buys nothing.
        """
        page = self._page
        cached = self._cdp.get(id(page))
        if cached is None:
            cached = self._context.new_cdp_session(page)
            self._cdp[id(page)] = cached
        return cached

    # -- screenshots -------------------------------------------------------
    def get_screenshot_as_base64(self) -> str:
        return base64.b64encode(self.get_screenshot_as_png()).decode("ascii")

    def get_screenshot_as_png(self) -> bytes:
        try:
            return self._call(lambda: self._page.screenshot(type="png"))
        except Exception as exc:
            raise _as_engine_error(exc) from exc

    # -- frames / windows --------------------------------------------------
    @property
    def switch_to(self) -> _SwitchTo:
        return _SwitchTo(self)


def _as_script_error(exc: BaseException) -> BaseException:
    """A thrown script is `ScriptError`; a dead page is not.

    `ops.control.run_js` reports the two differently -- one is the user's
    script being wrong, the other is the browser being gone -- so collapsing
    them would make a broken session look like a broken script.
    """
    mapped = _as_engine_error(exc)
    if isinstance(mapped, EngineError) and type(mapped) is EngineError:
        return ScriptError(str(exc))
    return mapped


def _elapsed_ms(started: float | None) -> int | None:
    if started is None:
        return None
    return int((time.monotonic() - started) * 1000)


def _content_length(response) -> int | None:
    """Bytes, when the headers admit to a number.

    Absent on anything chunked or compressed, which is most of the modern web,
    so this is genuinely often None rather than nominally so.
    """
    try:
        raw = response.header_value("content-length")
    except Exception:
        return None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _split_keys(text: str):
    """Split typed text into (chunk, is_named_key) runs, preserving order.

    Selenium lets literal text and named keys arrive in one call, so
    "hello" + ENTER has to type five characters and then press a key.
    """
    out: list[tuple[str, bool]] = []
    buffer: list[str] = []
    for char in text:
        if char in _KEY_NAMES:
            if buffer:
                out.append(("".join(buffer), False))
                buffer = []
            out.append((char, True))
        else:
            buffer.append(char)
    if buffer:
        out.append(("".join(buffer), False))
    return out


def _unwrap(value):
    if isinstance(value, PlaywrightElement):
        return value.raw
    if isinstance(value, (list, tuple)):
        return [_unwrap(v) for v in value]
    return value


def _handle_of(page) -> str:
    """A stable per-page identity string.

    `browser.py` keys its tab registry on these and never reissues one, so the
    value has to stay the same for a page's whole life. Python's id() does
    that, and the guid is not exposed by the sync API.
    """
    return f"page-{id(page):x}"


# --------------------------------------------------------------------------- #
# The pieces engine.py flagged as "not renames"
#
# ActionChains and Select are Selenium classes that type-check their arguments
# and drive a Selenium driver, so they cannot be handed a PlaywrightElement --
# the suite said so plainly: "move_to requires a WebElement". These are the
# Playwright-native equivalents. `engine.ActionChains` and `engine.Select`
# dispatch to them on type, which is why not one call site in `ops.interact` or
# `messenger` had to change.
# --------------------------------------------------------------------------- #


def _playwright_key(value: str) -> str:
    """A Selenium key codepoint as the name Playwright expects.

    Selenium spells keys as private-use unicode characters, Playwright as names
    like "Control" and "ArrowDown". The map is derived from `engine.KEYS` --
    the same rule that file warns about: generate it from the table and never
    type it out, or the spellings drift apart silently.
    """
    return _KEY_NAMES.get(value, value)


def _build_key_names() -> dict:
    """Reverse `engine.KEYS`, keeping the canonical name for each codepoint.

    Selenium gives several names to one key -- CONTROL and LEFT_CONTROL share a
    codepoint, so do ARROW_DOWN and DOWN -- so the reverse map has collisions
    and whichever wins is what Playwright gets asked for. Last-wins produced
    "LeftControl" and "Down", neither of which Playwright accepts, and the
    failure would have been a chord that silently pressed nothing.

    Alphabetical order nearly works and is not trustworthy: it picks `control`
    over `left_control` and `arrow_down` over `down`, but `left_shift` sorts
    before `shift` and so wins, and Playwright rejected "LeftShift" outright.
    Where the derived name is ambiguous the canonical one is stated, and the
    derivation handles everything else -- 60 keys, of which only these collide.
    """
    from .engine import KEYS

    names: dict[str, str] = {}
    for name, codepoint in KEYS.items():
        names.setdefault(
            codepoint, "".join(part.capitalize() for part in name.split("_"))
        )
    for canonical in ("shift", "control", "alt", "meta", "enter"):
        codepoint = KEYS.get(canonical)
        if codepoint is not None:
            names[codepoint] = canonical.capitalize()
    return names


_KEY_NAMES = _build_key_names()


class PlaywrightSelect:
    """Selenium's Select, for a <select> driven by Playwright."""

    def __init__(self, element) -> None:
        from .engine import UnexpectedTagName

        if element.tag_name != "select":
            raise UnexpectedTagName(
                f"Select only works on <select> elements, not <{element.tag_name}>"
            )
        self._element = element
        self._driver = element._driver

    def _select(self, **kw) -> None:
        # Playwright returns the list of values it actually matched, and an
        # empty list means nothing matched. It does not raise, so a bad option
        # would otherwise look like a successful no-op -- and `ops.interact`
        # reports "no matching option" off an exception.
        from .engine import NoSuchElement

        matched = self._driver._call(lambda: self._element.raw.select_option(**kw))
        if not matched:
            raise NoSuchElement(f"no option matched {kw}")

    def select_by_visible_text(self, text: str) -> None:
        self._select(label=text)

    def select_by_value(self, value: str) -> None:
        self._select(value=value)

    def select_by_index(self, index: int) -> None:
        self._select(index=index)

    @property
    def first_selected_option(self):
        handle = self._driver._call(
            lambda: self._element.raw.evaluate_handle(
                "e => e.selectedOptions[0] || e.options[e.selectedIndex]"
            )
        )
        element = handle.as_element()
        if element is None:
            from .engine import NoSuchElement

            raise NoSuchElement("this select has no selected option")
        return PlaywrightElement(self._driver, element)


class _PointerActions:
    """`chain.w3c_actions.pointer_action`, which `_click_at` reaches for."""

    def __init__(self, chain: PlaywrightActionChains) -> None:
        self._chain = chain

    def move_to_location(self, x: float, y: float):
        self._chain._steps.append(lambda page: page.mouse.move(x, y))
        return self

    def click(self):
        self._chain._steps.append(lambda page: page.mouse.down())
        self._chain._steps.append(lambda page: page.mouse.up())
        return self


class _W3CActions:
    def __init__(self, chain: PlaywrightActionChains) -> None:
        self.pointer_action = _PointerActions(chain)


class PlaywrightActionChains:
    """Selenium's ActionChains over Playwright's keyboard and mouse.

    Records steps and runs them on `perform()`, exactly as Selenium does. That
    matters for the chord path in `press`: the modifier must still be held when
    the main key is sent, which only holds if nothing executes early.
    """

    def __init__(self, driver: PlaywrightDriver) -> None:
        self._driver = driver
        self._steps: list = []
        # Whether Shift is held at this point in the recording. Tracked while
        # the chain is built, because that is when the order is known.
        self._shift = False
        self.w3c_actions = _W3CActions(self)

    def click(self, element=None):
        if element is None:
            self._steps.append(lambda page: page.mouse.down())
            self._steps.append(lambda page: page.mouse.up())
        else:
            self._steps.append(lambda page: element.raw.click())
        return self

    def move_to_element(self, element):
        self._steps.append(lambda page: element.raw.hover())
        return self

    def key_down(self, key: str):
        name = _playwright_key(key)
        if name == "Shift":
            self._shift = True
        self._steps.append(lambda page, n=name: page.keyboard.down(n))
        return self

    def key_up(self, key: str):
        name = _playwright_key(key)
        if name == "Shift":
            self._shift = False
        self._steps.append(lambda page, n=name: page.keyboard.up(n))
        return self

    def send_keys(self, *values):
        for value in values:
            text = str(value)
            named = _KEY_NAMES.get(text)
            if named is not None:
                # A named key is pressed, not typed: `keyboard.type` would
                # insert the private-use character as literal text.
                self._steps.append(
                    lambda page, name=named: page.keyboard.press(name)
                )
            elif len(text) == 1:
                # A held Shift does not shift the character. Measured, because
                # Playwright's own documentation says the opposite ("Holding
                # down Shift will type the text in upper case"):
                #
                #   down(Shift) + press("a")  -> "a"
                #   down(Shift) + type("a")   -> "a"
                #   press("Shift+a")          -> "a"
                #   down(Shift) + press("A")  -> "A"
                #
                # Selenium's chord sends the modifier and the plain key and the
                # browser does the shifting, so `shift+a` must arrive as "A".
                # Only the shifted character itself gets there.
                #
                # Letters only: shifted punctuation is layout-dependent and
                # `_resolve_press_keys` has never accepted a chord like
                # `shift+1` meaning "!", so there is nothing to preserve.
                char = text.upper() if self._shift and text.isalpha() else text
                self._steps.append(lambda page, t=char: page.keyboard.press(t))
            else:
                self._steps.append(lambda page, t=text: page.keyboard.type(t))
        return self

    def perform(self) -> None:
        def work():
            page = self._driver._page
            for step in self._steps:
                step(page)

        try:
            self._driver._call(work)
        except Exception as exc:
            raise _as_engine_error(exc) from exc
        finally:
            self._steps.clear()
