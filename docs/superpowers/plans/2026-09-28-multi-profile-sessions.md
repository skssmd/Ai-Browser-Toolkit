# Multi-Profile Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One abt server runs one hidden Chrome per profile and executes commands in named sessions — each with its own profile, lock, Playwright connection, tabs and log — in parallel, with sealed sessions that only a token holder can drive.

**Architecture:** `ProfileRegistry` launches Chrome per profile with a CDP port. Each session's `BrowserSession` connects its own `PlaywrightDriver` to that Chrome in attach mode, filtered through a per-profile `TabRegistry` that records tab ownership. `SessionRegistry` persists sessions and resolves every request to one; `server.py` runs each request under that session's lock. The legacy `create_app(browser_session)` path is wrapped as a one-session registry and behaves exactly as today.

**Tech Stack:** Python 3.11+, FastAPI/uvicorn, Playwright (sync API, `connect_over_cdp`), httpx, `websockets` (new), Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-multi-profile-sessions-design.md`

## Global Constraints

- **Never run the test suite locally** — not the whole suite, not one file, not `-k`. CI runs it on push. Every "verify" step below is a read-through or a throwaway probe script in the session scratchpad, never pytest. (Standing user rule.)
- **Push only with the user's go-ahead.** Pushing triggers CI; ask before each push.
- **Commit messages carry no `Co-Authored-By` or AI attribution.** (Standing user rule.)
- **Never run `abt serve` from a tool call.** Use `start-server.bat` / `./start-server.sh` / `abt up` if a server is needed.
- Profile and session names: `^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$` (lowercase, no trailing dot: NTFS folds case and drops a trailing dot), resolved path asserted inside its root.
- Transport: headers `X-ABT-Session`, `X-ABT-Token`; body fields `session`, `token`; env `ABT_SESSION`, `ABT_TOKEN`.
- New error types: `unknown_session`, `session_exists`, `session_sealed`, `tab_locked`, `profile_limit`, `profile_in_use`, `profile_not_found`. Malformed input stays `invalid_op`.
- Defaults: `--max-profiles 4`, `--profile-idle-minutes 30`.
- One new runtime dependency only: `websockets>=13`.
- `create_app(browser_session)` and `--engine selenium` keep today's behaviour byte for byte.
- Code style: `from __future__ import annotations`; comments explain *why*, in the voice of the surrounding code.

## Review Focus

1. **A name that is a path** (`../x`, `C:\x`, `a/b`, `.hidden`) given as a session or profile name must be refused with `invalid_op` and must never create, write or delete anything outside its root. → Task 3 and Task 7 tests.
2. **A bare command carrying `"session": "a"`** must reach session `a`, not be rejected by the schema's `extra="forbid"`. → Task 8 test.
3. **A server restart with a sealed session on disk**: the token issued before the restart must still work and a wrong one must still fail. → Task 7 test.
4. **Removing or stopping one session on a shared profile** must close only that session's tabs; the other session keeps working. → Task 5 test.
5. **Chrome already open on a profile** (a user's own window) must turn `browser_start` into a prompt `browser_dead` naming the lock, not a 60-second hang. → Task 3 test.

## Priority task list

| # | Task | Priority |
|---|---|---|
| 1 | Errors, paths, dependency | P0 |
| 2 | `TabRegistry` and `TabGate` | P0 |
| 3 | `ProfileRegistry` | P0 |
| 4 | `ProfileRegistry` against real Chrome | P0 |
| 5 | Attach mode in `PlaywrightDriver` | P0 |
| 6 | `BrowserSession` attach mode and tab ops | P0 |
| 7 | `SessionRegistry` | P0 |
| 8 | Server: resolve a session per request | P0 |
| 9 | Server: session, profile and tab-owner routes; per-session logs | P1 |
| 10 | Screencast | P1 |
| 11 | CLI and MCP | P1 |
| 12 | End-to-end live tests | P1 |
| 13 | Viewer picker and documentation | P2 |

Push points (ask first): after Task 6, after Task 9, after Task 13.

---

### Task 1: Errors, paths, dependency

**Files:**
- Modify: `src/abt/errors.py` (the `HINTS` dict)
- Modify: `src/abt/paths.py` (append two functions)
- Modify: `pyproject.toml` (`dependencies`)
- Modify: `.gitignore`
- Test: `tests/test_paths.py`, create `tests/test_session_errors.py`

**Interfaces:**
- Produces: `paths.profile_root(kind=None, home=None, env=None, cwd=None) -> Path`, `paths.sessions_dir(...) -> Path`; error types listed in Global Constraints.

- [ ] **Step 1: Write the tests**

Append to `tests/test_paths.py`:

```python
def test_sessions_dir_sits_beside_the_profiles_when_installed(home, elsewhere):
    env = {"LOCALAPPDATA": str(home / "local")}
    got = paths.sessions_dir(kind="windows", home=home, env=env, cwd=elsewhere)
    assert got == home / "local" / "AIBrowserToolkit" / "sessions"
    assert paths.profile_root(kind="windows", home=home, env=env, cwd=elsewhere) == (
        home / "local" / "AIBrowserToolkit" / "profiles"
    )


def test_sessions_dir_is_in_the_checkout_inside_one(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "ai-browser-toolkit"\n', encoding="utf-8"
    )
    assert paths.sessions_dir(cwd=tmp_path) == tmp_path / "sessions"
    assert paths.profile_root(cwd=tmp_path) == tmp_path / "profiles"
```

Create `tests/test_session_errors.py`:

```python
"""The session error types exist and each says what to do."""

from __future__ import annotations

import pytest

from abt.errors import ERROR_TYPES, OpError

NEW = (
    "unknown_session",
    "session_exists",
    "session_sealed",
    "tab_locked",
    "profile_limit",
    "profile_in_use",
    "profile_not_found",
)


@pytest.mark.parametrize("kind", NEW)
def test_each_session_error_has_a_hint(kind):
    assert kind in ERROR_TYPES
    assert OpError(kind, "x").hint
```

- [ ] **Step 2: Implement**

In `src/abt/errors.py`, add to `HINTS` after `"browser_not_found"`:

```python
    "unknown_session": (
        "`abt session list` shows what exists. Sessions are created by whoever "
        "launches the agent (`abt session new NAME --profile P`); a command "
        "never creates one, so a typo cannot land you somewhere unrestricted."
    ),
    "session_exists": "Pick another name, or use the session that is already there.",
    "session_sealed": (
        "This session is sealed: only the program that created it holds its "
        "token. It is not addressable from here -- use your own session."
    ),
    "tab_locked": (
        "Another session owns this tab. Open your own with `tab_new` rather "
        "than retrying: the lock lasts as long as its owner holds the tab."
    ),
    "profile_limit": (
        "Too many browsers are running. `browser_stop` in a session on a "
        "profile you are done with, or restart the server with a higher "
        "--max-profiles. Nothing is ever closed to make room."
    ),
    "profile_in_use": (
        "Remove or move the sessions using this profile, and stop its "
        "browser, before removing it."
    ),
    "profile_not_found": (
        "`abt profile list` shows what exists; `abt profile new NAME` "
        "creates one."
    ),
```

Append to `src/abt/paths.py`:

```python
def profile_root(
    kind: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """The directory named profiles live in: the default profile's parent."""
    return default_profile(kind, home, env, cwd).parent


def sessions_dir(
    kind: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Where session records, sealed-session tokens and the operator token live.

    Beside the profile root rather than inside it: a profile directory is a
    Chrome user-data-dir, and a name there is a profile name.
    """
    return profile_root(kind, home, env, cwd).parent / "sessions"
```

In `pyproject.toml` `dependencies`, after `"httpx>=0.27",` add:

```toml
    # Chrome's DevTools WebSocket for the screencast, and what gives uvicorn
    # WebSocket support at all.
    "websockets>=13",
```

In `.gitignore`, after the `profiles/` line add:

```
# Session records and tokens. A sealed session's token is a credential.
sessions/
```

- [ ] **Step 3: Verify by reading**

Re-read `paths.default_profile`: in a checkout it returns `<cwd>/profiles/default`, so `.parent.parent / "sessions"` is `<cwd>/sessions`; installed on Windows it is `%LOCALAPPDATA%/AIBrowserToolkit/profiles/default`, so the result is `.../AIBrowserToolkit/sessions`. Matches both tests.

- [ ] **Step 4: Commit**

```bash
git add src/abt/errors.py src/abt/paths.py pyproject.toml .gitignore tests/test_paths.py tests/test_session_errors.py
git commit -m "Add session error types, session paths and the websockets dependency"
```

---

### Task 2: `TabRegistry` and `TabGate`

**Files:**
- Create: `src/abt/tabs.py`
- Test: `tests/test_tabs_registry.py`

**Interfaces:**
- Produces:
  - `tabs.OWN`, `tabs.LOCKED`, `tabs.UNOWNED` (str constants)
  - `TabRegistry(profile: str)` with `label(target) -> str`, `target_of(label) -> str | None`, `owner_of(target) -> str | None`, `opened(target, session) -> str`, `adopt(target, opener: str | None) -> str | None`, `claim(target, session, opener: str | None = None) -> str`, `release(target, session) -> None`, `set_owner(target, session: str | None) -> str`, `access(target, session) -> str`, `owned_by(session) -> list[str]`, `forget(target) -> None`, `clear() -> None`
  - `TabGate(registry, session)` with attributes `registry`, `session` and `opened(target) -> str`, `sees(target, opener) -> bool`, `owns(target) -> bool`, `owner(target) -> str | None`, `label(target) -> str`, `target_of(label) -> str | None`, `check(label) -> None`, `claim(target, opener) -> str`, `release(target) -> None`

- [ ] **Step 1: Write the tests**

Create `tests/test_tabs_registry.py`:

```python
"""Tab ownership per profile. Pure bookkeeping, no browser."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.tabs import LOCKED, OWN, UNOWNED, TabGate, TabRegistry


@pytest.fixture
def reg():
    return TabRegistry("work")


def test_labels_are_stable_and_never_reissued(reg):
    assert reg.label("T1") == "tab_0"
    assert reg.label("T1") == "tab_0"
    assert reg.label("T2") == "tab_1"
    reg.forget("T1")
    assert reg.target_of("tab_0") is None
    assert reg.label("T3") == "tab_2"
    reg.clear()
    assert reg.label("T4") == "tab_3"


def test_a_tab_a_session_opened_is_its_own(reg):
    assert reg.opened("T1", "a") == "tab_0"
    assert reg.access("T1", "a") == OWN
    assert reg.access("T1", "b") == LOCKED


def test_opening_a_tab_someone_else_owns_is_refused(reg):
    reg.opened("T1", "a")
    with pytest.raises(OpError) as exc:
        reg.opened("T1", "b")
    assert exc.value.type == "tab_locked"
    assert "'a'" in exc.value.message


def test_a_popup_follows_its_openers_owner(reg):
    reg.opened("T1", "a")
    assert reg.adopt("POP", opener="T1") == "a"
    assert reg.owned_by("a") == ["T1", "POP"]


def test_a_page_with_no_owned_opener_starts_unowned(reg):
    assert reg.adopt("T9", opener=None) is None
    assert reg.access("T9", "a") == UNOWNED


def test_adopt_never_moves_a_placed_tab(reg):
    reg.opened("T1", "a")
    reg.opened("T2", "b")
    assert reg.adopt("T1", opener="T2") == "a"


def test_an_unowned_tab_can_be_claimed(reg):
    reg.adopt("T9", None)
    assert reg.claim("T9", "a") == "tab_0"
    assert reg.owner_of("T9") == "a"


def test_claiming_a_locked_tab_names_the_owner(reg):
    reg.opened("T1", "a")
    with pytest.raises(OpError) as exc:
        reg.claim("T1", "b")
    assert exc.value.type == "tab_locked"


def test_nobody_can_claim_someone_elses_popup_first(reg):
    """The window between a popup appearing and its owner noticing it."""
    reg.opened("T1", "a")
    with pytest.raises(OpError) as exc:
        reg.claim("POP", "b", opener="T1")
    assert exc.value.type == "tab_locked"
    assert reg.owner_of("POP") == "a"


def test_only_the_owner_can_release(reg):
    reg.opened("T1", "a")
    with pytest.raises(OpError):
        reg.release("T1", "b")
    reg.release("T1", "a")
    assert reg.owner_of("T1") is None


def test_the_operator_overrides_without_checks(reg):
    reg.opened("T1", "a")
    reg.set_owner("T1", "b")
    assert reg.owner_of("T1") == "b"


def test_gate_check_refuses_locked_and_unowned_and_passes_unknown(reg):
    reg.opened("T1", "a")
    reg.adopt("T2", None)
    gate = TabGate(reg, "b")
    for label in ("tab_0", "tab_1"):
        with pytest.raises(OpError) as exc:
            gate.check(label)
        assert exc.value.type == "tab_locked"
    gate.check("tab_99")  # unknown here: the session reports it as not found
    TabGate(reg, "a").check("tab_0")


def test_gate_sees_only_its_own(reg):
    reg.opened("T1", "a")
    assert TabGate(reg, "a").sees("T1", None) is True
    assert TabGate(reg, "b").sees("T1", None) is False
    assert TabGate(reg, "b").sees("POP", "T1") is False
    assert TabGate(reg, "a").sees("POP", "T1") is True
```

- [ ] **Step 2: Implement**

Create `src/abt/tabs.py`:

```python
"""Which session owns which tab, per profile.

One `TabRegistry` per profile, keyed on Chrome's target id -- the one identity
every connection to that Chrome agrees on. It also hands out the `tab_N` ids
callers see, so two sessions on one profile, and the GUI watching them, call
the same tab by the same name.

Pure bookkeeping: no browser, no I/O. The lock is held only to read or change
the maps, never across browser work, so it can never make one session wait on
another's click.
"""

from __future__ import annotations

import threading

from .errors import OpError

OWN = "own"
LOCKED = "locked"
UNOWNED = "unowned"


class TabRegistry:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self._lock = threading.Lock()
        # target -> owning session, or None for a tab nobody owns. A target
        # missing from this map has not been seen yet.
        self._owner: dict[str, str | None] = {}
        self._label: dict[str, str] = {}
        self._target: dict[str, str] = {}
        # Never reset, not even when Chrome restarts: a stale `tab_3` has to
        # fail as not-found rather than quietly land on a newer tab.
        self._counter = 0

    # --- ids ------------------------------------------------------------------

    def label(self, target: str) -> str:
        with self._lock:
            return self._label_of(target)

    def _label_of(self, target: str) -> str:
        found = self._label.get(target)
        if found is None:
            found = f"tab_{self._counter}"
            self._counter += 1
            self._label[target] = found
            self._target[found] = target
        return found

    def target_of(self, label: str) -> str | None:
        with self._lock:
            return self._target.get(label)

    # --- ownership ------------------------------------------------------------

    def owner_of(self, target: str) -> str | None:
        with self._lock:
            return self._owner.get(target)

    def opened(self, target: str, session: str) -> str:
        """A tab `session` opened itself. Returns its id.

        Another connection may already have noticed the page and recorded it
        as unowned -- that is not a conflict, only an owner is.
        """
        with self._lock:
            label = self._label_of(target)
            current = self._owner.get(target)
            if current not in (None, session):
                raise _locked(label, current)
            self._owner[target] = session
            return label

    def adopt(self, target: str, opener: str | None) -> str | None:
        """Place a page seen for the first time, and return its owner.

        A page opened by another page belongs to whoever owns the opener, so a
        popup follows the session that caused it. Anything else starts
        unowned. A page already placed keeps its owner.
        """
        with self._lock:
            self._label_of(target)
            if target in self._owner:
                return self._owner[target]
            owner = self._owner.get(opener) if opener else None
            self._owner[target] = owner
            return owner

    def claim(self, target: str, session: str, opener: str | None = None) -> str:
        """Take an unowned tab. A popup of someone else's tab is theirs, even
        if they have not noticed it yet -- otherwise there is a window in which
        any session can take it."""
        with self._lock:
            label = self._label_of(target)
            current = self._owner.get(target)
            if current is None and opener:
                current = self._owner.get(opener)
                if current is not None:
                    self._owner[target] = current
            if current not in (None, session):
                raise _locked(label, current)
            self._owner[target] = session
            return label

    def release(self, target: str, session: str) -> None:
        with self._lock:
            current = self._owner.get(target)
            if current != session:
                raise _locked(self._label_of(target), current)
            self._owner[target] = None

    def set_owner(self, target: str, session: str | None) -> str:
        """The operator's override. No ownership check, by design."""
        with self._lock:
            self._owner[target] = session
            return self._label_of(target)

    def access(self, target: str, session: str) -> str:
        with self._lock:
            owner = self._owner.get(target)
        if owner == session:
            return OWN
        return UNOWNED if owner is None else LOCKED

    def owned_by(self, session: str) -> list[str]:
        with self._lock:
            return [t for t, owner in self._owner.items() if owner == session]

    def forget(self, target: str) -> None:
        with self._lock:
            self._owner.pop(target, None)
            label = self._label.pop(target, None)
            if label is not None:
                self._target.pop(label, None)

    def clear(self) -> None:
        """Chrome restarted and every tab went with it. Ids are not reissued."""
        with self._lock:
            self._owner.clear()
            self._label.clear()
            self._target.clear()


def _locked(label: str, owner: str | None) -> OpError:
    if owner is None:
        return OpError(
            "tab_locked",
            f"{label} is not yours: nobody owns it",
            hint="Take it with tab_claim, or open your own with tab_new.",
        )
    return OpError("tab_locked", f"{label} belongs to session {owner!r}")


class TabGate:
    """One session's view of its profile's registry.

    What the driver and `BrowserSession` hold. They only ever ask about their
    own session, so the name is bound once here instead of being threaded
    through every call.
    """

    def __init__(self, registry: TabRegistry, session: str) -> None:
        self.registry = registry
        self.session = session

    def opened(self, target: str) -> str:
        return self.registry.opened(target, self.session)

    def sees(self, target: str, opener: str | None) -> bool:
        return self.registry.adopt(target, opener) == self.session

    def owns(self, target: str) -> bool:
        return self.registry.owner_of(target) == self.session

    def owner(self, target: str) -> str | None:
        return self.registry.owner_of(target)

    def label(self, target: str) -> str:
        return self.registry.label(target)

    def target_of(self, label: str) -> str | None:
        return self.registry.target_of(label)

    def check(self, label: str) -> None:
        """Refuse a tab id this session may not act on.

        An id this profile has never issued passes: the session's own tab
        registry then reports it as `tab_not_found`, exactly as it does today.
        """
        target = self.registry.target_of(label)
        if target is None:
            return
        if self.registry.access(target, self.session) != OWN:
            raise _locked(label, self.registry.owner_of(target))

    def claim(self, target: str, opener: str | None) -> str:
        return self.registry.claim(target, self.session, opener)

    def release(self, target: str) -> None:
        self.registry.release(target, self.session)
```

- [ ] **Step 3: Verify with a probe**

Write `<scratchpad>/probe_tabs.py` that imports `abt.tabs`, replays three of the tests (popup follows opener, claim of someone else's popup refused, labels not reissued after `clear`) with plain `assert`s, and run it with `py <scratchpad>/probe_tabs.py` from the repo root (`PYTHONPATH=src`). It must print nothing and exit 0. Delete it afterwards.

- [ ] **Step 4: Commit**

```bash
git add src/abt/tabs.py tests/test_tabs_registry.py
git commit -m "Add per-profile tab ownership: TabRegistry and TabGate"
```

---

### Task 3: `ProfileRegistry`

**Files:**
- Create: `src/abt/profiles.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `tabs.TabRegistry`; `browser._profile_locked(config)` (reads `config.profile`); `doctor.find_browsers()`.
- Produces:
  - `profiles.DEFAULT = "default"`, `profiles.NAME` (compiled regex), `check_name(name, what="profile") -> str`, `launch_argv(binary: Path, profile_dir: Path, headed: bool) -> list[str]`
  - `Running` dataclass: `process`, `port: int`, `headed: bool`, `sessions: set[str]`, `watchers: int`, `last_used: float`; `.url` (`http://127.0.0.1:<port>`), `.alive()`
  - `ProfileRegistry(root, default_dir=None, browser="chrome", max_running=4, idle_minutes=30.0, default_headed=False, spawn=None, find_binary=None, http_get=None, clock=time.monotonic, launch_timeout=60.0)` with `path(name)`, `exists(name)`, `require(name) -> str`, `meta(name) -> dict`, `describe(name) -> dict`, `list() -> list[dict]`, `create(name) -> dict`, `set_headed(name, headed) -> dict`, `remove(name, in_use: bool) -> None`, `tabs(name) -> TabRegistry`, `attach(name, session) -> str` (CDP URL), `detach(name, session) -> None`, `touch(name)`, `watch(name, delta: int)`, `running(name) -> Running | None`, `idle() -> list[str]`, `stop(name) -> bool`, `stop_all()`, `targets(name) -> list[dict]`; attribute `idle_seconds: float`

- [ ] **Step 1: Write the tests**

Create `tests/test_profiles.py`:

```python
"""Named profiles and the Chrome processes on them, with no real Chrome.

`spawn` is faked with a process that writes the DevToolsActivePort file Chrome
would, so launch, reuse, the cap, idle detection and crash recovery are all
checked in milliseconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abt.errors import OpError
from abt.profiles import DEFAULT, ProfileRegistry, check_name, launch_argv


class FakeProcess:
    _next_port = 9300

    def __init__(self, argv, write_port=True):
        self.argv = argv
        self.returncode = None
        profile = next(a for a in argv if a.startswith("--user-data-dir="))
        self.dir = Path(profile.split("=", 1)[1])
        if write_port:
            FakeProcess._next_port += 1
            (self.dir / "DevToolsActivePort").write_text(
                f"{FakeProcess._next_port}\n/devtools/browser/x", encoding="utf-8"
            )

    def poll(self):
        return self.returncode

    def die(self):
        self.returncode = 1

    def wait(self, timeout=None):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def spawned():
    return []


@pytest.fixture
def make(tmp_path, spawned):
    def build(**kw):
        def spawn(argv):
            process = FakeProcess(argv)
            spawned.append(process)
            return process

        kw.setdefault("spawn", spawn)
        kw.setdefault("find_binary", lambda browser: Path("/bin/chrome"))
        kw.setdefault("http_get", lambda url: [])
        return ProfileRegistry(root=tmp_path / "profiles", **kw)

    return build


@pytest.mark.parametrize(
    "bad", ["", "..", "../x", "/abs", "C:\\x", "a/b", "a\\b", ".hidden", "x" * 65, "a b"]
)
def test_names_that_are_paths_are_refused(bad):
    with pytest.raises(OpError) as exc:
        check_name(bad)
    assert exc.value.type == "invalid_op"


@pytest.mark.parametrize("good", ["work", "a.b-c_1", "A1", "x" * 64])
def test_ordinary_names_pass(good):
    assert check_name(good) == good


def test_default_lives_where_serve_was_told(make, tmp_path):
    reg = make(default_dir=tmp_path / "custom")
    assert reg.path(DEFAULT) == (tmp_path / "custom").resolve()
    assert reg.path("work") == (tmp_path / "profiles" / "work").resolve()


def test_create_list_remove(make):
    reg = make()
    reg.create("work")
    names = [p["name"] for p in reg.list()]
    assert names == ["default", "work"]
    with pytest.raises(OpError) as exc:
        reg.create("work")
    assert exc.value.type == "invalid_op"
    reg.remove("work", in_use=False)
    assert [p["name"] for p in reg.list()] == ["default"]


def test_a_bad_name_touches_nothing(make, tmp_path):
    reg = make()
    with pytest.raises(OpError):
        reg.create("../escape")
    assert not (tmp_path / "escape").exists()


def test_remove_is_refused_for_default_in_use_or_missing(make):
    reg = make()
    reg.create("work")
    with pytest.raises(OpError) as exc:
        reg.remove(DEFAULT, in_use=False)
    assert exc.value.type == "invalid_op"
    with pytest.raises(OpError) as exc:
        reg.remove("work", in_use=True)
    assert exc.value.type == "profile_in_use"
    with pytest.raises(OpError) as exc:
        reg.remove("ghost", in_use=False)
    assert exc.value.type == "profile_not_found"


def test_remove_is_refused_while_its_browser_runs(make):
    reg = make()
    reg.create("work")
    reg.attach("work", "s")
    with pytest.raises(OpError) as exc:
        reg.remove("work", in_use=False)
    assert exc.value.type == "profile_in_use"


def test_headed_persists(make):
    reg = make()
    reg.create("work")
    reg.set_headed("work", True)
    assert reg.meta("work")["headed"] is True


def test_default_headed_follows_the_server_until_set(make):
    assert make(default_headed=True).meta(DEFAULT)["headed"] is True
    assert make(default_headed=False).meta(DEFAULT)["headed"] is False


def test_launch_argv_hides_and_unthrottles(tmp_path):
    argv = launch_argv(Path("/bin/chrome"), tmp_path, headed=False)
    assert f"--user-data-dir={tmp_path}" in argv
    assert "--remote-debugging-port=0" in argv
    assert "--headless=new" in argv
    for flag in (
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
    ):
        assert flag in argv
    assert "--headless=new" not in launch_argv(Path("/bin/chrome"), tmp_path, headed=True)


def test_attach_launches_once_and_detach_stops_after_the_last(make, spawned):
    reg = make()
    url = reg.attach(DEFAULT, "a")
    assert url.startswith("http://127.0.0.1:")
    assert reg.attach(DEFAULT, "b") == url
    assert len(spawned) == 1
    reg.detach(DEFAULT, "a")
    assert reg.running(DEFAULT) is not None
    reg.detach(DEFAULT, "b")
    assert reg.running(DEFAULT) is None
    assert spawned[0].returncode is not None


def test_the_cap_refuses_and_never_evicts(make):
    reg = make(max_running=1)
    reg.create("other")
    reg.attach(DEFAULT, "a")
    with pytest.raises(OpError) as exc:
        reg.attach("other", "b")
    assert exc.value.type == "profile_limit"
    assert reg.running(DEFAULT) is not None


def test_a_dead_chrome_is_relaunched_with_its_tabs_forgotten(make, spawned):
    reg = make()
    reg.attach(DEFAULT, "a")
    reg.tabs(DEFAULT).opened("T1", "a")
    spawned[0].die()
    reg.attach(DEFAULT, "a")
    assert len(spawned) == 2
    assert reg.tabs(DEFAULT).owner_of("T1") is None


def test_a_profile_held_by_another_chrome_fails_fast(make, tmp_path):
    """Review focus 5: Chrome's single-instance handoff exits at once."""
    def spawn(argv):
        process = FakeProcess(argv, write_port=False)
        (process.dir / "SingletonLock").write_text("", encoding="utf-8")
        process.die()
        return process

    reg = make(spawn=spawn, launch_timeout=30.0)
    with pytest.raises(OpError) as exc:
        reg.attach(DEFAULT, "a")
    assert exc.value.type == "browser_dead"
    assert "holding the profile" in exc.value.message


def test_no_browser_installed(make):
    reg = make(find_binary=lambda browser: None)
    with pytest.raises(OpError) as exc:
        reg.attach(DEFAULT, "a")
    assert exc.value.type == "browser_not_found"


def test_idle_skips_watched_and_disabled(make):
    now = [100.0]
    reg = make(clock=lambda: now[0], idle_minutes=1)
    reg.create("watched")
    reg.attach(DEFAULT, "a")
    reg.attach("watched", "b")
    reg.watch("watched", +1)
    now[0] += 61
    assert reg.idle() == [DEFAULT]
    reg.touch(DEFAULT)
    assert reg.idle() == []
    assert make(idle_minutes=0).idle() == []


def test_targets_are_pages_only(make):
    rows = [{"id": "A", "type": "page"}, {"id": "B", "type": "service_worker"}]
    reg = make(http_get=lambda url: rows)
    reg.attach(DEFAULT, "a")
    assert [r["id"] for r in reg.targets(DEFAULT)] == ["A"]
```

- [ ] **Step 2: Implement**

Create `src/abt/profiles.py`:

```python
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

from .errors import OpError
from .tabs import TabRegistry

# A name becomes a path, so this is a security check rather than tidiness: it
# rejects `..`, separators, drive letters and leading dots by construction.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
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
            f"bad {what} name {name!r}: use letters, digits, '.', '_' and '-', "
            "starting with a letter or digit, at most 64 characters",
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
        # cost of being wrong is deleting something outside the profile root.
        if path.parent != self.root:
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
        headed = data.get("headed")
        if headed is None:
            # The default profile keeps whatever `abt serve` was told, so a
            # server started without --headless still shows its window.
            headed = self.default_headed if name == DEFAULT else False
        return {"name": name, "created": data.get("created"), "headed": bool(headed)}

    def _write_meta(self, name: str, meta: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._meta_path(name).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def describe(self, name: str) -> dict:
        with self._lock:
            running = self._live(name)
            info = {
                "running": running is not None,
                "port": running.port if running else None,
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
        self._write_meta(name, {"name": name, "created": _now(), "headed": False})
        return self.describe(name)

    def set_headed(self, name: str, headed: bool) -> dict:
        self.require(name)
        meta = self.meta(name)
        meta["headed"] = bool(headed)
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

    def attach(self, name: str, session: str) -> str:
        """Make sure `name`'s Chrome is up and count `session` on it."""
        with self._lock:
            launch_lock = self._launch_locks.setdefault(name, threading.Lock())
        with launch_lock:
            with self._lock:
                running = self._live(name)
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
                    running = self._launch(name)
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

    def detach(self, name: str, session: str) -> None:
        """`session` let go. The last one out stops Chrome, unless it is watched."""
        with self._lock:
            running = self._running.get(name)
            if running is None:
                return
            running.sessions.discard(session)
            if running.sessions or running.watchers:
                return
            del self._running[name]
            self._tabs_of(name).clear()
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
        if self.idle_seconds <= 0:
            return []
        now = self._clock()
        with self._lock:
            return sorted(
                name
                for name, running in self._running.items()
                if running.watchers == 0 and now - running.last_used >= self.idle_seconds
            )

    def stop(self, name: str) -> bool:
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

    def _launch(self, name: str) -> Running:
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
        headed = self.meta(name)["headed"]
        process = self._spawn(launch_argv(binary, directory, headed))
        port = self._await_port(process, port_file, directory)
        return Running(process=process, port=port, headed=headed, last_used=self._clock())

    def _await_port(self, process: Any, port_file: Path, directory: Path) -> int:
        deadline = time.monotonic() + self.launch_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                # Chrome single-instances per user-data-dir: a second launch
                # hands off to the incumbent and exits at once. Say so, rather
                # than leaving the caller to wait out the timeout.
                from .browser import _profile_locked

                if _profile_locked(SimpleNamespace(profile=directory)):
                    raise OpError(
                        "browser_dead",
                        f"another browser is holding the profile at {directory} -- "
                        "close it, then start again",
                    )
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
```

- [ ] **Step 3: Verify by reading**

Trace `test_attach_launches_once_and_detach_stops_after_the_last` through `attach`/`detach`: the second `attach` takes the `running is not None` branch (no spawn); `detach("b")` finds no sessions and no watchers, pops, and `_close` calls the fake's `wait`, which sets `returncode`. Trace `test_a_profile_held_by_another_chrome_fails_fast`: `poll()` returns 1 on the first loop, `SingletonLock` exists, so the message contains "holding the profile". Confirm that `_live` is only ever called with `self._lock` held.

- [ ] **Step 4: Commit**

```bash
git add src/abt/profiles.py tests/test_profiles.py
git commit -m "Add ProfileRegistry: named profiles and one hidden Chrome each"
```

---

### Task 4: `ProfileRegistry` against real Chrome

**Files:**
- Test: create `tests/test_profiles_live.py`
- Modify: `src/abt/profiles.py` only if the probe shows a problem

**Interfaces:**
- Consumes: `ProfileRegistry` from Task 3.

- [ ] **Step 1: Write the live test**

Create `tests/test_profiles_live.py`:

```python
"""ProfileRegistry against a real Chrome: launch, list, stop."""

from __future__ import annotations

import httpx
import pytest

from abt.profiles import DEFAULT, ProfileRegistry


@pytest.fixture
def reg(tmp_path):
    registry = ProfileRegistry(root=tmp_path / "profiles")
    yield registry
    registry.stop_all()


def test_a_profile_launches_hidden_and_answers_cdp(reg):
    url = reg.attach(DEFAULT, "a")
    version = httpx.get(f"{url}/json/version", timeout=5).json()
    assert "webSocketDebuggerUrl" in version
    assert any(t["url"] == "about:blank" for t in reg.targets(DEFAULT))


def test_the_last_detach_stops_chrome(reg):
    reg.attach(DEFAULT, "a")
    process = reg.running(DEFAULT).process
    reg.detach(DEFAULT, "a")
    assert reg.running(DEFAULT) is None
    assert process.poll() is not None


def test_two_profiles_run_side_by_side(reg):
    reg.create("other")
    first = reg.attach(DEFAULT, "a")
    second = reg.attach("other", "b")
    assert first != second
```

- [ ] **Step 2: Verify with a live probe**

Write `<scratchpad>/probe_profiles.py`, which builds a `ProfileRegistry` in a temp directory, calls `attach`, prints `targets()`, then `stop_all()` and prints `process.poll()`. Run it with `PYTHONPATH=src py <scratchpad>/probe_profiles.py`. Expect an `about:blank` page and a non-None exit code. If Chrome is not found, check `doctor.find_browsers()`. Delete the probe.

- [ ] **Step 3: Commit**

```bash
git add tests/test_profiles_live.py src/abt/profiles.py
git commit -m "Test ProfileRegistry against a real Chrome"
```

---

### Task 5: Attach mode in `PlaywrightDriver`

**Files:**
- Modify: `src/abt/pwdriver.py` (`__init__` ~line 596, `_boot` ~652–725, `_open_page`, `_activate`, `window_handles`, `current_window_handle`, `close`, `quit`; add `_tid`, `_handle`, `_on_page`, `opener_of`; module docstring's "phase 4" paragraph)
- Test: create `tests/test_pwdriver_attach.py`

**Interfaces:**
- Consumes: `TabGate` (Task 2); `ProfileRegistry.attach` (Task 3), used only in the test.
- Produces: `PlaywrightDriver(config, console_source=None, action_timeout=5.0, cdp_url: str | None = None, gate: TabGate | None = None)`; in gate mode handles are CDP target ids; `opener_of(target: str) -> str | None`.

- [ ] **Step 1: Write the live tests**

Create `tests/test_pwdriver_attach.py`:

```python
"""Two sessions, one Chrome: each connection sees only its own tabs."""

from __future__ import annotations

import pytest

from abt.launch import LaunchConfig
from abt.profiles import DEFAULT, ProfileRegistry
from abt.pwdriver import PlaywrightDriver
from abt.tabs import TabGate


@pytest.fixture
def reg(tmp_path):
    registry = ProfileRegistry(root=tmp_path / "profiles")
    yield registry
    registry.stop_all()


@pytest.fixture
def pair(reg, tmp_path):
    tabs = reg.tabs(DEFAULT)
    config = LaunchConfig(profile=tmp_path / "profiles" / DEFAULT)
    drivers = {}
    for name in ("a", "b"):
        url = reg.attach(DEFAULT, name)
        drivers[name] = PlaywrightDriver(config, cdp_url=url, gate=TabGate(tabs, name))
    yield drivers, tabs
    for driver in drivers.values():
        try:
            driver.quit()
        except Exception:
            pass


def test_each_session_starts_on_a_page_of_its_own(pair):
    drivers, tabs = pair
    a, b = drivers["a"].window_handles, drivers["b"].window_handles
    assert len(a) == 1 and len(b) == 1
    assert a != b
    assert tabs.owner_of(a[0]) == "a"
    assert tabs.owner_of(b[0]) == "b"


def test_a_popup_joins_its_openers_session_only(pair):
    drivers, _ = pair
    drivers["a"].execute_script("window.open('about:blank')")
    assert len(drivers["a"].window_handles) == 2
    assert len(drivers["b"].window_handles) == 1


def test_a_dialog_on_one_session_does_not_kill_the_other(pair):
    drivers, _ = pair
    drivers["a"].execute_script("setTimeout(() => confirm('x'), 0)")
    drivers["a"].execute_script("return 1")
    assert drivers["b"].current_url == "about:blank"


def test_quitting_one_session_closes_only_its_tabs(pair):
    """Review focus 4."""
    drivers, tabs = pair
    kept = drivers["b"].window_handles
    drivers["a"].quit()
    assert drivers["b"].window_handles == kept
    assert tabs.owned_by("a") == []


def test_opener_of_names_the_popups_parent(pair):
    drivers, _ = pair
    parent = drivers["a"].current_window_handle
    drivers["a"].execute_script("window.open('about:blank')")
    popup = [h for h in drivers["a"].window_handles if h != parent][0]
    assert drivers["a"].opener_of(popup) == parent
```

- [ ] **Step 2: Implement**

In `PlaywrightDriver.__init__`, change the signature and set the new state before `self._call(self._boot, config)`:

```python
    def __init__(
        self,
        config,
        console_source: str | None = None,
        action_timeout: float = 5.0,
        cdp_url: str | None = None,
        gate=None,
    ) -> None:
        ...
        # Attach to a browser a ProfileRegistry launched, as one session among
        # several. With a gate, this connection sees only the pages its
        # session owns; see `window_handles`.
        self._cdp_url = cdp_url
        self._gate = gate
        self._tids: dict[int, str] = {}
        self._call(self._boot, config)
```

In `_boot`, replace `cdp_url = os.environ.get("ABT_CDP_URL")` with:

```python
        cdp_url = self._cdp_url or os.environ.get("ABT_CDP_URL")
        # Only the environment variable means "someone else's browser". One a
        # ProfileRegistry launched can be relaunched from here.
        external = self._cdp_url is None
```

At the top of the attach `except Exception as exc:` block, before the existing `raise OpError(...)`, add:

```python
                if not external:
                    raise OpError(
                        "browser_dead",
                        f"could not connect to this profile's browser at {cdp_url}: {exc}",
                        hint=(
                            "The profile's browser went away. `browser_restart` in "
                            "this session relaunches it."
                        ),
                    ) from exc
```

Replace the tail of `_boot`, from `self._pages = list(self._context.pages) or [self._context.new_page()]` to the end of the method, with:

```python
        if self._gate is not None:
            # A session starts on a page of its own. Adopting every open page,
            # as the harness attach does, would hand it other sessions' tabs.
            page = self._context.new_page()
            self._gate.opened(self._tid(page))
            self._pages = [page]
            for other in self._context.pages:
                if other is not page:
                    other.on("dialog", _ignore)
        else:
            self._pages = list(self._context.pages) or [self._context.new_page()]
        self._active = 0
        # Every page, including ones the site opens itself -- a target=_blank
        # popup makes requests too, and it is usually the interesting one.
        self._context.on("page", self._on_page)
        for page in self._pages:
            self._watch(page)
```

Add the methods and the module-level `_ignore`:

```python
    def _on_page(self, page) -> None:
        if self._gate is None:
            self._watch(page)
            return
        # Possibly someone else's page. Listen without acting: with no
        # listener, Playwright auto-dismisses its dialogs from *this*
        # connection too, and a dismiss racing the owner's is the Node-side
        # rejection `_watch` exists to prevent. The owner's connection answers.
        page.on("dialog", _ignore)

    def _tid(self, page) -> str:
        """Chrome's target id for a page: the same on every connection."""
        key = id(page)
        found = self._tids.get(key)
        if found is None:
            session = self._cdp.get(key)
            if session is None:
                session = self._context.new_cdp_session(page)
                self._cdp[key] = session
            found = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            self._tids[key] = found
        return found

    def _handle(self, page) -> str:
        return self._tid(page) if self._gate is not None else _handle_of(page)

    def opener_of(self, target: str) -> str | None:
        """The target id of the page that opened `target`, if there was one."""

        def work():
            for page in self._context.pages:
                if not page.is_closed() and self._tid(page) == target:
                    opener = page.opener()
                    return self._tid(opener) if opener is not None else None
            return None

        return self._call(work)
```

```python
def _ignore(_dialog) -> None:
    """A dialog on a page this connection does not own. See `_on_page`."""
```

In `_open_page`'s `work()`, after `page = self._context.new_page()`:

```python
            if self._gate is not None:
                self._gate.opened(self._tid(page))
```

In `_activate`, replace `_handle_of(page) == handle` with `self._handle(page) == handle`. Replace the `bring_to_front` line with:

```python
                # Shared browsers never steal focus: another session's tab may
                # be the one in front, and Playwright acts on a page without it.
                if self._gate is None:
                    self._call(lambda: page.bring_to_front())
```

Replace `window_handles`:

```python
    @property
    def window_handles(self) -> list[str]:
        def work():
            active = (
                self._pages[self._active] if 0 <= self._active < len(self._pages) else None
            )
            live = [p for p in self._pages if not p.is_closed()]
            if self._gate is not None:
                for page in self._context.pages:
                    if page in live or page.is_closed():
                        continue
                    opener = page.opener()
                    opener_id = self._tid(opener) if opener is not None else None
                    if self._gate.sees(self._tid(page), opener_id):
                        self._watch(page)
                        live.append(page)
                # A tab released, or reassigned by the operator, leaves this
                # session's view at once rather than on its next navigation.
                live = [p for p in live if self._gate.owns(self._tid(p))]
            else:
                for page in self._context.pages:
                    if page not in live:
                        live.append(page)
            self._pages = live
            self._active = live.index(active) if active in live else 0
            return [self._handle(p) for p in live]

        return self._call(work)
```

Change `current_window_handle` to `return self._call(lambda: self._handle(self._page))`.

In `close()`'s `work()`:

```python
        def work():
            page = self._page
            target = self._tid(page) if self._gate is not None else None
            page.close()
            if target is not None:
                self._gate.registry.forget(target)
            self._pages = [p for p in self._pages if not p.is_closed()]
            self._active = max(0, min(self._active, len(self._pages) - 1))
            self._frame = None
```

In `quit()`'s `work()`, replace the body of the `try:` with:

```python
            try:
                if self._gate is not None:
                    # A session's tabs go with it. The browser, and every
                    # other session's tabs, stay.
                    for page in list(self._pages):
                        try:
                            target = self._tid(page)
                            page.close()
                            self._gate.registry.forget(target)
                        except Exception:
                            pass
                elif not getattr(self, "_cdp_attached", False):
                    self._context.close()
            finally:
                self._pw.stop()
```

In the module docstring, replace the sentence "Removing it is phase 4, and is what unlocks same-profile parallelism in the profile-sessions design." with "It does not block same-profile parallelism: each session attaches a connection of its own, so each has its own ambient state (see the multi-profile sessions design)."

- [ ] **Step 3: Verify with a live probe**

Write `<scratchpad>/probe_attach.py`, which replays `test_each_session_starts_on_a_page_of_its_own` and `test_quitting_one_session_closes_only_its_tabs` with plain asserts against a temp `ProfileRegistry`, cleaning up with `stop_all()` in `finally`. Run it with `PYTHONPATH=src py <scratchpad>/probe_attach.py`. Delete it.

- [ ] **Step 4: Commit**

```bash
git add src/abt/pwdriver.py tests/test_pwdriver_attach.py
git commit -m "Let PlaywrightDriver attach as one session among several"
```

---

### Task 6: `BrowserSession` attach mode and tab ops

**Files:**
- Modify: `src/abt/browser.py` (imports, `Attach` dataclass, `__init__`, `_launch_driver`, `start`, `stop`, `_new_tab_id`, `_sync_tabs`; new `shared`, `refuse_other_profile`, `check_tab`, `foreign_tabs`, `claim_tab`, `release_tab`)
- Modify: `src/abt/schema.py` (`TabClaim`, `TabRelease`, `Command` union)
- Modify: `src/abt/ops/tabs.py`, `src/abt/ops/__init__.py` (`REGISTRY`), `src/abt/ops/control.py` (`browser_open_manual`)
- Modify: `docs/reference.md:790`, `guidelines/toolkit-workflow.md:89` (tabs rows)
- Test: create `tests/test_session_tabs.py` (no browser) and `tests/test_session_tabs_live.py`

**Interfaces:**
- Consumes: `TabGate` (Task 2); `PlaywrightDriver(..., cdp_url, gate)`, `opener_of` (Task 5).
- Produces:
  - `browser.Attach(connect: Callable[[], str], disconnect: Callable[[], None], list_targets: Callable[[], list[dict]], gate: TabGate)`
  - `BrowserSession(..., attach: Attach | None = None)`; `.shared -> bool`; `.refuse_other_profile(profile)`; `.check_tab(tab_id)`; `.foreign_tabs() -> list[dict]`; `.claim_tab(tab_id) -> str`; `.release_tab(tab_id | None) -> str`
  - Ops `tab_claim {tab_id}` and `tab_release {tab_id?}`

- [ ] **Step 1: Write the tests**

Create `tests/test_session_tabs.py`:

```python
"""A shared BrowserSession's rules that need no browser."""

from __future__ import annotations

import pytest

from abt.browser import Attach, BrowserSession
from abt.errors import OpError
from abt.tabs import TabGate, TabRegistry


def shared(tmp_path, connects):
    gate = TabGate(TabRegistry("default"), "a")
    attach = Attach(
        connect=lambda: connects.append(1) or "http://127.0.0.1:1",
        disconnect=lambda: None,
        list_targets=lambda: [],
        gate=gate,
    )
    return BrowserSession(profile=tmp_path, headless=True, attach=attach)


def test_a_session_cannot_start_on_another_profile(tmp_path):
    connects = []
    session = shared(tmp_path, connects)
    with pytest.raises(OpError) as exc:
        session.start(profile=str(tmp_path / "elsewhere"))
    assert exc.value.type == "invalid_op"
    assert connects == []


def test_naming_its_own_profile_is_not_a_change(tmp_path):
    session = shared(tmp_path, [])
    session.refuse_other_profile(str(tmp_path))


def test_attach_needs_playwright(tmp_path):
    with pytest.raises(ValueError):
        BrowserSession(
            profile=tmp_path,
            engine="selenium",
            attach=Attach(lambda: "", lambda: None, lambda: [], TabGate(TabRegistry("p"), "a")),
        )


def test_tab_ownership_ops_need_sessions(tmp_path):
    legacy = BrowserSession(profile=tmp_path, headless=True)
    for call in (lambda: legacy.claim_tab("tab_0"), lambda: legacy.release_tab(None)):
        with pytest.raises(OpError) as exc:
            call()
        assert exc.value.type == "invalid_op"
    assert legacy.foreign_tabs() == []
    legacy.check_tab("tab_0")  # a no-op without sessions


def test_check_tab_refuses_another_sessions_tab(tmp_path):
    session = shared(tmp_path, [])
    session._attach.gate.registry.opened("T1", "b")
    with pytest.raises(OpError) as exc:
        session.check_tab("tab_0")
    assert exc.value.type == "tab_locked"


def test_the_new_ops_are_registered():
    from abt.ops import REGISTRY
    from abt.schema import parse_command

    assert parse_command({"op": "tab_claim", "tab_id": "tab_1"}).tab_id == "tab_1"
    assert parse_command({"op": "tab_release"}).tab_id is None
    assert {"tab_claim", "tab_release"} <= set(REGISTRY)
```

Create `tests/test_session_tabs_live.py`:

```python
"""Two BrowserSessions on one Chrome: listing, locks, claim and release."""

from __future__ import annotations

import pytest

from abt.browser import Attach, BrowserSession
from abt.errors import OpError
from abt.profiles import DEFAULT, ProfileRegistry
from abt.tabs import TabGate


@pytest.fixture
def reg(tmp_path):
    registry = ProfileRegistry(root=tmp_path / "profiles")
    yield registry
    registry.stop_all()


def make(reg, name, budgets):
    attach = Attach(
        connect=lambda: reg.attach(DEFAULT, name),
        disconnect=lambda: reg.detach(DEFAULT, name),
        list_targets=lambda: reg.targets(DEFAULT),
        gate=TabGate(reg.tabs(DEFAULT), name),
    )
    return BrowserSession(profile=reg.path(DEFAULT), headless=True, attach=attach, **budgets)


@pytest.fixture
def ab(reg, budgets):
    a, b = make(reg, "a", budgets), make(reg, "b", budgets)
    a.start()
    b.start()
    yield a, b
    for s in (a, b):
        s.stop()


def test_another_sessions_tab_is_listed_locked_without_its_page(ab, base_url):
    a, b = ab
    a.goto(f"{base_url}/form.html")
    rows = b.tabs() + b.foreign_tabs()
    locked = [r for r in rows if r.get("locked") == "a"]
    assert len(locked) == 1
    assert "url" not in locked[0]


def test_switching_to_it_is_refused(ab):
    a, b = ab
    with pytest.raises(OpError) as exc:
        b.check_tab(a.active_tab)
    assert exc.value.type == "tab_locked"


def test_release_then_claim_moves_a_tab(ab):
    a, b = ab
    given = a.new_tab(None, activate=False)
    a.release_tab(given)
    assert given not in [t["tab_id"] for t in a.tabs()]
    b.claim_tab(given)
    assert given in [t["tab_id"] for t in b.tabs()]


def test_releasing_the_last_tab_is_refused(ab):
    a, _ = ab
    with pytest.raises(OpError) as exc:
        a.release_tab(None)
    assert exc.value.type == "last_tab"


def test_stopping_one_session_leaves_the_other(ab):
    a, b = ab
    before = b.tabs()
    a.stop()
    assert b.tabs() == before
```

- [ ] **Step 2: Implement**

In `src/abt/browser.py` add imports:

```python
from dataclasses import dataclass
from typing import Callable

from .tabs import TabGate
```

After `_profile_locked`, add:

```python
@dataclass
class Attach:
    """How a session reaches a browser it shares rather than owns.

    Supplied by the SessionRegistry. `connect` makes sure the profile's Chrome
    is running and returns its CDP URL; `disconnect` says this session is
    finished with it; `list_targets` is every page in that Chrome.
    """

    connect: Callable[[], str]
    disconnect: Callable[[], None]
    list_targets: Callable[[], list[dict]]
    gate: TabGate
```

`BrowserSession.__init__`: add the parameter `attach: Attach | None = None` after `engine`, and after the engine validation:

```python
        if attach is not None and engine != "playwright":
            raise ValueError("a shared session needs the playwright engine")
        # Set when this session is one of several on a profile's browser.
        # Everything that differs between owning a browser and sharing one
        # branches on this.
        self._attach = attach
```

Add:

```python
    @property
    def shared(self) -> bool:
        return self._attach is not None

    def refuse_other_profile(self, profile) -> None:
        """A session's profile changes through `abt session set`, never from
        inside it: `browser_start {"profile": ...}` would otherwise walk an
        agent out of the profile it was given."""
        if self._attach is None or profile is None:
            return
        if Path(profile).expanduser().resolve() != self.defaults.profile:
            raise OpError(
                "invalid_op",
                "this session's profile is fixed; change it with "
                "`abt session set NAME --profile P`, not from inside the session",
            )
```

At the top of `start()`, before the `is_running` check: `self.refuse_other_profile(profile)`. At the top of `restart()`: the same call.

In `_launch_driver`, the playwright branch becomes:

```python
        if self._engine == "playwright":
            from .pwdriver import PlaywrightDriver

            if self._attach is not None:
                url = self._attach.connect()
                try:
                    return PlaywrightDriver(
                        config,
                        action_timeout=self.action_timeout,
                        cdp_url=url,
                        gate=self._attach.gate,
                    )
                except Exception:
                    self._attach.disconnect()
                    raise
            return PlaywrightDriver(config, action_timeout=self.action_timeout)
```

Replace `stop()` with:

```python
    def stop(self) -> dict:
        """Quit the browser and forget everything tied to it.

        Safe when nothing is running. A shared session only closes its own tabs
        and lets go; the profile's browser outlives it while anyone else is on
        it. See `_wait_for_profile_release` for why the owning case does more
        than call quit().
        """
        was_running = self.is_running
        if self._driver is not None:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            except Exception:
                # A shared browser that died under us raises Playwright's own
                # errors on the way out. Letting go must still succeed.
                if self._attach is None:
                    raise
            self._driver = None
        if self._attach is not None:
            if was_running:
                self._attach.disconnect()
            self._reset_state()
            return {"stopped": was_running, "profile_released": True}
        released = self._wait_for_profile_release(self.config) if was_running else True
        self._reset_state()
        return {"stopped": was_running, "profile_released": released}
```

Change `_new_tab_id`:

```python
    def _new_tab_id(self, handle: str | None = None) -> str:
        # Shared: the profile's registry numbers tabs, so every session and
        # the GUI agree on which one `tab_3` is.
        if self._attach is not None and handle is not None:
            return self._attach.gate.label(handle)
        tab_id = f"tab_{self._counter}"
        self._counter += 1
        return tab_id
```

In `_sync_tabs`, change `tab_id = self._new_tab_id()` to `tab_id = self._new_tab_id(handle)`.

Add after `close_tab`:

```python
    # --- sharing ----------------------------------------------------------------

    def _gate(self, op: str) -> TabGate:
        if self._attach is None:
            raise OpError(
                "invalid_op",
                f"{op} needs sessions: run `abt serve` on the playwright engine",
            )
        return self._attach.gate

    def check_tab(self, tab_id: str) -> None:
        """Refuse another session's tab before looking it up. No-op unshared."""
        if self._attach is not None:
            self._attach.gate.check(tab_id)

    def foreign_tabs(self) -> list[dict]:
        """Tabs on this profile that are not this session's.

        Another session's tab is named with its owner and nothing else: what is
        on it is that session's business. An unowned tab shows its page, since
        claiming it is the only thing to do with it.
        """
        if self._attach is None or not self.is_running:
            return []
        own = set(self._handles.values())
        gate = self._attach.gate
        rows = []
        for target in self._attach.list_targets():
            tid = target.get("id")
            if not tid or tid in own:
                continue
            label = gate.label(tid)
            owner = gate.owner(tid)
            if owner is None:
                rows.append({
                    "tab_id": label,
                    "url": target.get("url"),
                    "title": target.get("title"),
                    "unowned": True,
                })
            else:
                rows.append({"tab_id": label, "locked": owner})
        return rows

    def claim_tab(self, tab_id: str) -> str:
        gate = self._gate("tab_claim")
        target = gate.target_of(tab_id)
        if target is None:
            # An id straight from the GUI may not have been numbered on this
            # connection yet; listing numbers every page.
            self.foreign_tabs()
            target = gate.target_of(tab_id)
        if target is None:
            raise OpError("tab_not_found", f"no tab {tab_id!r}")
        gate.claim(target, self.driver.opener_of(target))
        self._sync_tabs()
        return tab_id

    def release_tab(self, tab_id: str | None) -> str:
        gate = self._gate("tab_release")
        self._sync_tabs()
        label = tab_id or self.active_tab
        handle = self._handles.get(label)
        if handle is None:
            self.check_tab(label)
            raise OpError("tab_not_found", f"no tab {label!r}")
        if len(self._order) == 1:
            # Same rule as close_tab: a session with no tab has no active page,
            # and every command after this would fail for a reason nobody
            # would guess.
            raise OpError(
                "last_tab",
                "refusing to release your last tab; open another with tab_new first",
            )
        gate.release(handle)
        self._sync_tabs()
        return label
```

In `src/abt/schema.py`, after `TabClose`:

```python
class TabClaim(Base):
    """Take a tab nobody owns. Shared sessions only."""

    op: Literal["tab_claim"]
    tab_id: str


class TabRelease(Base):
    """Give a tab up so another session can claim it. Defaults to the active tab."""

    op: Literal["tab_release"]
    tab_id: str | None = None
```

Then add `TabClaim, TabRelease` to the `Command` union after `TabClose`.

Replace `src/abt/ops/tabs.py` with:

```python
"""Tab ops. Tab ids are server-assigned and stay stable across switches.

On a shared profile they are numbered per profile, and another session's tab
is visible but locked: see `BrowserSession.foreign_tabs`.
"""

from __future__ import annotations

from ..browser import BrowserSession


def tab_new(session: BrowserSession, cmd) -> dict:
    tab_id = session.new_tab(cmd.url, cmd.activate)
    return {"tab_id": tab_id, "tabs": session.tabs()}


def tab_list(session: BrowserSession, cmd) -> list[dict]:
    return session.tabs() + session.foreign_tabs()


def tab_switch(session: BrowserSession, cmd) -> dict:
    session.check_tab(cmd.tab_id)
    session.switch_tab(cmd.tab_id)
    return {"tab_id": cmd.tab_id, **session.location()}


def tab_close(session: BrowserSession, cmd) -> dict:
    if cmd.tab_id:
        session.check_tab(cmd.tab_id)
    session.close_tab(cmd.tab_id)
    return {"active_tab": session.active_tab, "tabs": session.tabs()}


def tab_claim(session: BrowserSession, cmd) -> dict:
    tab_id = session.claim_tab(cmd.tab_id)
    return {"tab_id": tab_id, "tabs": session.tabs()}


def tab_release(session: BrowserSession, cmd) -> dict:
    tab_id = session.release_tab(cmd.tab_id)
    return {"released": tab_id, "tabs": session.tabs()}
```

In `src/abt/ops/__init__.py` `REGISTRY`, after `"tab_close": tabs.tab_close,` add:

```python
    "tab_claim": tabs.tab_claim,
    "tab_release": tabs.tab_release,
```

In `src/abt/ops/control.py` `browser_open_manual`, as its first line: `session.refuse_other_profile(cmd.profile)`.

In `docs/reference.md:790` and `guidelines/toolkit-workflow.md:89`, add `` `tab_claim` `tab_release` `` to the Tabs row.

- [ ] **Step 3: Verify by reading**

Check that `tests/test_schema.py::sorted(REGISTRY) == OP_NAMES` still holds (both new names are in both places). Walk `release_tab` in `test_release_then_claim_moves_a_tab`: `a` has two tabs, releases `given`, and the driver's `window_handles` filter drops it because `gate.owns` is now false. `b.claim_tab` resolves the label, `opener_of` returns None (opened by `new_page`), `claim` succeeds, and `b`'s next `window_handles` adopts it because `sees` returns true.

- [ ] **Step 4: Commit**

```bash
git add src/abt/browser.py src/abt/schema.py src/abt/ops/tabs.py src/abt/ops/__init__.py src/abt/ops/control.py docs/reference.md guidelines/toolkit-workflow.md tests/test_session_tabs.py tests/test_session_tabs_live.py
git commit -m "Let a BrowserSession share a profile's browser, with tab_claim and tab_release"
```

- [ ] **Step 5: Push point.** Ask the user whether to push the branch so CI runs Tasks 1–6.

---

### Task 7: `SessionRegistry`

**Files:**
- Create: `src/abt/sessions.py`
- Test: create `tests/test_sessions.py`

**Interfaces:**
- Consumes: `ProfileRegistry` (Task 3), `Attach`/`BrowserSession` (Task 6), `TabGate` (Task 2), `SessionRecorder`.
- Produces:
  - `SessionRecord(name, profile="default", sealed=False, created="", settings={}, token_hash=None)` with `.public(with_settings=True) -> dict`
  - `hash_token(token) -> str`, `write_private(path, text)`
  - `SessionStore(directory)` with `load() -> dict[str, SessionRecord]`, `save(record)`, `delete(name)`, `write_token(name, token)`
  - `Session` with `.record`, `.browser`, `.lock`, `.name`, `.log_root: Path | None`, `.recorder` (lazy), `.started_recorder`, `.close()`
  - `SessionRegistry(store, profiles, make_browser: Callable[[Path, Attach], BrowserSession], log_root=None, recorder_options=None, operator_token=None)` with `get(name, token=None) -> Session`, `create(name, profile="default", sealed=False, settings=None) -> dict`, `update(name, token=None, profile=None, settings=None) -> dict`, `remove(name, token=None)`, `list() -> list[dict]`, `info(name, token=None) -> dict`, `profile_in_use(profile) -> bool`, `remove_profile(name)`, `is_operator(token) -> bool`, `touch(session)`, `reap_idle() -> list[str]`, `start_reaper(interval=60.0)`, `close_all()`; attribute `profiles`
  - `SingleSessionRegistry(browser, recorder)` with the same `get`, `list`, `info`, `touch`, `is_operator`, `close_all`; `create`/`update`/`remove`/`remove_profile` raise `invalid_op`; `profiles = None`, `operator_token = None`

- [ ] **Step 1: Write the tests**

Create `tests/test_sessions.py`:

```python
"""Sessions: creation, sealing, persistence, and the legacy single session.

No browser: every BrowserSession here is built and never started.
"""

from __future__ import annotations

import json

import pytest

from abt.browser import BrowserSession
from abt.errors import OpError
from abt.profiles import ProfileRegistry
from abt.sessions import SessionRegistry, SessionStore, SingleSessionRegistry


@pytest.fixture
def parts(tmp_path):
    profiles = ProfileRegistry(root=tmp_path / "profiles")
    store = SessionStore(tmp_path / "sessions")

    def make_browser(directory, attach):
        return BrowserSession(profile=directory, headless=True, attach=attach)

    return profiles, store, make_browser


@pytest.fixture
def reg(parts):
    profiles, store, make_browser = parts
    return SessionRegistry(store, profiles, make_browser, operator_token="op")


def test_default_always_exists(reg):
    assert reg.get(None).name == "default"
    assert reg.get("default").browser.shared is True


def test_an_unknown_session_is_an_error_not_a_fallback(reg):
    with pytest.raises(OpError) as exc:
        reg.get("typo")
    assert exc.value.type == "unknown_session"


def test_create_open_session(reg):
    reg.profiles.create("work")
    out = reg.create("a", profile="work")
    assert out["profile"] == "work"
    assert "token" not in out
    assert reg.get("a").record.profile == "work"
    with pytest.raises(OpError) as exc:
        reg.create("a")
    assert exc.value.type == "session_exists"


@pytest.mark.parametrize("bad", ["../x", "a/b", "C:\\x", ".hidden", ""])
def test_a_session_name_that_is_a_path_writes_nothing(reg, tmp_path, bad):
    """Review focus 1."""
    with pytest.raises(OpError) as exc:
        reg.create(bad)
    assert exc.value.type == "invalid_op"
    assert sorted(p.name for p in (tmp_path / "sessions").glob("*")) == []


def test_a_session_on_a_missing_profile_is_refused(reg):
    with pytest.raises(OpError) as exc:
        reg.create("a", profile="ghost")
    assert exc.value.type == "profile_not_found"


def test_sealed_needs_its_token(reg, tmp_path):
    token = reg.create("s", sealed=True)["token"]
    for wrong in (None, "nope"):
        with pytest.raises(OpError) as exc:
            reg.get("s", wrong)
        assert exc.value.type == "session_sealed"
    assert reg.get("s", token).name == "s"
    assert (tmp_path / "sessions" / "s.token").read_text(encoding="utf-8") == token
    saved = json.loads((tmp_path / "sessions" / "s.json").read_text(encoding="utf-8"))
    assert token not in json.dumps(saved)


def test_a_sealed_token_survives_a_restart(parts):
    """Review focus 3."""
    profiles, store, make_browser = parts
    token = SessionRegistry(store, profiles, make_browser).create("s", sealed=True)["token"]
    again = SessionRegistry(store, profiles, make_browser)
    assert again.get("s", token).name == "s"
    with pytest.raises(OpError):
        again.get("s", "wrong")


def test_settings_merge_delete_and_keep_unknown_keys(parts):
    profiles, store, make_browser = parts
    reg = SessionRegistry(store, profiles, make_browser)
    reg.create("a", settings={"future": {"x": 1}, "gone": True})
    reg.update("a", settings={"gone": None, "added": 2})
    again = SessionRegistry(store, profiles, make_browser)
    assert again.get("a").record.settings == {"future": {"x": 1}, "added": 2}


def test_changing_profile_replaces_the_browser_and_warns(reg):
    reg.profiles.create("work")
    reg.create("a")
    before = reg.get("a").browser
    out = reg.update("a", profile="work")
    assert reg.get("a").browser is not before
    assert reg.get("a").browser.profile == reg.profiles.path("work")
    assert "warning" in out


def test_default_keeps_the_default_profile(reg):
    reg.profiles.create("work")
    with pytest.raises(OpError) as exc:
        reg.update("default", profile="work")
    assert exc.value.type == "invalid_op"


def test_remove(reg, tmp_path):
    with pytest.raises(OpError):
        reg.remove("default")
    token = reg.create("s", sealed=True)["token"]
    with pytest.raises(OpError) as exc:
        reg.remove("s")
    assert exc.value.type == "session_sealed"
    reg.remove("s", token)
    assert not (tmp_path / "sessions" / "s.json").exists()
    assert not (tmp_path / "sessions" / "s.token").exists()


def test_list_hides_a_sealed_sessions_settings(reg):
    reg.create("s", sealed=True, settings={"secret": 1})
    row = next(r for r in reg.list() if r["name"] == "s")
    assert row["sealed"] is True
    assert "settings" not in row


def test_a_profile_in_use_cannot_be_removed(reg):
    reg.profiles.create("work")
    reg.create("a", profile="work")
    with pytest.raises(OpError) as exc:
        reg.remove_profile("work")
    assert exc.value.type == "profile_in_use"


def test_the_operator_token(reg):
    assert reg.is_operator("op") is True
    assert reg.is_operator("no") is False
    assert reg.is_operator(None) is False


def test_reaping_skips_a_busy_session(reg, monkeypatch):
    stopped = []
    monkeypatch.setattr(reg.profiles, "idle", lambda: ["default"])
    monkeypatch.setattr(reg.profiles, "stop", lambda name: stopped.append(name) or True)
    session = reg.get(None)
    session.browser._driver = object()  # looks connected, so the reaper must lock it
    monkeypatch.setattr(session.browser, "stop", lambda: None)
    session.lock.acquire()
    try:
        assert reg.reap_idle() == []
    finally:
        session.lock.release()
    assert reg.reap_idle() == ["default"]
    assert stopped == ["default"]


def test_the_legacy_registry_has_only_default(tmp_path):
    browser = BrowserSession(profile=tmp_path, headless=True)
    reg = SingleSessionRegistry(browser, None)
    assert reg.get(None).browser is browser
    with pytest.raises(OpError) as exc:
        reg.get("other")
    assert exc.value.type == "unknown_session"
    with pytest.raises(OpError) as exc:
        reg.create("x")
    assert exc.value.type == "invalid_op"
```

- [ ] **Step 2: Implement**

Create `src/abt/sessions.py`:

```python
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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .browser import Attach, BrowserSession
from .errors import OpError
from .profiles import DEFAULT, ProfileRegistry, check_name
from .recorder import SessionRecorder
from .tabs import TabGate

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
        # Replaced when the session moves to another profile. Read it only
        # while holding `lock`.
        self.browser = browser
        self.lock = threading.Lock()
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
    ) -> None:
        self.store = store
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
            return self.profiles.attach(profile, name)

        attach = Attach(
            connect=connect,
            disconnect=lambda: self.profiles.detach(profile, name),
            list_targets=lambda: self.profiles.targets(profile),
            gate=TabGate(self.profiles.tabs(profile), name),
        )
        return self._make_browser(self.profiles.path(profile), attach)

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
            session.close()
        with self._lock:
            self._live.pop(name, None)
            self._records.pop(name, None)
        self.store.delete(name)

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

        thread = threading.Thread(target=loop, name="abt-reaper", daemon=True)
        thread.start()
        return thread

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
```

- [ ] **Step 3: Verify with a probe**

Write `<scratchpad>/probe_sessions.py`, which replays `test_sealed_needs_its_token` and `test_a_sealed_token_survives_a_restart` in a temp directory with plain asserts. Run it with `PYTHONPATH=src py ...`. It must exit 0. Delete it.

- [ ] **Step 4: Commit**

```bash
git add src/abt/sessions.py tests/test_sessions.py
git commit -m "Add SessionRegistry: persisted, optionally sealed sessions"
```

---

### Task 8: Server — resolve a session per request

**Files:**
- Modify: `src/abt/server.py` (module docstring, imports, `create_app` signature and body through `/browser/*`; module-level `_strip`)
- Test: create `tests/test_server_sessions.py`

**Interfaces:**
- Consumes: `SessionRegistry`, `SingleSessionRegistry`, `Session` (Task 7).
- Produces: `create_app(session=None, request_stop=None, recorder=None, shots=True, shot_quality=..., shot_width=..., registry=None)`; `app.state.registry`; `transport(request_headers, body) -> (name, token, body)`, exposed as module-level `_transport(headers, body)` for tests.

- [ ] **Step 1: Write the tests**

Create `tests/test_server_sessions.py`:

```python
"""Routing requests to sessions. No browser: `status` answers without one."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def registry(tmp_path):
    profiles = ProfileRegistry(root=tmp_path / "profiles")

    def make_browser(directory, attach):
        return BrowserSession(
            profile=directory,
            headless=True,
            attach=attach,
            run_js_enabled=attach.gate.session != "nojs",
        )

    return SessionRegistry(
        SessionStore(tmp_path / "sessions"), profiles, make_browser, operator_token="op"
    )


@pytest.fixture
def client(registry):
    with TestClient(create_app(registry=registry)) as test_client:
        yield test_client


def status(client, **kw):
    return client.post("/command-list", json={"op": "status"}, **kw).json()


def test_no_session_means_default(client):
    assert status(client)["ok"] is True


def test_an_unknown_session_is_refused(client):
    body = status(client, headers={"X-ABT-Session": "typo"})
    assert body["error"]["type"] == "unknown_session"


def test_a_session_field_on_a_bare_command_routes_it(client, registry):
    """Review focus 2: the schema forbids unknown fields."""
    registry.create("a")
    body = client.post("/command-list", json={"op": "status", "session": "a"}).json()
    assert body["ok"] is True


def test_a_list_naming_two_sessions_is_refused(client, registry):
    registry.create("a")
    registry.create("b")
    response = client.post(
        "/command-list",
        json=[{"op": "status", "session": "a"}, {"op": "status", "session": "b"}],
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_op"


def test_sealed_needs_the_token(client, registry):
    token = registry.create("s", sealed=True)["token"]
    assert status(client, headers={"X-ABT-Session": "s"})["error"]["type"] == "session_sealed"
    ok = status(client, headers={"X-ABT-Session": "s", "X-ABT-Token": token})
    assert ok["ok"] is True


def test_a_busy_session_does_not_block_another(client, registry):
    registry.create("a")
    registry.create("b")
    held = registry.get("a").lock
    held.acquire()
    try:
        done = []
        worker = threading.Thread(
            target=lambda: done.append(status(client, headers={"X-ABT-Session": "b"}))
        )
        worker.start()
        worker.join(timeout=10)
        assert done and done[0]["ok"] is True
    finally:
        held.release()


def test_status_says_which_session(client, registry):
    registry.create("a")
    body = client.get("/status", params={"session": "a"}).json()
    assert body["result"]["session"] == "a"


def test_ops_follow_the_sessions_run_js_switch(client, registry):
    registry.create("nojs")
    names = client.get("/ops", params={"names": True, "session": "nojs"}).json()["result"]
    assert "run_js" not in names
    assert "run_js" in client.get("/ops", params={"names": True}).json()["result"]


def test_the_legacy_app_knows_only_default(tmp_path):
    with TestClient(create_app(BrowserSession(profile=tmp_path, headless=True))) as c:
        assert status(c)["ok"] is True
        body = status(c, headers={"X-ABT-Session": "other"})
        assert body["error"]["type"] == "unknown_session"
```

- [ ] **Step 2: Implement**

Change the module docstring's first paragraph to:

```python
"""HTTP surface. The server process is the command loop.

Every request runs in a session. Each session owns a lock, and commands within
a session run in order under it; different sessions never wait on each other.
The blocking work is pushed to a threadpool so a long command never stalls the
event loop -- `GET /status` stays answerable meanwhile.
"""
```

Add imports:

```python
from .sessions import Session, SingleSessionRegistry
```

Add at module level, after `_unmapped`:

```python
def _strip(item: Any) -> tuple[Any, str | None, str | None]:
    """Take the transport fields off one command, leaving the command."""
    if isinstance(item, dict) and ("session" in item or "token" in item):
        item = dict(item)
        return item, item.pop("session", None), item.pop("token", None)
    return item, None, None


def _transport(headers: Any, body: Any) -> tuple[str | None, str | None, Any]:
    """(session, token, body without them).

    `session` and `token` say where a command runs, not what it does, so they
    come off before validation -- the command models forbid unknown fields and
    would otherwise reject every routed command. Headers win, then the batch
    envelope, then the first command that names one.
    """
    name = headers.get("x-abt-session") or None
    token = headers.get("x-abt-token") or None
    if isinstance(body, dict) and "op" in body:
        item, s, t = _strip(body)
        return name or s, token or t, item
    envelope = isinstance(body, dict)
    items = (body.get("commands") or body.get("command_list")) if envelope else body
    if not isinstance(items, list):
        return name, token, body
    cleaned, named, tokens = [], [], []
    for item in items:
        item, s, t = _strip(item)
        cleaned.append(item)
        if s:
            named.append(s)
        if t:
            tokens.append(t)
    chosen = name or (body.get("session") if envelope else None) or (named[0] if named else None)
    stray = sorted({n for n in named if n != chosen})
    if stray:
        # A batch is one sequence in one session. Switching part way through
        # would take and drop different locks mid-batch, which destroys the
        # one thing a batch promises: nothing else ran in between.
        raise OpError(
            "invalid_op",
            f"a command list runs in one session; this one also names {', '.join(stray)}",
        )
    chosen_token = token or (body.get("token") if envelope else None) or (tokens[0] if tokens else None)
    if not envelope:
        return chosen, chosen_token, cleaned
    rest = {k: v for k, v in body.items() if k not in ("session", "token")}
    rest["commands" if "commands" in body else "command_list"] = cleaned
    return chosen, chosen_token, rest


def _refused(exc: OpError) -> JSONResponse:
    """A request that could not be routed. Malformed is a 400; the rest are
    ordinary failures in the ordinary envelope, which is what agents branch on."""
    return JSONResponse(status_code=400 if exc.type == "invalid_op" else 200, content=fail(exc))
```

Change `create_app`:

```python
def create_app(
    session: BrowserSession | None = None,
    request_stop: Callable[[], None] | None = None,
    recorder: SessionRecorder | None = None,
    shots: bool = True,
    shot_quality: int = shots_util.DEFAULT_QUALITY,
    shot_width: int = shots_util.DEFAULT_WIDTH,
    registry: Any = None,
) -> FastAPI:
    if registry is None:
        if session is None:
            raise ValueError("create_app needs a BrowserSession or a registry")
        registry = SingleSessionRegistry(session, recorder)
    app = FastAPI(title="aibrowsertoolkit", version="0.1.0")
    app.state.registry = registry
    # The default session's browser, for callers that predate sessions.
    app.state.session = registry.get(None).browser
    app.state.recorder = recorder

    def _session_for(request: Request) -> Session:
        name = request.headers.get("x-abt-session") or request.query_params.get("session")
        token = request.headers.get("x-abt-token") or request.query_params.get("token")
        return registry.get(name or None, token or None)
```

Delete `lock = threading.Lock()`. Change `run_one`, `_attach_shot`, `_record`, `execute`, `teardown` to take the session:

```python
    def run_one(sess: Session, data: Any, op_index: int) -> dict:
        """Validate then execute one command. Never raises."""
        browser = sess.browser
        started = now_ms()
        browser.last_target = None
        try:
            cmd = parse_command(data)
            response = ok(dispatch(browser, cmd))
        except OpError as exc:
            response = fail(exc, op_index)
        except Exception as exc:  # an unmapped Selenium surprise
            response = fail(_unmapped(exc), op_index)
        if sess.recorder is not None:
            event = _record(sess, data, response, now_ms() - started)
            _attach_shot(sess, data, response, event)
        return response
```

In `_attach_shot(sess, data, response, event)`: use `recorder = sess.recorder`, and build the URL as:

```python
        result["path"] = str((recorder.shots_dir / name).resolve())
        url = f"/logs/{recorder.session_id}/shots/{name}"
        # The default session's logs are what /logs serves unqualified.
        result["url"] = url if sess.name == "default" else f"{url}?session={sess.name}"
```

In `_record(sess, data, response, elapsed)`: replace `session` with `sess.browser` and `recorder` with `sess.recorder`.

```python
    def execute(sess: Session, items: list[Any], continue_on_error: bool) -> list[dict]:
        with sess.lock:
            registry.touch(sess)
            results = []
            for index, item in enumerate(items):
                response = run_one(sess, item, index)
                results.append(response)
                if response["ok"] and _is_shutdown(item):
                    break
                if not response["ok"] and not continue_on_error:
                    break
            return results

    def teardown() -> None:
        # Let the response flush before the process goes away.
        time.sleep(0.25)
        registry.close_all()
        if request_stop is not None:
            request_stop()
```

In `_command_list`, right after the `isinstance(body, JSONResponse)` check:

```python
        try:
            name, token, body = _transport(request.headers, body)
            sess = registry.get(name, token)
        except OpError as exc:
            return _refused(exc)
```

and pass `sess` as the first argument of both `run_in_threadpool(execute, ...)` calls.


`/status`: resolve `sess = _session_for(request)` (refuse on `OpError`), use `sess.browser` in place of `session`, and add the name to the answer:

```python
            result = await asyncio.wait_for(
                run_in_threadpool(session_status, sess.browser), STATUS_TIMEOUT
            )
            return ok({"session": sess.name, **result})
```

and add `"session": sess.name` to the timeout dict.

`/ops`: resolve the session and use `sess.browser.run_js_enabled`.

`/health`: `{"ok": True, "running": registry.get(None).browser.is_running}`.

`/browser`: `ok(browser_state(sess.browser))` after resolving. `_lifecycle(request, op)`: resolve `sess` first (refuse on `OpError`), then `run_in_threadpool(execute, sess, [payload], False)`.

- [ ] **Step 3: Verify by reading**

Grep `server.py` for any remaining bare `session.` or `lock` references (`grep -n "session\.\|with lock" src/abt/server.py`). Every hit must be inside a function that has resolved `sess`. Confirm that `tests/test_inspect.py:239` (`client.app.state.session`) still gets the legacy `BrowserSession`.

- [ ] **Step 4: Commit**

```bash
git add src/abt/server.py tests/test_server_sessions.py
git commit -m "Run every request in a session, each under its own lock"
```

---

### Task 9: Server — session, profile and tab-owner routes; per-session logs

**Files:**
- Modify: `src/abt/server.py` (new routes; the `/logs*` routes)
- Test: create `tests/test_server_admin.py`

**Interfaces:**
- Consumes: `registry.create/update/remove/info/list/remove_profile/is_operator`, `registry.profiles` (Tasks 3, 7).
- Produces: `GET/POST /sessions`, `GET/PATCH/DELETE /sessions/{name}`, `GET/POST /profiles`, `PATCH/DELETE /profiles/{name}`, `POST /tabs/owner`; `/logs`, `/logs/sites`, `/logs/{run}`, `/logs/{run}/shots/{name}` resolve the session from `?session=` or the header.

- [ ] **Step 1: Write the tests**

Create `tests/test_server_admin.py`:

```python
"""Managing sessions, profiles and tab ownership over HTTP. No browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def registry(tmp_path):
    profiles = ProfileRegistry(root=tmp_path / "profiles")
    return SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        profiles,
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        log_root=tmp_path / "logs",
        operator_token="op",
    )


@pytest.fixture
def client(registry):
    with TestClient(create_app(registry=registry)) as c:
        yield c


def test_session_lifecycle(client):
    client.post("/profiles", json={"name": "work"})
    made = client.post("/sessions", json={"name": "a", "profile": "work"}).json()
    assert made["ok"] and made["result"]["profile"] == "work"
    names = [s["name"] for s in client.get("/sessions").json()["result"]]
    assert names == ["a", "default"]
    changed = client.patch("/sessions/a", json={"profile": "default"}).json()
    assert changed["result"]["profile"] == "default"
    assert client.delete("/sessions/a").json()["ok"] is True


def test_sealed_is_created_with_a_token_and_guarded(client):
    token = client.post("/sessions", json={"name": "s", "sealed": True}).json()["result"]["token"]
    assert client.delete("/sessions/s").json()["error"]["type"] == "session_sealed"
    assert client.delete("/sessions/s", headers={"X-ABT-Token": token}).json()["ok"] is True


def test_profiles_over_http(client):
    assert client.post("/profiles", json={"name": "work"}).json()["ok"] is True
    assert client.patch("/profiles/work", json={"headed": True}).json()["result"]["headed"] is True
    client.post("/sessions", json={"name": "a", "profile": "work"})
    assert client.delete("/profiles/work").json()["error"]["type"] == "profile_in_use"


def test_bad_names_are_400(client):
    response = client.post("/sessions", json={"name": "../x"})
    assert response.status_code == 400


def test_tab_owner_needs_the_operator(client):
    body = {"profile": "default", "tab_id": "tab_0", "session": None}
    assert client.post("/tabs/owner", json=body).json()["error"]["type"] == "session_sealed"
    missing = client.post("/tabs/owner", json=body, headers={"X-ABT-Token": "op"}).json()
    assert missing["error"]["type"] == "tab_not_found"


def test_logs_are_per_session(client):
    client.post("/sessions", json={"name": "a"})
    client.post("/command-list", json={"op": "status"}, headers={"X-ABT-Session": "a"})
    mine = client.get("/logs", params={"session": "a"}).json()["result"]
    assert len(mine["sessions"]) == 1
    assert client.get("/logs").json()["result"]["sessions"] == []


def test_the_legacy_app_has_no_profiles(tmp_path):
    with TestClient(create_app(BrowserSession(profile=tmp_path, headless=True))) as c:
        response = c.get("/profiles")
        assert response.json()["error"]["type"] == "invalid_op"
```

- [ ] **Step 2: Implement**

Add inside `create_app`, before `return app`:

```python
    # --- sessions and profiles -------------------------------------------------
    #
    # Management, not commands: these never touch a page, so they take no
    # session lock of their own beyond what the registry takes.

    def _token(request: Request) -> str | None:
        return request.headers.get("x-abt-token") or request.query_params.get("token")

    async def _admin(work: Callable[[], Any]):
        try:
            return ok(await run_in_threadpool(work))
        except OpError as exc:
            return _refused(exc)

    async def _object(request: Request) -> dict | JSONResponse:
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body
        if not isinstance(body, dict):
            return _refused(OpError("invalid_op", "body must be an object"))
        return body

    def _profiles():
        if registry.profiles is None:
            raise OpError("invalid_op", NO_SESSIONS)
        return registry.profiles

    @app.get("/sessions")
    async def sessions_list():
        return await _admin(registry.list)

    @app.post("/sessions")
    async def sessions_create(request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: registry.create(
            body.get("name"),
            body.get("profile") or DEFAULT,
            bool(body.get("sealed")),
            body.get("settings"),
        ))

    @app.get("/sessions/{name}")
    async def sessions_show(name: str, request: Request):
        return await _admin(lambda: registry.info(name, _token(request)))

    @app.patch("/sessions/{name}")
    async def sessions_update(name: str, request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: registry.update(
            name, _token(request), profile=body.get("profile"), settings=body.get("settings")
        ))

    @app.delete("/sessions/{name}")
    async def sessions_remove(name: str, request: Request):
        return await _admin(lambda: registry.remove(name, _token(request)) or {"removed": name})

    @app.get("/profiles")
    async def profiles_list():
        return await _admin(lambda: _profiles().list())

    @app.post("/profiles")
    async def profiles_create(request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: _profiles().create(body.get("name")))

    @app.patch("/profiles/{name}")
    async def profiles_update(name: str, request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: _profiles().set_headed(name, bool(body.get("headed"))))

    @app.delete("/profiles/{name}")
    async def profiles_remove(name: str):
        return await _admin(lambda: registry.remove_profile(name) or {"removed": name})

    @app.post("/tabs/owner")
    async def tabs_owner(request: Request):
        """The operator hands a tab to a session, or frees it (session: null)."""
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body

        def work():
            if not registry.is_operator(_token(request)):
                raise OpError(
                    "session_sealed", "reassigning tabs needs the operator token"
                )
            profile = body.get("profile") or DEFAULT
            tabs = _profiles().tabs(profile)
            target = tabs.target_of(str(body.get("tab_id")))
            if target is None:
                for row in _profiles().targets(profile):
                    tabs.label(row["id"])
                target = tabs.target_of(str(body.get("tab_id")))
            if target is None:
                raise OpError("tab_not_found", f"no tab {body.get('tab_id')!r} on {profile}")
            owner = body.get("session")
            if owner is not None:
                registry.info(owner)  # unknown_session if there is no such session
            return {"tab_id": tabs.set_owner(target, owner), "session": owner}

        return await _admin(work)
```

Import `DEFAULT` from `.profiles` and `NO_SESSIONS` from `.sessions`.

Logs: replace `_root()` with:

```python
    def _logs_of(request: Request) -> tuple[Session | None, Path | None]:
        sess = _session_for(request)
        return sess, sess.log_root
```

In each `/logs*` route add `request: Request`, wrap the resolution in `try/except OpError as exc: return _refused(exc)`, and use `root` from `_logs_of`. In `/logs`, `"current"` becomes `sess.started_recorder.session_id if sess.started_recorder else None`, and `"recording"` is `root is not None`.

- [ ] **Step 3: Verify by reading**

Trace `test_logs_are_per_session`. The `status` command in session `a` creates its recorder at `<tmp>/logs/sessions/a/<run>/`, so `list_sessions` on that root returns one run. The default session has no recorder yet, so `list_sessions(<tmp>/logs/sessions/default)` returns `[]` because the directory does not exist.

- [ ] **Step 4: Commit**

```bash
git add src/abt/server.py tests/test_server_admin.py
git commit -m "Add session, profile and tab-owner routes, and per-session logs"
```

- [ ] **Step 5: Push point.** Ask the user whether to push so CI runs Tasks 7–9.

---

### Task 10: Screencast

**Files:**
- Create: `src/abt/screencast.py`
- Modify: `src/abt/server.py` (WebSocket route)
- Test: create `tests/test_screencast.py` (no browser) and `tests/test_screencast_live.py`

**Interfaces:**
- Consumes: `ProfileRegistry.tabs/targets/running/watch`, `TabRegistry.access`, `registry.get/is_operator/info`.
- Produces: `screencast.to_cdp(event: dict) -> tuple[str, dict] | None`; `async screencast.relay(client, devtools_url, quality=60, max_width=1600)`; route `WS /screencast?tab=&session=&profile=&token=`. Messages to the client are `{"type": "frame", "data": <base64 jpeg>, "metadata": {...}}`, or an error envelope before close. Messages from the client are `{"type": "mouse", "event", "x", "y", "button"?, "clickCount"?, "deltaX"?, "deltaY"?, "modifiers"?}`, `{"type": "key", "event", "key"?, "code"?, "text"?, "modifiers"?, "windowsVirtualKeyCode"?}`, or `{"type": "text", "text"}`. Coordinates are CSS pixels of the page; the GUI scales from the image using `metadata.deviceWidth`.

- [ ] **Step 1: Write the tests**

Create `tests/test_screencast.py`:

```python
"""Screencast input translation and access rules. No browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.screencast import to_cdp
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


def test_a_click_is_a_mouse_event():
    method, params = to_cdp({"type": "mouse", "event": "mousePressed", "x": 5, "y": 6})
    assert method == "Input.dispatchMouseEvent"
    assert params == {
        "type": "mousePressed", "x": 5.0, "y": 6.0, "button": "left",
        "clickCount": 1, "modifiers": 0,
    }


def test_a_wheel_carries_deltas():
    _, params = to_cdp({"type": "mouse", "event": "mouseWheel", "x": 1, "y": 1, "deltaY": 120})
    assert params["deltaY"] == 120.0 and params["deltaX"] == 0.0


def test_keys_and_text():
    assert to_cdp({"type": "key", "event": "keyDown", "key": "Enter"})[0] == "Input.dispatchKeyEvent"
    assert to_cdp({"type": "text", "text": "hi"}) == ("Input.insertText", {"text": "hi"})


@pytest.mark.parametrize("bad", [
    {}, {"type": "mouse", "event": "explode", "x": 1, "y": 1},
    {"type": "mouse", "event": "mouseMoved"}, {"type": "key", "event": "nope"},
    {"type": "eval", "expression": "1"},
])
def test_anything_else_is_dropped(bad):
    assert to_cdp(bad) is None


@pytest.fixture
def client(tmp_path):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        operator_token="op",
    )
    registry.create("s", sealed=True)
    with TestClient(create_app(registry=registry)) as c:
        yield c


def test_a_sealed_sessions_tabs_need_its_token(client):
    with client.websocket_connect("/screencast?tab=tab_0&session=s") as ws:
        assert ws.receive_json()["error"]["type"] == "session_sealed"


def test_an_unknown_tab_is_refused(client):
    with client.websocket_connect("/screencast?tab=tab_9&token=op") as ws:
        assert ws.receive_json()["error"]["type"] == "tab_not_found"
```

Create `tests/test_screencast_live.py`:

```python
"""A real frame arrives and a real click lands."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore

PAGE = (
    "data:text/html,<button id=b style='position:fixed;left:0;top:0;"
    "width:200px;height:200px' onclick='document.title=\"hit\"'>x</button>"
)


@pytest.fixture
def setup(tmp_path, budgets):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        operator_token="op",
    )
    with TestClient(create_app(registry=registry)) as client:
        yield registry, client
    registry.close_all()


def test_frames_stream_and_clicks_land(setup):
    registry, client = setup
    client.post("/command-list", json=[{"op": "browser_start"}, {"op": "goto", "url": PAGE}])
    tab = registry.get(None).browser.active_tab
    with client.websocket_connect(f"/screencast?tab={tab}") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "frame"
        assert frame["data"].startswith("/9j/")  # JPEG, base64
        for event in ("mousePressed", "mouseReleased"):
            ws.send_json({"type": "mouse", "event": event, "x": 50, "y": 50})
        ws.send_json({"type": "text", "text": ""})
    # The click is dispatched asynchronously in Chrome; give it a moment.
    title = None
    for _ in range(30):
        body = client.post(
            "/command-list", json={"op": "run_js", "script": "return document.title"}
        ).json()
        title = body["result"]["value"]
        if title == "hit":
            break
        time.sleep(0.1)
    assert title == "hit"
```

- [ ] **Step 2: Implement**

Create `src/abt/screencast.py`:

```python
"""A live view of one tab, and a way to reach into it.

The server opens Chrome's own DevTools WebSocket for the tab and relays
between it and the GUI. That is a separate DevTools client from every
session's Playwright connection, so watching never contends with an agent
working the same tab.

Input is translated from a small, closed vocabulary rather than forwarded as
raw CDP: a raw pipe would hand whoever holds the socket every DevTools method,
`Runtime.evaluate` included -- which is `run_js` without the switch that can
turn it off.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

MOUSE = {"mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"}
KEYS = {"keyDown", "keyUp", "rawKeyDown", "char"}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_cdp(event: Any) -> tuple[str, dict] | None:
    """One GUI input event as one CDP call, or None to drop it."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "mouse" and event.get("event") in MOUSE:
        x, y = _number(event.get("x")), _number(event.get("y"))
        if x is None or y is None:
            return None
        params: dict[str, Any] = {
            "type": event["event"],
            "x": x,
            "y": y,
            "modifiers": int(event.get("modifiers") or 0),
        }
        if event["event"] == "mouseWheel":
            params["deltaX"] = _number(event.get("deltaX")) or 0.0
            params["deltaY"] = _number(event.get("deltaY")) or 0.0
        else:
            params["button"] = str(event.get("button") or "left")
            params["clickCount"] = int(event.get("clickCount") or 1)
        return "Input.dispatchMouseEvent", params
    if kind == "key" and event.get("event") in KEYS:
        params = {"type": event["event"], "modifiers": int(event.get("modifiers") or 0)}
        for name in ("key", "code", "text"):
            if isinstance(event.get(name), str):
                params[name] = event[name]
        if event.get("windowsVirtualKeyCode") is not None:
            params["windowsVirtualKeyCode"] = int(event["windowsVirtualKeyCode"])
        return "Input.dispatchKeyEvent", params
    if kind == "text" and isinstance(event.get("text"), str):
        return "Input.insertText", {"text": event["text"]}
    return None


async def relay(client, devtools_url: str, quality: int = 60, max_width: int = 1600) -> None:
    """Pump frames to `client` and its input to Chrome until either side goes."""
    from websockets.asyncio.client import connect

    ids = itertools.count(1)
    async with connect(devtools_url, max_size=None) as chrome:

        async def send(method: str, params: dict | None = None) -> None:
            await chrome.send(json.dumps({"id": next(ids), "method": method, "params": params or {}}))

        await send("Page.startScreencast", {
            "format": "jpeg",
            "quality": quality,
            "maxWidth": max_width,
            "maxHeight": max_width,
        })

        async def from_chrome() -> None:
            async for raw in chrome:
                message = json.loads(raw)
                method = message.get("method")
                if method == "Page.screencastFrame":
                    params = message["params"]
                    # Unacknowledged, Chrome stops sending after a frame or two.
                    await send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
                    await client.send_json({
                        "type": "frame",
                        "data": params["data"],
                        "metadata": params.get("metadata", {}),
                    })
                elif method == "Inspector.detached":
                    return

        async def from_client() -> None:
            while True:
                call = to_cdp(await client.receive_json())
                if call is not None:
                    await send(*call)

        tasks = {asyncio.create_task(from_chrome()), asyncio.create_task(from_client())}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and type(exc).__name__ not in ("WebSocketDisconnect", "ConnectionClosedOK"):
                raise exc
```

In `server.py`, import `WebSocket` from `fastapi`, `from . import screencast as screencast_util`, `from .tabs import OWN` and `from .browser import NO_BROWSER_MESSAGE`, then add:

```python
    # --- screencast --------------------------------------------------------------

    def _screencast_target(
        name: str | None, profile: str | None, tab: str | None, token: str | None
    ) -> tuple[str, str, int]:
        profiles = _profiles()
        if not tab:
            raise OpError("invalid_op", "screencast needs ?tab=")
        if registry.is_operator(token):
            # The human at the GUI: any tab, locks included.
            profile = profile or (registry.info(name)["profile"] if name else DEFAULT)
            watcher = None
        else:
            sess = registry.get(name or None, token)
            profile, watcher = sess.record.profile, sess.name
        tabs = profiles.tabs(profile)
        target = tabs.target_of(tab)
        if target is None:
            for row in profiles.targets(profile):
                tabs.label(row["id"])
            target = tabs.target_of(tab)
        if target is None:
            raise OpError("tab_not_found", f"no tab {tab!r} on {profile}")
        if watcher is not None and tabs.access(target, watcher) != OWN:
            raise OpError("tab_locked", f"{tab} is not this session's")
        running = profiles.running(profile)
        if running is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        return profile, target, running.port

    @app.websocket("/screencast")
    async def screencast(ws: WebSocket):
        params = ws.query_params
        token = ws.headers.get("x-abt-token") or params.get("token")
        await ws.accept()
        try:
            profile, target, port = await run_in_threadpool(
                _screencast_target,
                params.get("session"), params.get("profile"), params.get("tab"), token,
            )
        except OpError as exc:
            await ws.send_json(fail(exc))
            await ws.close(code=1008)
            return
        registry.profiles.watch(profile, +1)
        try:
            await screencast_util.relay(ws, f"ws://127.0.0.1:{port}/devtools/page/{target}")
        except Exception:
            pass
        finally:
            registry.profiles.watch(profile, -1)
            try:
                await ws.close()
            except Exception:
                pass
```

- [ ] **Step 3: Verify with a live probe**

`<scratchpad>/probe_screencast.py`: build the registry as in the live test, start the default session, `goto` the button page, then open the WebSocket through `TestClient` and print the first frame's `metadata`. Send a click and print `document.title`. Run it with `PYTHONPATH=src py`, expect `hit`, then delete the probe.

- [ ] **Step 4: Commit**

```bash
git add src/abt/screencast.py src/abt/server.py tests/test_screencast.py tests/test_screencast_live.py
git commit -m "Add the screencast: a live, clickable view of one tab"
```

---

### Task 11: CLI and MCP

**Files:**
- Modify: `src/abt/cli.py` (`_main` callback, `_call`, `serve`, `mcp`; new `session_app`, `profile_app`, `_headers`, `_build_registry`)
- Modify: `src/abt/mcp.py` (`Bridge.__init__`, `serve`)
- Modify: `tests/test_surface_parity.py` (`LIFECYCLE`)
- Test: create `tests/test_cli_sessions.py`; append to `tests/test_mcp.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `abt --session NAME --token T <cmd>` (env `ABT_SESSION`, `ABT_TOKEN`); `abt session list|new|show|set|rm`; `abt profile list|new|rm|set`; `abt serve --max-profiles N --profile-idle-minutes M`; `abt mcp --session NAME --token T`; `mcp.Bridge(api, timeout=180.0, session=None, token=None)`; `mcp.serve(api, stdin=None, stdout=None, session=None, token=None)`.

- [ ] **Step 1: Write the tests**

Create `tests/test_cli_sessions.py`:

```python
"""The CLI carries the session on every call and manages sessions and profiles.

httpx.request is replaced, so no server is needed.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from abt import cli


class Reply:
    def json(self):
        return {"ok": True, "result": {}}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def request(method, url, json=None, headers=None, timeout=None):
        seen.append({"method": method, "url": url, "json": json, "headers": headers or {}})
        return Reply()

    monkeypatch.setattr(cli.httpx, "request", request)
    monkeypatch.delenv("ABT_SESSION", raising=False)
    monkeypatch.delenv("ABT_TOKEN", raising=False)
    return seen


def run(*args, env=None):
    return CliRunner().invoke(cli.app, list(args), env=env or {})


def test_the_session_rides_along(calls):
    run("--session", "a", "command-list", '{"op":"status"}')
    assert calls[-1]["headers"]["X-ABT-Session"] == "a"


def test_the_environment_names_the_session_and_token(calls):
    run("command-list", '{"op":"status"}', env={"ABT_SESSION": "b", "ABT_TOKEN": "t"})
    assert calls[-1]["headers"] == {"X-ABT-Session": "b", "X-ABT-Token": "t"}


def test_no_session_sends_no_header(calls):
    run("command-list", '{"op":"status"}')
    assert "X-ABT-Session" not in calls[-1]["headers"]


def test_session_management(calls):
    run("session", "new", "a", "--profile", "work", "--sealed")
    assert calls[-1]["method"] == "POST" and calls[-1]["url"].endswith("/sessions")
    assert calls[-1]["json"] == {"name": "a", "profile": "work", "sealed": True}
    run("session", "set", "a", "--profile", "home")
    assert calls[-1]["method"] == "PATCH" and calls[-1]["json"] == {"profile": "home"}
    run("session", "rm", "a", "--yes")
    assert calls[-1]["method"] == "DELETE" and calls[-1]["url"].endswith("/sessions/a")


def test_profile_management(calls):
    run("profile", "new", "work")
    assert calls[-1]["json"] == {"name": "work"}
    run("profile", "set", "work", "--headed")
    assert calls[-1]["method"] == "PATCH" and calls[-1]["json"] == {"headed": True}
    run("profile", "rm", "work", "--yes")
    assert calls[-1]["method"] == "DELETE"
```

Append to `tests/test_mcp.py`:

```python
def test_the_bridge_carries_its_session_and_token():
    bridge = Bridge("http://127.0.0.1:1", session="a", token="t")
    assert bridge.client.headers["x-abt-session"] == "a"
    assert bridge.client.headers["x-abt-token"] == "t"
    assert "x-abt-session" not in Bridge("http://127.0.0.1:1").client.headers
```

In `tests/test_surface_parity.py`, add `"session", "profile",` to `LIFECYCLE` with the comment `# sessions and profiles: where commands run, not what they do`.

- [ ] **Step 2: Implement**

In `cli.py`, near `DEFAULT_PORT`:

```python
# Set once per invocation by the global --session/--token options, and sent
# with every call to the server.
_ROUTE: dict[str, str | None] = {"session": None, "token": None}


def _headers() -> dict[str, str]:
    headers = {}
    if _ROUTE["session"]:
        headers["X-ABT-Session"] = _ROUTE["session"]
    if _ROUTE["token"]:
        headers["X-ABT-Token"] = _ROUTE["token"]
    return headers
```

Add these parameters to the `_main` callback, and set `_ROUTE` in its body:

```python
    session: Optional[str] = typer.Option(
        None,
        "--session",
        envvar="ABT_SESSION",
        help="Run in this session instead of `default`. Keeps cooperating "
        "agents apart; it is NOT a security boundary -- any process can name "
        "any open session.",
    ),
    token: Optional[str] = typer.Option(
        None, "--token", envvar="ABT_TOKEN", help="The token of a sealed session."
    ),
```

```python
    _ROUTE["session"] = session
    _ROUTE["token"] = token
```

In `_call`, replace the `if method == "GET": ... else: ...` block with:

```python
        response = httpx.request(
            method,
            url,
            json=None if method == "GET" else payload,
            headers=_headers(),
            timeout=timeout,
        )
```

Add the groups after `browser_app`:

```python
session_app = typer.Typer(
    add_completion=False,
    help="Sessions: a profile, its settings, its tabs and its log. Whoever "
    "launches an agent chooses its session; the agent never does.",
)
app.add_typer(session_app, name="session")
profile_app = typer.Typer(
    add_completion=False, help="Named browser profiles, each with its own logins."
)
app.add_typer(profile_app, name="profile")
```

```python
@session_app.command("list")
def session_list(port: int = _port_option()) -> None:
    """Every session, its profile, and whether its browser is connected."""
    _call(port, "/sessions", method="GET")


@session_app.command("new")
def session_new(
    name: str = typer.Argument(..., help="Letters, digits, '.', '_', '-'."),
    profile: str = typer.Option("default", "--profile", help="Profile it runs on."),
    sealed: bool = typer.Option(
        False,
        "--sealed",
        help="Require a token for every command. Printed once, and saved "
        "beside the session for the program that launches the agent.",
    ),
    port: int = _port_option(),
) -> None:
    """Create a session. It starts with no browser: send browser_start in it."""
    _call(port, "/sessions", {"name": name, "profile": profile, "sealed": sealed})


@session_app.command("show")
def session_show(name: str, port: int = _port_option()) -> None:
    _call(port, f"/sessions/{name}", method="GET")


@session_app.command("set")
def session_set(
    name: str,
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Move to another profile. Closes the session's tabs."
    ),
    port: int = _port_option(),
) -> None:
    """Change a session. Applies from its next command."""
    payload = {}
    if profile is not None:
        payload["profile"] = profile
    _call(port, f"/sessions/{name}", payload, method="PATCH")


@session_app.command("rm")
def session_rm(
    name: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask."),
    port: int = _port_option(),
) -> None:
    """Remove a session. Its tabs close; its logs are kept."""
    if not _confirm(f"Remove session {name}? Its tabs close; its logs are kept.", yes):
        raise typer.Exit(1)
    _call(port, f"/sessions/{name}", method="DELETE")


@profile_app.command("list")
def profile_list(port: int = _port_option()) -> None:
    _call(port, "/profiles", method="GET")


@profile_app.command("new")
def profile_new(name: str, port: int = _port_option()) -> None:
    """Create an empty profile. Sign in through a session on it."""
    _call(port, "/profiles", {"name": name})


@profile_app.command("set")
def profile_set(
    name: str,
    headed: bool = typer.Option(
        ...,
        "--headed/--headless",
        help="Show a real window for sites that misbehave hidden. Applies the "
        "next time the profile's browser starts.",
    ),
    port: int = _port_option(),
) -> None:
    _call(port, f"/profiles/{name}", {"headed": headed}, method="PATCH")


@profile_app.command("rm")
def profile_rm(
    name: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask."),
    port: int = _port_option(),
) -> None:
    """Delete a profile and every login in it. Cannot be undone."""
    if not _confirm(f"Delete profile {name} and every login in it? This cannot be undone.", yes):
        raise typer.Exit(1)
    _call(port, f"/profiles/{name}", method="DELETE")
```

In `serve`, add the options:

```python
    max_profiles: int = typer.Option(
        4,
        "--max-profiles",
        help="Most profile browsers running at once. A launch past it is "
        "refused; nothing is ever closed to make room.",
    ),
    profile_idle_minutes: float = typer.Option(
        30.0,
        "--profile-idle-minutes",
        help="Stop a profile's browser after this long with no commands and "
        "nobody watching it. 0 keeps browsers running.",
    ),
```

Replace the body from `session = BrowserSession(` down to (but not including) `config = uvicorn.Config(` with:

```python
    behaviour = dict(
        action_timeout=action_timeout,
        diff_enabled=not no_diff,
        diff_max_tokens=diff_max_tokens,
        settle_timeout=settle_timeout,
        settle_network_grace=settle_network_grace,
        interaction_settle=interaction_settle,
        frames_enabled=not no_frames,
        run_js_enabled=not no_run_js,
        max_frames=max_frames,
        max_frame_depth=max_frame_depth,
        engine=engine,
    )
    holder: dict[str, Any] = {}
    stop = lambda: holder["server"].__setattr__("should_exit", True)  # noqa: E731
    shot_options = dict(shots=not no_shots, shot_quality=shot_quality, shot_width=shot_width)

    if engine == "playwright":
        registry = _build_registry(
            browser, profile, headless, log_dir, no_log, shots_max_mb,
            max_profiles, profile_idle_minutes, behaviour,
        )
        default = registry.get(None).browser
        if start_browser:
            typer.echo(f"starting {browser} (profile: {default.profile})")
            default.start()
        else:
            typer.echo(f"no browser running (default profile: {default.profile})")
            typer.echo('start one with {"op": "browser_start"} or POST /browser/start')
        typer.echo(f"sessions: {len(registry.list())} (`abt session list`)")
        typer.echo(f"operator token -> {paths.sessions_dir() / 'operator.token'}")
        application = create_app(registry=registry, request_stop=stop, **shot_options)
        registry.start_reaper()
        closer = registry.close_all
    else:
        session = BrowserSession(profile=profile, browser=browser, headless=headless, **behaviour)
        if start_browser:
            typer.echo(f"starting {browser} via {engine} (profile: {session.profile})")
            session.start()
        else:
            typer.echo(f"no browser running (default: {browser}, profile: {session.profile})")
            typer.echo('start one with {"op": "browser_start"} or POST /browser/start')
        recorder = None if no_log else SessionRecorder(log_dir, max_shot_mb=shots_max_mb)
        if recorder is not None:
            typer.echo(f"recording session {recorder.session_id} -> {recorder.path}")
            if not no_shots:
                typer.echo(f"capturing frames -> {recorder.shots_dir}")
        application = create_app(session, request_stop=stop, recorder=recorder, **shot_options)
        closer = session.quit
```

Change the `if recorder is not None: typer.echo(f"log viewer ...")` line to `if not no_log:`. In `finally:` replace `session.quit()` with `closer()`.

Add:

```python
def _build_registry(
    browser, profile, headless, log_dir, no_log, shots_max_mb,
    max_profiles, idle_minutes, behaviour,
):
    """The sessions a playwright server runs: profiles, records, the operator."""
    import secrets

    from .browser import BrowserSession
    from .profiles import ProfileRegistry
    from .sessions import SessionRegistry, SessionStore, write_private

    profiles = ProfileRegistry(
        root=paths.profile_root(),
        default_dir=profile,
        browser=browser,
        max_running=max_profiles,
        idle_minutes=idle_minutes,
        # A server started without --headless showed its window before
        # sessions existed, and still does for the default profile.
        default_headed=not headless,
    )
    store_dir = paths.sessions_dir()
    # A fresh operator token per server run, readable only by this user. The
    # desktop app reads it from here; nothing ever sends it to a model.
    operator = secrets.token_urlsafe(32)
    write_private(store_dir / "operator.token", operator)

    def make_browser(directory, attach):
        return BrowserSession(
            profile=directory, browser=browser, headless=headless, attach=attach, **behaviour
        )

    return SessionRegistry(
        SessionStore(store_dir),
        profiles,
        make_browser,
        log_root=None if no_log else log_dir,
        recorder_options={"max_shot_mb": shots_max_mb},
        operator_token=operator,
    )
```

Change the `mcp` command:

```python
@app.command()
def mcp(
    api: str = typer.Option(
        "http://127.0.0.1:8765", "--api", help="Where the toolkit server is listening."
    ),
    session: Optional[str] = typer.Option(
        None, "--session", envvar="ABT_SESSION",
        help="Bind this connection to a session. Fixed for its life; no tool can change it.",
    ),
    token: Optional[str] = typer.Option(None, "--token", envvar="ABT_TOKEN"),
) -> None:
    """..."""  # keep the existing docstring
    from . import mcp as mcp_module

    mcp_module.serve(
        api, session=session or _ROUTE["session"], token=token or _ROUTE["token"]
    )
```

In `mcp.py`:

```python
class Bridge:
    """Forwards tool calls to the HTTP API."""

    def __init__(
        self,
        api: str = DEFAULT_API,
        timeout: float = 180.0,
        session: str | None = None,
        token: str | None = None,
    ) -> None:
        self.api = api.rstrip("/")
        # Bound here, once, by whoever launched this process -- never by the
        # model. No tool takes a session, so a model cannot leave its own.
        headers = {}
        if session:
            headers["X-ABT-Session"] = session
        if token:
            headers["X-ABT-Token"] = token
        self.client = httpx.Client(timeout=timeout, headers=headers)
```

```python
def serve(
    api: str = DEFAULT_API,
    stdin=None,
    stdout=None,
    session: str | None = None,
    token: str | None = None,
) -> None:
    ...
    server = Server(Bridge(api, session=session, token=token))
```

- [ ] **Step 3: Verify by reading**

Confirm `_confirm(question, assume_yes)` returns True for `--yes` without prompting (read `cli.py:1116`). Confirm `CliRunner().invoke(cli.app, ...)` runs the `_main` callback, which sets `_ROUTE`, before the subcommand. Confirm `serve` no longer references `session` in the playwright branch.

- [ ] **Step 4: Commit**

```bash
git add src/abt/cli.py src/abt/mcp.py tests/test_cli_sessions.py tests/test_mcp.py tests/test_surface_parity.py
git commit -m "Add sessions and profiles to the CLI and MCP, and serve them"
```

---

### Task 12: End-to-end live tests

**Files:**
- Test: create `tests/test_sessions_live.py`
- Modify: any source file only if a probe exposes a defect (fix it in this task, with the test that exposed it)

**Interfaces:**
- Consumes: the full server in registry mode.

- [ ] **Step 1: Write the tests**

Create `tests/test_sessions_live.py`:

```python
"""The whole thing, over HTTP, against real Chrome.

The timing tests use the fixture server's `?delay=` so each goto takes a known
two seconds; serial execution would take at least four.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def env(tmp_path, budgets):
    profiles = ProfileRegistry(root=tmp_path / "profiles")
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        profiles,
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        operator_token="op",
    )
    profiles.create("p1")
    profiles.create("p2")
    registry.create("s1", profile="p1")
    registry.create("s2", profile="p2")
    registry.create("s3", profile="p1")
    with TestClient(create_app(registry=registry)) as client:
        yield registry, client
    registry.close_all()


def send(client, session, body, token=None):
    headers = {"X-ABT-Session": session}
    if token:
        headers["X-ABT-Token"] = token
    return client.post("/command-list", json=body, headers=headers).json()


def both(client, first, second, body):
    out = {}
    threads = [
        threading.Thread(target=lambda s=s: out.__setitem__(s, send(client, s, body)))
        for s in (first, second)
    ]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return time.monotonic() - started, out


def start(client, *sessions):
    for s in sessions:
        assert send(client, s, {"op": "browser_start"})["ok"] is True


def test_two_profiles_run_in_parallel(env, base_url):
    _, client = env
    start(client, "s1", "s2")
    took, out = both(client, "s1", "s2", {"op": "goto", "url": f"{base_url}/form.html?delay=2"})
    assert all(r["ok"] for r in out.values())
    assert took < 3.5


def test_two_sessions_on_one_profile_run_in_parallel(env, base_url):
    _, client = env
    start(client, "s1", "s3")
    took, out = both(client, "s1", "s3", {"op": "goto", "url": f"{base_url}/form.html?delay=2"})
    assert all(r["ok"] for r in out.values())
    assert took < 3.5


def test_isolation_across_and_within_profiles(env, base_url):
    _, client = env
    start(client, "s1", "s2", "s3")
    send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})
    mine = send(client, "s1", {"op": "status"})["result"]["active_tab"]
    shared = send(client, "s3", {"op": "tab_list"})["result"]
    assert {"tab_id": mine, "locked": "s1"} in shared
    refused = send(client, "s3", {"op": "tab_switch", "tab_id": mine})
    assert refused["error"]["type"] == "tab_locked"
    other = send(client, "s2", {"op": "tab_list"})["result"]
    assert all("form.html" not in (row.get("url") or "") for row in other)


def test_a_popup_stays_with_its_session(env, base_url):
    _, client = env
    start(client, "s1", "s3")
    send(client, "s1", {"op": "run_js", "script": f"window.open('{base_url}/cards.html')"})
    own = [r for r in send(client, "s1", {"op": "tab_list"})["result"] if "locked" not in r and "unowned" not in r]
    assert len(own) == 2
    locked = [r for r in send(client, "s3", {"op": "tab_list"})["result"] if r.get("locked") == "s1"]
    assert len(locked) == 2


def test_a_sealed_session_over_http(env):
    registry, client = env
    token = registry.create("sealed", profile="p2", sealed=True)["token"]
    assert send(client, "sealed", {"op": "status"})["error"]["type"] == "session_sealed"
    assert send(client, "sealed", {"op": "status"}, token=token)["ok"] is True


def test_a_crashed_profile_comes_back_on_restart(env, base_url):
    registry, client = env
    start(client, "s1")
    registry.profiles.running("p1").process.kill()
    registry.profiles.running("p1")  # noticed dead and forgotten
    dead = send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})
    assert dead["ok"] is False
    assert send(client, "s1", {"op": "browser_restart"})["ok"] is True
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True


def test_idle_profiles_are_stopped_and_can_start_again(env):
    registry, client = env
    start(client, "s2")
    registry.profiles.idle_seconds = 0.01
    time.sleep(0.05)
    assert "p2" in registry.reap_idle()
    assert send(client, "s2", {"op": "status"})["result"]["running"] is False
    start(client, "s2")
```

- [ ] **Step 2: Verify with a live probe**

`<scratchpad>/probe_e2e.py` replays `test_two_sessions_on_one_profile_run_in_parallel` and `test_isolation_across_and_within_profiles` through `TestClient`. Serve fixtures with `http.server` on a free port (copy `_serve` from `tests/conftest.py`). Print the timing and the `tab_list` rows, then delete the probe. If `took` is close to 4s, `bring_to_front` or throttling is back: check the flags in `launch_argv` and the gate branch in `_activate`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sessions_live.py
git commit -m "Test sessions end to end: parallelism, isolation, popups, sealing, recovery"
```

---

### Task 13: Viewer picker and documentation

**Files:**
- Modify: `src/abt/viewer.py` (header markup, `get`, `boot`, `shotUrl`)
- Modify: `AGENTS.md`, `guidelines/toolkit-workflow.md`, `README.md`, `docs/reference.md` (errors table), `docs/known-issues.md`
- Modify: `docs/superpowers/specs/2026-08-19-profile-sessions-design.md` (status line)

**Interfaces:**
- Consumes: `GET /sessions`, `/logs?session=`.

- [ ] **Step 1: Viewer**

In `VIEWER_HTML`, after `<span class="sub" id="hint">loading…</span>`, add `<select id="session-pick" hidden></select>`. In the script, replace `get` and `shotUrl` and extend `boot`:

```js
// Which session's logs these are. Carried on every request, so frames and
// filtered views stay inside the session that was picked.
const routeSession = new URLSearchParams(location.search).get("session") || "";
const withSession = (url) => routeSession
  ? url + (url.includes("?") ? "&" : "?") + "session=" + encodeURIComponent(routeSession)
  : url;

async function get(url) {
  const r = await fetch(withSession(url));
  const b = await r.json();
  if (!b.ok) throw new Error((b.error && b.error.message) || "request failed");
  return b.result;
}

async function pickerFill() {
  try {
    const r = await fetch("/sessions");
    const b = await r.json();
    // Sealed sessions' logs need their token, which this page never has.
    const open = (b.result || []).filter(s => !s.sealed);
    if (open.length < 2) return;
    const pick = $("#session-pick");
    pick.innerHTML = open.map(s =>
      `<option value="${esc(s.name)}"${s.name === (routeSession || "default") ? " selected" : ""}>${esc(s.name)}</option>`
    ).join("");
    pick.hidden = false;
    pick.onchange = () => { location.search = "?session=" + encodeURIComponent(pick.value); };
  } catch (e) { /* an older server without sessions */ }
}
```

At the top of `boot()`, add `pickerFill();`. `shotUrl` returns `withSession(\`/logs/${...}/shots/${...}\`)`.

- [ ] **Step 2: Documentation**

`AGENTS.md`, after "The eight rules", add:

```markdown
## Sessions

Every command runs in a **session**: a profile (its logins), its own tabs, its
own log. Say nothing and you are in `default`, which behaves exactly as this
server always has. Whoever launches you picks your session (`ABT_SESSION`,
`abt --session`, `abt mcp --session`) — do not pick one yourself.

- `--session` is **not** a security boundary. Any process can name any open
  session; it only keeps cooperating agents out of each other's way.
- **Sealed** sessions need a token only their launcher holds. `session_sealed`
  means it is not yours to use.
- A tab belongs to the session that opened it, and popups follow it. Another
  session's tab shows in `tab_list` as `locked` and refuses every action with
  `tab_locked` — open your own with `tab_new` rather than retrying.
- `tab_claim` takes an `unowned` tab; `tab_release` gives one up.
- Sessions on different profiles, and on the same profile, run in parallel.
```

In `guidelines/toolkit-workflow.md`, add the same bullets as a "Sessions" subsection next to the tabs table. In `README.md`, add a "Sessions and profiles" section with the CLI examples from Task 11 and the "not a security boundary" warning. In `docs/reference.md`, add the seven new error types to the errors table with one line each (copy the `HINTS` text). In `docs/known-issues.md`, add: "Each running profile is a full Chrome (roughly 300–500 MB). `--max-profiles` caps them, and idle ones stop after `--profile-idle-minutes`."

In `docs/superpowers/specs/2026-08-19-profile-sessions-design.md`, change `Status: Approved` to `Status: Superseded by 2026-09-28-multi-profile-sessions-design.md (never built)`.

- [ ] **Step 3: Verify by reading**

Open the viewer HTML string and check that every `fetch(` except the `/sessions` one goes through `get`/`withSession`. Grep `tests/test_guidelines.py` for assertions about `AGENTS.md` or `toolkit-workflow.md` content, and make sure the additions don't break any exact-text check.

- [ ] **Step 4: Commit**

```bash
git add src/abt/viewer.py AGENTS.md guidelines/toolkit-workflow.md README.md docs/reference.md docs/known-issues.md docs/superpowers/specs/2026-08-19-profile-sessions-design.md
git commit -m "Document sessions, and let the log viewer pick one"
```

- [ ] **Step 5: Push point.** Ask the user whether to push so CI runs the full suite.
