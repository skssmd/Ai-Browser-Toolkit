"""Console and network ops: what the page said, and what it asked for.

The DOM tells you what a page *is*. These tell you what it *did* -- and when a
request fails there is usually nothing in the DOM about it at all. A site can
show "Failed to load PDF" while the only fact that matters, a 404 on a storage
key, exists solely in the network log.

Console messages come from a buffer installed at document start (see
`BrowserSession._install_console_capture`), because output is gone by the time
anyone asks. Requests come from the Resource Timing API, which the browser keeps
for free -- no patching of fetch or XHR, nothing to install, and it survives
navigation.
"""

from __future__ import annotations

import re

from selenium.common.exceptions import WebDriverException

from ..browser import BrowserSession
from ..errors import OpError

_CONSOLE_JS = "return window.__abtConsole || null;"

_NETWORK_JS = """
return performance.getEntriesByType('resource').map(function (e) {
  return {
    url: e.name,
    kind: e.initiatorType,
    status: e.responseStatus === undefined ? null : e.responseStatus,
    ms: Math.round(e.duration),
    bytes: e.encodedBodySize,
    // A cross-origin response with no Timing-Allow-Origin reports zeroes. Say
    // so, rather than letting a real 0-byte body and an opaque one look alike.
    opaque: e.responseStatus === undefined && e.transferSize === 0
  };
});
"""


def _compile(pattern: str | None):
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise OpError("invalid_op", f"bad pattern {pattern!r}: {exc}") from exc


def read_console(session: BrowserSession, cmd) -> dict:
    """Console output for the active tab, oldest first."""
    try:
        entries = session.driver.execute_script(_CONSOLE_JS)
    except WebDriverException as exc:
        raise OpError("js_error", f"could not read the console: {exc.msg or exc}") from exc

    if entries is None:
        return {
            "available": False,
            "count": 0,
            "messages": [],
            "note": (
                "no console buffer on this page; capture is installed at document "
                "start, so a page open from before the server started, or a browser "
                "without CDP, will not have one -- reload the page"
            ),
        }

    matcher = _compile(cmd.pattern)
    wanted = set(cmd.levels or [])
    rows = [
        e
        for e in entries
        if (not wanted or e.get("level") in wanted)
        and (matcher is None or matcher.search(e.get("text") or ""))
    ]
    total = len(rows)
    if cmd.limit and total > cmd.limit:
        rows = rows[-cmd.limit :]  # the newest are the ones you came for
    return {
        "available": True,
        "count": len(rows),
        "total_matched": total,
        "messages": rows,
    }


def read_network(session: BrowserSession, cmd) -> dict:
    """Requests the active tab has made, in the order the browser recorded them.

    Statuses and URLs, not bodies -- which is what a diagnosis usually needs and
    costs nothing to keep.
    """
    try:
        entries = session.driver.execute_script(_NETWORK_JS) or []
    except WebDriverException as exc:
        raise OpError("js_error", f"could not read the network log: {exc.msg or exc}") from exc

    matcher = _compile(cmd.pattern)
    rows = []
    for entry in entries:
        status = entry.get("status")
        if cmd.failures_only and not (status is None or status >= 400):
            continue
        if cmd.min_status is not None and (status is None or status < cmd.min_status):
            continue
        if matcher is not None and not matcher.search(entry.get("url") or ""):
            continue
        rows.append(entry)

    total = len(rows)
    if cmd.limit and total > cmd.limit:
        rows = rows[-cmd.limit :]
    return {"count": len(rows), "total_matched": total, "requests": rows}
