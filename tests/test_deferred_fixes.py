"""The review's deferred findings, each pinned. No browser."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abt import cli, paths
from abt.browser import BrowserSession
from abt.profiles import DEFAULT, ProfileRegistry
from abt.server import _unmapped, create_app
from abt.sessions import SessionRegistry, SessionStore


def test_profiles_do_not_publish_the_debugging_port(tmp_path):
    reg = ProfileRegistry(root=tmp_path / "profiles")
    assert "port" not in reg.describe(DEFAULT)


def test_the_operator_token_survives_a_restart(tmp_path, monkeypatch):
    """An open app keeps working when the server comes back, and two servers
    started from one folder no longer overwrite each other's token."""
    monkeypatch.setattr(paths, "profile_root", lambda *a, **k: tmp_path / "profiles")
    monkeypatch.setattr(paths, "sessions_dir", lambda *a, **k: tmp_path / "sessions")
    monkeypatch.setattr(paths, "files_home", lambda *a, **k: tmp_path / "files")
    build = lambda: cli._build_registry(  # noqa: E731
        "chrome", tmp_path / "profiles" / "default", True, tmp_path / "logs", True, 10.0, 2, 30.0, {}
    )
    first = build().operator_token
    assert build().operator_token == first
    assert (tmp_path / "sessions" / "operator.token").read_text(encoding="utf-8") == first


def test_a_session_with_no_tab_is_told_to_open_one_not_to_restart():
    class NoSuchWindowException(Exception):
        pass

    error = _unmapped(NoSuchWindowException("no active page"))
    assert error.type == "tab_not_found"
    assert "tab_new" in error.hint


def test_a_tab_cannot_be_given_to_a_session_on_another_profile(tmp_path):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        operator_token="op",
    )
    registry.profiles.create("other")
    registry.create("elsewhere", profile="other")
    registry.profiles.tabs(DEFAULT).label("T1")  # a tab on the default profile
    with TestClient(create_app(registry=registry)) as client:
        body = {"profile": DEFAULT, "tab_id": "tab_0", "session": "elsewhere"}
        out = client.post("/tabs/owner", json=body, headers={"X-ABT-Token": "op"})
        assert out.status_code == 400 and out.json()["error"]["type"] == "invalid_op"


# -- browser_dead is for a browser that is gone ---------------------------------------


def test_only_a_browser_that_is_gone_is_reported_as_dead():
    """The app answers browser_dead by restarting the browser, and an agent does
    the same: so every wrong browser_dead costs the tabs of a healthy one. Seen
    live, five times in a row, for a colour input's "Malformed value"."""
    from abt import engine

    dead = [
        engine.DeadSession("the browser connection stopped answering"),
        RuntimeError("cannot schedule new futures after shutdown"),
        engine.EngineError("Page.title: Target page, context or browser has been closed"),
        ConnectionResetError("reset"),
    ]
    for exc in dead:
        assert _unmapped(exc).type == "browser_dead", exc


def test_a_refusal_is_not_a_dead_browser():
    from abt import engine

    expected = {
        "not_interactable": [engine.EngineError("fill: Malformed value"),
                             engine.InvalidElementState("readonly"), engine.UnexpectedAlert("alert open")],
        "stale_ref": [engine.StaleElement("detached"),
                      engine.EngineError("Execution context was destroyed, most likely because of a navigation")],
        "element_not_found": [engine.NoSuchElement("none"), engine.NoSuchFrame("none")],
        "js_error": [engine.ScriptError("boom")],
    }
    for kind, errors in expected.items():
        for exc in errors:
            assert _unmapped(exc).type == kind, (kind, exc)


def test_a_fault_in_the_toolkit_is_not_a_dead_browser(capsys):
    """A KeyError inside an op used to read "browser is dead; restart it"."""
    for exc in (KeyError("missing"), AttributeError("nope"), ValueError("bad"), TypeError("x")):
        error = _unmapped(exc)
        assert error.type == "internal_error"
        assert "browser" in error.hint.lower() and "still up" in error.hint.lower()
    assert "KeyError" in capsys.readouterr().err  # the traceback is kept for the log


def test_playwrights_closed_target_error_is_a_dead_session_at_the_source():
    from abt import engine
    from abt.pwdriver import _as_engine_error

    class TargetClosedError(Exception):
        pass

    for message in ("Page.title: Target page, context or browser has been closed",
                    "Target closed", "Browser has been closed", "Connection closed while reading"):
        assert isinstance(_as_engine_error(Exception(message)), engine.DeadSession), message
    assert isinstance(_as_engine_error(TargetClosedError("anything")), engine.DeadSession)
    assert not isinstance(_as_engine_error(Exception("fill: Malformed value")), engine.DeadSession)


def test_a_session_with_no_current_tab_is_told_so_not_that_its_browser_died(tmp_path):
    from abt.browser import Attach, BrowserSession
    from abt.errors import OpError
    from abt.tabs import TabGate, TabRegistry
    from types import SimpleNamespace

    browser = BrowserSession(profile=tmp_path, headless=True, attach=Attach(
        connect=lambda: "", disconnect=lambda: None, list_targets=lambda: [],
        gate=TabGate(TabRegistry("default"), "a")))
    browser._driver = SimpleNamespace(current_window_handle="h-unknown", window_handles=["h-other"])
    try:
        browser.active_tab
    except OpError as exc:
        assert exc.type == "tab_not_found" and "tab_new" in exc.hint
    else:
        raise AssertionError("expected an error")
