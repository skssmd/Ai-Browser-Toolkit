"""Managing sessions, profiles and tab ownership over HTTP. No browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def registry(tmp_path):
    profiles = ProfileRegistry(root=tmp_path / "profiles")
    return SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        profiles,
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        log_root=tmp_path / "logs",
        operator_token="op",
    )


@pytest.fixture
def client(registry):
    with TestClient(create_app(registry=registry)) as c:
        yield c


def test_session_lifecycle(client):
    client.post("/profiles", json={"name": "work"})
    made = client.post("/sessions", json={"name": "a", "profile": "work"}).json()
    assert made["ok"] and made["result"]["profile"] == "work"
    names = [s["name"] for s in client.get("/sessions").json()["result"]]
    assert names == ["a", "default"]
    changed = client.patch("/sessions/a", json={"profile": "default"}).json()
    assert changed["result"]["profile"] == "default"
    assert client.delete("/sessions/a").json()["ok"] is True


def test_sealed_is_created_with_a_token_and_guarded(client):
    token = client.post("/sessions", json={"name": "s", "sealed": True}).json()["result"]["token"]
    assert client.delete("/sessions/s").json()["error"]["type"] == "session_sealed"
    assert client.delete("/sessions/s", headers={"X-ABT-Token": token}).json()["ok"] is True


def test_profiles_over_http(client):
    assert client.post("/profiles", json={"name": "work"}).json()["ok"] is True
    assert client.patch("/profiles/work", json={"headed": True}).json()["result"]["headed"] is True
    client.post("/sessions", json={"name": "a", "profile": "work"})
    assert client.delete("/profiles/work").json()["error"]["type"] == "profile_in_use"


def test_bad_names_are_400(client):
    response = client.post("/sessions", json={"name": "../x"})
    assert response.status_code == 400


def test_tab_owner_needs_the_operator(client):
    body = {"profile": "default", "tab_id": "tab_0", "session": None}
    assert client.post("/tabs/owner", json=body).json()["error"]["type"] == "session_sealed"
    missing = client.post("/tabs/owner", json=body, headers={"X-ABT-Token": "op"}).json()
    assert missing["error"]["type"] == "tab_not_found"


def test_logs_are_per_session(client):
    client.post("/sessions", json={"name": "a"})
    client.post("/command-list", json={"op": "status"}, headers={"X-ABT-Session": "a"})
    mine = client.get("/logs", params={"session": "a"}).json()["result"]
    assert len(mine["sessions"]) == 1
    assert client.get("/logs").json()["result"]["sessions"] == []


def test_the_legacy_app_has_no_profiles(tmp_path):
    with TestClient(create_app(BrowserSession(profile=tmp_path, headless=True))) as c:
        response = c.get("/profiles")
        assert response.json()["error"]["type"] == "invalid_op"
