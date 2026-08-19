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

    class StubDriver:
        def implicitly_wait(self, _seconds):
            return None

    def fake_launch(config):
        captured["config"] = config
        return StubDriver()

    monkeypatch.setattr(session, "_launch_driver", fake_launch)
    monkeypatch.setattr(session, "_verify_session", lambda: None)
    monkeypatch.setattr(session, "_install_console_capture", lambda: None)
    monkeypatch.setattr(session, "_sync_tabs", lambda: None)
    monkeypatch.setattr(type(session), "active_tab", property(lambda self: "tab_0"))

    session.start()

    assert captured["config"].headless is session.defaults.headless
