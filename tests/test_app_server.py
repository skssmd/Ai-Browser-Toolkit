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
    for route in ("/app/chat", "/screencast", "/app/settings", "/app/models/free", "/app/chats", "/app/overview"):
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
    monkeypatch.setattr(agent, "complete", lambda endpoint, key, model, messages, tools, **kw: next(replies))
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
    assert kinds == ["user", "tool_call", "tool_result", "assistant", "done"]
    assert all(e["chat_id"] == chat["id"] for e in events)
    result = json.loads(events[2]["text"])
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
    monkeypatch.setattr(agent, "complete", lambda *a, **kw: next(replies))
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "stop everything"})
        events = []
        while (event := ws.receive_json())["type"] != "done":
            events.append(event)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["error"] is True and "shutdown" in result["text"]
    assert client.get("/health").json()["ok"] is True


def test_replies_keep_running_when_the_page_leaves_and_run_side_by_side(client, registry, monkeypatch):
    """Switching profile or session in the app must not stop anything: each
    chat replies on the server, and a page that comes back sees what it missed."""
    import threading
    import time

    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
    registry.profiles.create("other")
    registry.create("b", profile="other")
    gate = threading.Event()
    started = []

    def complete(endpoint, key, model, messages, tools, **kw):
        started.append(model)
        gate.wait(10)  # both replies are in flight at once until released
        return {"content": "finished"}

    monkeypatch.setattr(agent, "complete", complete)
    first = client.post("/app/chats", json={}).json()["result"]
    second = client.post("/app/chats", json={}, headers={"X-ABT-Session": "b"}).json()["result"]
    with client.websocket_connect("/app/chat?session=default") as ws:
        ws.send_json({"type": "send", "chat_id": first["id"], "text": "one"})
        assert ws.receive_json()["type"] == "user"
    # The page left mid-reply. The other session's chat starts regardless.
    with client.websocket_connect("/app/chat?session=b") as ws:
        ws.send_json({"type": "send", "chat_id": second["id"], "text": "two"})
        assert ws.receive_json()["type"] == "user"
    deadline = time.monotonic() + 5
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(started) == 2, "the two chats did not run side by side"
    assert set(client.get("/app/runs").json()["result"]) == {first["id"]}
    # Back on the first session: what was missed is replayed, then the rest.
    with client.websocket_connect("/app/chat?session=default") as ws:
        assert ws.receive_json() == {"type": "resume", "chat_id": first["id"]}
        assert ws.receive_json()["type"] == "user"
        gate.set()
        kinds = []
        while (event := ws.receive_json())["type"] != "done":
            kinds.append(event["type"])
        assert kinds == ["assistant"]
    saved = client.get(f"/app/chats/{first['id']}").json()["result"]
    assert saved["messages"][-1]["content"] == "finished"


def test_the_reply_streams_to_the_page(client, monkeypatch):
    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)

    def complete(endpoint, key, model, messages, tools, on_text=None):
        for piece in ("Wor", "king", " on it."):
            on_text(piece)
        return {"content": "Working on it."}

    monkeypatch.setattr(agent, "complete", complete)
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "hi"})
        events = []
        while (event := ws.receive_json())["type"] != "done":
            events.append(event)
    kinds = [e["type"] for e in events]
    assert kinds == ["user", "delta", "delta", "delta", "assistant"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Working on it."


def test_the_chat_list_says_which_chats_are_empty(client, monkeypatch):
    """The app opens the latest chat with something in it, not an empty one."""
    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
    monkeypatch.setattr(agent, "complete", lambda *a, **kw: {"content": "hi"})
    used = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": used["id"], "text": "hello"})
        while ws.receive_json()["type"] != "done":
            pass
    client.post("/app/chats", json={})  # an empty one, newer
    rows = {r["id"]: r["messages"] for r in client.get("/app/chats").json()["result"]}
    assert rows[used["id"]] == 2
    assert sorted(rows.values()) == [0, 2]


def test_a_chat_error_is_saved_with_the_chat(client, monkeypatch):
    """It used to exist only on screen, and was gone after a reload."""
    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)

    def complete(*a, **kw):
        raise agent.ModelError("fake/model: HTTP 429: rate limited", retry_elsewhere=False)

    monkeypatch.setattr(agent, "complete", complete)
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "go"})
        while ws.receive_json()["type"] != "done":
            pass
    saved = client.get(f"/app/chats/{chat['id']}").json()["result"]
    assert saved["messages"][-1] == {"role": "error", "content": "fake/model: HTTP 429: rate limited"}


def test_a_habitual_browser_start_is_answered_not_refused(client, monkeypatch):
    client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
    replies = iter([
        {"content": "", "tool_calls": [{"id": "t1", "type": "function",
            "function": {"name": "browser_session", "arguments": json.dumps({"action": "start"})}}]},
        {"content": "ok"},
    ])
    monkeypatch.setattr(agent, "complete", lambda *a, **kw: next(replies))
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "go"})
        events = []
        while (event := ws.receive_json())["type"] != "done":
            events.append(event)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["error"] is False and "manages the browser" in result["text"]


def test_the_overview_lists_every_chat_for_the_operator_only(client, registry):
    """Each chat is its own session; the app's chat list spans all of them."""
    registry.create("chat-a", sealed=True)
    token = registry.store.directory.joinpath("chat-a.token").read_text(encoding="utf-8")
    mine = {"X-ABT-Session": "chat-a", "X-ABT-Token": token}
    sealed = client.post("/app/chats", json={}, headers=mine).json()["result"]
    plain = client.post("/app/chats", json={}).json()["result"]

    assert client.get("/app/overview").json()["error"]["type"] == "session_sealed"
    rows = client.get("/app/overview", headers=OP).json()["result"]
    by_chat = {r["chat_id"]: r for r in rows}
    assert by_chat[sealed["id"]]["session"] == "chat-a" and by_chat[sealed["id"]]["sealed"] is True
    assert by_chat[plain["id"]]["session"] == "default"
    assert all(r["running"] is False and r["messages"] == 0 for r in rows)


def test_closing_the_app_closes_its_browsers_but_not_the_server(client, registry, monkeypatch):
    stopped = []
    monkeypatch.setattr(registry.profiles, "sweep", lambda: stopped.append(True) or [])
    assert client.post("/app/quit").json()["error"]["type"] == "session_sealed"
    assert client.post("/app/quit", headers=OP).json()["ok"] is True
    assert stopped == [True]
    assert client.get("/health").status_code == 200


def test_force_close_is_for_the_operator_only(client, registry, monkeypatch):
    monkeypatch.setattr(registry.profiles, "force_close", lambda name: {"profile": name, "closed": 1})
    assert client.post("/profiles/default/force-close").json()["error"]["type"] == "session_sealed"
    assert client.post("/profiles/default/force-close", headers=OP).json()["result"] == {
        "profile": "default", "closed": 1,
    }
