"""The chat never asks anyone to press start: it brings the browser up, and
brings it back when it dies. Real Chrome; the model is a scripted fake."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from abt import agent
from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore

OP = {"X-ABT-Token": "op"}


@pytest.fixture
def setup(tmp_path, budgets):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        operator_token="op",
    )
    with TestClient(create_app(registry=registry)) as client:
        client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
        yield registry, client
    registry.close_all()


def ask(client, monkeypatch, commands):
    replies = iter([
        {"content": "", "tool_calls": [{
            "id": "t1", "type": "function",
            "function": {"name": "command_list", "arguments": json.dumps({"commands": commands})},
        }]},
        {"content": "done"},
    ])
    monkeypatch.setattr(agent, "complete", lambda *a: next(replies))
    chat = client.post("/app/chats", json={}).json()["result"]
    with client.websocket_connect("/app/chat") as ws:
        ws.send_json({"type": "send", "chat_id": chat["id"], "text": "go"})
        events = []
        while (event := ws.receive_json())["type"] != "done":
            events.append(event)
    return json.loads(next(e for e in events if e["type"] == "tool_result")["text"])


def test_a_chat_starts_the_browser_it_needs(setup, monkeypatch, base_url):
    registry, client = setup
    assert registry.get(None).browser.is_running is False
    result = ask(client, monkeypatch, [{"op": "goto", "url": f"{base_url}/form.html"}])
    assert result["ok"] is True, result
    assert registry.get(None).browser.is_running is True


def test_a_chat_brings_a_dead_browser_back(setup, monkeypatch, base_url):
    registry, client = setup
    ask(client, monkeypatch, [{"op": "goto", "url": f"{base_url}/form.html"}])
    registry.profiles.running("default").process.kill()
    registry.profiles.running("default")  # noticed dead
    result = ask(client, monkeypatch, [{"op": "goto", "url": f"{base_url}/cards.html"}])
    assert result["ok"] is True, result
