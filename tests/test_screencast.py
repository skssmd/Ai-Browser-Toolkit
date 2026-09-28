"""Screencast input translation and access rules. No browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.screencast import to_cdp
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


def test_a_click_is_a_mouse_event():
    method, params = to_cdp({"type": "mouse", "event": "mousePressed", "x": 5, "y": 6})
    assert method == "Input.dispatchMouseEvent"
    assert params == {
        "type": "mousePressed", "x": 5.0, "y": 6.0, "button": "left",
        "clickCount": 1, "modifiers": 0,
    }


def test_a_wheel_carries_deltas():
    _, params = to_cdp({"type": "mouse", "event": "mouseWheel", "x": 1, "y": 1, "deltaY": 120})
    assert params["deltaY"] == 120.0 and params["deltaX"] == 0.0


def test_keys_and_text():
    assert to_cdp({"type": "key", "event": "keyDown", "key": "Enter"})[0] == "Input.dispatchKeyEvent"
    assert to_cdp({"type": "text", "text": "hi"}) == ("Input.insertText", {"text": "hi"})


@pytest.mark.parametrize("bad", [
    {}, {"type": "mouse", "event": "explode", "x": 1, "y": 1},
    {"type": "mouse", "event": "mouseMoved"}, {"type": "key", "event": "nope"},
    {"type": "eval", "expression": "1"},
])
def test_anything_else_is_dropped(bad):
    assert to_cdp(bad) is None


@pytest.fixture
def client(tmp_path):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        operator_token="op",
    )
    registry.create("s", sealed=True)
    with TestClient(create_app(registry=registry)) as c:
        yield c


def test_a_sealed_sessions_tabs_need_its_token(client):
    with client.websocket_connect("/screencast?tab=tab_0&session=s") as ws:
        assert ws.receive_json()["error"]["type"] == "session_sealed"


def test_an_unknown_tab_is_refused(client):
    with client.websocket_connect("/screencast?tab=tab_9&token=op") as ws:
        assert ws.receive_json()["error"]["type"] == "tab_not_found"
