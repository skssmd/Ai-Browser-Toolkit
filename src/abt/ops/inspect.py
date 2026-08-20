"""Console and network ops: what the page said, and what it asked for.

The DOM tells you what a page *is*. These tell you what it *did* -- and when a
request fails there is usually nothing in the DOM about it at all. A site can
show "Failed to load PDF" while the only fact that matters, a 404 on a storage
key, exists solely in the network log.

Console messages come from a buffer installed at document start (see
`BrowserSession._install_console_capture`), because output is gone by the time
anyone asks.

Requests come from whichever source the engine can offer. An engine that
watches the browser's own network events answers natively; the rest fall back
to the Resource Timing API, which the browser keeps for free but which is a
*page* API and therefore blind to a cross-origin status and to a request that
never got a response. Same op, same response shape, more truth where the engine
can supply it.

**Neither source captures headers or bodies**, so `Authorization` and `Cookie`
never reach a row. URLs are redacted on the way out, because a credential in a
query string would otherwise be handed to a model and written to the session
log -- the same reason `diff.py` refuses to capture password field values.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..browser import BrowserSession
from ..engine import EngineError
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


# Query parameters whose value is a credential rather than a fact about the
# request. `diff.py` already refuses to capture password field values, for the
# stated reason that diffs get written to session logs; network rows go to the
# same file and are handed to a model besides, so the same rule applies here.
#
# The names are matched case-insensitively and as whole parameters, which is
# why `key` is on the list and `pkey` would not match. Erring towards redacting
# something harmless costs a diagnosis nothing -- the URL, path and status all
# survive -- while erring the other way writes a bearer token to disk.
#
# Headers and bodies are not captured at all, which is the larger half of this:
# `Authorization` and `Cookie` never reach a row in the first place.
SENSITIVE_PARAMS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "code",
        "id_token",
        "key",
        "password",
        "passwd",
        "pwd",
        "refresh_token",
        "secret",
        "session",
        "sid",
        "sig",
        "signature",
        "token",
    }
)

# No brackets: urlencode would percent-escape them to %5B...%5D, which is
# noise in something a model reads.
REDACTED = "REDACTED"


def redact(url: str) -> str:
    """A URL with any credential in it replaced, and nothing else changed.

    Applied to both engines: Resource Timing reported URLs too, so this is not
    a new exposure introduced by watching the browser's events -- it is one
    that was always there and is worth closing while the code is open.
    """
    if not url or ("?" not in url and "@" not in url):
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    netloc = parts.netloc
    # https://user:token@host -- the password half is a credential.
    if "@" in netloc:
        creds, _, host = netloc.rpartition("@")
        name, sep, _ = creds.partition(":")
        netloc = f"{name}{sep}{REDACTED if sep else ''}@{host}"

    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        if any(name.lower() in SENSITIVE_PARAMS for name, _ in pairs):
            query = urlencode(
                [
                    (name, REDACTED if name.lower() in SENSITIVE_PARAMS else value)
                    for name, value in pairs
                ]
            )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


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
    except EngineError as exc:
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
    # An engine that watches the browser's own network events answers this
    # better than the page can, so ask it first. Selenium has no such method
    # and falls through to Resource Timing, which is what both engines used
    # until the Playwright backend existed.
    #
    # What this actually buys, stated narrowly because the obvious wider claim
    # does not survive testing:
    #
    #   A request that never produced a response -- refused, DNS failure,
    #   aborted, or blocked by the browser -- leaves *no Resource Timing entry
    #   at all*, so the failure is invisible. The native log reports it with
    #   the reason. This is the real win.
    #
    #   `method`, which Resource Timing does not have.
    #
    # It does NOT reliably recover cross-origin statuses. Chrome's Opaque
    # Response Blocking rejects a mismatched cross-origin subresource before
    # any response event exists, so the status is unavailable to the engine
    # too -- measured, after asserting the opposite and being wrong twice.
    native = getattr(session.driver, "network_log", None)
    if native is not None:
        entries = native()
    else:
        try:
            entries = session.driver.execute_script(_NETWORK_JS) or []
        except EngineError as exc:
            raise OpError(
                "js_error", f"could not read the network log: {exc.msg or exc}"
            ) from exc

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
    # Redacted last, so `pattern` still matches what the page actually
    # requested and only what leaves this function is sanitised. Copied rather
    # than mutated: on the native path these dicts are the driver's own log.
    rows = [{**row, "url": redact(row.get("url") or "")} for row in rows]
    return {"count": len(rows), "total_matched": total, "requests": rows}
