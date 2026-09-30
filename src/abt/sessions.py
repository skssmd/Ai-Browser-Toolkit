"""Sessions: the unit every command runs in.

A session is a name, a profile, settings, and at run time a `BrowserSession`
of its own, a lock of its own and a log of its own. Two sessions never wait on
each other; commands within one run in order.

**Open** sessions are addressed by name alone. That keeps cooperating agents
out of each other's way and is not a security boundary -- any process can name
any open session. **Sealed** sessions also need a token that exists only in the
creator's hands (and, hashed, here), so a model driving the desktop app, or
another agent on the machine, cannot reach one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .browser import Attach, BrowserSession
from .errors import OpError
from .policy import validate_settings
from .profiles import DEFAULT, ProfileRegistry, check_name
from .recorder import SessionRecorder
from .tabs import TabGate

# A session's pages come back after a browser restart only if it ran a command
# this recently: a crash mid-task, not a session picked up again an hour later.
RESTORE_WITHIN_SECONDS = 600
# How often an idle session's page list is brought in step with its tabs.
PAGES_REFRESH_SECONDS = 5

NO_SESSIONS = (
    "sessions need `abt serve` on the playwright engine; this server has "
    "only the `default` session"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read.

    POSIX gets 0600 at creation, so there is no moment at which it is world
    readable. On Windows the per-user directories this lives in already carry
    an owner-only ACL, and chmod cannot express more.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


@dataclass
class SessionRecord:
    name: str
    profile: str = DEFAULT
    sealed: bool = False
    created: str = ""
    # Kept verbatim, unknown keys included, so later features can add
    # settings without a migration.
    settings: dict = field(default_factory=dict)
    token_hash: str | None = None
    # The session's open pages, last seen: {"urls": [...], "active": index}.
    # Reopened when its browser starts again, after a crash or a restart.
    pages: dict = field(default_factory=dict)

    def public(self, with_settings: bool = True) -> dict:
        out = {
            "name": self.name,
            "profile": self.profile,
            "sealed": self.sealed,
            "created": self.created,
        }
        if with_settings:
            out["settings"] = self.settings
        return out


class SessionStore:
    """`<dir>/<name>.json` per session, plus `<name>.token` for sealed ones."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def load(self) -> dict[str, SessionRecord]:
        found: dict[str, SessionRecord] = {}
        if not self.directory.is_dir():
            return found
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = check_name(data.get("name"), "session")
            except (OSError, ValueError, OpError, AttributeError):
                continue
            # A file whose name disagrees with its contents was not written
            # here. Loading it would let a stray file answer for a session.
            if path.stem != name:
                continue
            found[name] = SessionRecord(
                name=name,
                profile=str(data.get("profile") or DEFAULT),
                sealed=bool(data.get("sealed")),
                created=str(data.get("created") or ""),
                settings=dict(data.get("settings") or {}),
                token_hash=data.get("token_hash"),
                pages=dict(data.get("pages") or {}),
            )
        return found

    def save(self, record: SessionRecord) -> None:
        write_private(self._path(record.name), json.dumps(asdict(record), indent=2))

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)
        (self.directory / f"{name}.token").unlink(missing_ok=True)

    def write_token(self, name: str, token: str) -> None:
        write_private(self.directory / f"{name}.token", token)


class Session:
    """A record plus what it needs to run: a browser, a lock, a log."""

    # A stretch of work: commands closer together than this count as one run
    # in the app's Live view; a longer gap starts the clock again.
    ACTIVITY_GAP_SECONDS = 600

    def __init__(
        self,
        record: SessionRecord,
        browser: BrowserSession,
        *,
        recorder: SessionRecorder | None = None,
        recorder_factory: Callable[[], SessionRecorder] | None = None,
        log_root: Path | None = None,
    ) -> None:
        self.record = record
        # What it did last, for the app's Live view: {op, ok, at, steps, since}.
        self.activity: dict = {}
        # Replaced when the session moves to another profile. Read it only
        # while holding `lock`.
        self.browser = browser
        self.lock = threading.Lock()
        # Set by `remove`. A request that fetched this session before it was
        # removed must not bring it back to life by running afterwards.
        self.closed = False
        self.log_root = log_root
        self._recorder = recorder
        self._recorder_factory = recorder_factory

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def recorder(self) -> SessionRecorder | None:
        """Created on first use, so a session that never runs leaves no log."""
        if self._recorder is None and self._recorder_factory is not None:
            self._recorder = self._recorder_factory()
            self._recorder_factory = None
        return self._recorder

    @property
    def started_recorder(self) -> SessionRecorder | None:
        return self._recorder

    def close(self) -> None:
        try:
            self.browser.stop()
        except Exception:
            pass
        if self._recorder is not None:
            self._recorder.close()


class SessionRegistry:
    def __init__(
        self,
        store: SessionStore,
        profiles: ProfileRegistry,
        make_browser: Callable[[Path, Attach], BrowserSession],
        log_root: Path | None = None,
        recorder_options: dict[str, Any] | None = None,
        operator_token: str | None = None,
        files_root: Path | None = None,
    ) -> None:
        self.store = store
        # Each profile's uploads and downloads folders live under here.
        self.files_root = Path(files_root) if files_root is not None else None
        self.profiles = profiles
        self.operator_token = operator_token
        self._make_browser = make_browser
        self._log_root = Path(log_root) if log_root is not None else None
        self._recorder_options = recorder_options or {}
        self._lock = threading.Lock()
        self._records = store.load()
        # `default` is always there, always open, always on the default
        # profile -- whatever a file on disk claims.
        default = self._records.get(DEFAULT) or SessionRecord(name=DEFAULT, created=_now())
        default.profile, default.sealed, default.token_hash = DEFAULT, False, None
        self._records[DEFAULT] = default
        self._live: dict[str, Session] = {}
        self._stop_reaper = threading.Event()

    # --- lookup ------------------------------------------------------------------

    def get(self, name: str | None, token: str | None = None) -> Session:
        name = name or DEFAULT
        with self._lock:
            record = self._records.get(name)
            if record is None:
                raise OpError(
                    "unknown_session",
                    f"no session {name!r}; sessions: {', '.join(sorted(self._records))}",
                )
            self._authorize(record, token)
            return self._runtime(record)

    @staticmethod
    def _authorize(record: SessionRecord, token: str | None) -> None:
        if not record.sealed:
            return
        if not token or not hmac.compare_digest(hash_token(token), record.token_hash or ""):
            raise OpError("session_sealed", f"session {record.name!r} is sealed")

    def _runtime(self, record: SessionRecord) -> Session:
        found = self._live.get(record.name)
        if found is None:
            root = self._log_root / "sessions" / record.name if self._log_root else None
            factory = (
                (lambda: SessionRecorder(root, **self._recorder_options)) if root else None
            )
            found = Session(
                record,
                self._build_browser(record),
                recorder_factory=factory,
                log_root=root,
            )
            self._live[record.name] = found
        return found

    def _build_browser(self, record: SessionRecord) -> BrowserSession:
        # Captured by value: a later `update` rebinds record.profile, and the
        # old browser must keep letting go of the profile it was on.
        name, profile = record.name, record.profile

        def connect() -> str:
            self.profiles.require(profile)
            # Read at connect time, so a change to the setting applies the next
            # time this session starts the profile's browser.
            hidden = record.settings.get("headless")
            return self.profiles.attach(
                profile, name, headed=None if hidden is None else not hidden
            )

        attach = Attach(
            connect=connect,
            disconnect=lambda: self.profiles.detach(profile, name),
            list_targets=lambda: self.profiles.targets(profile),
            gate=TabGate(self.profiles.tabs(profile), name),
        )
        browser = self._make_browser(self.profiles.path(profile), attach)
        # Read when the browser starts: what was open last -- but only for a
        # session in the middle of its work. Reopening an idle session's old
        # pages brought back tabs the person had long finished with.
        def pages_to_restore():
            live = self._live.get(name)
            at = (live.activity or {}).get("at") if live is not None else None
            if not at or time.time() - at > RESTORE_WITHIN_SECONDS:
                return None
            return record.pages

        browser.pages_to_restore = pages_to_restore
        if self.files_root is not None:
            # Per profile, like the logins: every chat and agent on a profile
            # shares one uploads and one downloads folder, so a file is where
            # you would look for it, not scattered one folder per chat.
            browser.uploads_dir = self.files_root / profile / "uploads"
            browser.downloads_dir = self.files_root / profile / "downloads"
            # Only files the person put in the uploads folder reach a page --
            # except in `default`, which keeps what scripts driving it
            # have always been able to do, unless its settings say otherwise.
            browser.uploads_only_default = name != DEFAULT
        browser.apply_settings(record.settings)
        return browser

    # --- management ---------------------------------------------------------------

    def create(
        self,
        name: str,
        profile: str = DEFAULT,
        sealed: bool = False,
        settings: dict | None = None,
    ) -> dict:
        check_name(name, "session")
        self.profiles.require(profile)
        validate_settings(settings)
        token = None
        with self._lock:
            if name in self._records:
                raise OpError("session_exists", f"session {name!r} already exists")
            record = SessionRecord(
                name=name,
                profile=profile,
                sealed=bool(sealed),
                created=_now(),
                settings=dict(settings or {}),
            )
            if record.sealed:
                token = secrets.token_urlsafe(32)
                record.token_hash = hash_token(token)
                self.store.write_token(name, token)
            self.store.save(record)
            self._records[name] = record
        out = record.public()
        if token:
            # The only time the token is ever returned.
            out["token"] = token
        return out

    def update(
        self,
        name: str,
        token: str | None = None,
        profile: str | None = None,
        settings: dict | None = None,
    ) -> dict:
        validate_settings(settings)
        session = self.get(name, token)
        record = session.record
        if name == DEFAULT and profile not in (None, DEFAULT):
            raise OpError("invalid_op", "the default session always uses the default profile")
        warning = None
        with session.lock:
            if profile is not None and profile != record.profile:
                self.profiles.require(profile)
                was_running = session.browser.is_running
                session.browser.stop()
                record.profile = profile
                session.browser = self._build_browser(record)
                warning = "profile changed: this session's tabs were closed"
                if was_running:
                    warning += "; send browser_start to connect to the new profile"
            if settings is not None:
                merged = {**record.settings, **settings}
                record.settings = {k: v for k, v in merged.items() if v is not None}
                session.browser.apply_settings(record.settings)
            self.store.save(record)
        out = record.public()
        if warning:
            out["warning"] = warning
        return out

    def remove(self, name: str, token: str | None = None) -> None:
        if name == DEFAULT:
            raise OpError("invalid_op", "the default session cannot be removed")
        session = self.get(name, token)
        with session.lock:
            session.closed = True
            session.close()
        with self._lock:
            self._live.pop(name, None)
            self._records.pop(name, None)
        self.store.delete(name)
        self._retire_logs(name, session.log_root)

    def _retire_logs(self, name: str, root: Path | None) -> None:
        """Keep a removed session's logs, but not where its name points.

        Otherwise the next session created under the same name -- by anyone --
        would read every event and frame of the one removed, sealed or not.
        """
        if root is None or not root.exists() or self._log_root is None:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        retired = self._log_root / "removed-sessions" / f"{name}-{stamp}"
        retired.parent.mkdir(parents=True, exist_ok=True)
        root.rename(retired)

    def info(self, name: str, token: str | None = None) -> dict:
        with self._lock:
            record = self._records.get(name)
        if record is None:
            raise OpError("unknown_session", f"no session {name!r}")
        try:
            self._authorize(record, token)
            authorized = True
        except OpError:
            authorized = False
        return record.public(with_settings=authorized)

    def list(self) -> list[dict]:
        with self._lock:
            records = sorted(self._records.values(), key=lambda r: r.name)
            live = dict(self._live)
        rows = []
        for record in records:
            row = record.public(with_settings=not record.sealed)
            session = live.get(record.name)
            row["running"] = bool(session and session.browser.is_running)
            row["tabs"] = len(self.profiles.tabs(record.profile).owned_by(record.name))
            rows.append(row)
        return rows

    def profile_in_use(self, profile: str) -> bool:
        with self._lock:
            return any(r.profile == profile for r in self._records.values())

    def remove_profile(self, name: str) -> None:
        self.profiles.remove(name, in_use=self.profile_in_use(name))

    def is_operator(self, token: str | None) -> bool:
        return bool(
            self.operator_token and token and hmac.compare_digest(token, self.operator_token)
        )

    def touch(self, session: Session) -> None:
        self.profiles.touch(session.record.profile)

    # --- idle shutdown ------------------------------------------------------------

    def reap_idle(self) -> list[str]:
        """Stop browsers nobody has used for a while.

        A profile with any session mid-command is skipped rather than waited
        for: a busy session is by definition not idle, and blocking the reaper
        on one would stall every other profile's shutdown behind it.
        """
        stopped = []
        for profile in self.profiles.idle():
            with self._lock:
                sessions = [
                    s for s in self._live.values()
                    if s.record.profile == profile and s.browser.is_running
                ]
            acquired = []
            busy = False
            for session in sessions:
                if session.lock.acquire(blocking=False):
                    acquired.append(session)
                else:
                    busy = True
                    break
            try:
                if busy:
                    continue
                for session in acquired:
                    session.browser.stop()
                self.profiles.stop(profile)
                stopped.append(profile)
            finally:
                for session in acquired:
                    session.lock.release()
        return stopped

    def start_reaper(self, interval: float = 60.0) -> threading.Thread:
        def loop() -> None:
            while not self._stop_reaper.wait(interval):
                try:
                    self.reap_idle()
                except Exception:
                    pass

        def pages_loop() -> None:
            while not self._stop_reaper.wait(PAGES_REFRESH_SECONDS):
                self.refresh_pages()

        threading.Thread(target=pages_loop, name="abt-pages", daemon=True).start()
        thread = threading.Thread(target=loop, name="abt-reaper", daemon=True)
        thread.start()
        return thread

    @staticmethod
    def note_activity(session: Session, op: str, ok: bool, now: float) -> None:
        """Count one command toward the session's current stretch of work."""
        last = session.activity
        fresh = not last or now - last.get("at", 0) > Session.ACTIVITY_GAP_SECONDS
        session.activity = {
            "op": op,
            "ok": ok,
            "at": now,
            "steps": 1 if fresh else last.get("steps", 0) + 1,
            "since": now if fresh else last.get("since", now),
        }

    def remember_pages(self, session: Session) -> None:
        """Note the session's open pages, so a restart can reopen them.

        Saved only when they changed. A browser that has just died lists no
        pages -- `page_snapshot` answers None then -- and that must not erase
        the last good list. With the browser alive, though, the list is what is
        really open, empty included: a tab the person closed by hand stays
        closed, where it used to come back at the next restart.
        """
        snapshot = session.browser.page_snapshot()
        if snapshot is None or snapshot == session.record.pages:
            return
        if not snapshot["urls"] and not session.record.pages:
            return
        session.record.pages = snapshot
        self.store.save(session.record)

    def refresh_pages(self) -> None:
        """Keep idle sessions' page lists in step with their tabs.

        After a command is not enough: a tab closed by hand between commands
        was still on the list when the browser next restarted. A session mid
        command is skipped -- it records its pages when the command ends.
        """
        with self._lock:
            sessions = [s for s in self._live.values() if s.browser.is_running]
        for session in sessions:
            if not session.lock.acquire(blocking=False):
                continue
            try:
                self.remember_pages(session)
            except Exception:
                pass
            finally:
                session.lock.release()

    def close_all(self) -> None:
        self._stop_reaper.set()
        with self._lock:
            sessions = list(self._live.values())
        for session in sessions:
            session.close()
        self.profiles.stop_all()


class SingleSessionRegistry:
    """The legacy shape: one BrowserSession, called `default`, nothing else.

    What `create_app(browser_session)` wraps its argument in, so the server has
    one code path. It behaves exactly as the server did before sessions.
    """

    profiles = None
    operator_token = None

    def __init__(self, browser: BrowserSession, recorder: SessionRecorder | None) -> None:
        record = SessionRecord(name=DEFAULT)
        self._session = Session(
            record,
            browser,
            recorder=recorder,
            log_root=recorder.root if recorder is not None else None,
        )

    def get(self, name: str | None = None, token: str | None = None) -> Session:
        if name not in (None, DEFAULT):
            raise OpError("unknown_session", f"no session {name!r}: {NO_SESSIONS}")
        return self._session

    def list(self) -> list[dict]:
        return [{**self._session.record.public(), "running": self._session.browser.is_running}]

    def info(self, name: str, token: str | None = None) -> dict:
        return self.get(name).record.public()

    def create(self, *args, **kwargs) -> dict:
        raise OpError("invalid_op", NO_SESSIONS)

    update = create
    remove = create
    remove_profile = create

    def is_operator(self, token: str | None) -> bool:
        return False

    def touch(self, session: Session) -> None:
        pass

    def close_all(self) -> None:
        self._session.browser.quit()
        recorder = self._session.started_recorder
        if recorder is not None:
            recorder.close()
