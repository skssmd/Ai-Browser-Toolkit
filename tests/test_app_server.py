"""The desktop app's server side: settings, chats, and the chat socket.

The model is replaced by a scripted fake (`agent.complete` is patched), so the
socket test drives a real tool call through the real session path without a
network. No browser: `status` answers without one.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from abt import agent, appstate
from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore

OP = {"X-ABT-Token": "op"}


@pytest.fixture
def registry(tmp_path):
    return SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        operator_token="op",
    )


@pytest.fixture
def client(registry):
    with TestClient(create_app(registry=registry)) as c:
        yield c


def test_the_page_is_served_and_uses_the_routes_it_should(client):
    html = client.get("/app").text
    for route in ("/app/chat", "/screencast", "/app/settings", "/app/models/free", "/app/chats"):
        assert route in html


def test_settings_need_the_operator_and_never_return_the_key(client, tmp_path):
    assert client.get("/app/settings").json()["error"]["type"] == "session_sealed"
    body = client.put(
        "/app/settings",
        json={"api_key": "sk-secret-12345678", "models": ["a/b:free"], "endpoint": "https://x.test/v1"},
        headers=OP,
    ).json()["result"]
    assert body["has_key"] is True and "secret" not in json.dumps(body)
    assert body["key_hint"] == "…5678"
    saved = json.loads((tmp_path / "sessions" / "app.json").read_text(encoding="utf-8"))
    assert saved["api_key"] == "sk-secret-12345678"


def test_bad_settings_are_refused(client):
    r = client.put("/app/settings", json={"endpoint": "file:///x"}, headers=OP)
    assert r.status_code == 400


def test_free_models_are_free_and_take_tools():
    body = {"data": [
        {"id": "good:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"], "context_length": 8},
        {"id": "paid", "pricing": {"prompt": "0.001", "completion": "0"}, "supported_parameters": ["tools"]},
        {"id": "notools:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": []},
    ]}
    found = appstate.free_models("https://x.test/v1", get=lambda url, headers: body)
    assert [m["id"] for m in found] == ["good:free"]


def test_chats_belong_to_their_session(client, registry):
    registry.create("s", sealed=True)
    token = registry.store.directory.joinpath("s.token").read_text(encoding="utf-8")
    mine = {"X-ABT-Session": "s", "X-ABT-Token": token}
    made = client.post("/app/chats", json={}, headers=mine).json()["result"]
    assert [c["id"] for c in client.get("/app/chats", headers=mine).json()["result"]] == [made["id"]]
    assert client.get("/app/chats").json()["result"] == []
    assert client.get("/app/chats", headers={"X-ABT-Session": "s"}).json()["error"]["type"] == "session_sealed"


def test_a_web_page_cannot_open_the_chat(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/app/chat", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_the_chat_drives_a_real_tool_call(client, registry, monkeypatch):
    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
    replies = iter([
        {"content": "", "tool_calls": [{
            "id": "t1", "type": "function",
            "function": {"name": "command_list", "arguments": json.dumps({"commands": [{"op": "status"}]})},
        }]},
        {"content": "No browser is running yet."},
    ])
    monkeypatch.setattr(agent, "complete", lambda endpoint, key, model, messages, tools: next(replies))
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat?session=default") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "is the browser up?"})
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] == "done":
                break
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "assistant", "done"]
    result = json.loads(events[1]["text"])
    assert result["ok"] is True and result["results"][0]["result"]["running"] is False
    saved = client.get(f"/app/chats/{chat['id']}").json()["result"]
    assert saved["title"] == "is the browser up?"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert saved["model"] == "fake/model"


def test_the_chat_cannot_shut_the_server_down(client, monkeypatch):
    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
    replies = iter([
        {"content": "", "tool_calls": [{
            "id": "t1", "type": "function",
            "function": {"name": "command_list", "arguments": json.dumps({"commands": [{"op": "shutdown"}]})},
        }]},
        {"content": "ok"},
    ])
    monkeypatch.setattr(agent, "complete", lambda *a: next(replies))
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "stop everything"})
        events = []
        while (event := ws.receive_json())["type"] != "done":
            events.append(event)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["error"] is True and "shutdown" in result["text"]
    assert client.get("/health").json()["ok"] is True
