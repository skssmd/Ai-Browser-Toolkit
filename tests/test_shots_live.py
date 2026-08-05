"""Capturing frames from a real browser, through the real HTTP surface.

The storage rules are unit-tested in test_shots.py. What can only be proved
against a live page is that the capture produces a real image, that the
highlight box lands on the element the command acted on, and that a frame comes
back over HTTP the way the viewer fetches it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.recorder import SessionRecorder
from abt.server import create_app


@pytest.fixture
def shot_client(clean_session, tmp_path):
    recorder = SessionRecorder(tmp_path / "logs", session_id="20250101-120000")
    with TestClient(create_app(clean_session, recorder=recorder)) as client:
        yield client, recorder


def events_of(client, recorder):
    return client.get(f"/logs/{recorder.session_id}").json()["result"]["events"]


def test_a_navigation_is_photographed(shot_client, base_url):
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})

    event = events_of(client, recorder)[0]
    assert event["shot"] == "00001.jpg"
    frame = (recorder.shots_dir / event["shot"]).read_bytes()
    assert frame[:2] == b"\xff\xd8"  # a real jpeg, not an empty file
    assert len(frame) > 500


def test_a_read_is_not_photographed_but_a_click_is(shot_client, base_url):
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    client.post("/command", json={"op": "find", "css": "#name"})
    client.post("/command", json={"op": "click", "css": "#name"})

    by_op = {e["op"]: e for e in events_of(client, recorder)}
    assert "shot" in by_op["goto"]
    assert "shot" not in by_op["find"]
    assert "shot" in by_op["click"]


def test_a_failure_is_photographed_even_though_it_is_a_read(shot_client, base_url):
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    client.post("/command", json={"op": "find", "css": "#ghost", "timeout": 0.2})

    failed = [e for e in events_of(client, recorder) if not e["ok"]]
    assert failed and "shot" in failed[0]


def test_the_box_marks_where_the_click_landed(shot_client, base_url):
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    client.post("/command", json={"op": "click", "css": "#name"})

    box = events_of(client, recorder)[-1]["shot_box"]
    assert 0 <= box["x"] < 1 and 0 <= box["y"] < 1
    assert 0 < box["w"] <= 1 and 0 < box["h"] <= 1


def test_a_navigation_carries_no_box(shot_client, base_url):
    """Nothing was targeted, so there is nothing honest to draw on the frame."""
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    assert "shot_box" not in events_of(client, recorder)[0]


def test_a_frame_is_served_over_http(shot_client, base_url):
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    name = events_of(client, recorder)[0]["shot"]

    response = client.get(f"/logs/{recorder.session_id}/shots/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"


def test_a_frame_name_we_did_not_write_is_a_404(shot_client):
    client, recorder = shot_client
    assert client.get(f"/logs/{recorder.session_id}/shots/meta.json").status_code == 404
    assert client.get(f"/logs/{recorder.session_id}/shots/00009.jpg").status_code == 404


def test_shots_can_be_turned_off(clean_session, tmp_path, base_url):
    recorder = SessionRecorder(tmp_path / "logs", session_id="20250101-130000")
    with TestClient(create_app(clean_session, recorder=recorder, shots=False)) as client:
        client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
        event = events_of(client, recorder)[0]

    assert "shot" not in event
    assert not recorder.shots_dir.exists()


def test_the_session_index_counts_frames(shot_client, base_url):
    client, recorder = shot_client
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    client.post("/command", json={"op": "find", "css": "#name"})

    listed = client.get("/logs").json()["result"]["sessions"]
    row = next(s for s in listed if s["session_id"] == recorder.session_id)
    assert row["events"] == 2
    assert row["shots"] == 1
