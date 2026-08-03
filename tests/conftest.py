"""Shared fixtures: a local static file server and one headless Chrome session."""

from __future__ import annotations

import functools
import http.server
import tempfile
import threading
from pathlib import Path

import pytest

from abt.browser import BrowserSession
from abt.server import create_app

FIXTURES = Path(__file__).parent / "fixtures"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output readable
        pass


@pytest.fixture(scope="session")
def base_url():
    """Serve tests/fixtures over HTTP so pages behave like real pages."""
    handler = functools.partial(_QuietHandler, directory=str(FIXTURES))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def session():
    profile = Path(tempfile.mkdtemp(prefix="abt-test-profile-"))
    browser = BrowserSession(profile=profile, headless=True, action_timeout=3.0)
    browser.start()
    yield browser
    browser.quit()


@pytest.fixture
def clean_session(session, base_url):
    """One tab, on a known page, refs cleared."""
    for tab in list(session.tabs()):
        if not tab["active"]:
            session.close_tab(tab["tab_id"])
    session.goto(f"{base_url}/cards.html")
    return session


@pytest.fixture
def client(clean_session):
    from fastapi.testclient import TestClient

    with TestClient(create_app(clean_session)) as test_client:
        yield test_client
