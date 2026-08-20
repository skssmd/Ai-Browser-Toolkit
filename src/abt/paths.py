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


def _resolved(
    kind: str | None, home: Path | None, env: Mapping[str, str] | None
) -> tuple[str, Path, Mapping[str, str]]:
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
