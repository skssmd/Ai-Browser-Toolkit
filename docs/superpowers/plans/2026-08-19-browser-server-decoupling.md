# Browser / Server Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the browser a resource the server manages rather than a precondition it requires — the server boots in ~1s with no browser, and gains explicit `browser_start`/`stop`/`restart`/`status` lifecycle control plus a launcher that spawns it outside the caller's job object.

**Architecture:** One `BrowserSession` lives for the server's lifetime with a *swappable* driver underneath it, so the nine closures in `create_app` and the twenty-seven `session` parameters in `messenger.py` stay valid across a restart. Launch parameters move into a frozen `LaunchConfig` that supports per-start overrides layered over serve-time defaults. Recovery is explicit-only: a dead browser returns `browser_dead` until someone asks for a new one.

**Tech Stack:** Python 3.11+, Selenium 4, FastAPI, uvicorn, Pydantic v2, Typer, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-browser-server-decoupling-design.md`

## Global Constraints

- **No new error types.** `errors.ERROR_TYPES` is a closed set and stays unchanged. Lifecycle failures use `browser_dead` (cannot drive the page) or `invalid_op` (nonsensical request, e.g. starting a browser that is already running). `OpError.__init__` raises `ValueError` on an unknown type, so a typo here fails loudly.
- **One browser maximum.** This changes the count from exactly-one to zero-or-one, never to many.
- **Never call `abt serve` from a tool call.** It never returns. Use `start-server.bat` / `./start-server.sh`, or `abt up` once Task 9 lands.
- **Existing public keys on `/status` are preserved** — `url`, `title`, `active_tab`, `tabs`, `refs_valid`, `headless`, `profile` — present whenever a browser is running.
- **`BrowserSession.__init__` keeps its current keyword signature** (`profile`, `browser`, `headless`, `action_timeout`, `diff_enabled`, `diff_max_tokens`, `settle_timeout`, `settle_network_grace`, `frames_enabled`, `max_frames`, `max_frame_depth`). `tests/conftest.py:78` and `tests/test_settle.py:142` construct it positionally-by-keyword and must keep working untouched.
- **Commit messages carry no attribution trailer.** No `Co-Authored-By`, no "Generated with Claude Code".
- **After editing anything under `src/abt/`, restart the server** or it keeps serving the old code.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/abt/launch.py` | create | `LaunchConfig`: what to launch (browser/profile/headless), validation, `merge`, `to_dict` |
| `src/abt/proc.py` | create | Spawning a process that outlives the caller and escapes its job object |
| `src/abt/browser.py` | modify | Re-entrant lifecycle: `start`/`stop`/`restart`/`is_running`/`_reset_state`, profile-release handling |
| `src/abt/schema.py` | modify | Four new command models, added to the `Command` union |
| `src/abt/ops/control.py` | modify | Four new handlers plus the shared `browser_state` helper |
| `src/abt/ops/__init__.py` | modify | Registry entries and `NO_HEALTH_CHECK` |
| `src/abt/server.py` | modify | `/browser/*` routes, `/health`, `running` on `/status` |
| `src/abt/cli.py` | modify | `serve` no longer launches; new `abt up` |
| `src/abt/mcp.py` | modify | One `browser_session` tool |
| `tests/test_launch.py` | create | `LaunchConfig` unit tests, no browser |
| `tests/test_lifecycle.py` | create | Lifecycle unit tests + browser-less route tests |
| `tests/test_lifecycle_live.py` | create | The two tests that genuinely need Chrome |
| `tests/conftest.py` | modify | Add an `unstarted_session` fixture beside the existing eager one |

**Ordering note:** Tasks 1–8 are the decoupling and are strictly sequential. Task 9 (`abt up`) is independent of the browser lifecycle but depends on `/health` from Task 6, so it must not be started before then. Task 10 is documentation and lands last.

---

### Task 1: `LaunchConfig`

**Files:**
- Create: `src/abt/launch.py`
- Test: `tests/test_launch.py`

**Interfaces:**
- Consumes: `abt.errors.OpError`
- Produces: `LaunchConfig(browser: str = "chrome", profile: Path = Path("./profile"), headless: bool = False)`, frozen dataclass; `SUPPORTED_BROWSERS: tuple[str, ...]`; methods `merge(browser=None, profile=None, headless=None) -> LaunchConfig` and `to_dict() -> dict`. Construction lowercases `browser`, resolves `profile` to an absolute `Path`, and raises `OpError("bad_browser", …)` for anything unsupported.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_launch.py`:

```python
"""LaunchConfig: the parameters that describe the browser process itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from abt.errors import OpError
from abt.launch import SUPPORTED_BROWSERS, LaunchConfig


def test_defaults_are_chrome_windowed():
    config = LaunchConfig()
    assert config.browser == "chrome"
    assert config.headless is False


def test_browser_is_lowercased():
    assert LaunchConfig(browser="CHROME").browser == "chrome"
    assert LaunchConfig(browser="Edge").browser == "edge"


def test_an_unsupported_browser_raises_bad_browser():
    with pytest.raises(OpError) as exc:
        LaunchConfig(browser="firefox")
    assert exc.value.type == "bad_browser"
    assert "chrome" in exc.value.message


def test_profile_is_resolved_to_an_absolute_path(tmp_path):
    config = LaunchConfig(profile=tmp_path / "sub")
    assert config.profile.is_absolute()


def test_profile_accepts_a_string(tmp_path):
    config = LaunchConfig(profile=str(tmp_path))
    assert config.profile == tmp_path.resolve()


def test_merge_replaces_only_what_is_supplied(tmp_path):
    base = LaunchConfig(browser="chrome", profile=tmp_path, headless=False)
    merged = base.merge(headless=True)
    assert merged.headless is True
    assert merged.browser == "chrome"
    assert merged.profile == tmp_path.resolve()


def test_merge_treats_none_as_keep(tmp_path):
    base = LaunchConfig(browser="edge", profile=tmp_path, headless=True)
    assert base.merge(browser=None, profile=None, headless=None) == base


def test_merge_can_turn_headless_back_off(tmp_path):
    """False is a value, not an absence -- the bug a truthiness check would cause."""
    base = LaunchConfig(profile=tmp_path, headless=True)
    assert base.merge(headless=False).headless is False


def test_merge_validates_the_result(tmp_path):
    base = LaunchConfig(profile=tmp_path)
    with pytest.raises(OpError) as exc:
        base.merge(browser="safari")
    assert exc.value.type == "bad_browser"


def test_config_is_frozen(tmp_path):
    config = LaunchConfig(profile=tmp_path)
    with pytest.raises(Exception):
        config.browser = "edge"


def test_to_dict_is_json_safe(tmp_path):
    import json

    payload = LaunchConfig(profile=tmp_path).to_dict()
    assert set(payload) == {"browser", "profile", "headless"}
    assert isinstance(payload["profile"], str)
    json.dumps(payload)


def test_supported_browsers_is_what_the_session_offers():
    assert SUPPORTED_BROWSERS == ("chrome", "edge")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_launch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abt.launch'`

- [ ] **Step 3: Write the implementation**

Create `src/abt/launch.py`:

```python
"""What to launch: the parameters that describe the browser process itself.

Kept apart from the rest of BrowserSession's settings deliberately.
`action_timeout`, the diff budget and the settle windows are *behaviour* knobs
that hold no matter which browser is up; these three describe the *process*.
Keeping that line sharp is what stops `POST /browser/start` from accreting into
a second copy of `abt serve`'s twenty-flag list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import OpError

SUPPORTED_BROWSERS = ("chrome", "edge")


@dataclass(frozen=True)
class LaunchConfig:
    browser: str = "chrome"
    profile: Path = Path("./profile")
    headless: bool = False

    def __post_init__(self) -> None:
        browser = str(self.browser).strip().lower()
        if browser not in SUPPORTED_BROWSERS:
            raise OpError(
                "bad_browser",
                f"unsupported browser {self.browser!r}; "
                f"choose from {', '.join(SUPPORTED_BROWSERS)}",
            )
        # A frozen dataclass still gets to normalise itself during __post_init__;
        # object.__setattr__ is the sanctioned way in.
        object.__setattr__(self, "browser", browser)
        object.__setattr__(self, "profile", Path(self.profile).expanduser().resolve())

    def merge(
        self,
        browser: str | None = None,
        profile: Path | str | None = None,
        headless: bool | None = None,
    ) -> "LaunchConfig":
        """This config with only the supplied fields replaced.

        `None` means keep, which is why `headless` is compared against None
        rather than tested for truth -- `headless=False` is a caller asking for
        a window, not a caller saying nothing.
        """
        return LaunchConfig(
            browser=self.browser if browser is None else browser,
            profile=self.profile if profile is None else profile,
            headless=self.headless if headless is None else headless,
        )

    def to_dict(self) -> dict:
        return {
            "browser": self.browser,
            "profile": str(self.profile),
            "headless": self.headless,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_launch.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add src/abt/launch.py tests/test_launch.py
git commit -m "Add LaunchConfig, the parameters that describe the browser process

Separates what to launch (browser, profile, headless) from how to drive it
(timeouts, diff budget, settle windows). merge() layers per-start overrides
over serve-time defaults and treats None as keep, so headless=False can turn
a headless session back into a windowed one."
```

---

### Task 2: Re-entrant lifecycle on `BrowserSession`

**Files:**
- Modify: `src/abt/browser.py` (`__init__`, `start`, `quit`, `_make_options`, add `stop`/`restart`/`is_running`/`config`/`_reset_state`)
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: `LaunchConfig` from Task 1.
- Produces: on `BrowserSession` — properties `is_running -> bool`, `config -> LaunchConfig`, `defaults -> LaunchConfig`, `launch -> LaunchConfig | None`; methods `start(browser=None, profile=None, headless=None) -> dict`, `stop() -> dict`, `restart(browser=None, profile=None, headless=None) -> dict`, `_reset_state() -> None`. `start` returns `{"running": True, "config": {...}, "active_tab": str}`; `stop` returns `{"stopped": bool, "profile_released": bool}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lifecycle.py`:

```python
"""Browser lifecycle, tested without launching a browser.

Everything here pokes at state directly rather than starting Chrome. That is
the point: the reset and the config layering are exactly the logic that used to
be untestable because it was welded to a two-minute launch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abt.browser import BrowserSession
from abt.errors import OpError
from abt.launch import LaunchConfig


@pytest.fixture
def session(tmp_path):
    """A session that has never launched anything."""
    return BrowserSession(profile=tmp_path, headless=True, action_timeout=3.0)


def test_a_fresh_session_is_not_running(session):
    assert session.is_running is False
    assert session.launch is None


def test_the_constructor_signature_is_unchanged(tmp_path):
    """conftest.py and test_settle.py build it this way; they must keep working."""
    built = BrowserSession(profile=tmp_path, headless=True, action_timeout=3.0)
    assert built.profile == tmp_path.resolve()
    assert built.headless is True
    assert built.action_timeout == 3.0


def test_an_unsupported_browser_still_fails_at_construction(tmp_path):
    with pytest.raises(OpError) as exc:
        BrowserSession(profile=tmp_path, browser="firefox")
    assert exc.value.type == "bad_browser"


def test_config_falls_back_to_defaults_until_something_launches(session, tmp_path):
    assert session.config == session.defaults
    assert session.config.profile == tmp_path.resolve()


def test_starting_a_running_browser_is_refused(session):
    session._driver = object()  # pretend one is up
    with pytest.raises(OpError) as exc:
        session.start()
    assert exc.value.type == "invalid_op"
    assert "browser_restart" in exc.value.message


def test_reset_state_clears_everything_tied_to_a_driver(session):
    session._handles = {"tab_0": "h0", "tab_1": "h1"}
    session._order = ["tab_0", "tab_1"]
    session._counter = 7
    session._captured = {"h0"}
    session._baselines = {"tab_0": {"url": "x"}}
    session.last_target = object()
    session._in_frame = True
    previous_refs = session.refs

    session._reset_state()

    assert session._handles == {}
    assert session._order == []
    assert session._counter == 0
    assert session._captured == set()
    assert session._baselines == {}
    assert session.last_target is None
    assert session._in_frame is False
    # A whole new cache, not the old one emptied -- refs hold WebElements that
    # belong to a browser that no longer exists.
    assert session.refs is not previous_refs
    assert session.refs.count("tab_0") == 0


def test_stopping_a_stopped_session_is_harmless(session):
    result = session.stop()
    assert result["stopped"] is False


def test_restart_layers_over_the_effective_config_not_the_defaults(
    session, monkeypatch
):
    """A session started headless must come back headless."""
    session.launch = session.defaults.merge(headless=True, browser="edge")
    seen = {}

    def fake_start(browser=None, profile=None, headless=None):
        seen.update(browser=browser, profile=profile, headless=headless)
        return {"running": True}

    monkeypatch.setattr(session, "start", fake_start)
    monkeypatch.setattr(session, "stop", lambda: {"stopped": False})

    session.restart()

    assert seen["headless"] is True
    assert seen["browser"] == "edge"


def test_restart_overrides_beat_the_effective_config(session, monkeypatch):
    session.launch = session.defaults.merge(headless=True)
    seen = {}
    monkeypatch.setattr(
        session, "start", lambda **kw: seen.update(kw) or {"running": True}
    )
    monkeypatch.setattr(session, "stop", lambda: {"stopped": False})

    session.restart(headless=False)

    assert seen["headless"] is False


def test_start_after_stop_returns_to_the_serve_defaults(session, monkeypatch):
    """start means 'fresh'; restart means 'that same browser again'."""
    session.launch = session.defaults.merge(headless=True)
    session.stop()
    captured = {}

    def fake_launch(config):
        captured["config"] = config
        return object()

    monkeypatch.setattr(session, "_launch_driver", fake_launch)
    monkeypatch.setattr(session, "_verify_session", lambda: None)
    monkeypatch.setattr(session, "_install_console_capture", lambda: None)
    monkeypatch.setattr(session, "_sync_tabs", lambda: None)
    monkeypatch.setattr(
        type(session), "active_tab", property(lambda self: "tab_0")
    )

    session.start()

    assert captured["config"].headless is session.defaults.headless
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v`
Expected: FAIL — `AttributeError: 'BrowserSession' object has no attribute 'is_running'`

- [ ] **Step 3: Rewrite the lifecycle section of `browser.py`**

Replace the `_SUPPORTED_BROWSERS` constant and the import block at the top:

```python
from .errors import OpError
from .launch import LaunchConfig
from .refs import RefCache
```

Delete the module-level `_SUPPORTED_BROWSERS = ("chrome", "edge")` line — it now lives in `launch.py`.

In `__init__`, replace the browser-validation block and the three assignments:

```python
        # Validation lives in LaunchConfig, so an unsupported browser is
        # rejected identically whether it arrived from `abt serve` or from
        # POST /browser/start.
        self.defaults = LaunchConfig(
            browser=browser, profile=profile, headless=headless
        )
        # What is running now, or ran most recently. None until the first start.
        self.launch: LaunchConfig | None = None
```

Everything after `self.action_timeout = action_timeout` stays as it is. Add these properties immediately after `__init__`:

```python
    # --- launch configuration -------------------------------------------------

    @property
    def config(self) -> LaunchConfig:
        """The effective config: what is running, or what ran most recently."""
        return self.launch or self.defaults

    @property
    def browser(self) -> str:
        return self.config.browser

    @property
    def profile(self) -> Path:
        return self.config.profile

    @property
    def headless(self) -> bool:
        return self.config.headless

    @property
    def is_running(self) -> bool:
        return self._driver is not None
```

Replace the whole `start` method and `quit`:

```python
    # --- lifecycle ------------------------------------------------------------

    def start(
        self,
        browser: str | None = None,
        profile: Path | str | None = None,
        headless: bool | None = None,
    ) -> dict:
        """Launch a browser. Overrides layer over the serve-time defaults.

        Deliberately not idempotent. Silently no-op'ing a start that named a
        different profile would hand back a session on the wrong identity with
        no way to tell -- and the profile is the logins. A caller that wants
        "running, whatever it takes" wants `restart`.
        """
        if self.is_running:
            raise OpError(
                "invalid_op",
                "a browser is already running; use browser_restart to replace "
                "it, or browser_stop first",
            )
        config = self.defaults.merge(
            browser=browser, profile=profile, headless=headless
        )
        config.profile.mkdir(parents=True, exist_ok=True)
        self._driver = self._launch_driver(config)
        self.launch = config
        # Implicit waits interact badly with explicit waits and make every
        # failed lookup cost the full timeout. All waiting here is explicit.
        self._driver.implicitly_wait(0)
        self._verify_session()
        self._install_console_capture()
        self._sync_tabs()
        return {
            "running": True,
            "config": config.to_dict(),
            "active_tab": self.active_tab,
        }

    def _launch_driver(self, config: LaunchConfig):
        options = self._make_options(config)
        if config.browser == "edge":
            return webdriver.Edge(options=options)
        return webdriver.Chrome(options=options)

    def stop(self) -> dict:
        """Quit the browser and forget everything tied to it.

        Safe when nothing is running. See `_wait_for_profile_release` for why
        this does more than call quit().
        """
        was_running = self.is_running
        if self._driver is not None:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            self._driver = None
        released = self._wait_for_profile_release(self.config) if was_running else True
        self._reset_state()
        return {"stopped": was_running, "profile_released": released}

    def restart(
        self,
        browser: str | None = None,
        profile: Path | str | None = None,
        headless: bool | None = None,
    ) -> dict:
        """Stop and start again.

        Overrides layer over the *effective* config, not the serve-time
        defaults: a session you started headless comes back headless, and one
        on a throwaway profile stays on it. `start` is the one that means
        "fresh". Works as `start` when nothing is running.
        """
        target = self.config.merge(
            browser=browser, profile=profile, headless=headless
        )
        self.stop()
        return self.start(
            browser=target.browser,
            profile=target.profile,
            headless=target.headless,
        )

    def quit(self) -> None:
        """Alias for `stop`, kept because conftest and server teardown call it."""
        self.stop()

    def _reset_state(self) -> None:
        """Drop everything that only means something against a live driver.

        Config and the recorder are untouched: the session log spans the
        server's life, and a browser crash plus its recovery is among the more
        interesting things that log can hold.
        """
        self._handles.clear()
        self._order.clear()
        self._counter = 0
        self._captured.clear()
        self._baselines.clear()
        self.refs = RefCache()
        self.last_target = None
        self._in_frame = False
```

Change `_make_options` to take the config rather than read `self`:

```python
    def _make_options(self, config: LaunchConfig):
        if config.browser == "edge":
            options = EdgeOptions()
        else:
            options = ChromeOptions()
        options.add_argument(f"--user-data-dir={config.profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        if config.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,900")
        return options
```

Add temporary stubs for the two methods Task 3 fills in, so this task's tests pass on their own:

```python
    def _verify_session(self) -> None:
        """Filled in by the profile-release task."""
        return None

    def _wait_for_profile_release(self, config: LaunchConfig) -> bool:
        """Filled in by the profile-release task."""
        return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py tests/test_launch.py -v`
Expected: PASS

- [ ] **Step 5: Run the existing suite for regressions**

Run: `.venv/Scripts/python -m pytest tests/ -x -q`
Expected: PASS. `tests/test_inspect.py::test_an_unsupported_browser_fails_cleanly` and `tests/test_settle.py` both construct `BrowserSession` directly and must still pass unchanged. If either fails, the constructor signature was not preserved — fix that rather than the test.

- [ ] **Step 6: Commit**

```bash
git add src/abt/browser.py tests/test_lifecycle.py
git commit -m "Make the browser lifecycle re-entrant

start/stop/restart replace a one-shot start. One BrowserSession still lives for
the server's lifetime, with the driver swapped underneath it, so the closures
in create_app and the session parameters threaded through messenger.py stay
valid across a restart.

start is not idempotent on purpose: a start naming a different profile is a
different identity, and no-oping it would hand back the wrong logins silently.
restart layers over the effective config, start over the serve defaults."
```

---

### Task 3: Profile release and post-launch verification

**Files:**
- Modify: `src/abt/browser.py` (replace the two stubs from Task 2)
- Test: `tests/test_lifecycle.py` (append)

**Interfaces:**
- Consumes: `LaunchConfig`, `stop`/`start` from Task 2.
- Produces: `_profile_locked(config) -> bool` (module-level function), `BrowserSession._wait_for_profile_release(config, timeout=None) -> bool`, `BrowserSession._verify_session() -> None` (raises `OpError("browser_dead", …)` and cleans up on failure). Module constants `PROFILE_LOCK_FILES`, `PROFILE_RELEASE_TIMEOUT`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lifecycle.py`:

```python
# --- profile release -------------------------------------------------------


def test_a_clean_profile_reads_as_unlocked(tmp_path):
    from abt.browser import _profile_locked
    from abt.launch import LaunchConfig

    assert _profile_locked(LaunchConfig(profile=tmp_path)) is False


def test_a_singleton_lock_reads_as_locked(tmp_path):
    from abt.browser import _profile_locked
    from abt.launch import LaunchConfig

    (tmp_path / "SingletonLock").write_text("host-1234")
    assert _profile_locked(LaunchConfig(profile=tmp_path)) is True


def test_waiting_returns_true_on_a_free_profile(session, tmp_path):
    from abt.launch import LaunchConfig

    assert (
        session._wait_for_profile_release(
            LaunchConfig(profile=tmp_path), timeout=0.5
        )
        is True
    )


def test_waiting_returns_true_as_soon_as_the_lock_goes_away(session, tmp_path):
    """It must poll, not check once -- the lock clears a moment after quit()."""
    import threading

    from abt.launch import LaunchConfig

    lock = tmp_path / "SingletonLock"
    lock.write_text("host-1234")
    threading.Timer(0.4, lambda: lock.unlink(missing_ok=True)).start()

    assert (
        session._wait_for_profile_release(
            LaunchConfig(profile=tmp_path), timeout=5.0
        )
        is True
    )
    assert lock.exists() is False


def test_waiting_gives_up_and_says_so(session, tmp_path):
    from abt.launch import LaunchConfig

    (tmp_path / "SingletonLock").write_text("host-1234")
    assert session._wait_for_profile_release(
        LaunchConfig(profile=tmp_path), timeout=0.3
    ) is False


def test_stop_reports_an_unreleased_profile(session, tmp_path):
    (tmp_path / "SingletonLock").write_text("host-1234")

    class FakeDriver:
        def quit(self):
            return None

    session._driver = FakeDriver()
    session.launch = session.defaults
    session._profile_release_timeout = 0.3

    result = session.stop()

    assert result["stopped"] is True
    assert result["profile_released"] is False


def test_verify_session_raises_and_cleans_up_on_a_dead_handoff(session):
    from selenium.common.exceptions import WebDriverException

    class Handoff:
        @property
        def window_handles(self):
            raise WebDriverException("no such window")

        def quit(self):
            return None

    session._driver = Handoff()
    session.launch = session.defaults

    with pytest.raises(OpError) as exc:
        session._verify_session()

    assert exc.value.type == "browser_dead"
    assert "profile" in exc.value.message.lower()
    assert session.is_running is False  # cleaned up, not left half-alive


def test_verify_session_passes_a_healthy_driver(session):
    class Healthy:
        window_handles = ["h0"]
        current_url = "about:blank"

    session._driver = Healthy()
    assert session._verify_session() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v -k "profile or verify"`
Expected: FAIL — `ImportError: cannot import name '_profile_locked'`

- [ ] **Step 3: Replace the two stubs in `browser.py`**

Add near the other module constants at the top of `browser.py`:

```python
# Chrome single-instances per --user-data-dir. A second launch against a locked
# profile does not open its own browser: it signals the incumbent and exits,
# leaving chromedriver holding a session that dies on first use. driver.quit()
# returns before the Chrome process has exited and released these, so a restart
# that launches immediately lands in that window essentially every time.
PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")
PROFILE_RELEASE_TIMEOUT = 8.0
PROFILE_RELEASE_INTERVAL = 0.2


def _profile_locked(config) -> bool:
    """Whether a browser still appears to hold this profile.

    A heuristic, and treated as one. On POSIX the lock is a symlink encoding
    host and pid which can dangle, so is_symlink matters as much as exists.
    Nothing refuses to act on the answer -- see `_verify_session` for the check
    that actually decides.
    """
    for name in PROFILE_LOCK_FILES:
        path = config.profile / name
        try:
            if path.exists() or path.is_symlink():
                return True
        except OSError:
            continue
    return False
```

Replace the stubbed methods:

```python
    def _wait_for_profile_release(self, config, timeout: float | None = None) -> bool:
        """Wait, briefly, for the old browser to let go of the profile.

        Prevention, not a guarantee. A hard-killed Chrome leaves its lock
        behind, so this can spend the whole timeout waiting for a file nobody
        owns -- which is why the answer is only ever *reported*, never enforced.
        """
        budget = self._profile_release_timeout if timeout is None else timeout
        deadline = time.monotonic() + budget
        while True:
            if not _profile_locked(config):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(PROFILE_RELEASE_INTERVAL)

    def _verify_session(self) -> None:
        """Prove the driver we just got is actually driving a browser.

        This is the half that decides. A launch that handed off to an incumbent
        returns a perfectly ordinary-looking driver whose first real command
        fails, so asking it a question is the only way to tell the two apart --
        and unlike checking for a lock file, it cannot false-positive on a
        stale lock left by a crash.
        """
        try:
            self._driver.window_handles
            self._driver.current_url
        except WebDriverException as exc:
            self._driver = None
            self._reset_state()
            raise OpError(
                "browser_dead",
                "the browser exited immediately after starting "
                f"({exc.msg or exc}). Another browser is most likely still "
                f"holding the profile at {self.config.profile} -- close it, "
                "then start again.",
            ) from exc
```

Add the per-session timeout in `__init__` beside the other knobs, so tests can shorten it:

```python
        self._profile_release_timeout = PROFILE_RELEASE_TIMEOUT
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/abt/browser.py tests/test_lifecycle.py
git commit -m "Handle the profile hand-off that kills a freshly restarted browser

Chrome single-instances per user-data-dir: a launch against a still-locked
profile signals the incumbent and exits, leaving chromedriver with a session
that dies on first use. driver.quit() returns before the lock clears, so a
restart hits this on the common path, not an edge case.

stop() now waits briefly for the lock to clear and reports whether it did.
start() probes the new session and fails loudly if it is already dead. It
deliberately does not refuse on the lock file's presence: a hard-killed Chrome
leaves a stale one, and gating on it would make the post-crash case -- the case
that most needs a new browser -- permanently unstartable."
```

---

### Task 4: Actionable `browser_dead` messages

**Files:**
- Modify: `src/abt/browser.py` (`driver` property, `health_check`)
- Test: `tests/test_lifecycle.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: module constant `NO_BROWSER_MESSAGE: str`. Behaviour only — no signature changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lifecycle.py`:

```python
# --- error messages --------------------------------------------------------


def test_the_no_browser_message_names_the_remedy(session):
    with pytest.raises(OpError) as exc:
        session.driver
    assert exc.value.type == "browser_dead"
    assert "browser_start" in exc.value.message


def test_health_check_on_a_stopped_session_names_the_remedy(session):
    with pytest.raises(OpError) as exc:
        session.health_check()
    assert "browser_start" in exc.value.message


def test_an_unreachable_browser_points_at_restart_not_start(session):
    from selenium.common.exceptions import WebDriverException

    class Corpse:
        @property
        def window_handles(self):
            raise WebDriverException("no such window: target window already closed")

    session._driver = Corpse()

    with pytest.raises(OpError) as exc:
        session.health_check()

    assert exc.value.type == "browser_dead"
    assert "browser_restart" in exc.value.message
    assert "target window already closed" in exc.value.message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v -k "message or remedy or restart_not_start"`
Expected: FAIL — `assert 'browser_start' in 'browser is not running'`

- [ ] **Step 3: Write the implementation**

Add the constant beside the other module constants in `browser.py`:

```python
# Recovery is explicit-only, so this string is the entire recovery interface.
# "browser is not running" was a dead end: true, and no help at all.
NO_BROWSER_MESSAGE = (
    'no browser is running; start one with {"op": "browser_start"} '
    "or POST /browser/start"
)
```

Replace the `driver` property and `health_check`:

```python
    @property
    def driver(self) -> webdriver.Chrome | webdriver.Edge:
        if self._driver is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        return self._driver

    def health_check(self) -> None:
        """Raise browser_dead rather than hanging on a driver that has gone away."""
        if self._driver is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        try:
            self._driver.window_handles
        except WebDriverException as exc:
            raise OpError(
                "browser_dead",
                f"browser is no longer reachable: {exc.msg or exc}; "
                'relaunch it with {"op": "browser_restart"} '
                "or POST /browser/restart",
            ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/abt/browser.py tests/test_lifecycle.py
git commit -m "Make browser_dead say how to recover

Under explicit-only recovery this message is the whole recovery interface, and
'browser is not running' was a dead end. Name browser_start when nothing is up
and browser_restart when one died, keeping the driver's own text so the cause
is still legible."
```

---

### Task 5: Lifecycle ops

**Files:**
- Modify: `src/abt/schema.py` (four models, `Command` union)
- Modify: `src/abt/ops/control.py` (four handlers, `browser_state` helper)
- Modify: `src/abt/ops/__init__.py` (registry, `NO_HEALTH_CHECK`)
- Modify: `tests/test_inspect.py:200` (the `NO_HEALTH_CHECK` assertion)
- Test: `tests/test_lifecycle.py` (append)

**Interfaces:**
- Consumes: `BrowserSession.start/stop/restart/is_running/config/defaults`.
- Produces: ops `browser_start`, `browser_stop`, `browser_restart`, `browser_status`; `abt.ops.control.browser_state(session) -> dict` returning `{"running": bool, "config": dict, "defaults": dict}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lifecycle.py`:

```python
# --- ops -------------------------------------------------------------------


def test_the_new_ops_are_registered():
    from abt.schema import OP_NAMES

    for name in ("browser_start", "browser_stop", "browser_restart", "browser_status"):
        assert name in OP_NAMES


def test_the_new_ops_skip_the_health_check():
    from abt.ops import NO_HEALTH_CHECK

    assert NO_HEALTH_CHECK == {
        "shutdown",
        "status",
        "browser_start",
        "browser_stop",
        "browser_restart",
        "browser_status",
    }


def test_browser_start_accepts_overrides():
    from abt.schema import parse_command

    cmd = parse_command(
        {"op": "browser_start", "browser": "edge", "headless": True}
    )
    assert cmd.browser == "edge"
    assert cmd.headless is True
    assert cmd.profile is None


def test_browser_start_takes_no_arguments_happily():
    from abt.schema import parse_command

    cmd = parse_command({"op": "browser_start"})
    assert (cmd.browser, cmd.profile, cmd.headless) == (None, None, None)


def test_browser_stop_rejects_stray_fields():
    from abt.schema import parse_command

    with pytest.raises(OpError) as exc:
        parse_command({"op": "browser_stop", "headless": True})
    assert exc.value.type == "invalid_op"


def test_browser_state_reports_both_configs(session):
    from abt.ops.control import browser_state

    session.launch = session.defaults.merge(headless=False)
    state = browser_state(session)

    assert state["running"] is False
    assert state["config"]["headless"] is False
    assert state["defaults"]["headless"] is True
    assert isinstance(state["config"]["profile"], str)


def test_browser_status_op_dispatches_without_a_browser(session):
    from abt.ops import dispatch
    from abt.schema import parse_command

    state = dispatch(session, parse_command({"op": "browser_status"}))
    assert state["running"] is False


def test_the_lifecycle_ops_are_not_treated_as_dom_touching():
    from abt.ops import DIFFABLE_OPS, DOM_TOUCHING_OPS, NAVIGATION_OPS

    for name in ("browser_start", "browser_stop", "browser_restart", "browser_status"):
        assert name not in DIFFABLE_OPS
        assert name not in NAVIGATION_OPS
        assert name not in DOM_TOUCHING_OPS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v -k "ops or browser_st or browser_state"`
Expected: FAIL — `unknown op 'browser_start'`

- [ ] **Step 3: Add the models to `schema.py`**

Insert immediately before the `Command = Annotated[...]` union:

```python
class BrowserStart(Base):
    """Launch a browser. Omitted fields fall back to the server's defaults."""

    op: Literal["browser_start"]
    browser: str | None = None
    profile: str | None = None
    headless: bool | None = None


class BrowserStop(Base):
    op: Literal["browser_stop"]


class BrowserRestart(Base):
    """Stop and start again. Omitted fields keep what is running now."""

    op: Literal["browser_restart"]
    browser: str | None = None
    profile: str | None = None
    headless: bool | None = None


class BrowserStatus(Base):
    op: Literal["browser_status"]
```

Extend the union — add the new line inside `Union[...]`:

```python
        RunJs, Diff, Status, Shutdown, Alert,
        ReadConsole, ReadNetwork,
        BrowserStart, BrowserStop, BrowserRestart, BrowserStatus,
```

- [ ] **Step 4: Add the handlers to `ops/control.py`**

Append to the end of the file:

```python
# --- browser lifecycle ------------------------------------------------------


def browser_state(session: BrowserSession) -> dict:
    """Lifecycle state, answerable with no browser present.

    Two configs, because one key cannot answer both questions. `config` is what
    is running now (or ran most recently), which is what a bare browser_restart
    will use. `defaults` is what `abt serve` was given, which is what a bare
    browser_start will use.
    """
    return {
        "running": session.is_running,
        "config": session.config.to_dict(),
        "defaults": session.defaults.to_dict(),
    }


def browser_start(session: BrowserSession, cmd) -> dict:
    return session.start(
        browser=cmd.browser, profile=cmd.profile, headless=cmd.headless
    )


def browser_stop(session: BrowserSession, cmd) -> dict:
    return session.stop()


def browser_restart(session: BrowserSession, cmd) -> dict:
    return session.restart(
        browser=cmd.browser, profile=cmd.profile, headless=cmd.headless
    )


def browser_status(session: BrowserSession, cmd) -> dict:
    return browser_state(session)
```

- [ ] **Step 5: Wire them into `ops/__init__.py`**

Add to `REGISTRY`, after the `"shutdown"` entry:

```python
    "browser_start": control.browser_start,
    "browser_stop": control.browser_stop,
    "browser_restart": control.browser_restart,
    "browser_status": control.browser_status,
```

Replace `NO_HEALTH_CHECK`:

```python
# The health check exists to fail fast instead of hanging on a dead driver. But
# these are exactly what you reach for *when* it has died -- gating them behind
# it means a server whose browser crashed can never recover or be shut down.
NO_HEALTH_CHECK = frozenset(
    {
        "shutdown",
        "status",
        "browser_start",
        "browser_stop",
        "browser_restart",
        "browser_status",
    }
)
```

- [ ] **Step 6: Update the existing assertion in `tests/test_inspect.py`**

Replace the body of `test_status_and_shutdown_skip_the_health_check` (line ~200) so it no longer pins the old two-element set:

```python
def test_status_and_shutdown_skip_the_health_check():
    from abt.ops import NO_HEALTH_CHECK

    assert {"shutdown", "status"} <= NO_HEALTH_CHECK
```

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py tests/test_schema.py tests/test_inspect.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/abt/schema.py src/abt/ops/control.py src/abt/ops/__init__.py tests/test_lifecycle.py tests/test_inspect.py
git commit -m "Add browser_start / stop / restart / status ops

All four skip the health check, for the reason the existing comment beside
shutdown and status already gives: gating a command whose job is to fix the
browser behind a check that needs a working browser makes recovery impossible.

None of them join DIFFABLE_OPS or DOM_TOUCHING_OPS -- a fresh browser lands on
a blank tab with every baseline just dropped, so there is nothing to diff."
```

---

### Task 6: HTTP surface — `/browser/*`, `/health`, `running` on `/status`

**Files:**
- Modify: `src/abt/server.py` (routes)
- Modify: `src/abt/ops/control.py` (`session_status`)
- Modify: `tests/conftest.py` (add `unstarted_session` and `unstarted_client` fixtures)
- Test: `tests/test_lifecycle.py` (append)

**Interfaces:**
- Consumes: `browser_state` from Task 5, `session.is_running`.
- Produces: routes `GET /health`, `GET /browser`, `POST /browser/start`, `POST /browser/stop`, `POST /browser/restart`. `session_status` gains an always-present `running` key.

- [ ] **Step 1: Add the fixtures to `tests/conftest.py`**

Append:

```python
@pytest.fixture
def unstarted_session(tmp_path):
    """A session that never launched a browser.

    The existing `session` fixture starts Chrome eagerly and is session-scoped;
    this one is the counterpart for everything that should work without one.
    """
    return BrowserSession(profile=tmp_path, headless=True, action_timeout=3.0)


@pytest.fixture
def unstarted_client(unstarted_session):
    from fastapi.testclient import TestClient

    with TestClient(create_app(unstarted_session)) as test_client:
        yield test_client
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_lifecycle.py`:

```python
# --- HTTP ------------------------------------------------------------------


def test_health_answers_without_a_browser(unstarted_client):
    body = unstarted_client.get("/health").json()
    assert body["ok"] is True
    assert body["running"] is False


def test_status_answers_without_a_browser(unstarted_client):
    body = unstarted_client.get("/status").json()
    assert body["ok"] is True
    assert body["result"]["running"] is False
    assert "url" not in body["result"]


def test_browser_route_reports_the_defaults(unstarted_client):
    body = unstarted_client.get("/browser").json()
    assert body["ok"] is True
    assert body["result"]["running"] is False
    assert body["result"]["defaults"]["headless"] is True


def test_a_page_command_without_a_browser_says_how_to_recover(unstarted_client):
    body = unstarted_client.post(
        "/command", json={"op": "goto", "url": "https://example.com"}
    ).json()
    assert body["ok"] is False
    assert body["error"]["type"] == "browser_dead"
    assert "browser_start" in body["error"]["message"]


def test_stopping_a_stopped_browser_over_http_is_harmless(unstarted_client):
    body = unstarted_client.post("/browser/stop").json()
    assert body["ok"] is True
    assert body["result"]["stopped"] is False


def test_start_route_reports_a_bad_browser_without_launching(unstarted_client):
    body = unstarted_client.post("/browser/start", json={"browser": "firefox"}).json()
    assert body["ok"] is False
    assert body["error"]["type"] == "bad_browser"


def test_ops_route_lists_the_lifecycle_ops(unstarted_client):
    body = unstarted_client.get("/ops").json()
    assert "browser_start" in body["result"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v -k "health or status_answers or browser_route or recover or stopping_a_stopped_browser or start_route or ops_route"`
Expected: FAIL — 404 on `/health`

- [ ] **Step 4: Update `session_status` in `ops/control.py`**

Move the `browser_state` helper added in Task 5 **above** `session_status` in
the file, then replace `session_status` with:

```python
def session_status(session: BrowserSession) -> dict:
    """Where the session is, or that there is no session.

    `running` is always present. Everything else is only meaningful with a
    browser up, and a caller that reads `url` without checking `running` should
    find it missing rather than find a lie.
    """
    if not session.is_running:
        return browser_state(session)
    tabs = session.tabs()
    active = session.active_tab
    return {
        "running": True,
        "url": session.driver.current_url,
        "title": session.driver.title,
        "active_tab": active,
        "tabs": tabs,
        "refs_valid": session.refs.count(active),
        "headless": session.headless,
        "profile": str(session.profile),
    }
```

`browser_state` is defined later in the file than `session_status`; that is fine, since the lookup happens at call time. Move `browser_state` above `session_status` anyway for readability.

- [ ] **Step 5: Add the routes to `server.py`**

Add the import beside the existing one:

```python
from .ops.control import browser_state, session_status
```

Add the routes just before the `# --- session logs` divider:

```python
    # --- browser lifecycle ----------------------------------------------------

    @app.get("/health")
    async def health():
        """Is the *server* up. Never touches the driver or the command lock.

        This is what launchers and readiness polls want. /status cannot serve
        that purpose once the browser is optional: a healthy server with no
        browser would look like a failure to whatever started it.
        """
        return {"ok": True, "running": session.is_running}

    @app.get("/browser")
    async def browser():
        return ok(browser_state(session))

    async def _lifecycle(request: Request, op: str) -> dict:
        """Run a lifecycle op through the normal path: one lock, one log entry.

        Serialized against in-flight commands on purpose -- a start that raced
        a running command would launch Chrome underneath it.
        """
        payload = {"op": op}
        if op in ("browser_start", "browser_restart"):
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                for field in ("browser", "profile", "headless"):
                    if body.get(field) is not None:
                        payload[field] = body[field]
        results = await run_in_threadpool(execute, [payload], False)
        return results[0]

    @app.post("/browser/start")
    async def browser_start_route(request: Request):
        return await _lifecycle(request, "browser_start")

    @app.post("/browser/stop")
    async def browser_stop_route(request: Request):
        return await _lifecycle(request, "browser_stop")

    @app.post("/browser/restart")
    async def browser_restart_route(request: Request):
        return await _lifecycle(request, "browser_restart")
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py tests/test_server.py -v`
Expected: PASS. `tests/test_inspect.py::test_status_answers_even_when_the_browser_is_gone` must also still pass — it uses a `Corpse` driver, so `is_running` is True and the route still returns `browser_dead`.

- [ ] **Step 7: Commit**

```bash
git add src/abt/server.py src/abt/ops/control.py tests/conftest.py tests/test_lifecycle.py
git commit -m "Serve /health, /browser and a running flag on /status

/status cannot double as a readiness probe once the browser is optional: a
healthy server with no browser would read as a failure to whatever started it.
/health answers that question alone and touches neither the driver nor the
command lock.

The lifecycle routes go through the same execute path as every command, so a
start cannot race an in-flight command and launch Chrome underneath it."
```

---

### Task 7: `abt serve` stops launching a browser

**Files:**
- Modify: `src/abt/cli.py` (`serve`)
- Test: `tests/test_lifecycle.py` (append)

**Interfaces:**
- Consumes: `BrowserSession` lifecycle.
- Produces: `abt serve --start-browser/--no-start-browser`, default off.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lifecycle.py`:

```python
# --- CLI -------------------------------------------------------------------


def test_serve_has_an_opt_in_browser_launch_flag():
    """The old eager behaviour must stay reachable, and stay off by default."""
    import inspect

    from abt.cli import serve

    parameter = inspect.signature(serve).parameters["start_browser"]
    assert parameter.default.default is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v -k serve_has`
Expected: FAIL — `KeyError: 'start_browser'`

- [ ] **Step 3: Edit `serve` in `cli.py`**

Add the option to the signature, after `headless`:

```python
    start_browser: bool = typer.Option(
        False,
        "--start-browser/--no-start-browser",
        help="Launch the browser at startup instead of waiting for a "
        "browser_start command. Off by default: the server is useful "
        "immediately, and Chrome on a persistent profile can take two minutes.",
    ),
```

Replace the block from `typer.echo(f"starting {browser} …")` through `session.start()` with:

```python
    if start_browser:
        typer.echo(f"starting {browser} (profile: {session.profile})")
        session.start()
    else:
        typer.echo(f"no browser running (default: {browser}, profile: {session.profile})")
        typer.echo('start one with {"op": "browser_start"} or POST /browser/start')
```

Replace the final `finally: session.quit()` — it already calls `quit`, which is now `stop`, so it needs no change. Leave it.

- [ ] **Step 4: Run the test**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle.py -v -k serve_has`
Expected: PASS

- [ ] **Step 5: Verify by hand that the server now boots without Chrome**

```bash
./start-server.sh --no-wait
sleep 3
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/browser
```
Expected: `/health` answers within seconds with `"running": false`, and no Chrome window appears.

Then confirm the lifecycle end to end:
```bash
curl -s -X POST http://127.0.0.1:8765/browser/start -H 'content-type: application/json' -d '{"headless": true}'
curl -s http://127.0.0.1:8765/status
curl -s -X POST http://127.0.0.1:8765/browser/stop
curl -s -X POST http://127.0.0.1:8765/command -H 'content-type: application/json' -d '{"op": "shutdown"}'
```

- [ ] **Step 6: Commit**

```bash
git add src/abt/cli.py tests/test_lifecycle.py
git commit -m "Stop launching a browser from abt serve

The server now listens in about a second instead of waiting up to two minutes
for Chrome on the persistent profile. --start-browser keeps the old behaviour
one flag away."
```

---

### Task 8: The `browser_session` MCP tool

**Files:**
- Modify: `src/abt/mcp.py` (`TOOLS`, `to_op`)
- Test: `tests/test_mcp.py` (append)

**Interfaces:**
- Consumes: the ops from Task 5.
- Produces: MCP tool `browser_session` with `action` in `start|stop|restart|status` plus optional `browser`, `profile`, `headless`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
def test_browser_session_tool_is_offered():
    from abt.mcp import TOOLS

    names = [tool["name"] for tool in TOOLS]
    assert "browser_session" in names


def test_browser_session_maps_each_action_to_its_op():
    from abt.mcp import to_op

    assert to_op("browser_session", {"action": "status"})["op"] == "browser_status"
    assert to_op("browser_session", {"action": "stop"})["op"] == "browser_stop"
    assert to_op("browser_session", {"action": "restart"})["op"] == "browser_restart"


def test_browser_session_passes_launch_overrides_through():
    from abt.mcp import to_op

    payload = to_op(
        "browser_session", {"action": "start", "browser": "edge", "headless": True}
    )
    assert payload == {"op": "browser_start", "browser": "edge", "headless": True}


def test_browser_session_omits_absent_overrides():
    from abt.mcp import to_op

    assert to_op("browser_session", {"action": "start"}) == {"op": "browser_start"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_mcp.py -v -k browser_session`
Expected: FAIL — `browser_session` not in names

- [ ] **Step 3: Add the tool definition**

Append to the `TOOLS` list in `mcp.py`:

```python
    {
        "name": "browser_session",
        "description": (
            "Start, stop or restart the browser, or ask whether one is running. "
            "Every page command fails with browser_dead until a browser is "
            "started; nothing starts one for you. Use restart after a crash or "
            "after a tab closed the session. start uses the server's defaults, "
            "restart keeps whatever the last browser used."
        ),
        "inputSchema": _schema(
            {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "status"],
                },
                "browser": {"type": "string", "enum": ["chrome", "edge"]},
                "profile": {"type": "string"},
                "headless": {"type": "boolean"},
            },
            ["action"],
        ),
    },
```

- [ ] **Step 4: Add the mapping in `to_op`**

Add a branch beside the other tool mappings:

```python
    if tool == "browser_session":
        payload = {"op": f"browser_{args['action']}"}
        for field in ("browser", "profile", "headless"):
            if args.get(field) is not None:
                payload[field] = args[field]
        return payload
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_mcp.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/abt/mcp.py tests/test_mcp.py
git commit -m "Add a browser_session MCP tool

Recovering from a dead browser unaided is the point of this work, and the only
alternative was browser_raw -- the unvalidated pass-through whose failure mode
this module's own docstring documents. One tool, four actions."
```

---

### Task 9: `abt up` — spawn the server outside the caller's job object

**Files:**
- Create: `src/abt/proc.py`
- Modify: `src/abt/cli.py` (new `up` command)
- Test: `tests/test_proc.py`

**Interfaces:**
- Consumes: `GET /health` from Task 6.
- Produces: `abt.proc.spawn_detached(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> str` returning the name of the mechanism that worked (`"wmi"`, `"schtasks"`, `"detached"`, or `"setsid"`); `abt.proc.windows_command_line(argv, stdout, stderr) -> str`; CLI command `abt up`.

**Background the implementer needs:** on Windows a process started by a shell belongs to that shell's *job object*. A harness that waits on the job — opencode, observed — blocks until every member exits, so `nohup`, `start /b`, and stdio redirection all fail to help. `CREATE_BREAKAWAY_FROM_JOB` is the documented escape but silently fails when the job forbids breakaway, which is exactly the case that needs escaping. Asking a *third party* to spawn the process sidesteps it: the new process's parent is then a Windows service (`WmiPrvSE.exe` or the Task Scheduler service), and it belongs to no job of ours.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_proc.py`:

```python
"""Detached spawning. The platform-specific half is exercised by hand."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from abt import proc


def test_windows_command_line_quotes_paths_with_spaces(tmp_path):
    out = tmp_path / "a b" / "server.log"
    err = tmp_path / "a b" / "server.err"
    line = proc.windows_command_line(
        [str(tmp_path / "a b" / "abt.exe"), "serve", "--port", "8765"], out, err
    )
    assert line.startswith("cmd.exe /c ")
    assert '"' in line
    assert str(out) in line
    assert "2>" in line


def test_powershell_quoting_doubles_single_quotes():
    assert proc.powershell_single_quote("it's") == "'it''s'"
    assert proc.powershell_single_quote("plain") == "'plain'"


def test_spawn_detached_reports_the_mechanism(tmp_path):
    """A real spawn of something harmless that exits on its own."""
    out = tmp_path / "out.log"
    err = tmp_path / "err.log"
    mechanism = proc.spawn_detached(
        [sys.executable, "-c", "print('hello')"], tmp_path, out, err
    )
    assert mechanism in {"wmi", "schtasks", "detached", "setsid"}


def test_spawn_detached_rejects_an_empty_command(tmp_path):
    with pytest.raises(ValueError):
        proc.spawn_detached([], tmp_path, tmp_path / "o", tmp_path / "e")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_proc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abt.proc'`

- [ ] **Step 3: Write `src/abt/proc.py`**

```python
"""Starting a process that outlives the one that asked for it.

On Windows a process started by a shell joins that shell's *job object*. A
harness that waits on the job blocks until every member exits, so `nohup`,
`start /b`, and redirecting stdio all fail to help -- which is why
`start-server.bat` never fixed this. CREATE_BREAKAWAY_FROM_JOB is the
documented escape and silently fails when the job forbids breakaway, which is
precisely the case that needs escaping.

So ask someone else to do the spawning. A process created through WMI is a
child of WmiPrvSE.exe, and one created through Task Scheduler is a child of the
scheduler service; either way it belongs to no job of ours and nothing in the
calling session can wait on it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def powershell_single_quote(value: str) -> str:
    """Wrap a value as a PowerShell literal string. Doubling escapes a quote."""
    return "'" + str(value).replace("'", "''") + "'"


def windows_command_line(argv: list[str], stdout: Path, stderr: Path) -> str:
    """A cmd.exe line that runs argv with its output redirected to files.

    WMI cannot redirect, so the redirection has to be part of the command. The
    outer `cmd.exe /c "..."` wrapper keeps cmd's own quoting rules happy when
    any of the paths contain spaces, which on Windows they usually do.
    """
    inner = subprocess.list2cmdline(argv)
    return f'cmd.exe /c "{inner} > "{stdout}" 2> "{stderr}""'


def _spawn_wmi(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> bool:
    command = windows_command_line(argv, stdout, stderr)
    script = (
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine=" + powershell_single_quote(command) +
        "; CurrentDirectory=" + powershell_single_quote(str(cwd)) + "}; "
        "exit $r.ReturnValue"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _spawn_schtasks(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> bool:
    """Fallback: a one-shot scheduled task, run immediately and deleted.

    Slower and leaves a task behind for a moment, but works where WMI is
    blocked by security software.
    """
    name = f"abt-up-{os.getpid()}"
    command = windows_command_line(argv, stdout, stderr)
    try:
        created = subprocess.run(
            ["schtasks", "/create", "/tn", name, "/tr", command,
             "/sc", "once", "/st", "00:00", "/f"],
            capture_output=True,
            timeout=60,
        )
        if created.returncode != 0:
            return False
        run = subprocess.run(
            ["schtasks", "/run", "/tn", name], capture_output=True, timeout=60
        )
        return run.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            subprocess.run(
                ["schtasks", "/delete", "/tn", name, "/f"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _spawn_windows_detached(
    argv: list[str], cwd: Path, stdout: Path, stderr: Path
) -> bool:
    """Last resort. Escapes the console but not necessarily the job object."""
    flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )
    try:
        with open(stdout, "ab") as out, open(stderr, "ab") as err:
            subprocess.Popen(
                argv, cwd=str(cwd), stdout=out, stderr=err,
                stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True,
            )
        return True
    except OSError:
        return False


def _spawn_posix(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> bool:
    try:
        with open(stdout, "ab") as out, open(stderr, "ab") as err:
            subprocess.Popen(
                argv, cwd=str(cwd), stdout=out, stderr=err,
                stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            )
        return True
    except OSError:
        return False


def spawn_detached(
    argv: list[str], cwd: Path, stdout: Path, stderr: Path
) -> str:
    """Start argv so it outlives this process. Returns the mechanism that worked."""
    if not argv:
        raise ValueError("nothing to spawn: argv is empty")
    cwd = Path(cwd)
    stdout = Path(stdout)
    stderr = Path(stderr)
    stdout.parent.mkdir(parents=True, exist_ok=True)
    stderr.parent.mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS:
        attempts = (
            ("wmi", _spawn_wmi),
            ("schtasks", _spawn_schtasks),
            ("detached", _spawn_windows_detached),
        )
    else:
        attempts = (("setsid", _spawn_posix),)

    for name, attempt in attempts:
        if attempt(argv, cwd, stdout, stderr):
            return name
    raise OSError("could not start the server detached; see the log files")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_proc.py -v`
Expected: PASS

- [ ] **Step 5: Add the `up` command to `cli.py`**

```python
@app.command()
def up(
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p", help="Port to listen on."),
    browser: str = typer.Option(
        None, "--browser", help="Default browser for later browser_start calls."
    ),
    profile: Optional[Path] = typer.Option(None, "--profile"),
    headless: bool = typer.Option(False, "--headless"),
    wait: float = typer.Option(
        20.0, "--wait", help="Seconds to wait for the server to answer /health."
    ),
) -> None:
    """Start the server if it is not already up, and return immediately.

    Never blocks: the server is spawned so that it belongs to no job object of
    this process, which is what `abt serve` in a background job could not
    manage. Safe to run at any time -- it no-ops when a server already answers.
    """
    import time

    from .proc import spawn_detached

    base = f"http://{HOST}:{port}"
    if _healthy(base):
        typer.echo(f"[abt] already up on {HOST}:{port}")
        raise typer.Exit(0)

    repo = Path(__file__).resolve().parent.parent.parent
    suffix = "" if port == DEFAULT_PORT else f"-{port}"
    argv = [sys.executable, "-m", "abt.cli", "serve", "--port", str(port)]
    if browser:
        argv += ["--browser", browser]
    if profile:
        argv += ["--profile", str(profile)]
    if headless:
        argv += ["--headless"]

    mechanism = spawn_detached(
        argv, repo, repo / f"server{suffix}.log", repo / f"server{suffix}.err"
    )
    typer.echo(f"[abt] launched via {mechanism}; waiting for {base}/health")

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _healthy(base):
            typer.echo(f"[abt] up on {HOST}:{port}")
            raise typer.Exit(0)
        time.sleep(0.5)

    typer.secho(
        f"[abt] no answer from {base}/health within {wait}s; "
        f"check {repo / f'server{suffix}.err'}",
        fg="red",
        err=True,
    )
    raise typer.Exit(1)


def _healthy(base: str) -> bool:
    try:
        return httpx.get(f"{base}/health", timeout=3).json().get("ok") is True
    except Exception:
        return False
```

`abt.cli` needs a `__main__` entry for `python -m abt.cli` — it already has `if __name__ == "__main__": app()` at the bottom, so nothing to add.

- [ ] **Step 6: Verify by hand from a tool call — this is the whole point**

```bash
curl -s -X POST http://127.0.0.1:8765/command -H 'content-type: application/json' -d '{"op":"shutdown"}' || true
.venv/Scripts/abt up
```
Expected: the command **returns within a few seconds** rather than hanging, prints the mechanism used, and `/health` answers afterwards. If it hangs, the spawn fell through to `detached` and the job object still holds it — check which mechanism was reported.

- [ ] **Step 7: Commit**

```bash
git add src/abt/proc.py src/abt/cli.py tests/test_proc.py
git commit -m "Add abt up: start the server without wedging the caller

A process started by a shell joins that shell's job object, and a harness that
waits on the job blocks until every member exits -- which is why nohup, start
/b and redirecting stdio never fixed this, and why CREATE_BREAKAWAY_FROM_JOB
cannot be relied on either: it fails silently when the job forbids breakaway.

Ask a third party to spawn instead. Through WMI the new process is a child of
WmiPrvSE, through Task Scheduler a child of the scheduler service; either way
it belongs to no job of ours. POSIX uses start_new_session."
```

---

### Task 10: Live tests, scripts, and documentation

**Files:**
- Create: `tests/test_lifecycle_live.py`
- Modify: `start-server.sh`, `start-server.bat`
- Modify: `README.md`, `AGENTS.md`, `guidelines/toolkit-workflow.md`, `docs/known-issues.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no new code interfaces.

- [ ] **Step 1: Write the live tests**

Create `tests/test_lifecycle_live.py`:

```python
"""The two lifecycle tests that genuinely need a browser."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from abt.browser import BrowserSession


@pytest.fixture
def own_session():
    """A session this test owns outright, so stopping it breaks nothing else."""
    profile = Path(tempfile.mkdtemp(prefix="abt-lifecycle-"))
    built = BrowserSession(profile=profile, headless=True, action_timeout=3.0)
    yield built
    built.stop()


def test_a_stopped_browser_comes_back_clean(own_session, base_url):
    own_session.start()
    own_session.goto(f"{base_url}/cards.html")
    first_tab = own_session.active_tab

    stopped = own_session.stop()
    assert stopped["stopped"] is True
    assert own_session.is_running is False

    own_session.start()
    own_session.goto(f"{base_url}/cards.html")

    # A fresh browser deserves tab_0, and nothing from before may survive.
    assert own_session.active_tab == "tab_0" == first_tab
    assert own_session.refs.count(own_session.active_tab) == 0
    assert own_session.baseline() is not None


def test_back_to_back_restarts_survive_the_profile_handoff(own_session, base_url):
    """The regression test for the hand-off.

    Without the wait in stop(), the second browser attaches to the dying first
    one and this goto fails -- and it fails looking like a flaky network rather
    than a lifecycle bug, which is why it is worth spending a live test on.
    """
    own_session.start()
    own_session.restart()
    own_session.restart()

    own_session.goto(f"{base_url}/cards.html")
    assert own_session.is_running is True
    assert "cards" in own_session.driver.current_url
```

- [ ] **Step 2: Run the live tests**

Run: `.venv/Scripts/python -m pytest tests/test_lifecycle_live.py -v`
Expected: PASS. These are slow (three Chrome launches); that is expected.

- [ ] **Step 3: Point the start scripts at `/health` and `abt up`**

In `start-server.sh`, change `STATUS_URL`:

```bash
STATUS_URL="http://127.0.0.1:$PORT/health"
```

and drop `WAIT_SECONDS` from 180 to 30 — no browser launch is in the path any more:

```bash
# No browser is launched at startup any more, so the server answers in about a
# second. The old 180s budget existed only to cover Chrome on a cold profile.
WAIT_SECONDS=30
```

Make the same two edits in `start-server.bat` (its `STATUS_URL` equivalent and its wait budget).

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Update the documentation**

`guidelines/toolkit-workflow.md`, section "A tab that closes itself takes the session with it" — replace the recovery paragraph. It currently says the only way back is `shutdown` plus `start-server.sh`/`start-server.bat`, and the paragraph after it warns the reader to check no Chrome still holds the profile. Both change:

```markdown
Once it has happened, send `{"op": "browser_restart"}` (which works with a dead
browser, like `status` and `shutdown`). The server stays up, the session log
continues, and you get a fresh browser on the same profile — so you are still
logged in, but every tab and every ref is gone and you must navigate back.

You no longer have to check that no Chrome is still holding the profile:
`browser_restart` waits for the old one to let go, and fails loudly naming the
profile if a browser it cannot see is still there.
```

`README.md` — add the four ops to the ops table, add `/health`, `/browser/*` and `GET /browser` to the HTTP section, and note that `abt serve` no longer opens a browser.

`AGENTS.md` — same three points, plus `abt up` as the way to start a server.

`docs/known-issues.md` — append to entry 4 that the remedy for a dead browser is now `browser_restart` rather than killing the process.

`CLAUDE.md` and the global instructions describe checking `GET /status` first; add that `/health` answers whether the *server* is up and `/browser` whether a *browser* is, and that a server with no browser is now the normal state after boot.

- [ ] **Step 6: Commit**

```bash
git add tests/test_lifecycle_live.py start-server.sh start-server.bat README.md AGENTS.md guidelines/toolkit-workflow.md docs/known-issues.md
git commit -m "Cover the lifecycle live, and correct the docs that say it is fatal

toolkit-workflow.md told agents that a self-closing tab ends the session and
the only way back is bouncing the server. That is now false, and it was the
line most likely to leave an agent stuck after this change.

The live tests are two: a clean stop/start cycle, and back-to-back restarts,
which is the regression test for the profile hand-off -- it fails looking like
a flaky network rather than a lifecycle bug, so it earns its place."
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: Recovery policy → Tasks 4, 5; `LaunchConfig` → 1; lifecycle methods → 2; `_reset_state` → 2; Releasing the profile → 3; Error semantics → 4; Ops → 5; HTTP API incl. `/health` and `running` → 6; CLI `serve` → 7; `abt up` → 9; MCP → 8; Testing → spread across all, with the live pair in 10; Documentation → 10.

**Known gap, deliberately deferred:** the spec's `docs/TODO.md` packaging work is out of scope by construction, and the opt-in logon task belongs to it rather than to `abt up`.

**Type consistency.** `LaunchConfig.merge(browser, profile, headless)` and `to_dict()` are used with those exact names in Tasks 2, 5, 6. `session.start/stop/restart` keep the same three keyword names throughout. `browser_state(session)` is defined in Task 5 and consumed in Tasks 5 and 6. `_verify_session()` and `_wait_for_profile_release(config, timeout=None)` are stubbed in Task 2 and implemented in Task 3 with matching signatures. `spawn_detached(argv, cwd, stdout, stderr) -> str` is defined and consumed in Task 9.

**Ordering risk to watch:** Task 2 introduces stubs that Task 3 replaces. If Tasks 2 and 3 are run out of order or in parallel, `stop()` will not wait and the live test in Task 10 will fail intermittently. Run them in order.
