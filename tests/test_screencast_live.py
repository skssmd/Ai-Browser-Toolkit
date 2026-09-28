"""A real frame arrives and a real click lands."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore

PAGE = (
    "data:text/html,<button id=b style='position:fixed;left:0;top:0;"
    "width:200px;height:200px' onclick='document.title=\"hit\"'>x</button>"
)


@pytest.fixture
def setup(tmp_path, budgets):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        operator_token="op",
    )
    with TestClient(create_app(registry=registry)) as client:
        yield registry, client
    registry.close_all()


def test_frames_stream_and_clicks_land(setup):
    registry, client = setup
    client.post("/command-list", json=[{"op": "browser_start"}, {"op": "goto", "url": PAGE}])
    tab = registry.get(None).browser.active_tab
    with client.websocket_connect(f"/screencast?tab={tab}") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "frame"
        assert frame["data"].startswith("/9j/")  # JPEG, base64
        for event in ("mousePressed", "mouseReleased"):
            ws.send_json({"type": "mouse", "event": event, "x": 50, "y": 50})
        ws.send_json({"type": "text", "text": ""})
    # The click is dispatched asynchronously in Chrome; give it a moment.
    title = None
    for _ in range(30):
        body = client.post(
            "/command-list", json={"op": "run_js", "script": "return document.title"}
        ).json()
        title = body["result"]["value"]
        if title == "hit":
            break
        time.sleep(0.1)
    assert title == "hit"
