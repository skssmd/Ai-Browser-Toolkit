# Packaging and Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the toolkit as an installable program on PyPI, winget, a downloadable Windows installer, Scoop, a Homebrew tap, the AUR and a Gemfury apt/rpm/apk repository, all from a single `v*` tag.

**Architecture:** One tag produces two kinds of build output — a wheel, and five self-contained bundles (one per OS/arch) each consisting of a python-build-standalone CPython with the toolkit installed into its `site-packages` behind a launcher shim. The GitHub release is published first; six independent publisher jobs then repackage those already-smoke-tested bytes for their own ecosystems. No channel builds anything.

**Tech Stack:** Python 3.11+ (bundles pin 3.13), hatchling, `uv`, python-build-standalone, GitHub Actions, Inno Setup, `nfpm`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-packaging-and-distribution-design.md`

## Global Constraints

- **Distribution name is `aibrowsertoolkit`. Command name is `abt`.** The name `abt` is taken on PyPI by an unrelated project; this is harmless because `abt` is a console script, not a distribution.
- **Repository is `skssmd/Ai-Browser-Toolkit` and is public.** Free ARM runners and free build provenance are therefore available.
- **Bundled interpreter is CPython 3.13** from python-build-standalone. `pyproject.toml` keeps `requires-python = ">=3.11"` — the floor for pip users is unchanged.
- **No virtualenv inside a bundle, ever.** `pyvenv.cfg` records an absolute `home =`; a venv built on a runner is broken on a user's machine. Install into the standalone interpreter's own `site-packages`.
- **Every install is per-user. Never elevated.** No Program Files, no `sudo`-requiring paths beyond the distro packages' own `/opt`.
- **Autostart is opt-in and never default-on.** The installer checkbox ships unchecked. This rule is load-bearing: see `src/abt/autostart.py`'s module docstring.
- **Chrome is `optdepends` / `Recommends`, never a hard dependency.**
- **Signing is free-tier only:** PyPI Trusted Publishing (OIDC), `actions/attest-build-provenance`, `checksums.txt`. No GPG. No Authenticode.
- **Secret names:** `TAP_TOKEN`, `WINGET_TOKEN`, `AUR_SSH_KEY`, `FURY_TOKEN`. PyPI uses no secret.
- **Shared repositories** (`the-graft-project/homebrew-tap`, `the-graft-project/winget-pkgs`) are also written by Graft's release workflow. Every push into one does `pull --rebase` and retries twice.
- **Five bundle targets:** `linux-x86_64`, `linux-aarch64`, `macos-arm64`, `macos-x86_64`, `windows-x86_64`.

---

## File Structure

**Wave 1 — prerequisite**
- `src/abt/paths.py` — where an installed copy keeps its profile and logs. Pure functions, no I/O beyond reading `pyproject.toml` for the checkout test.
- `tests/test_paths.py` — all three platforms exercised from whichever one the tests run on.
- Modified: `src/abt/launch.py` (the `LaunchConfig.profile` default), `src/abt/cli.py` (two `--profile` defaults, two `--log-dir` defaults).
- Modified: `docs/TODO.md` — replace the parked entry with a pointer to the spec.
- Modified: `src/abt/pwdriver.py` — translate a missing browser into this toolkit's own error (Task 2b).

**Wave 2 — build and PyPI**
- `src/abt/__main__.py` — makes `python -m abt` work, which the launcher shim depends on.
- `packaging/__init__.py` — empty; makes `packaging.bundle` importable by the tests.
- `packaging/bundle.py` — builds one bundle. Runs on a laptop, not only in CI.
- `packaging/smoke.sh` — proves a built bundle runs. The reason the matrix is native.
- `tests/test_bundle.py` — target table, naming, and shim content. Not the download.
- `.github/workflows/ci.yml` — pytest on push and PR.
- `.github/workflows/release.yml` — the whole pipeline. Grows in every later wave.
- `docs/packaging.md` — how to cut a release. Grows in every later wave.

**Wave 3 — Windows**
- `packaging/windows/abt.iss` — Inno Setup script; per-user, PATH entry, autostart checkbox.
- `packaging/scoop/manifest.json.template`
- Modified: `.github/workflows/release.yml` — `installer`, `winget`, `scoop` jobs.

**Wave 4 — Unix packages**
- `packaging/homebrew/formula.rb.template`
- `packaging/aur/PKGBUILD.template`, `packaging/aur/aibrowsertoolkit-bin.install`
- `packaging/nfpm.yaml`
- Modified: `.github/workflows/release.yml` — `brew`, `aur`, `fury` jobs.

---

# Wave 1 — Prerequisite: per-user data directories

Nothing else can ship correctly until an installed `abt` finds its profile. Today `--profile` defaults to `./profiles/default` and `--log-dir` to `./logs`, both resolved against the working directory.

### Task 1: `paths.py` — resolve profile and log directories per platform

**Files:**
- Create: `src/abt/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `current_kind() -> str` — one of `"windows"`, `"macos"`, `"linux"`.
  - `in_source_checkout(cwd: Path | None = None) -> bool`
  - `default_profile(kind: str | None = None, home: Path | None = None, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> Path`
  - `default_log_dir(kind: str | None = None, home: Path | None = None, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> Path`
  - Constants `APP_DIR = "AIBrowserToolkit"`, `XDG_DIR = "aibrowsertoolkit"`, `DIST_NAME = "aibrowsertoolkit"`.

The `kind` / `home` / `env` / `cwd` parameters exist so all three platforms can be checked from whichever one the tests run on. This mirrors `autostart.plan()`, which takes `kind`, `home` and `exe` for exactly the same reason — read `tests/test_autostart.py` for the pattern before writing these tests.

- [ ] **Step 1: Write the failing tests**

```python
"""Where an installed copy keeps its profile and its logs.

Pure like `autostart.plan()`, and for the same reason: the three platforms are
one shape, so all three are checked from whichever one the tests run on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abt import paths


KINDS = ("windows", "macos", "linux")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    """A working directory that is not a checkout of this project."""
    d = tmp_path / "elsewhere"
    d.mkdir()
    return d


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    d = tmp_path / "checkout"
    d.mkdir()
    (d / "pyproject.toml").write_text(
        '[project]\nname = "aibrowsertoolkit"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    return d


@pytest.mark.parametrize("kind", KINDS)
def test_profile_is_absolute_and_under_home(kind, home, elsewhere):
    got = paths.default_profile(kind=kind, home=home, env={}, cwd=elsewhere)
    assert got.is_absolute()
    assert home in got.parents


@pytest.mark.parametrize("kind", KINDS)
def test_profile_never_lands_in_the_working_directory(kind, home, elsewhere):
    """The whole point. A cwd-relative profile run from a logon task resolves
    against C:\\Windows\\System32 and silently builds an empty second profile
    holding none of the logins."""
    got = paths.default_profile(kind=kind, home=home, env={}, cwd=elsewhere)
    assert elsewhere not in got.parents
    assert got != elsewhere / "profiles" / "default"


def test_windows_uses_localappdata_when_set(home, elsewhere):
    env = {"LOCALAPPDATA": str(home / "AppData" / "Local")}
    got = paths.default_profile(kind="windows", home=home, env=env, cwd=elsewhere)
    assert got == home / "AppData/Local/AIBrowserToolkit/profiles/default"


def test_windows_falls_back_when_localappdata_is_missing(home, elsewhere):
    got = paths.default_profile(kind="windows", home=home, env={}, cwd=elsewhere)
    assert got == home / "AppData/Local/AIBrowserToolkit/profiles/default"


def test_macos_profile_and_logs_use_the_two_library_directories(home, elsewhere):
    profile = paths.default_profile(kind="macos", home=home, env={}, cwd=elsewhere)
    logs = paths.default_log_dir(kind="macos", home=home, env={}, cwd=elsewhere)
    assert profile == home / "Library/Application Support/AIBrowserToolkit/profiles/default"
    assert logs == home / "Library/Logs/AIBrowserToolkit"


def test_linux_honours_xdg_variables(home, elsewhere):
    env = {"XDG_DATA_HOME": str(home / "data"), "XDG_STATE_HOME": str(home / "state")}
    profile = paths.default_profile(kind="linux", home=home, env=env, cwd=elsewhere)
    logs = paths.default_log_dir(kind="linux", home=home, env=env, cwd=elsewhere)
    assert profile == home / "data/aibrowsertoolkit/profiles/default"
    assert logs == home / "state/aibrowsertoolkit/logs"


def test_linux_falls_back_to_the_xdg_defaults(home, elsewhere):
    profile = paths.default_profile(kind="linux", home=home, env={}, cwd=elsewhere)
    logs = paths.default_log_dir(kind="linux", home=home, env={}, cwd=elsewhere)
    assert profile == home / ".local/share/aibrowsertoolkit/profiles/default"
    assert logs == home / ".local/state/aibrowsertoolkit/logs"


@pytest.mark.parametrize("kind", KINDS)
def test_a_checkout_keeps_the_old_relative_locations(kind, home, checkout):
    """Protects start-server.bat, the live profiles/default and its logins,
    and every guideline that says `./logs`."""
    profile = paths.default_profile(kind=kind, home=home, env={}, cwd=checkout)
    logs = paths.default_log_dir(kind=kind, home=home, env={}, cwd=checkout)
    assert profile == checkout / "profiles" / "default"
    assert logs == checkout / "logs"


def test_someone_elses_pyproject_is_not_our_checkout(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "pyproject.toml").write_text(
        '[project]\nname = "something-else"\n', encoding="utf-8"
    )
    assert paths.in_source_checkout(other) is False


def test_malformed_pyproject_is_not_our_checkout(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "pyproject.toml").write_text("this is not toml {{{", encoding="utf-8")
    assert paths.in_source_checkout(bad) is False


def test_current_kind_is_one_of_the_three():
    assert paths.current_kind() in KINDS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abt.paths'`

- [ ] **Step 3: Write the implementation**

```python
"""Where an installed copy keeps its profile and its logs.

`--profile` defaulted to `./profiles/default` and `--log-dir` to `./logs`, both
resolved against the current working directory. That is right for a repo
checkout and wrong for an installed program: run `abt serve` from a home
directory and it silently builds a second, empty Chrome profile there holding
none of the logins. Run it from a logon task and the working directory is
`C:\\Windows\\System32` -- the failure `autostart.py` already warns about.

Pure like `autostart.plan()`, and for the same reason: the three platforms are
one shape, so all three can be checked from whichever one the tests run on.
"""

from __future__ import annotations

import os
import platform
import tomllib
from collections.abc import Mapping
from pathlib import Path

# Windows and macOS want a display name; XDG wants a lowercase one.
APP_DIR = "AIBrowserToolkit"
XDG_DIR = "aibrowsertoolkit"
DIST_NAME = "aibrowsertoolkit"


def current_kind() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    return "linux"


def in_source_checkout(cwd: Path | None = None) -> bool:
    """True when the working directory is this project's own checkout.

    The escape hatch that keeps `start-server.bat`, the existing
    `profiles/default` with its live logins, and every guideline working
    untouched. An installed copy never sees this file.
    """
    root = Path.cwd() if cwd is None else Path(cwd)
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        # A pyproject.toml we cannot read is somebody else's problem, not a
        # signal that we are in our own tree.
        return False
    return data.get("project", {}).get("name") == DIST_NAME


def _resolved(kind: str | None, home: Path | None, env: Mapping[str, str] | None):
    return (
        kind or current_kind(),
        Path(home) if home is not None else Path.home(),
        os.environ if env is None else env,
    )


def _data_root(kind: str, home: Path, env: Mapping[str, str]) -> Path:
    if kind == "windows":
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / APP_DIR
    if kind == "macos":
        return home / "Library" / "Application Support" / APP_DIR
    xdg = env.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else home / ".local" / "share") / XDG_DIR


def _state_root(kind: str, home: Path, env: Mapping[str, str]) -> Path:
    if kind == "windows":
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / APP_DIR
    if kind == "macos":
        return home / "Library" / "Logs" / APP_DIR
    xdg = env.get("XDG_STATE_HOME")
    return (Path(xdg) if xdg else home / ".local" / "state") / XDG_DIR


def default_profile(
    kind: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    if in_source_checkout(cwd):
        root = Path.cwd() if cwd is None else Path(cwd)
        return root / "profiles" / "default"
    kind, home, env = _resolved(kind, home, env)
    return _data_root(kind, home, env) / "profiles" / "default"


def default_log_dir(
    kind: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    if in_source_checkout(cwd):
        root = Path.cwd() if cwd is None else Path(cwd)
        return root / "logs"
    kind, home, env = _resolved(kind, home, env)
    root = _state_root(kind, home, env)
    # macOS already names the directory Logs; the others need the suffix.
    return root if kind == "macos" else root / "logs"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_paths.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add src/abt/paths.py tests/test_paths.py
git commit -m "Give an installed copy somewhere to keep its profile"
```

---

### Task 2: Wire the new defaults into the four call sites

**Files:**
- Modify: `src/abt/launch.py` (the `LaunchConfig.profile` field and `__post_init__`)
- Modify: `src/abt/cli.py:87` (`serve --profile`), `src/abt/cli.py` (`serve --log-dir`), `src/abt/cli.py:627` (`autostart install --profile`), and `autostart install --log-dir`
- Modify: `docs/TODO.md`
- Test: `tests/test_launch.py` (add), `tests/test_paths.py` (add)

**Interfaces:**
- Consumes: `paths.default_profile()`, `paths.default_log_dir()` from Task 1.
- Produces: `LaunchConfig(profile=None)` resolving to `paths.default_profile()`. No other signature changes — `merge()` keeps its "`None` means keep" contract, which is safe because `merge` only ever passes `self.profile`, already resolved and never `None`.

Typer evaluates option defaults once, at function-definition time. Computing the default there would freeze whatever the working directory was at import. So the options default to `None` and resolve inside the function body.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_launch.py`:

```python
def test_launch_config_defaults_to_the_per_user_profile(monkeypatch, tmp_path):
    """A LaunchConfig built with no profile must not point at the cwd."""
    monkeypatch.chdir(tmp_path)
    from abt import paths
    from abt.launch import LaunchConfig

    assert LaunchConfig().profile == paths.default_profile().expanduser().resolve()


def test_an_explicit_profile_still_wins(tmp_path):
    from abt.launch import LaunchConfig

    assert LaunchConfig(profile=tmp_path / "mine").profile == (tmp_path / "mine").resolve()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_launch.py -v`
Expected: FAIL — the default is still `./profiles/default` resolved against `tmp_path`.

- [ ] **Step 3: Change `launch.py`**

Replace the field and its normalisation:

```python
@dataclass(frozen=True)
class LaunchConfig:
    browser: str = "chrome"
    profile: Path | None = None   # None means "wherever this install keeps it"
    headless: bool = False

    def __post_init__(self) -> None:
        browser = str(self.browser).strip().lower()
        if browser not in SUPPORTED_BROWSERS:
            raise OpError(
                "bad_browser",
                f"unsupported browser {self.browser!r}; "
                f"choose from {', '.join(SUPPORTED_BROWSERS)}",
            )
        profile = self.profile if self.profile is not None else paths.default_profile()
        # A frozen dataclass still gets to normalise itself during __post_init__;
        # object.__setattr__ is the sanctioned way in.
        object.__setattr__(self, "browser", browser)
        object.__setattr__(self, "profile", Path(profile).expanduser().resolve())
```

Add `from . import paths` to the imports.

- [ ] **Step 4: Change the four CLI options**

In `src/abt/cli.py`, for `serve` and for `autostart install`, both `--profile` and `--log-dir` become:

```python
    profile: Path = typer.Option(
        None,
        "--profile",
        help="Persistent browser user-data-dir. Defaults to this install's "
        "own per-user directory, or ./profiles/default inside a checkout.",
    ),
    log_dir: Path = typer.Option(
        None,
        "--log-dir",
        help="Where session logs are written. Defaults to this install's own "
        "per-user directory, or ./logs inside a checkout.",
    ),
```

and the first lines of each function body resolve them:

```python
    profile = profile or paths.default_profile()
    log_dir = log_dir or paths.default_log_dir()
```

Add `from . import paths` to `cli.py`'s imports. `autostart install` already turns these into absolute paths before writing the entry, so it needs no further change.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS. Pay attention to `tests/test_autostart.py` — it passes explicit paths, so it should be unaffected; if it is not, the resolution moved to the wrong place.

- [ ] **Step 6: Verify the escape hatch by hand**

```bash
.venv/Scripts/python -c "from abt import paths; print(paths.default_profile())"
```
Expected: the repo's own `profiles\default` — because the working directory is the checkout.

```bash
cd "$TEMP" && "$OLDPWD/.venv/Scripts/python" -c "from abt import paths; print(paths.default_profile())"
```
Expected: `...\AppData\Local\AIBrowserToolkit\profiles\default`.

- [ ] **Step 7: Replace the parked entry in `docs/TODO.md`**

Delete the whole "Packaged application + installer" section and put in its place:

```markdown
## Packaged application + installer

Designed and planned, 2026-08-20. See
[the design](superpowers/specs/2026-08-20-packaging-and-distribution-design.md)
and [the plan](superpowers/plans/2026-08-20-packaging-and-distribution.md).
The shapes considered and rejected — tray app, full desktop app, one-file
PyInstaller binary — are recorded in the design's non-goals.
```

- [ ] **Step 8: Commit**

```bash
git add src/abt/launch.py src/abt/cli.py tests/test_launch.py docs/TODO.md
git commit -m "Stop resolving the profile against the working directory"
```

---

### Task 2b: What an installed copy says when it cannot help itself

**Files:**
- Modify: `src/abt/pwdriver.py` (`_boot`), `src/abt/cli.py` (`serve`)
- Test: `tests/test_paths.py` (add), `tests/test_launch.py` (add)

**Interfaces:**
- Consumes: `paths.default_log_dir()` from Task 1.
- Produces: `paths.first_run_marker(...) -> Path`; `OpError("browser_dead", …)` raised when the requested browser is not installed.

Two spec requirements that have no home in any other task. Both exist because an installed copy has no README beside it and no terminal history to read.

**Why now, not later:** every packaging channel is a way of putting this program in front of someone who did not clone it. A raw `playwright._impl._errors.Error` is an acceptable failure for a developer in a checkout and a dead end for someone who installed from winget.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_launch.py`:

```python
def test_a_missing_browser_is_a_browser_dead_error_naming_both():
    """Playwright raises its own error when a channel is not installed. It
    does not mention Edge, and it does not say what to do."""
    from abt import pwdriver

    translated = pwdriver.translate_launch_failure(
        RuntimeError(
            "Chromium distribution 'chrome' is not found at "
            "/opt/google/chrome/chrome"
        ),
        "chrome",
    )
    assert translated.type == "browser_dead"
    assert "chrome" in translated.message.lower()
    assert "edge" in translated.message.lower()


def test_an_unrelated_launch_failure_is_left_alone():
    from abt import pwdriver

    original = RuntimeError("the disk is on fire")
    assert pwdriver.translate_launch_failure(original, "chrome") is None
```

Add to `tests/test_paths.py`:

```python
def test_the_first_run_marker_lives_beside_the_logs(home, elsewhere):
    marker = paths.first_run_marker(kind="linux", home=home, env={}, cwd=elsewhere)
    logs = paths.default_log_dir(kind="linux", home=home, env={}, cwd=elsewhere)
    assert marker.parent == logs.parent


def test_a_checkout_has_no_first_run_hint(home, checkout):
    """A developer in the repo already knows; the hint is for someone who
    installed this from a package manager."""
    assert paths.first_run_marker(kind="linux", home=home, env={}, cwd=checkout) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_launch.py tests/test_paths.py -v`
Expected: FAIL — `AttributeError: module 'abt.pwdriver' has no attribute 'translate_launch_failure'` and the same for `paths.first_run_marker`.

- [ ] **Step 3: Add `translate_launch_failure` to `pwdriver.py`**

```python
def translate_launch_failure(exc: Exception, browser: str) -> OpError | None:
    """A missing browser, said in this toolkit's own vocabulary.

    Playwright reports "Chromium distribution 'chrome' is not found at ...",
    which is true and useless: it does not mention that Edge is supported, and
    it does not say what to install. A developer in a checkout can work that
    out. Someone who installed this from winget cannot.
    """
    text = str(exc).lower()
    if "is not found" not in text and "executable doesn't exist" not in text:
        return None
    return OpError(
        "browser_dead",
        f"{browser} is not installed, or not where Playwright looks for it. "
        f"This toolkit drives an existing Google Chrome or Microsoft Edge and "
        f"bundles neither. Install one, or pass --browser "
        f"{'edge' if browser == 'chrome' else 'chrome'}.",
    )
```

Wrap the launch in `_boot`:

```python
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
```

- [ ] **Step 4: Add `first_run_marker` to `paths.py`**

```python
def first_run_marker(
    kind: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Where to record that the one-time hint has been shown.

    None inside a checkout: a developer in the repo has the README, and a hint
    printed on every `abt serve` during development would be noise.
    """
    if in_source_checkout(cwd):
        return None
    kind, home, env = _resolved(kind, home, env)
    return _state_root(kind, home, env) / ".first-run-shown"
```

- [ ] **Step 5: Print the hint once, in `serve`**

At the top of `serve`'s body, after the profile and log_dir resolution:

```python
    marker = paths.first_run_marker()
    if marker is not None and not marker.exists():
        typer.echo(
            "Tip: to start this server automatically at every logon, run\n"
            "    abt autostart install --browser chrome\n"
            "It is opt-in and user-level; `abt autostart uninstall` removes it.",
            err=True,
        )
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
```

Written to stderr so it can never contaminate a caller parsing stdout.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS. In particular the hint must not appear when running from the checkout — confirm by running `.venv/Scripts/abt serve --help` and seeing no tip.

- [ ] **Step 7: Commit**

```bash
git add src/abt/pwdriver.py src/abt/paths.py src/abt/cli.py tests/
git commit -m "Say something useful when there is no browser, and once about autostart"
```

---

# Wave 2 — Build and PyPI

Needs no repository secrets. `GITHUB_TOKEN` is issued automatically; PyPI Trusted Publishing is configuration on PyPI's side.

### Task 3: `python -m abt` and the bundle builder

**Files:**
- Create: `src/abt/__main__.py`, `packaging/bundle.py`
- Test: `tests/test_bundle.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `TARGETS: dict[str, str]` — bundle target name → python-build-standalone triple.
  - `PYTHON_VERSION: str` — `"3.13"`.
  - `bundle_stem(version: str, target: str) -> str` — e.g. `aibrowsertoolkit-0.2.0-linux-x86_64`.
  - `shim_for(target: str) -> tuple[str, str]` — `(relative_path, file_contents)`.
  - `build(version: str, target: str, wheel: Path, dest: Path) -> Path` — returns the archive path.

- [ ] **Step 1: Write the failing tests**

```python
"""The bundle's shape, checked without downloading a 30MB interpreter.

What is worth asserting here is the part that silently breaks: the launcher
must reach the bundled interpreter by a path relative to itself, because the
bundle is built in one directory and installed in another.
"""

from __future__ import annotations

import pytest

from packaging import bundle


def test_five_targets_exactly():
    assert set(bundle.TARGETS) == {
        "linux-x86_64",
        "linux-aarch64",
        "macos-arm64",
        "macos-x86_64",
        "windows-x86_64",
    }


def test_stem_carries_version_and_target():
    assert bundle.bundle_stem("0.2.0", "linux-x86_64") == "aibrowsertoolkit-0.2.0-linux-x86_64"


def test_host_target_is_one_we_ship():
    """Also the guard against a typo in TARGETS: a host that maps to a name
    not in the table would fail only on a release runner."""
    assert bundle.host_target() in bundle.TARGETS


def test_target_names_end_in_the_arch_the_aur_will_ask_for():
    """PKGBUILD resolves the unpacked directory using $CARCH, which is x86_64
    or aarch64. The target names must match or package() looks in the wrong
    place."""
    assert bundle.TARGETS["linux-x86_64"].startswith("x86_64")
    assert bundle.TARGETS["linux-aarch64"].startswith("aarch64")


@pytest.mark.parametrize("target", sorted(bundle.TARGETS))
def test_the_shim_never_hardcodes_a_build_path(target):
    _, body = bundle.shim_for(target)
    assert "/home/runner" not in body
    assert "C:\\Users" not in body


@pytest.mark.parametrize("target", sorted(bundle.TARGETS))
def test_the_shim_runs_the_module_not_a_console_script(target):
    """Generated console scripts carry an absolute shebang. The shim exists to
    avoid them."""
    _, body = bundle.shim_for(target)
    assert "-m abt" in body


def test_windows_shim_is_a_cmd_at_the_root():
    path, body = bundle.shim_for("windows-x86_64")
    assert path == "abt.cmd"
    assert "%~dp0" in body


def test_unix_shim_lives_in_bin_and_dereferences_symlinks():
    """Homebrew installs the tree in libexec and symlinks bin/abt to it. A shim
    using $0 without readlink resolves against the symlink and misses python."""
    path, body = bundle.shim_for("linux-x86_64")
    assert path == "bin/abt"
    assert "readlink" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_bundle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'packaging.bundle'`

If the stdlib-adjacent `packaging` distribution shadows the local directory, add `packaging/__init__.py` (empty) and ensure the repo root is on `sys.path` — `tests/conftest.py` already runs from the repo root, so an empty `__init__.py` is sufficient.

- [ ] **Step 3: Write `src/abt/__main__.py`**

```python
"""`python -m abt`, which the bundle's launcher shim invokes.

The shim cannot use the generated `abt` console script: that script carries an
absolute shebang pointing at whatever interpreter path existed when the wheel
was installed, which on a build runner is not a path that exists anywhere else.
"""

from .cli import app

app()
```

- [ ] **Step 4: Write `packaging/bundle.py`**

```python
"""Build one self-contained bundle.

Runs on a laptop as well as in CI, on purpose: a six-channel pipeline whose
build step exists only inside a workflow is one that gets debugged at ten
minutes per push.

    python packaging/bundle.py --version 0.2.0 --target linux-x86_64 \
        --wheel dist/aibrowsertoolkit-0.2.0-py3-none-any.whl --dest dist/

There is deliberately no virtualenv in the output. `uv venv --relocatable`
rewrites script shebangs but leaves `pyvenv.cfg`'s `home =` absolute, pointing
at the interpreter that built it -- so the bundle would work on the build
machine and nowhere else. Packages go straight into the standalone
interpreter's own site-packages instead; those distributions are relocatable by
construction.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.13"

# Bundle target -> the python-build-standalone triple that provides it.
TARGETS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
    "windows-x86_64": "x86_64-pc-windows-msvc",
}

PAYLOAD = ("LICENSE", "README.md", "guidelines")

UNIX_SHIM = """#!/bin/sh
# Resolve through symlinks: Homebrew puts the tree in libexec and symlinks to
# this file, so $0 alone points somewhere with no python/ beside it.
here=$(dirname "$(readlink -f "$0")")
exec "$here/../python/bin/python3" -m abt "$@"
"""

WINDOWS_SHIM = '@"%~dp0python\\python.exe" -m abt %*\r\n'


def bundle_stem(version: str, target: str) -> str:
    return f"aibrowsertoolkit-{version}-{target}"


def shim_for(target: str) -> tuple[str, str]:
    if target.startswith("windows"):
        return "abt.cmd", WINDOWS_SHIM
    return "bin/abt", UNIX_SHIM


def host_target() -> str:
    """Which of TARGETS this machine builds.

    Bundles are built natively, one runner per target, because the smoke test
    is the whole point of the matrix -- a cross-built bundle is never executed
    on the platform it is for, and Playwright's driver is exactly the thing
    most likely to break there.
    """
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    system = platform.system()
    if system == "Windows":
        return "windows-x86_64"
    if system == "Darwin":
        return "macos-arm64" if arm else "macos-x86_64"
    return "linux-aarch64" if arm else "linux-x86_64"


def _fetch_python(target: str, into: Path) -> Path:
    """Place a standalone CPython at `into/python`.

    `uv python install` is what knows how to find these builds.
    python-build-standalone's asset names embed a build date
    (`cpython-3.13.1+20241206-x86_64-unknown-linux-gnu-install_only.tar.gz`),
    so a hand-built "latest/download/..." URL resolves to nothing -- do not
    reintroduce one.

    uv installs for the host platform only, which is why this refuses a target
    that is not the host rather than producing something silently wrong.
    """
    if target != host_target():
        raise SystemExit(
            f"cannot build {target} on {host_target()}; bundles are built "
            f"natively, one runner per target"
        )
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "uv", "python", "install",
            "--install-dir", str(into),
            "--managed-python",
            PYTHON_VERSION,
        ],
        check=True,
    )
    # uv unpacks to a versioned directory name; there is exactly one.
    installed = next(d for d in sorted(into.iterdir()) if d.is_dir())
    target_dir = into / "python"
    installed.rename(target_dir)
    return target_dir


def _interpreter(python_root: Path, target: str) -> Path:
    if target.startswith("windows"):
        return python_root / "python.exe"
    return python_root / "bin" / "python3"


def build(version: str, target: str, wheel: Path, dest: Path) -> Path:
    stem = bundle_stem(version, target)
    staging = dest / stem
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    python_root = _fetch_python(target, staging)
    interpreter = _interpreter(python_root, target)

    subprocess.run(
        ["uv", "pip", "install", "--python", str(interpreter), str(wheel)],
        check=True,
    )

    rel, body = shim_for(target)
    shim = staging / rel
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(body, encoding="utf-8", newline="")
    if not target.startswith("windows"):
        shim.chmod(0o755)

    root = Path(__file__).resolve().parent.parent
    for item in PAYLOAD:
        src = root / item
        if src.is_dir():
            shutil.copytree(src, staging / item)
        else:
            shutil.copy2(src, staging / item)

    return _archive(staging, target)


def _archive(staging: Path, target: str) -> Path:
    """zip for Windows because Scoop wants one; tar.gz elsewhere because it
    preserves the executable bit on the shim."""
    if target.startswith("windows"):
        out = staging.with_suffix(".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                zf.write(path, path.relative_to(staging.parent))
        return out
    out = Path(str(staging) + ".tar.gz")
    with tarfile.open(out, "w:gz") as tar:
        tar.add(staging, arcname=staging.name)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--target",
        default=host_target(),
        choices=sorted(TARGETS),
        help="Defaults to this machine's target; a different one is refused.",
    )
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args(argv)
    out = build(args.version, args.target, args.wheel, args.dest)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_bundle.py -v`
Expected: PASS.

- [ ] **Step 6: Build one bundle for real, locally**

```bash
.venv/Scripts/python -m pip install build
.venv/Scripts/python -m build --wheel
.venv/Scripts/python packaging/bundle.py --version 0.1.0 --target windows-x86_64 \
    --wheel dist/aibrowsertoolkit-0.1.0-py3-none-any.whl --dest dist/
```

Then prove the relocation, which is the entire point:

```bash
cd "$TEMP" && rm -rf abtcheck && mkdir abtcheck && cd abtcheck
unzip -q "$OLDPWD/dist/aibrowsertoolkit-0.1.0-windows-x86_64.zip"
./aibrowsertoolkit-0.1.0-windows-x86_64/abt.cmd --version
```

Expected: the version prints, from a directory that is not where it was built. If this fails with a missing interpreter, the shim's relative path is wrong — fix it before writing any workflow.

- [ ] **Step 7: Commit**

```bash
git add src/abt/__main__.py packaging/ tests/test_bundle.py
git commit -m "Build a bundle that survives being moved"
```

---

### Task 4: CI workflow — tests on push and PR

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the test suite as it stands.
- Produces: a green check that the release workflow's `test` job mirrors.

The live tests (`test_lifecycle_live.py`, `test_shots_live.py`) need a real Chrome and are deselected here; CI runs the rest.

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, windows-latest, macos-14]
        python: ["3.11", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - name: Install
        run: uv pip install --system -e ".[dev]"
      - name: Test
        run: python -m pytest -q --deselect tests/test_lifecycle_live.py --deselect tests/test_shots_live.py
```

- [ ] **Step 2: Verify it parses and passes locally first**

Run: `.venv/Scripts/python -m pytest -q --deselect tests/test_lifecycle_live.py --deselect tests/test_shots_live.py`
Expected: PASS. If any non-live test needs a browser, deselect it here too and note why in the workflow.

- [ ] **Step 3: Commit and push, then confirm the run is green**

```bash
git add .github/workflows/ci.yml
git commit -m "Run the suite on every push"
git push
```

Expected: the CI run on GitHub finishes green across all six matrix cells. Fix and re-push until it does — later waves assume this baseline.

---

### Task 5: Release workflow — wheel, five bundles, smoke test

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `packaging/bundle.py` from Task 3.
- Produces: artifacts named `bundle-<target>` and `dist` that Tasks 6–13 all download.

- [ ] **Step 1: Write the workflow**

```yaml
name: Release

on:
  push:
    tags: ["v*"]
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Build and smoke-test everything, publish nothing"
        type: boolean
        default: true

permissions:
  contents: write
  id-token: write
  attestations: write

jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv pip install --system -e ".[dev]"
      - run: python -m pytest -q --deselect tests/test_lifecycle_live.py --deselect tests/test_shots_live.py

  wheel:
    needs: test
    runs-on: ubuntu-24.04
    outputs:
      version: ${{ steps.v.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - name: Read the version from pyproject
        id: v
        run: |
          version=$(python -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
          echo "version=$version" >> "$GITHUB_OUTPUT"
      - name: Guard the tag against the version
        if: startsWith(github.ref, 'refs/tags/')
        run: |
          tag="${GITHUB_REF_NAME#v}"
          if [ "$tag" != "${{ steps.v.outputs.version }}" ]; then
            echo "tag $GITHUB_REF_NAME does not match pyproject version ${{ steps.v.outputs.version }}"
            exit 1
          fi
      - run: uv build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  bundle:
    needs: wheel
    strategy:
      fail-fast: false
      matrix:
        include:
          - target: linux-x86_64
            os: ubuntu-24.04
          - target: linux-aarch64
            os: ubuntu-24.04-arm
          - target: macos-arm64
            os: macos-14
          - target: macos-x86_64
            os: macos-13
          - target: windows-x86_64
            os: windows-latest
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist
      - name: Build the bundle
        shell: bash
        run: |
          wheel=$(ls dist/*.whl)
          python packaging/bundle.py \
            --version "${{ needs.wheel.outputs.version }}" \
            --target "${{ matrix.target }}" \
            --wheel "$wheel" \
            --dest dist/
      - name: Smoke test
        shell: bash
        run: bash packaging/smoke.sh "dist/aibrowsertoolkit-${{ needs.wheel.outputs.version }}-${{ matrix.target }}"
      - uses: actions/upload-artifact@v4
        with:
          name: bundle-${{ matrix.target }}
          path: |
            dist/*.tar.gz
            dist/*.zip
```

- [ ] **Step 2: Write `packaging/smoke.sh`**

This is the reason for a native matrix rather than one cross-building host.

```sh
#!/bin/sh
# Prove a freshly built bundle actually runs: the relocated interpreter, the
# launcher shim, and Playwright's Node driver import are the three things that
# break silently, and all three are exercised by starting the server.
set -eu

dir="$1"
if [ -f "$dir/abt.cmd" ]; then
    abt="$dir/abt.cmd"
else
    abt="$dir/bin/abt"
fi

"$abt" --version

port=8${RANDOM:-765}
"$abt" serve --browser chrome --no-start-browser --port "$port" >smoke.log 2>&1 &

i=0
while [ $i -lt 60 ]; do
    if curl -fsS "http://127.0.0.1:$port/status" >/dev/null 2>&1; then
        "$abt" shutdown --port "$port"
        echo "smoke test passed on port $port"
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

echo "server never answered on port $port"
cat smoke.log
exit 1
```

Note the flags: `--browser chrome` is stated explicitly and `--no-start-browser` is mandatory. `abt serve` prompts when `--browser` is missing and stdin is a tty, and a runner that prompts waits forever — `src/abt/autostart.py`'s docstring records this being observed. Starting a browser on a CI runner would also fail, and is not what this test is for.

- [ ] **Step 3: Trigger a dry run and confirm all five bundles pass**

```bash
git add .github/workflows/release.yml packaging/smoke.sh
git commit -m "Build and smoke-test five bundles on every target"
git push
gh workflow run Release -f dry_run=true
```

Expected: five green `bundle` jobs. A failure here is a real bug in the bundle, not in the workflow — read `smoke.log` in the job output before changing any YAML.

---

### Task 6: Release job — checksums, provenance, GitHub release

**Files:**
- Modify: `.github/workflows/release.yml` (add the `release` job)

**Interfaces:**
- Consumes: artifacts `dist` and `bundle-*` from Task 5.
- Produces: a published GitHub release whose asset URLs every publisher job reads.

- [ ] **Step 1: Add the job**

```yaml
  release:
    needs: [wheel, bundle]
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/download-artifact@v4
        with:
          path: staging
      - name: Collect every artifact into one directory
        run: |
          mkdir -p out
          find staging -type f \( -name '*.tar.gz' -o -name '*.zip' \
            -o -name '*.whl' -o -name '*.exe' \) -exec cp {} out/ \;
          ls -l out
          # Five bundles + wheel + sdist + installer. A missing one means an
          # upstream job was skipped, and shipping a partial release is worse
          # than failing here.
          test "$(ls out | wc -l)" -ge 8
      - name: Checksums
        run: cd out && sha256sum * > checksums.txt && cat checksums.txt
      - uses: actions/attest-build-provenance@v2
        with:
          subject-path: "out/*"
      - uses: softprops/action-gh-release@v2
        with:
          files: out/*
          generate_release_notes: true
          prerelease: ${{ contains(github.ref_name, '-rc') || contains(github.ref_name, '-beta') }}
```

`checksums.txt` is generated before the attestation so it is itself attested.

- [ ] **Step 2: Cut a real prerelease tag and confirm the assets**

```bash
# bump pyproject version to 0.2.0-rc1 first, or the version guard fails
git tag v0.2.0-rc1 && git push origin v0.2.0-rc1
```

Expected: a prerelease containing five bundles, a wheel, an sdist and `checksums.txt`, each with a provenance attestation visible under the repo's Attestations tab.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "Publish the release the publishers read from"
```

---

### Task 7: PyPI via Trusted Publishing

**Files:**
- Modify: `.github/workflows/release.yml` (add the `pypi` job)
- Create: `docs/packaging.md`

**Interfaces:**
- Consumes: the `dist` artifact from Task 5.
- Produces: `pip install aibrowsertoolkit` working on every platform.

**Before this runs**, register the pending publisher at pypi.org → Your projects → Publishing → Add a new pending publisher: PyPI project name `aibrowsertoolkit`, owner `skssmd`, repository `Ai-Browser-Toolkit`, workflow `release.yml`, environment `pypi`. Then create a GitHub environment named `pypi` in the repository settings. There is no secret to store.

- [ ] **Step 1: Add the job**

```yaml
  pypi:
    needs: release
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-24.04
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 2: Write `docs/packaging.md`**

```markdown
# Cutting a release

The whole pipeline hangs off one tag. Nothing is published by hand.

1. Bump `version` in `pyproject.toml`.
2. `git commit -am "Release vX.Y.Z" && git tag vX.Y.Z && git push --follow-tags`
3. Watch the Release workflow. It tests, builds a wheel and five bundles,
   smoke-tests each bundle on its own operating system, publishes a GitHub
   release with checksums and build provenance, then fans out to the channels.

The tag must match `pyproject.toml`'s version or the run fails on purpose --
a release shipping mislabelled wheels cannot be fixed afterwards.

## Testing without burning a version

`gh workflow run Release -f dry_run=true` builds and smoke-tests everything and
publishes nothing.

## When one channel fails

The publisher jobs are independent. Re-run the single failed job rather than
the whole release; the release and its assets already exist.

## Verifying an install by hand

    pipx install aibrowsertoolkit
    abt --version
```

- [ ] **Step 3: Tag a real release and verify from PyPI**

```bash
pipx install aibrowsertoolkit
abt --version
abt autostart install --browser chrome --dry-run
```

Expected: the version prints, and the dry-run autostart plan shows absolute paths pointing at the pipx install, not at a checkout.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml docs/packaging.md
git commit -m "Publish to PyPI without storing a token"
```

---

# Wave 3 — Windows

Needs `WINGET_TOKEN` and `TAP_TOKEN`. Also needs a fork of `microsoft/winget-pkgs` under an account `WINGET_TOKEN` can push to, synced with upstream `master`, and a `scoop-bucket` repository.

### Task 8: Inno Setup installer with the autostart checkbox

**Files:**
- Create: `packaging/windows/abt.iss`
- Modify: `.github/workflows/release.yml` (add the `installer` job, and include its output in `release`)

**Interfaces:**
- Consumes: the `bundle-windows-x86_64` artifact.
- Produces: `aibrowsertoolkit-<version>-windows-x86_64-setup.exe` on the release, which both the standalone download and the winget manifest point at.

- [ ] **Step 1: Write the Inno script**

```pascal
; Per-user by design. The toolkit's premise is a per-user Chrome profile and a
; user-level logon task -- autostart.py is explicit that a system service runs
; as another user and finds none of the logins. So: no Program Files, no UAC.

#define AppName "AI Browser Toolkit"
#define AppExe "abt.cmd"

[Setup]
AppId={{7C4C9B2E-2F1A-4E63-9D5B-3A1C8F6E2D74}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=skssmd
AppPublisherURL=https://github.com/skssmd/Ai-Browser-Toolkit
DefaultDirName={localappdata}\Programs\AIBrowserToolkit
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=aibrowsertoolkit-{#AppVersion}-windows-x86_64-setup
Compression=lzma2
SolidCompression=yes
LicenseFile=..\..\LICENSE
WizardStyle=modern
UninstallDisplayName={#AppName}

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
; Unchecked, deliberately. The opt-in rule is recorded in autostart.py.
Name: "autostart"; Description: "Start {#AppName} at logon"; Flags: unchecked
Name: "addtopath"; Description: "Add abt to my PATH"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath('{app}'); Tasks: addtopath

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "autostart install --browser chrome"; \
    Tasks: autostart; Flags: runhidden; StatusMsg: "Registering the logon task..."

[UninstallRun]
; Before the files go, or Task Scheduler is left pointing at a deleted target.
Filename: "{app}\{#AppExe}"; Parameters: "autostart uninstall"; \
    Flags: runhidden; RunOnceId: "RemoveAutostart"

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + ExpandConstant(Param) + ';', ';' + OrigPath + ';') = 0;
end;
```

- [ ] **Step 2: Add the `installer` job**

```yaml
  installer:
    needs: [wheel, bundle]
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: bundle-windows-x86_64
          path: dl
      - name: Unpack the bundle
        shell: bash
        run: |
          mkdir -p payload
          unzip -q dl/*.zip -d payload
          mv payload/*/ payload/tree
      - name: Compile
        shell: cmd
        run: >
          iscc /DAppVersion=${{ needs.wheel.outputs.version }}
          /DPayloadDir=%CD%\payload\tree
          /O%CD%\out
          packaging\windows\abt.iss
      - uses: actions/upload-artifact@v4
        with:
          name: installer
          path: out/*.exe
```

Inno Setup is preinstalled on `windows-latest`; if `iscc` is not on PATH, add `choco install innosetup -y` as a prior step.

Add `installer` to the `release` job's `needs:` list so the `.exe` is collected, checksummed, attested and uploaded with everything else.

- [ ] **Step 3: Install it locally and verify all four behaviours**

Download the `.exe` from a dry run and check, in order:

1. It installs with no UAC prompt.
2. A new terminal resolves `abt --version`.
3. With the box left unchecked, `abt autostart` reports nothing installed — confirm in Task Scheduler that no "AI Browser Toolkit server" task exists.
4. Re-run the installer with the box **checked**, confirm the task appears, then uninstall and confirm the task is gone.

Point 4 is the one that regresses silently. Do not skip it.

- [ ] **Step 4: Commit**

```bash
git add packaging/windows/abt.iss .github/workflows/release.yml
git commit -m "Offer the logon task as a checkbox, unchecked"
```

---

### Task 9: winget and Scoop

**Files:**
- Create: `packaging/scoop/manifest.json.template`
- Modify: `.github/workflows/release.yml` (add `winget` and `scoop` jobs)

**Interfaces:**
- Consumes: the `installer` artifact (winget) and `bundle-windows-x86_64` (Scoop).
- Produces: a PR into `microsoft/winget-pkgs`, and a commit in the Scoop bucket.

- [ ] **Step 1: Add the `winget` job**

```yaml
  winget:
    needs: release
    if: startsWith(github.ref, 'refs/tags/') && !contains(github.ref_name, '-rc')
    runs-on: ubuntu-24.04
    steps:
      - uses: vedantmgoyal9/winget-releaser@main
        with:
          identifier: skssmd.AIBrowserToolkit
          version: ${{ needs.wheel.outputs.version }}
          installers-regex: '-setup\.exe$'
          fork-user: the-graft-project
          token: ${{ secrets.WINGET_TOKEN }}
```

Add `wheel` to this job's `needs:` so `needs.wheel.outputs.version` resolves.

`WINGET_TOKEN` must be a **classic** PAT with the `public_repo` scope — `winget-releaser` does not work with fine-grained tokens. Release candidates are excluded: the winget community repository does not want them.

The manifest's installer metadata (`InstallerType: inno`, `Scope: user`, silent switches) is inferred by the action from the Inno installer itself. Verify it on the generated PR before merging the first one.

- [ ] **Step 2: Write the Scoop manifest template**

`packaging/scoop/manifest.json.template`:

```json
{
    "version": "@VERSION@",
    "description": "Browser API for AI agents, over HTTP",
    "homepage": "https://github.com/skssmd/Ai-Browser-Toolkit",
    "license": "Apache-2.0",
    "architecture": {
        "64bit": {
            "url": "https://github.com/skssmd/Ai-Browser-Toolkit/releases/download/v@VERSION@/aibrowsertoolkit-@VERSION@-windows-x86_64.zip",
            "hash": "@HASH@",
            "extract_dir": "aibrowsertoolkit-@VERSION@-windows-x86_64"
        }
    },
    "bin": "abt.cmd",
    "notes": [
        "Needs Google Chrome or Microsoft Edge installed.",
        "To start the server at logon: abt autostart install --browser chrome"
    ],
    "checkver": {
        "github": "https://github.com/skssmd/Ai-Browser-Toolkit"
    },
    "autoupdate": {
        "architecture": {
            "64bit": {
                "url": "https://github.com/skssmd/Ai-Browser-Toolkit/releases/download/v$version/aibrowsertoolkit-$version-windows-x86_64.zip"
            }
        }
    }
}
```

- [ ] **Step 3: Add the `scoop` job**

```yaml
  scoop:
    needs: [wheel, release]
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: bundle-windows-x86_64
          path: dl
      - name: Render the manifest
        run: |
          version="${{ needs.wheel.outputs.version }}"
          hash=$(sha256sum dl/*.zip | cut -d' ' -f1)
          sed -e "s/@VERSION@/$version/g" -e "s/@HASH@/$hash/g" \
            packaging/scoop/manifest.json.template > aibrowsertoolkit.json
          cat aibrowsertoolkit.json
      - name: Push to the bucket
        env:
          TOKEN: ${{ secrets.TAP_TOKEN }}
        run: |
          git clone "https://x-access-token:$TOKEN@github.com/the-graft-project/scoop-bucket.git" bucket
          mkdir -p bucket/bucket
          cp aibrowsertoolkit.json bucket/bucket/aibrowsertoolkit.json
          cd bucket
          git config user.name "skssmd"
          git config user.email "skssmd78475@gmail.com"
          git add bucket/aibrowsertoolkit.json
          git commit -m "aibrowsertoolkit: ${{ needs.wheel.outputs.version }}"
          # Graft's release workflow writes to this repo too; a simultaneous
          # release would otherwise lose this push to a non-fast-forward.
          for attempt in 1 2 3; do
            git pull --rebase && git push && exit 0
            sleep 5
          done
          exit 1
```

- [ ] **Step 4: Verify both**

```powershell
scoop bucket add graft https://github.com/the-graft-project/scoop-bucket
scoop install aibrowsertoolkit
abt --version
```

For winget, read the generated PR's manifest and confirm `Scope: user` and `InstallerType: inno` before merging.

- [ ] **Step 5: Commit**

```bash
git add packaging/scoop .github/workflows/release.yml
git commit -m "Ship the Windows bundle to winget and Scoop"
```

---

# Wave 4 — Unix packages

Needs `TAP_TOKEN`, `AUR_SSH_KEY` and `FURY_TOKEN`.

### Task 10: Homebrew tap

**Files:**
- Create: `packaging/homebrew/formula.rb.template`
- Modify: `.github/workflows/release.yml` (add the `brew` job), `docs/packaging.md`

**Interfaces:**
- Consumes: `bundle-macos-arm64`, `bundle-macos-x86_64`.
- Produces: `Formula/aibrowsertoolkit.rb` in `the-graft-project/homebrew-tap`.

- [ ] **Step 1: Write the template**

```ruby
class Aibrowsertoolkit < Formula
  desc "Browser API for AI agents, over HTTP"
  homepage "https://github.com/skssmd/Ai-Browser-Toolkit"
  version "@VERSION@"
  license "Apache-2.0"

  on_macos do
    on_arm do
      url "https://github.com/skssmd/Ai-Browser-Toolkit/releases/download/v@VERSION@/aibrowsertoolkit-@VERSION@-macos-arm64.tar.gz"
      sha256 "@SHA_ARM@"
    end
    on_intel do
      url "https://github.com/skssmd/Ai-Browser-Toolkit/releases/download/v@VERSION@/aibrowsertoolkit-@VERSION@-macos-x86_64.tar.gz"
      sha256 "@SHA_INTEL@"
    end
  end

  def install
    libexec.install Dir["*"]
    bin.install_symlink libexec/"bin/abt"
  end

  def caveats
    <<~EOS
      Needs Google Chrome or Microsoft Edge installed; no browser is bundled.

      To start the server at logon:
        abt autostart install --browser chrome

      Homebrew has no uninstall hook, so `brew uninstall` will NOT remove that
      launchd agent. Run `abt autostart uninstall` before uninstalling, or the
      agent fails at your next login.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/abt --version")
  end
end
```

The caveats' final paragraph is required, not decorative — it is the one known gap in the design and the user has no other way to learn of it.

- [ ] **Step 2: Add the `brew` job**

```yaml
  brew:
    needs: [wheel, release]
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: bundle-macos-*
          path: dl
      - name: Render the formula
        run: |
          version="${{ needs.wheel.outputs.version }}"
          arm=$(sha256sum dl/bundle-macos-arm64/*.tar.gz | cut -d' ' -f1)
          intel=$(sha256sum dl/bundle-macos-x86_64/*.tar.gz | cut -d' ' -f1)
          sed -e "s/@VERSION@/$version/g" -e "s/@SHA_ARM@/$arm/g" -e "s/@SHA_INTEL@/$intel/g" \
            packaging/homebrew/formula.rb.template > aibrowsertoolkit.rb
          cat aibrowsertoolkit.rb
      - name: Push to the tap
        env:
          TOKEN: ${{ secrets.TAP_TOKEN }}
        run: |
          git clone "https://x-access-token:$TOKEN@github.com/the-graft-project/homebrew-tap.git" tap
          mkdir -p tap/Formula
          cp aibrowsertoolkit.rb tap/Formula/aibrowsertoolkit.rb
          cd tap
          git config user.name "skssmd"
          git config user.email "skssmd78475@gmail.com"
          git add Formula/aibrowsertoolkit.rb
          git commit -m "aibrowsertoolkit ${{ needs.wheel.outputs.version }}"
          # Graft writes Formula/graft.rb in this same repo.
          for attempt in 1 2 3; do
            git pull --rebase && git push && exit 0
            sleep 5
          done
          exit 1
```

- [ ] **Step 3: Verify on a Mac**

```bash
brew tap the-graft-project/tap
brew install aibrowsertoolkit
abt --version
```

Expected: installs, runs, and prints the caveats including the uninstall warning.

- [ ] **Step 4: Commit**

```bash
git add packaging/homebrew .github/workflows/release.yml
git commit -m "Publish the macOS bundles through the tap"
```

---

### Task 11: AUR

**Files:**
- Create: `packaging/aur/PKGBUILD.template`, `packaging/aur/aibrowsertoolkit-bin.install`
- Modify: `.github/workflows/release.yml` (add the `aur` job)

**Interfaces:**
- Consumes: `bundle-linux-x86_64`, `bundle-linux-aarch64`.
- Produces: the `aibrowsertoolkit-bin` AUR package.

- [ ] **Step 1: Write the PKGBUILD template**

```bash
# Maintainer: skssmd <skssmd78475@gmail.com>
pkgname=aibrowsertoolkit-bin
pkgver=@VERSION@
pkgrel=1
pkgdesc="Browser API for AI agents, over HTTP"
arch=('x86_64' 'aarch64')
url="https://github.com/skssmd/Ai-Browser-Toolkit"
license=('Apache-2.0')
# Chrome is required at runtime but is not in the repos, and Edge counts too --
# a hard dependency would make this uninstallable on a clean Arch box.
optdepends=('google-chrome: the browser this drives'
            'microsoft-edge-stable-bin: alternative browser')
provides=('aibrowsertoolkit')
conflicts=('aibrowsertoolkit')
install="${pkgname}.install"
source_x86_64=("${url}/releases/download/v${pkgver}/aibrowsertoolkit-${pkgver}-linux-x86_64.tar.gz")
source_aarch64=("${url}/releases/download/v${pkgver}/aibrowsertoolkit-${pkgver}-linux-aarch64.tar.gz")
sha256sums_x86_64=('@SHA_X86@')
sha256sums_aarch64=('@SHA_ARM@')

package() {
    local src="${srcdir}/aibrowsertoolkit-${pkgver}-${CARCH}"
    install -dm755 "${pkgdir}/opt/aibrowsertoolkit"
    cp -a "${src}/." "${pkgdir}/opt/aibrowsertoolkit/"
    install -dm755 "${pkgdir}/usr/bin"
    ln -s /opt/aibrowsertoolkit/bin/abt "${pkgdir}/usr/bin/abt"
    install -Dm644 "${src}/LICENSE" "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
```

The tarball's top-level directory is named for the bundle target, and `CARCH` is `x86_64` or `aarch64` — which match the target names by construction. This is why `TARGETS` uses those exact strings.

- [ ] **Step 2: Write the install hook**

`packaging/aur/aibrowsertoolkit-bin.install`:

```bash
post_install() {
    cat <<'EOF'
Needs Google Chrome or Microsoft Edge installed; no browser is bundled.

To start the server at logon:
    abt autostart install --browser chrome
EOF
}

post_upgrade() {
    post_install
}

pre_remove() {
    # Leave no systemd user unit pointing at files that are about to vanish.
    abt autostart uninstall >/dev/null 2>&1 || true
}
```

- [ ] **Step 3: Add the `aur` job**

```yaml
  aur:
    needs: [wheel, release]
    if: startsWith(github.ref, 'refs/tags/') && !contains(github.ref_name, '-rc')
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: bundle-linux-*
          path: dl
      - name: Render the PKGBUILD
        run: |
          version="${{ needs.wheel.outputs.version }}"
          x86=$(sha256sum dl/bundle-linux-x86_64/*.tar.gz | cut -d' ' -f1)
          arm=$(sha256sum dl/bundle-linux-aarch64/*.tar.gz | cut -d' ' -f1)
          mkdir -p aurpkg
          sed -e "s/@VERSION@/$version/g" -e "s/@SHA_X86@/$x86/g" -e "s/@SHA_ARM@/$arm/g" \
            packaging/aur/PKGBUILD.template > aurpkg/PKGBUILD
          cp packaging/aur/aibrowsertoolkit-bin.install aurpkg/
          cat aurpkg/PKGBUILD
      - uses: KSXGitHub/github-actions-deploy-aur@v3
        with:
          pkgname: aibrowsertoolkit-bin
          pkgbuild: aurpkg/PKGBUILD
          assets: aurpkg/aibrowsertoolkit-bin.install
          commit_username: skssmd
          commit_email: skssmd78475@gmail.com
          ssh_private_key: ${{ secrets.AUR_SSH_KEY }}
          commit_message: "aibrowsertoolkit-bin ${{ needs.wheel.outputs.version }}"
```

The action generates `.SRCINFO` itself.

- [ ] **Step 4: Verify inside a container before the first real push**

```bash
docker run --rm -it -v "$PWD/aurpkg:/pkg" archlinux bash -c '
  pacman -Sy --noconfirm base-devel
  useradd -m build && chown -R build /pkg
  su build -c "cd /pkg && makepkg -s --noconfirm"
'
```

Expected: a `.pkg.tar.zst` builds. The AUR is public and a broken first push is visible to everyone, so do this before tagging.

- [ ] **Step 5: Commit**

```bash
git add packaging/aur .github/workflows/release.yml
git commit -m "Publish aibrowsertoolkit-bin to the AUR"
```

---

### Task 12: deb, rpm and apk via Gemfury

**Files:**
- Create: `packaging/nfpm.yaml`
- Modify: `.github/workflows/release.yml` (add the `fury` job), `docs/packaging.md`

**Interfaces:**
- Consumes: `bundle-linux-x86_64`, `bundle-linux-aarch64`.
- Produces: packages in the Gemfury repository.

- [ ] **Step 1: Write the nfpm config**

```yaml
name: aibrowsertoolkit
arch: ${PKG_ARCH}
platform: linux
version: ${PKG_VERSION}
section: utils
maintainer: skssmd <skssmd78475@gmail.com>
description: Browser API for AI agents, over HTTP
vendor: skssmd
homepage: https://github.com/skssmd/Ai-Browser-Toolkit
license: Apache-2.0

# Chrome is required at runtime but is not in Debian, and Edge counts too.
recommends:
  - google-chrome-stable

contents:
  - src: ./payload/
    dst: /opt/aibrowsertoolkit
  - src: /opt/aibrowsertoolkit/bin/abt
    dst: /usr/bin/abt
    type: symlink

scripts:
  postinstall: ./packaging/postinstall.sh
  preremove: ./packaging/preremove.sh
```

- [ ] **Step 2: Write the two maintainer scripts**

`packaging/postinstall.sh`:

```sh
#!/bin/sh
cat <<'EOF'
AI Browser Toolkit installed.

Needs Google Chrome or Microsoft Edge; no browser is bundled.

To start the server at logon:
    abt autostart install --browser chrome
EOF
```

`packaging/preremove.sh`:

```sh
#!/bin/sh
# Leave no systemd user unit pointing at files that are about to vanish.
abt autostart uninstall >/dev/null 2>&1 || true
exit 0
```

Both must be committed executable: `git update-index --chmod=+x packaging/postinstall.sh packaging/preremove.sh`.

- [ ] **Step 3: Add the `fury` job**

```yaml
  fury:
    needs: [wheel, release]
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: bundle-linux-*
          path: dl
      - name: Install nfpm
        env:
          # Pinned on purpose: a release pipeline that silently picks up a new
          # packaging tool is one that breaks on a day you changed nothing.
          NFPM_VERSION: "2.41.3"
        run: |
          curl -fsSL -o nfpm.tar.gz \
            "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/nfpm_${NFPM_VERSION}_Linux_x86_64.tar.gz"
          tar xf nfpm.tar.gz nfpm && sudo mv nfpm /usr/local/bin/
          nfpm --version
      - name: Build and push every package
        env:
          PKG_VERSION: ${{ needs.wheel.outputs.version }}
          FURY_TOKEN: ${{ secrets.FURY_TOKEN }}
        run: |
          set -eu
          for pair in "x86_64:amd64" "aarch64:arm64"; do
            target="${pair%%:*}"; PKG_ARCH="${pair##*:}"
            export PKG_ARCH
            rm -rf payload && mkdir payload
            tar xzf dl/bundle-linux-$target/*.tar.gz -C payload --strip-components=1
            for fmt in deb rpm apk; do
              nfpm pkg --config packaging/nfpm.yaml --packager "$fmt" --target out/
            done
          done
          for pkg in out/*; do
            echo "pushing $pkg"
            curl -fsS -F package=@"$pkg" "https://$FURY_TOKEN@push.fury.io/skssmd/"
          done
```

- [ ] **Step 4: Verify in a container**

```bash
docker run --rm -it debian:bookworm bash -c '
  apt-get update && apt-get install -y curl gnupg
  echo "deb [trusted=yes] https://apt.fury.io/skssmd/ /" > /etc/apt/sources.list.d/fury.list
  apt-get update && apt-get install -y aibrowsertoolkit
  abt --version
'
```

Expected: installs, prints the postinstall hint, and `abt --version` works.

- [ ] **Step 5: Extend `docs/packaging.md`**

Append:

```markdown
## Channels and what feeds them

| Channel | Artifact | Repository |
|---|---|---|
| PyPI | wheel + sdist | pypi.org/project/aibrowsertoolkit |
| Standalone / winget | Inno `.exe` | GitHub release / microsoft/winget-pkgs |
| Scoop | Windows zip | the-graft-project/scoop-bucket |
| Homebrew | macOS tarballs | the-graft-project/homebrew-tap |
| AUR | Linux tarballs | aibrowsertoolkit-bin |
| apt / dnf / apk | Linux tarballs | apt.fury.io/skssmd |

The tap and the winget fork are shared with Graft. Every push into them
rebases and retries, because a simultaneous Graft release would otherwise lose
this one to a non-fast-forward rejection.
```

- [ ] **Step 6: Commit**

```bash
git add packaging/nfpm.yaml packaging/postinstall.sh packaging/preremove.sh \
        .github/workflows/release.yml docs/packaging.md
git commit -m "Push deb, rpm and apk to Gemfury"
```

---

## Deferred: Snap, Nix, Chocolatey

Not tasks in this plan, recorded so the reasons are not rediscovered. Snap needs store credentials and passes a review — Graft's `snapcrafts:` block is commented out. Nix means a pull request into `nixpkgs` reviewed by strangers on their schedule. Chocolatey has a moderation queue and in practice expects an Authenticode-signed installer, which the free-tier signing decision does not provide. All three are wanted; none belongs in a first release that has not shipped once cleanly.
