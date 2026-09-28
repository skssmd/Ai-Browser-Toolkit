"""Findings from the whole-branch review of multi-profile sessions.

Each test pins one way the first cut could hurt someone: a name that aliases
another on a case-insensitive disk, a web page reaching the screencast, a
sealed session's messages or logs leaking to whoever asks next. No browser.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from abt import cli
from abt.browser import Attach, BrowserSession
from abt.errors import OpError
from abt.profiles import DEFAULT, ProfileRegistry, check_name
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore
from abt.tabs import TabGate, TabRegistry


@pytest.fixture
def registry(tmp_path):
    return SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        log_root=tmp_path / "logs",
        operator_token="op",
    )


@pytest.fixture
def client(registry):
    with TestClient(create_app(registry=registry)) as c:
        yield c


# --- names ---------------------------------------------------------------------


@pytest.mark.parametrize("alias", ["Default", "DEFAULT", "Work", "work.", "a."])
def test_a_name_that_could_alias_another_on_disk_is_refused(alias):
    """NTFS folds case and drops a trailing dot: `Default` *is* `default`."""
    with pytest.raises(OpError) as exc:
        check_name(alias)
    assert exc.value.type == "invalid_op"


def test_removing_default_by_another_spelling_touches_nothing(registry):
    default_dir = registry.profiles.path(DEFAULT)
    default_dir.mkdir(parents=True)
    with pytest.raises(OpError):
        registry.remove_profile("Default")
    assert default_dir.is_dir()


# --- ABT_CDP_URL ---------------------------------------------------------------


def test_an_external_browser_keeps_the_single_browser_server(monkeypatch):
    monkeypatch.setenv("ABT_CDP_URL", "http://127.0.0.1:9222")
    assert cli._use_sessions("playwright") is False
    monkeypatch.delenv("ABT_CDP_URL")
    assert cli._use_sessions("playwright") is True
    assert cli._use_sessions("selenium") is False


# --- screencast origin -----------------------------------------------------------


def test_a_web_page_cannot_open_the_screencast(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/screencast?tab=tab_0", headers={"origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()


def test_the_app_itself_may_open_it(client):
    with client.websocket_connect(
        "/screencast?tab=tab_9&token=op", headers={"origin": "http://127.0.0.1:8765"}
    ) as ws:
        assert ws.receive_json()["error"]["type"] == "tab_not_found"


# --- Chrome already holding a profile (Windows) ----------------------------------


def test_a_windows_handoff_names_the_lock(tmp_path):
    class Handed:
        returncode = 0

        def poll(self):
            return 0

    def spawn(argv):
        directory = next(a for a in argv if a.startswith("--user-data-dir="))
        from pathlib import Path

        (Path(directory.split("=", 1)[1]) / "lockfile").write_text("", encoding="utf-8")
        return Handed()

    reg = ProfileRegistry(
        root=tmp_path / "profiles",
        spawn=spawn,
        find_binary=lambda b: tmp_path / "chrome",
        http_get=lambda url: [],
    )
    with pytest.raises(OpError) as exc:
        reg.attach(DEFAULT, "a")
    assert "holding the profile" in exc.value.message


# --- messenger jobs are per session ------------------------------------------------


def test_messenger_jobs_are_visible_only_to_their_session(client, registry):
    registry.create("s", sealed=False)
    made = client.post(
        "/messenger/sendmessage/async",
        json={"thread_url": "https://www.messenger.com/t/1", "message": "secret"},
        headers={"X-ABT-Session": "s"},
    ).json()
    job = made["result"]["job_id"]
    assert client.get("/messenger/jobs").json()["result"] == []
    assert client.get(f"/messenger/jobs/{job}").status_code == 404
    mine = client.get("/messenger/jobs", headers={"X-ABT-Session": "s"}).json()["result"]
    assert [j["job_id"] for j in mine] == [job]


# --- a reused name does not inherit logs --------------------------------------------


def test_a_new_session_with_a_removed_name_starts_with_no_logs(client, registry, tmp_path):
    token = registry.create("work", sealed=True)["token"]
    client.post(
        "/command-list",
        json={"op": "status"},
        headers={"X-ABT-Session": "work", "X-ABT-Token": token},
    )
    assert (tmp_path / "logs" / "sessions" / "work").is_dir()
    registry.remove("work", token)
    registry.create("work")
    seen = client.get("/logs", params={"session": "work"}).json()["result"]
    assert seen["sessions"] == []
    assert any((tmp_path / "logs" / "removed-sessions").iterdir())


# --- a page nobody has placed yet ---------------------------------------------------


class _Driver:
    window_handles: list = []
    current_window_handle = None


def test_an_unplaced_page_is_listed_without_its_contents(tmp_path):
    tabs = TabRegistry(DEFAULT)
    rows = [{"id": "T9", "type": "page", "url": "https://idp.example/cb?code=x", "title": "t"}]
    session = BrowserSession(
        profile=tmp_path,
        headless=True,
        attach=Attach(lambda: "", lambda: None, lambda: rows, TabGate(tabs, "a")),
    )
    session._driver = _Driver()
    [row] = session.foreign_tabs()
    assert row.get("pending") is True
    assert "url" not in row and "title" not in row


# --- the default profile is not reaped -----------------------------------------------


def test_the_default_profile_is_never_idle(tmp_path):
    now = [0.0]
    from pathlib import Path

    class Proc:
        returncode = None

        def poll(self):
            return None

    def spawn(argv):
        directory = Path(next(a for a in argv if a.startswith("--user-data-dir=")).split("=", 1)[1])
        (directory / "DevToolsActivePort").write_text("9555\n", encoding="utf-8")
        return Proc()

    reg = ProfileRegistry(
        root=tmp_path / "profiles",
        spawn=spawn,
        find_binary=lambda b: tmp_path / "chrome",
        http_get=lambda url: [],
        clock=lambda: now[0],
        idle_minutes=1,
    )
    reg.create("work")
    reg.attach(DEFAULT, "a")
    reg.attach("work", "b")
    now[0] += 3600
    assert reg.idle() == ["work"]


# --- only default may shut the server down ----------------------------------------------


def test_a_session_cannot_shut_down_everyone(client, registry):
    registry.create("a")
    body = client.post(
        "/command-list", json={"op": "shutdown"}, headers={"X-ABT-Session": "a"}
    ).json()
    assert body["error"]["type"] == "invalid_op"
    assert client.get("/health").json()["ok"] is True


# --- a removed session stays removed --------------------------------------------------


def test_a_removed_session_is_marked_closed(registry):
    registry.create("a")
    held = registry.get("a")
    registry.remove("a")
    assert held.closed is True
