"""One-tap connect: an agent harness gets its own session and an `abt` MCP entry.

Every test works in a throwaway home folder; nothing here touches real config.
"""

from __future__ import annotations

import json

import pytest

from abt import connect
from abt.errors import OpError

API = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def no_claude_cli(monkeypatch):
    """Tests edit files directly; the real `claude` command must never run."""
    monkeypatch.setattr(connect, "_claude_cli", lambda: None)


def rows_by_id(home):
    return {r["id"]: r for r in connect.status(home, which=lambda _: None)}


@pytest.mark.parametrize("harness,section", [
    ("cursor", "mcpServers"), ("gemini", "mcpServers"), ("windsurf", "mcpServers"),
    ("claude-code", "mcpServers"), ("vscode", "servers"), ("opencode", "mcp"),
])
def test_json_harnesses_connect_and_disconnect(tmp_path, monkeypatch, harness, section):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    path = connect.find(harness).config(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"theme": "dark", section: {"other": {"command": "x"}}}), encoding="utf-8")

    out = connect.connect(harness, "agent-1", API, home=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and "other" in data[section]  # the rest survives
    entry = data[section]["abt"]
    words = entry["command"] if isinstance(entry["command"], list) else [entry["command"], *entry["args"]]
    assert words[1:] == ["-m", "abt", "mcp", "--session", "agent-1", "--api", API]
    assert out["session"] == "agent-1"
    assert rows_by_id(tmp_path)[harness]["session"] == "agent-1"
    assert path.with_name(path.name + ".abt-backup").exists()

    connect.disconnect(harness, home=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "abt" not in data[section] and "other" in data[section]
    assert rows_by_id(tmp_path)[harness]["session"] is None


def test_codex_toml_keeps_other_tables(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    path.write_text('model = "o3"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
    connect.connect("codex", "codex", API, home=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert 'model = "o3"' in text and "[mcp_servers.other]" in text and "[mcp_servers.abt]" in text
    assert rows_by_id(tmp_path)["codex"]["session"] == "codex"
    # Connecting again replaces the table rather than adding a second one.
    connect.connect("codex", "codex-2", API, home=tmp_path)
    assert path.read_text(encoding="utf-8").count("[mcp_servers.abt]") == 1
    connect.disconnect("codex", home=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "[mcp_servers.abt]" not in text and "[mcp_servers.other]" in text


def test_a_file_that_is_not_plain_json_is_left_alone(tmp_path):
    path = tmp_path / ".cursor" / "mcp.json"
    path.parent.mkdir()
    original = '{ // my servers\n "mcpServers": {} }'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(OpError):
        connect.connect("cursor", "cursor", API, home=tmp_path)
    assert path.read_text(encoding="utf-8") == original


def test_a_missing_config_file_is_created(tmp_path):
    connect.connect("gemini", "gemini", API, home=tmp_path)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert "abt" in data["mcpServers"]


def test_installed_is_detected_by_folder_or_command(tmp_path):
    (tmp_path / ".cursor").mkdir()
    found = {r["id"]: r["installed"] for r in connect.status(tmp_path, which=lambda c: "/bin/x" if c == "opencode" else None)}
    assert found["cursor"] is True and found["opencode"] is True and found["codex"] is False


def test_the_bridge_is_started_with_python_not_pythonw(monkeypatch, tmp_path):
    fake = tmp_path / "pythonw.exe"
    fake.write_text("")
    (tmp_path / "python.exe").write_text("")
    monkeypatch.setattr(connect.sys, "executable", str(fake))
    assert connect.mcp_command("s", API)[0] == str(tmp_path / "python.exe")


def test_an_unknown_harness_is_refused():
    with pytest.raises(OpError):
        connect.find("notepad")


def test_the_app_connects_a_harness_to_a_session_of_its_own(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from abt.browser import BrowserSession
    from abt.profiles import ProfileRegistry
    from abt.server import create_app
    from abt.sessions import SessionRegistry, SessionStore

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"), ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a), operator_token="op",
    )
    op = {"X-ABT-Token": "op"}
    with TestClient(create_app(registry=registry)) as client:
        assert client.post("/app/connect/gemini", json={}).json()["error"]["type"] == "session_sealed"
        out = client.post("/app/connect/gemini", json={"profile": "default"}, headers=op).json()["result"]
        assert out["session"] == "gemini"
        assert registry.info("gemini")["profile"] == "default"
        written = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
        assert "--session" in written["mcpServers"]["abt"]["args"]
        rows = {r["id"]: r for r in client.get("/app/connect", headers=op).json()["result"]}
        assert rows["gemini"]["session"] == "gemini"
        client.delete("/app/connect/gemini", headers=op)
        rows = {r["id"]: r for r in client.get("/app/connect", headers=op).json()["result"]}
        assert rows["gemini"]["session"] is None
        assert registry.info("gemini")["name"] == "gemini"  # the session and its logs stay
