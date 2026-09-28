"""The network half of a session's URL rules.

For every tab a session owns, the guard holds a DevTools connection of its own
with the Fetch domain on, and decides each paused request against the
session's `Policy`: continue it, or fail it with `BlockedByClient`. That is
what makes the rules hold for a link click, a redirect, or a `fetch()` from
`run_js` -- not only for the `goto` the op-level check sees.

It runs on its own threads, over Chrome's raw DevTools WebSockets, not through
the session's Playwright connection. Sync Playwright only delivers route
callbacks while a command is in flight on its thread, so routing there would
freeze every page's requests in the gaps between an agent's commands.

A watcher thread polls the browser's targets and starts guarding a page as soon
as the session owns it -- or as soon as its opener is guarded, which catches a
popup before the owning session has even looked at it.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from typing import Callable

import httpx

from .policy import Policy

POLL_INTERVAL = 0.25


def _open(url: str):
    from websockets.sync.client import connect

    # Entered explicitly rather than used bare: websockets 17 deprecates a
    # bare connect(), and on older versions __enter__ returns the connection
    # itself, so this is the same on every release the dependency allows.
    # The guard holds these open across calls, so a `with` block cannot fit.
    return connect(url, max_size=None, open_timeout=5).__enter__()


class PageGuard:
    """Fetch interception on one tab."""

    def __init__(self, port: int, target: str, url: str, policy: Callable[[], Policy]) -> None:
        self.target = target
        self._policy = policy
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._ids = itertools.count(1)
        self._ws = _open(f"ws://127.0.0.1:{port}/devtools/page/{target}")
        self._thread = threading.Thread(
            target=self._run, args=(url,), name=f"abt-guard-{target[:8]}", daemon=True
        )
        self._thread.start()

    def _send(self, method: str, params: dict | None = None) -> None:
        self._ws.send(json.dumps({"id": next(self._ids), "method": method, "params": params or {}}))

    def wait_ready(self, timeout: float = 3.0) -> bool:
        return self._ready.wait(timeout)

    def _run(self, first_url: str) -> None:
        try:
            self._send(
                "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}
            )
            self._ready.set()
            # A popup can reach a blocked page before anyone was watching it.
            if first_url and not self._policy().allows(first_url):
                self._send("Page.navigate", {"url": "about:blank"})
            while not self._stop.is_set():
                try:
                    raw = self._ws.recv(timeout=0.5)
                except TimeoutError:
                    continue
                message = json.loads(raw)
                if message.get("method") == "Fetch.requestPaused":
                    self._decide(message["params"])
                elif message.get("method") == "Inspector.detached":
                    return
        except Exception:
            # The tab closed, or Chrome went away. Nothing left to guard.
            pass
        finally:
            self._ready.set()
            try:
                self._ws.close()
            except Exception:
                pass

    def _decide(self, params: dict) -> None:
        policy = self._policy()
        url = params.get("request", {}).get("url", "")
        kind = params.get("resourceType", "")
        request_id = params["requestId"]
        if not policy or not policy.guards(kind) or policy.allows(url):
            self._send("Fetch.continueRequest", {"requestId": request_id})
        else:
            self._send(
                "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
            )

    def enforce(self, url: str) -> None:
        """Send the tab away from a page it may not be on.

        The watcher calls this every pass with the tab's current URL. It is
        what catches the navigation that happened in the gap between a popup
        opening and its guard attaching -- Fetch only sees requests made after
        it was enabled.
        """
        if not url or self._stop.is_set():
            return
        if url.startswith("chrome-error:") or self._policy().allows(url):
            return
        try:
            self._send("Page.navigate", {"url": "about:blank"})
        except Exception:
            pass

    def alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._send("Fetch.disable")
        except Exception:
            pass


class Guard:
    """One session's guards: which of its tabs are watched, kept in step."""

    def __init__(
        self,
        port: int,
        policy: Callable[[], Policy],
        owned: Callable[[], set[str]],
        http_get: Callable[[str], object] | None = None,
    ) -> None:
        self.port = port
        self._policy = policy
        self._owned = owned
        self._http_get = http_get or (lambda url: httpx.get(url, timeout=3).json())
        self._pages: dict[str, PageGuard] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._browser_ws = None
        self._ids = itertools.count(1)

    # --- lifecycle ------------------------------------------------------------

    def sync(self) -> None:
        """Start watching if the session has rules; stop if it has none.

        Also runs one pass right now, so a tab a command just opened is
        guarded before that command's navigation, not up to a poll later.
        """
        if not self._policy():
            self.stop()
            return
        self._pass()
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._loop, name="abt-guard", daemon=True)
                self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            pages, self._pages = list(self._pages.values()), {}
            ws, self._browser_ws = self._browser_ws, None
        for page in pages:
            page.stop()
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def guarded(self) -> set[str]:
        with self._lock:
            return {t for t, g in self._pages.items() if g.alive()}

    # --- the watch -----------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.wait(POLL_INTERVAL):
            if not self._policy():
                self.stop()
                return
            try:
                self._pass()
            except Exception:
                pass

    def _targets(self) -> list[dict]:
        """Every page, with its opener. /json/list has no opener, so this asks
        the browser target directly."""
        with self._lock:
            ws = self._browser_ws
        if ws is None:
            info = self._http_get(f"http://127.0.0.1:{self.port}/json/version")
            ws = _open(info["webSocketDebuggerUrl"])
            with self._lock:
                self._browser_ws = ws
        request = next(self._ids)
        ws.send(json.dumps({"id": request, "method": "Target.getTargets"}))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            message = json.loads(ws.recv(timeout=3))
            if message.get("id") == request:
                infos = message.get("result", {}).get("targetInfos", [])
                return [t for t in infos if t.get("type") == "page"]
        return []

    def _pass(self) -> None:
        try:
            targets = self._targets()
        except Exception:
            with self._lock:
                self._browser_ws = None
            return
        owned = self._owned()
        live = {t["targetId"] for t in targets}
        with self._lock:
            for gone in [t for t in self._pages if t not in live or not self._pages[t].alive()]:
                self._pages.pop(gone).stop()
            watched = set(self._pages)
            current = dict(self._pages)
        for info in targets:
            page = current.get(info["targetId"])
            if page is not None:
                page.enforce(info.get("url", ""))
        fresh = []
        for info in targets:
            target = info["targetId"]
            if target in watched:
                continue
            opener = info.get("openerId")
            if target in owned or (opener and (opener in watched or opener in owned)):
                try:
                    guard = PageGuard(self.port, target, info.get("url", ""), self._policy)
                except Exception:
                    continue
                fresh.append(guard)
                watched.add(target)
        for guard in fresh:
            guard.wait_ready()
        with self._lock:
            for guard in fresh:
                self._pages[guard.target] = guard
