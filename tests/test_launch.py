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


def test_launch_config_defaults_to_the_per_user_profile(monkeypatch, tmp_path):
    """A LaunchConfig built with no profile must not point at the cwd."""
    monkeypatch.chdir(tmp_path)
    from abt import paths

    assert LaunchConfig().profile == paths.default_profile().expanduser().resolve()


def test_an_explicit_profile_still_wins(tmp_path):
    assert LaunchConfig(profile=tmp_path / "mine").profile == (tmp_path / "mine").resolve()


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

    assert pwdriver.translate_launch_failure(
        RuntimeError("the disk is on fire"), "chrome"
    ) is None
