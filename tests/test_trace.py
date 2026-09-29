"""The step trace: what is running now, and how long each finished step took."""

from __future__ import annotations

import json
import threading
import time

import pytest

from abt import trace


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    trace.configure(tmp_path / "trace")
    trace._recent.clear()
    trace._active.clear()
    yield tmp_path / "trace"
    trace.configure(None)


def written(folder):
    return [json.loads(line) for f in folder.glob("*.jsonl") for line in f.read_text(encoding="utf-8").splitlines()]


def test_a_running_step_shows_its_age_and_chain(fresh):
    release = threading.Event()

    def reply():
        with trace.span("chat.reply", "audit", session="s1"):
            with trace.span("tool", "command_list"):
                with trace.span("command", "goto", op="goto"):
                    release.wait(5)

    worker = threading.Thread(target=reply)
    worker.start()
    time.sleep(0.2)
    active = trace.active()
    innermost = [a for a in active if a["kind"] == "command"][0]
    assert innermost["chain"] == "chat.reply audit > tool command_list > command goto"
    assert innermost["age_s"] >= 0.1
    release.set()
    worker.join()
    assert trace.active() == []


def test_finished_steps_are_written_with_their_duration(fresh):
    with trace.span("command", "click", session="s1", op="click"):
        time.sleep(0.05)
    rows = written(fresh)
    assert rows[0]["kind"] == "command" and rows[0]["op"] == "click" and rows[0]["ok"] is True
    assert rows[0]["ms"] >= 40


def test_a_failure_is_recorded(fresh):
    with pytest.raises(ValueError):
        with trace.span("command", "goto"):
            raise ValueError("no such page")
    row = written(fresh)[0]
    assert row["ok"] is False and "no such page" in row["error"]


def test_quick_driver_calls_stay_out_of_the_file_but_slow_ones_are_kept(fresh, monkeypatch):
    with trace.span("driver", "title"):
        pass
    assert written(fresh) == []
    monkeypatch.setattr(trace, "QUIET_MIN_SECONDS", 0.01)
    with trace.span("driver", "get"):
        time.sleep(0.03)
    assert [r["name"] for r in written(fresh)] == ["get"]


def test_a_slow_step_is_printed(capsys, monkeypatch):
    monkeypatch.setattr(trace, "SLOW_SECONDS", 0.01)
    with trace.span("model", "some/model", session="s1"):
        time.sleep(0.03)
    assert "slow model some/model" in capsys.readouterr().err


def test_the_trace_route_is_for_the_operator_only(tmp_path):
    from fastapi.testclient import TestClient

    from abt.browser import BrowserSession
    from abt.profiles import ProfileRegistry
    from abt.server import create_app
    from abt.sessions import SessionRegistry, SessionStore

    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"), ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a), operator_token="op",
    )
    with TestClient(create_app(registry=registry)) as client:
        assert client.get("/debug/trace").json()["error"]["type"] == "session_sealed"
        client.post("/command-list", json={"op": "status"})
        body = client.get("/debug/trace", headers={"X-ABT-Token": "op"}).json()["result"]
    assert "active" in body
    assert any(r["kind"] == "command" and r["name"] == "status" for r in body["recent"])
