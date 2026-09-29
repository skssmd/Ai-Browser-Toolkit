"""Agentic chats: a lead proposes a plan, the person approves, helpers run and report.

The model is scripted (`agent.complete` is patched), so this drives the real
server path -- sessions, runs, tools, save_file, the finish notice -- without a
network or a browser.
"""

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


def call(name, args, id="c1"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def registry(tmp_path):
    return SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        operator_token="op",
        files_root=tmp_path / "files",
    )


def tool_results(messages):
    return [m.get("content", "") for m in messages if m.get("role") == "tool"]


def test_a_lead_plans_waits_for_the_person_then_runs_a_helper(registry, monkeypatch):
    registry.create("lead", settings={"agentic": True, "headless": True})
    seen_by_lead = []

    helper_script = iter([
        {"content": "", "tool_calls": [call("command_list", {"commands": [
            {"op": "save_file", "name": "seo-report.md", "content": "# SEO\n\nTitles are fine."}]})]},
        {"content": "SEO looks fine; details in seo-report.md."},
    ])
    lead_script = iter([
        # Turn 1: plan, try to jump the gun, then stop.
        {"content": "", "tool_calls": [call("propose_plan", {
            "summary": "One helper for SEO.",
            "workers": [{"role": "SEO expert", "task": "Check example.com's titles."}]})]},
        {"content": "", "tool_calls": [call("start_worker", {"role": "SEO expert", "task": "x"}, id="c2")]},
        {"content": "Here is my plan: one SEO expert. Shall I start?"},
        # Turn 2, after "go": start, wait, read, answer.
        {"content": "", "tool_calls": [call("start_worker", {
            "role": "SEO expert", "task": "Check example.com's titles."}, id="c3")]},
        {"content": "", "tool_calls": [call("wait_for_workers", {"timeout_s": 30}, id="c4")]},
        {"content": "", "tool_calls": [call("read_report", {"worker": "lead-w1"}, id="c5")]},
        {"content": "Combined: SEO is fine."},
    ])

    def complete(endpoint, key, model, messages, tools, **kw):
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        if "YOU ARE A HELPER AGENT" in system:
            return next(helper_script)
        seen_by_lead.append({"tools": [t["function"]["name"] for t in tools], "messages": messages})
        return next(lead_script)

    monkeypatch.setattr(agent, "complete", complete)
    with TestClient(create_app(registry=registry)) as client:
        client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
        chat = client.post("/app/chats", json={}, headers={"X-ABT-Session": "lead"}).json()["result"]
        with client.websocket_connect("/app/chat?session=lead") as ws:
            for text in ("audit example.com", "go"):
                ws.send_json({"type": "send", "chat_id": chat["id"], "text": text})
                while ws.receive_json()["type"] != "done":
                    pass

    # The lead was offered the helper tools; a plain session is not (checked below).
    assert "start_worker" in seen_by_lead[0]["tools"]
    turn1 = tool_results(seen_by_lead[2]["messages"])
    assert any("not answered the plan" in r for r in turn1)  # refused before approval
    # The helper: its own sealed session, its role, the lead's profile.
    helper = registry._records["lead-w1"]
    assert helper.sealed and helper.settings["role"] == "SEO expert" and helper.settings["lead"] == "lead"
    assert helper.settings["agentic"] is False and helper.settings["headless"] is True
    # Its report landed in the profile's downloads folder, and the lead read it.
    last = tool_results(seen_by_lead[-1]["messages"])
    assert any("Titles are fine." in r for r in last)
    downloads = registry.get("lead").browser.downloads_dir
    assert (downloads / "seo-report.md").read_text(encoding="utf-8").startswith("# SEO")


def test_a_plain_chat_gets_no_helper_tools(registry, monkeypatch):
    registry.create("solo", settings={"headless": True})
    offered = []

    def complete(endpoint, key, model, messages, tools, **kw):
        offered.append([t["function"]["name"] for t in tools])
        return {"content": "done"}

    monkeypatch.setattr(agent, "complete", complete)
    with TestClient(create_app(registry=registry)) as client:
        client.put("/app/settings", json={"models": ["fake/model"]}, headers=OP)
        chat = client.post("/app/chats", json={}, headers={"X-ABT-Session": "solo"}).json()["result"]
        with client.websocket_connect("/app/chat?session=solo") as ws:
            ws.send_json({"type": "send", "chat_id": chat["id"], "text": "hi"})
            while ws.receive_json()["type"] != "done":
                pass
    assert offered and not (set(offered[0]) & agent.ORCHESTRATION_NAMES)


def test_a_plan_is_capped_at_five_helpers():
    assert agent.MAX_WORKERS == 5
