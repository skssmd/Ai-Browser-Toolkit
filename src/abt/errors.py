"""The closed set of error types every command can fail with.

Every error carries a `hint`: what this failure usually means and what to do
next. An agent that hits `browser_dead` and is told only "browser is not
reachable" restarts the server, hits it again, and guesses -- that is a real
session, and it cost four commands to get moving. The hint is the difference
between an error and an instruction.

Hints say what to *do*. They are not apologies, and they do not restate the
message; a caller already has that.
"""

from __future__ import annotations

# type -> what to do about it. Keep these one or two sentences: they ride along
# with every failure, and an agent reads them more often than it reads the docs.
HINTS = {
    "invalid_op": (
        "Check the op name and its parameters with `abt ops`. That list is "
        "generated from the server you are talking to, so it is never stale."
    ),
    "element_not_found": (
        "A search that finds nothing is an answer -- usually the page has not "
        "created the control yet. Do not widen with `run_js`: `find` already "
        "covered the document, every frame and open shadow roots. Act on what "
        "the page is showing, then look again."
    ),
    "stale_ref": (
        "Refs die on navigation or when the element leaves the DOM. Take a "
        "fresh one from the last `dom_diff.actionable.added`, or run `find` "
        "again. A stale ref never silently hits a different element."
    ),
    "not_interactable": (
        "Something is covering the target -- the message names it. Dismiss the "
        "overlay, scroll it into view, or wait for it to go, then retry."
    ),
    "not_a_select": (
        "`select` only drives a real <select>. A custom dropdown is a click on "
        "the control, then a click on the option that appears in the diff."
    ),
    "timeout": (
        "The element did not appear inside the budget. Raise it with "
        "--action-timeout, or wait for something that does appear with "
        "`wait_for`. If the page is slow rather than wrong, the budget is the "
        "problem."
    ),
    "navigation_failed": (
        "The browser did not end up anywhere usable. Check the URL, and check "
        "`abt status` -- a redirect that merely overran its budget reports "
        "`navigation_slow` and is not a failure."
    ),
    "js_error": (
        "Your script threw. `run_js` is the escape hatch, not the tool -- if "
        "you are writing querySelectorAll to find something, `find` already "
        "does it, into frames and shadow roots."
    ),
    "last_tab": (
        "The browser keeps one tab. Open another with `tab_new` before closing "
        "this one, or stop the browser with `abt browser stop`."
    ),
    "tab_not_found": (
        "List what is actually open with `abt tabs`. Tab ids do not survive a "
        "browser restart."
    ),
    "browser_dead": (
        "No usable browser. If you have not started one: `abt browser start` "
        "-- the server runs without a browser on purpose. If one died (a tab "
        "that closes itself takes the session with it): `abt browser restart`, "
        "which keeps your logins but loses every tab."
    ),
    "bad_browser": (
        "Only chrome and edge are supported. `abt doctor` reports which are "
        "installed and where."
    ),
    "browser_not_found": (
        "The named browser is supported but not installed where abt looked. "
        "`abt doctor --install-browser` installs one."
    ),
}

ERROR_TYPES = frozenset(HINTS)


class OpError(Exception):
    """A command failure with a machine-branchable type, and a way forward."""

    def __init__(self, type: str, message: str, hint: str | None = None) -> None:
        if type not in ERROR_TYPES:
            raise ValueError(f"unknown error type: {type}")
        super().__init__(message)
        self.type = type
        self.message = message
        # An explicit hint wins: some failures know more about the remedy than
        # their type does.
        self.hint = hint or HINTS[type]

    def to_dict(self, op_index: int = 0) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            "hint": self.hint,
            "op_index": op_index,
        }
