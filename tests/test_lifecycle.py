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


# --- profile release -------------------------------------------------------


def test_a_clean_profile_reads_as_unlocked(tmp_path):
    from abt.browser import _profile_locked

    assert _profile_locked(LaunchConfig(profile=tmp_path)) is False


def test_a_singleton_lock_reads_as_locked(tmp_path):
    from abt.browser import _profile_locked

    (tmp_path / "SingletonLock").write_text("host-1234")
    assert _profile_locked(LaunchConfig(profile=tmp_path)) is True


def test_waiting_returns_true_on_a_free_profile(session, tmp_path):
    assert (
        session._wait_for_profile_release(
            LaunchConfig(profile=tmp_path), timeout=0.5
        )
        is True
    )


def test_waiting_returns_true_as_soon_as_the_lock_goes_away(session, tmp_path):
    """It must poll, not check once -- the lock clears a moment after quit()."""
    import threading

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
    (tmp_path / "SingletonLock").write_text("host-1234")
    assert (
        session._wait_for_profile_release(
            LaunchConfig(profile=tmp_path), timeout=0.3
        )
        is False
    )


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


# --- ops -------------------------------------------------------------------


def test_the_new_ops_are_registered():
    from abt.schema import OP_NAMES

    for name in ("browser_start", "browser_stop", "browser_restart", "browser_status"):
        assert name in OP_NAMES


def test_the_lifecycle_ops_skip_the_health_check():
    """These are what you reach for *when* the browser has died.

    Gating them behind the health check means a server whose browser crashed
    can never recover or be shut down.
    """
    from abt.ops import NO_HEALTH_CHECK

    assert {
        "shutdown",
        "status",
        "browser_start",
        "browser_stop",
        "browser_restart",
        "browser_status",
    } <= NO_HEALTH_CHECK


def test_the_guidelines_ops_skip_it_too():
    """For a different reason: they read and write files and never touch the
    page. Gating them on a live browser would stop an agent looking up a
    site's playbook before starting a browser -- which is exactly when it is
    most worth reading."""
    from abt.ops import NO_HEALTH_CHECK

    assert {
        "guidelines_search",
        "guidelines_read",
        "guidelines_note",
    } <= NO_HEALTH_CHECK


def test_nothing_that_touches_the_page_skips_the_health_check():
    """The exemption is a hole in the fail-fast guarantee, so it must not grow
    by accident. Anything that drives the browser belongs behind it."""
    from abt.ops import NO_HEALTH_CHECK

    for op in ("click", "goto", "find", "get_text", "run_js", "screenshot"):
        assert op not in NO_HEALTH_CHECK


def test_browser_start_accepts_overrides():
    from abt.schema import parse_command

    cmd = parse_command({"op": "browser_start", "browser": "edge", "headless": True})
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
        "/command-list", json={"op": "goto", "url": "https://example.com"}
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


# --- CLI -------------------------------------------------------------------


def test_serve_has_an_opt_in_browser_launch_flag():
    """The old eager behaviour must stay reachable, and stay off by default."""
    import inspect

    from abt.cli import serve

    parameter = inspect.signature(serve).parameters["start_browser"]
    assert parameter.default.default is False
