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
