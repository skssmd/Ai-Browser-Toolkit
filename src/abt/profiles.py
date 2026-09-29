"""Named browser profiles, and at most one hidden Chrome per profile.

A profile is a Chrome user-data directory with a name. This registry owns the
directories and the Chrome processes running on them; it knows nothing about
sessions. A session asks for its profile's CDP endpoint with `attach` and says
it is finished with `detach`.

Chrome is launched as a plain process with `--remote-debugging-port=0`, not by
Playwright, because every session connects a Playwright of its own to it --
which is what lets two sessions on one profile run at the same moment. Remote
debugging is allowed here because these are custom user-data directories;
Chrome refuses it only on its own default profile.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import httpx

from . import holders
from . import trace as trace_util
from .errors import OpError
from .tabs import TabRegistry

# A name becomes a path, so this is a security check rather than tidiness: it
# rejects `..`, separators, drive letters and leading dots by construction.
# Lowercase only, and no trailing dot, because NTFS folds case and drops a
# trailing dot: `Default` and `default.` both *are* `default` on Windows, and
# `abt profile rm Default` would otherwise delete the default profile's logins.
NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$")
DEFAULT = "default"
LAUNCH_TIMEOUT = 60.0
PORT_FILE = "DevToolsActivePort"

# Chrome throttles what it thinks is in the background. With several sessions
# driving several tabs at once, every tab is "in the background" to somebody.
_UNTHROTTLED = (
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
)


def check_name(name: Any, what: str = "profile") -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise OpError(
            "invalid_op",
            f"bad {what} name {name!r}: use lowercase letters, digits, '.', '_' "
            "and '-', starting with a letter or digit and not ending in '.', at "
            "most 64 characters",
        )
    return name


def launch_argv(binary: Path, profile_dir: Path, headed: bool) -> list[str]:
    argv = [
        str(binary),
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        # The same anti-detection flag `BrowserSession._make_options` sets.
        "--disable-blink-features=AutomationControlled",
        # Playwright's own launcher always passes this, so the browser abt
        # drove before sessions never blocked a popup. Without it, a
        # window.open from a script -- no user gesture -- is blocked on some
        # platforms and not others (macOS blocked it, Windows did not).
        "--disable-popup-blocking",
        *_UNTHROTTLED,
    ]
    if not headed:
        argv += ["--headless=new", "--window-size=1440,900"]
    argv.append("about:blank")
    return argv


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_port(path: Path) -> int | None:
    """The port Chrome chose, once it has finished writing the file."""
    try:
        return int(path.read_text(encoding="utf-8").splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None


def _spawn(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _find_binary(browser: str) -> Path | None:
    from . import doctor

    return {b.name: b.path for b in doctor.find_browsers()}.get(browser)


def _http_get(url: str) -> Any:
    return httpx.get(url, timeout=3).json()


@dataclass
class Running:
    process: Any
    port: int
    headed: bool
    sessions: set[str] = field(default_factory=set)
    watchers: int = 0
    last_used: float = 0.0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.process.poll() is None


class _ProfileHeld(Exception):
    """Chrome handed off to a browser already holding the folder, and exited."""


class ProfileRegistry:
    def __init__(
        self,
        root: Path,
        default_dir: Path | None = None,
        browser: str = "chrome",
        max_running: int = 4,
        idle_minutes: float = 30.0,
        default_headed: bool = False,
        spawn: Callable[[list[str]], Any] | None = None,
        find_binary: Callable[[str], Path | None] | None = None,
        http_get: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        launch_timeout: float = LAUNCH_TIMEOUT,
        find_holders: Callable[..., list[int]] | None = None,
        kill_holders: Callable[[list[int]], int] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.default_dir = (
            Path(default_dir).expanduser().resolve() if default_dir else self.root / DEFAULT
        )
        self.browser = browser
        self.max_running = max_running
        self.idle_seconds = idle_minutes * 60
        self.default_headed = default_headed
        self._spawn = spawn or _spawn
        self._find_binary = find_binary or _find_binary
        self._http_get = http_get or _http_get
        self._clock = clock
        self.launch_timeout = launch_timeout
        self._find_holders = find_holders or holders.find
        self._kill_holders = kill_holders or holders.kill
        # Guards the maps only. Launching and stopping take seconds, so they
        # happen outside it -- one profile starting must never stall another
        # session's `tab_list` on a different profile.
        self._lock = threading.Lock()
        self._running: dict[str, Running] = {}
        self._launching: set[str] = set()
        self._launch_locks: dict[str, threading.Lock] = {}
        self._tabs: dict[str, TabRegistry] = {}

    # --- names and directories -------------------------------------------------

    def path(self, name: str) -> Path:
        check_name(name)
        if name == DEFAULT:
            return self.default_dir
        path = (self.root / name).resolve()
        # Belt and braces: the regex already makes this impossible, and the
        # cost of being wrong is deleting something outside the profile root --
        # or, on a case-folding disk, a different profile inside it.
        if path.parent != self.root or path.name != name:
            raise OpError("invalid_op", f"profile {name!r} resolves outside {self.root}")
        return path

    def exists(self, name: str) -> bool:
        return name == DEFAULT or self.path(name).is_dir()

    def require(self, name: str) -> str:
        if not self.exists(name):
            raise OpError("profile_not_found", f"no profile {name!r}")
        return name

    def _meta_path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def meta(self, name: str) -> dict:
        try:
            data = json.loads(self._meta_path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        explicit = data.get("headed")
        # Unset unless someone chose (`abt profile set --headed/--headless`).
        # Unset, the session asking decides -- the app's chats run hidden, the
        # CLI's follow the server (a window unless it was started --headless).
        # `headed` reports what a launch with no preference would do.
        headed = self.default_headed if explicit is None else bool(explicit)
        return {
            "name": name, "created": data.get("created"),
            "headed": headed, "headed_set": explicit is not None,
        }

    def _write_meta(self, name: str, meta: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._meta_path(name).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def describe(self, name: str) -> dict:
        with self._lock:
            running = self._live(name)
            # No port: it is a direct way into the browser, around every
            # session's rules and locks, and nothing that reads this needs it.
            info = {
                "running": running is not None,
                "sessions": sorted(running.sessions) if running else [],
            }
        return {**self.meta(name), "path": str(self.path(name)), **info}

    def list(self) -> list[dict]:
        names = {DEFAULT}
        if self.root.is_dir():
            for entry in self.root.iterdir():
                if entry.is_dir() and NAME.match(entry.name):
                    names.add(entry.name)
        return [self.describe(name) for name in sorted(names)]

    def create(self, name: str) -> dict:
        check_name(name)
        if self.exists(name):
            raise OpError("invalid_op", f"profile {name!r} already exists")
        self.path(name).mkdir(parents=True)
        self._write_meta(name, {"name": name, "created": _now()})
        return self.describe(name)

    def set_headed(self, name: str, headed: bool) -> dict:
        self.require(name)
        meta = self.meta(name)
        meta["headed"] = bool(headed)
        meta.pop("headed_set", None)
        self._write_meta(name, meta)
        return self.describe(name)

    def remove(self, name: str, in_use: bool) -> None:
        self.require(name)
        if name == DEFAULT:
            raise OpError("invalid_op", "the default profile cannot be removed")
        with self._lock:
            if in_use or self._live(name) is not None or name in self._launching:
                raise OpError(
                    "profile_in_use",
                    f"profile {name!r} is used by a session or its browser is running",
                )
            self._tabs.pop(name, None)
        shutil.rmtree(self.path(name))
        self._meta_path(name).unlink(missing_ok=True)

    # --- running browsers ------------------------------------------------------

    def tabs(self, name: str) -> TabRegistry:
        with self._lock:
            return self._tabs_of(name)

    def _tabs_of(self, name: str) -> TabRegistry:
        found = self._tabs.get(name)
        if found is None:
            found = self._tabs[name] = TabRegistry(name)
        return found

    def _live(self, name: str) -> Running | None:
        """The running Chrome for `name`, forgetting it if it has died."""
        running = self._running.get(name)
        if running is not None and not running.alive():
            del self._running[name]
            self._tabs_of(name).clear()
            return None
        return running

    def running(self, name: str) -> Running | None:
        with self._lock:
            return self._live(name)

    def attach(self, name: str, session: str, headed: bool | None = None) -> str:
        """Make sure `name`'s Chrome is up and count `session` on it.

        `headed` is the session's wish, used only when this call is the one
        that launches the browser and the profile has no setting of its own.
        One Chrome serves every session on a profile, so whoever starts it
        decides whether it has a window.
        """
        with trace_util.span("profile.attach", name, session=session) as step, self._launch_lock(name):
            with self._lock:
                running = self._live(name)
                # Traced: a session on a profile whose Chrome is up only
                # connects to it; it never starts a second one.
                step.note(reused=running is not None)
                if running is None:
                    live = [n for n in list(self._running) if self._live(n) is not None]
                    if len(live) + len(self._launching) >= self.max_running:
                        raise OpError(
                            "profile_limit",
                            f"{len(live)} browsers already running "
                            f"({', '.join(sorted(live)) or 'none'}); the limit is "
                            f"{self.max_running}",
                        )
                    self._launching.add(name)
            if running is None:
                try:
                    with trace_util.span("profile.launch", name, session=session):
                        running = self._launch(name, headed)
                finally:
                    with self._lock:
                        self._launching.discard(name)
                with self._lock:
                    self._tabs_of(name).clear()
                    self._running[name] = running
            with self._lock:
                running.sessions.add(session)
                running.last_used = self._clock()
                return running.url

    def _launch_lock(self, name: str) -> threading.Lock:
        with self._lock:
            return self._launch_locks.setdefault(name, threading.Lock())

    def detach(self, name: str, session: str) -> None:
        """`session` let go. The last one out stops Chrome, unless it is watched.

        Chrome is closed under the profile's launch lock, so an `attach` from
        another session waits for it to be gone and launches a fresh one,
        rather than connecting to a browser on its way out.
        """
        with trace_util.span("profile.detach", name, session=session) as step, self._launch_lock(name):
            with self._lock:
                running = self._running.get(name)
                if running is None:
                    return
                running.sessions.discard(session)
                if running.sessions or running.watchers:
                    step.note(closed_chrome=False, still_using=len(running.sessions))
                    return
                del self._running[name]
                self._tabs_of(name).clear()
            step.note(closed_chrome=True)
            self._close(running)

    def touch(self, name: str) -> None:
        with self._lock:
            running = self._running.get(name)
            if running is not None:
                running.last_used = self._clock()

    def watch(self, name: str, delta: int) -> None:
        """A screencast opened (+1) or closed (-1). Watched means not idle."""
        with self._lock:
            running = self._running.get(name)
            if running is not None:
                running.watchers = max(0, running.watchers + delta)
                running.last_used = self._clock()

    def idle(self) -> list[str]:
        """Profiles nobody has used for a while. Never the default one: it
        stayed up for the server's whole life before sessions existed, and an
        agent that pauses for half an hour must not come back to no browser."""
        if self.idle_seconds <= 0:
            return []
        now = self._clock()
        with self._lock:
            return sorted(
                name
                for name, running in self._running.items()
                if name != DEFAULT
                and running.watchers == 0
                and now - running.last_used >= self.idle_seconds
            )

    def stop(self, name: str) -> bool:
        with self._launch_lock(name):
            with self._lock:
                running = self._running.pop(name, None)
                if running is None:
                    return False
                self._tabs_of(name).clear()
            self._close(running)
        return True

    def stop_all(self) -> None:
        with self._lock:
            names = list(self._running)
        for name in names:
            self.stop(name)

    def targets(self, name: str) -> list[dict]:
        """Every page in `name`'s Chrome, from Chrome's own /json/list."""
        running = self.running(name)
        if running is None:
            return []
        try:
            rows = self._http_get(f"{running.url}/json/list")
        except Exception:
            return []
        return [r for r in rows or [] if r.get("type") == "page"]

    # --- process handling ------------------------------------------------------

    def _launch(self, name: str, wish: bool | None = None) -> Running:
        binary = self._find_binary(self.browser)
        if binary is None:
            raise OpError(
                "browser_not_found",
                f"no installed {self.browser} found; run `abt doctor --install-browser`.",
            )
        directory = self.path(name)
        directory.mkdir(parents=True, exist_ok=True)
        port_file = directory / PORT_FILE
        # A file left by an earlier run names a port nobody is listening on.
        port_file.unlink(missing_ok=True)
        meta = self.meta(name)
        if meta["headed_set"]:
            headed = meta["headed"]
        else:
            headed = self.default_headed if wish is None else wish
        argv = launch_argv(binary, directory, headed)
        process = self._spawn(argv)
        try:
            port = self._await_port(process, port_file, directory)
        except _ProfileHeld:
            # Most often a hidden browser left by an earlier server that died
            # without closing it. Those are ours to end; then try once more.
            if not self._kill_holders(self._find_holders(directory, ours_only=True)):
                raise self._held(name, directory) from None
            time.sleep(1.0)
            port_file.unlink(missing_ok=True)
            process = self._spawn(argv)
            try:
                port = self._await_port(process, port_file, directory)
            except _ProfileHeld:
                raise self._held(name, directory) from None
        return Running(process=process, port=port, headed=headed, last_used=self._clock())

    def _held(self, name: str, directory: Path) -> OpError:
        return OpError(
            "browser_dead",
            f"another browser is holding the profile at {directory}. Close the "
            "Chrome window that uses it, or force-close it: in the app, the "
            f"button beside this message; over HTTP, POST /profiles/{name}/force-close "
            "with the operator token. Then start again.",
        )

    def sweep(self) -> list[str]:
        """Stop every browser, and end abt's own left behind by an earlier run.

        `stop_all` reaches only the browsers this registry started. One left by
        a server that died is invisible to it, yet still holds its profile, so
        each profile folder is checked for abt-launched holders as well. A
        person's own Chrome window is never touched here.
        """
        closed = [row["name"] for row in self.list() if self.running(row["name"])]
        self.stop_all()
        for row in self.list():
            pids = self._find_holders(self.path(row["name"]), ours_only=True)
            if pids and self._kill_holders(pids) and row["name"] not in closed:
                closed.append(row["name"])
        return closed

    def force_close(self, name: str) -> dict:
        """End every browser holding `name`'s folder, ours or not.

        For the person, who has said to: this also closes a Chrome window they
        opened on the profile themselves. Unsaved work in it is lost.
        """
        self.require(name)
        self.stop(name)
        pids = self._find_holders(self.path(name), ours_only=False)
        return {"profile": name, "closed": self._kill_holders(pids)}

    def _await_port(self, process: Any, port_file: Path, directory: Path) -> int:
        deadline = time.monotonic() + self.launch_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                # Chrome single-instances per user-data-dir: a second launch
                # hands off to the incumbent and exits at once. Say so, rather
                # than leaving the caller to wait out the timeout.
                from .browser import _profile_locked

                # POSIX Chrome leaves Singleton* files; Windows Chrome holds
                # `lockfile`, and a handoff to the incumbent exits cleanly.
                if (
                    _profile_locked(SimpleNamespace(profile=directory))
                    or (directory / "lockfile").exists()
                    or process.returncode == 0
                ):
                    raise _ProfileHeld(directory)
                raise OpError(
                    "browser_dead",
                    f"chrome exited during launch (exit code {process.returncode})",
                )
            port = _read_port(port_file)
            if port is not None:
                return port
            time.sleep(0.1)
        process.kill()
        raise OpError(
            "browser_dead",
            f"chrome did not open its debugging port within {self.launch_timeout:g}s",
        )

    def _close(self, running: Running) -> None:
        """Ask Chrome to close, then insist.

        `Browser.close` over CDP lets Chrome flush the profile -- cookies
        written in the last second are logins. Killing is the fallback.
        """
        try:
            info = self._http_get(f"{running.url}/json/version")
            from websockets.sync.client import connect

            with connect(info["webSocketDebuggerUrl"], open_timeout=3) as ws:
                ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
        except Exception:
            pass
        try:
            running.process.wait(timeout=10)
        except Exception:
            running.process.kill()
            try:
                running.process.wait(timeout=5)
            except Exception:
                pass
