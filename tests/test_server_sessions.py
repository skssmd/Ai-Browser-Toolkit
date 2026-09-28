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
