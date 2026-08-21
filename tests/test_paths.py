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
        '[project]\nname = "ai-browser-toolkit"\nversion = "0.1.0"\n',
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


def test_the_first_run_marker_lives_beside_the_logs(home, elsewhere):
    marker = paths.first_run_marker(kind="linux", home=home, env={}, cwd=elsewhere)
    logs = paths.default_log_dir(kind="linux", home=home, env={}, cwd=elsewhere)
    assert marker.parent == logs.parent


def test_a_checkout_has_no_first_run_hint(home, checkout):
    """A developer in the repo already knows; the hint is for someone who
    installed this from a package manager."""
    assert paths.first_run_marker(kind="linux", home=home, env={}, cwd=checkout) is None
