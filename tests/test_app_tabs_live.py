"""The app's tab strip never waits for an agent."""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


def test_tabs_answer_while_the_session_is_busy(tmp_path, budgets, base_url):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        operator_token="op",
    )
    try:
        with TestClient(create_app(registry=registry)) as client:
            client.post("/command-list", json=[
                {"op": "browser_start"},
                {"op": "goto", "url": f"{base_url}/form.html"},
                {"op": "tab_new", "url": f"{base_url}/cards.html"},
            ])
            session = registry.get(None)
            # An agent mid-command holds the session's lock.
            session.lock.acquire()
            try:
                result = {}
                worker = threading.Thread(target=lambda: result.update(client.get("/app/tabs").json()))
                started = time.monotonic()
                worker.start()
                worker.join(timeout=5)
                took = time.monotonic() - started
            finally:
                session.lock.release()
            assert result.get("ok") is True, result
            titles = {row["title"] for row in result["result"]}
            assert titles == {"Form", "Cards"}
            assert took < 3, "the tab strip waited for the agent"
    finally:
        registry.close_all()
