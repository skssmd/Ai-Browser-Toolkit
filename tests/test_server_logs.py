"""The log endpoints, driven through the real HTTP surface with a live browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.recorder import SessionRecorder
from abt.server import create_app


@pytest.fixture
def logged(clean_session, tmp_path):
    recorder = SessionRecorder(tmp_path / "logs", session_id="20250101-120000")
    with TestClient(create_app(clean_session, recorder=recorder)) as client:
        yield client, recorder


def test_commands_are_recorded(logged, base_url):
    client, recorder = logged
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    client.post("/command", json={"op": "find", "css": "#name"})

    events = client.get(f"/logs/{recorder.session_id}").json()["result"]["events"]
    assert [e["op"] for e in events] == ["goto", "find"]
    assert all(e["ok"] for e in events)
    assert events[0]["request"]["url"].endswith("/form.html")
    assert events[0]["duration_ms"] > 0


def test_failures_are_recorded_with_their_type(logged):
    client, recorder = logged
    client.post("/command", json={"op": "click", "css": "#ghost"})
    event = client.get(f"/logs/{recorder.session_id}").json()["result"]["events"][0]
    assert event["ok"] is False
    assert event["error_type"] == "element_not_found"


def test_each_event_carries_its_tab_and_site(logged, base_url):
    client, recorder = logged
    client.post("/command", json={"op": "goto", "url": f"{base_url}/cards.html"})
    event = client.get(f"/logs/{recorder.session_id}").json()["result"]["events"][0]
    assert event["tab_id"].startswith("tab_")
    assert event["site"] == base_url.replace("http://", "")


def test_batch_records_every_command(logged, base_url):
    client, recorder = logged
    client.post("/commands", json=[
        {"op": "goto", "url": f"{base_url}/form.html"},
        {"op": "input", "css": "#name", "value": "x"},
        {"op": "click", "css": "#go"},
    ])
    events = client.get(f"/logs/{recorder.session_id}").json()["result"]["events"]
    assert [e["op"] for e in events] == ["goto", "input", "click"]


def test_filter_by_op(logged, base_url):
    client, recorder = logged
    client.post("/commands", json=[
        {"op": "goto", "url": f"{base_url}/cards.html"},
        {"op": "find", "css": ".card"},
        {"op": "find", "css": "#p1"},
    ])
    result = client.get(f"/logs/{recorder.session_id}?op=find").json()["result"]
    assert result["count"] == 2


def test_filter_errors_only(logged):
    client, recorder = logged
    client.post("/command", json={"op": "current_url"})
    client.post("/command", json={"op": "click", "css": "#ghost"})
    result = client.get(f"/logs/{recorder.session_id}?errors_only=true").json()["result"]
    assert result["count"] == 1
    assert result["events"][0]["error_type"] == "element_not_found"


def test_filter_by_site_excludes_others(logged, base_url):
    client, recorder = logged
    client.post("/command", json={"op": "goto", "url": f"{base_url}/cards.html"})
    host = base_url.replace("http://", "")
    assert client.get(f"/logs/{recorder.session_id}?site={host}").json()["result"]["count"] >= 1
    assert client.get(f"/logs/{recorder.session_id}?site=nope.test").json()["result"]["count"] == 0


def test_sessions_index_lists_the_live_session(logged):
    client, recorder = logged
    client.post("/command", json={"op": "current_url"})
    body = client.get("/logs").json()["result"]
    assert body["recording"] is True
    assert body["current"] == recorder.session_id
    assert body["sessions"][0]["session_id"] == recorder.session_id


def test_sites_index_endpoint(logged, base_url):
    client, _ = logged
    client.post("/command", json={"op": "goto", "url": f"{base_url}/cards.html"})
    rows = client.get("/logs/sites").json()["result"]
    assert any(r["site"] == base_url.replace("http://", "") for r in rows)


def test_unknown_session_is_404(logged):
    client, _ = logged
    assert client.get("/logs/19990101-000000").status_code == 404


def test_viewer_page_is_served(logged):
    client, _ = logged
    response = client.get("/viewer")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "abt session logs" in response.text


def test_logging_off_still_serves_the_endpoints(clean_session):
    with TestClient(create_app(clean_session)) as client:
        client.post("/command", json={"op": "current_url"})
        body = client.get("/logs").json()["result"]
        assert body["recording"] is False
        assert body["sessions"] == []
        assert client.get("/logs/sites").json()["result"] == []


def test_a_broken_recorder_never_fails_a_command(clean_session, tmp_path):
    class Broken(SessionRecorder):
        def record(self, *args, **kwargs):
            raise RuntimeError("disk full")

    recorder = Broken(tmp_path / "logs")
    with TestClient(create_app(clean_session, recorder=recorder)) as client:
        body = client.post("/command", json={"op": "current_url"}).json()
        assert body["ok"] is True
