"""Shared fixtures: a local static file server and one headless Chrome session."""

from __future__ import annotations

import functools
import http.server
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from abt.browser import BrowserSession
from abt.server import create_app

FIXTURES = Path(__file__).parent / "fixtures"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output readable
        pass

    def do_GET(self):
        """Support `?delay=0.8` so a fixture can model a slow API call.

        Everything served here is local and instant, which is precisely the
        condition under which a broken settle check still looks correct. A
        request that actually takes a while is the only way to prove the
        in-flight counter is doing the work.
        """
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "delay" in params:
            try:
                time.sleep(min(float(params["delay"][0]), 5.0))
            except ValueError:
                pass
        self.path = parsed.path
        super().do_GET()


def _serve():
    handler = functools.partial(_QuietHandler, directory=str(FIXTURES))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture(scope="session")
def base_url():
    """Serve tests/fixtures over HTTP so pages behave like real pages."""
    server = _serve()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def other_origin():
    """The same files on a second port.

    A different port is a different origin, so a frame served from here is one
    the parent document is genuinely forbidden to read -- the only way to test
    the frames that matter without reaching for the live internet.
    """
    server = _serve()
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


@pytest.fixture
def unstarted_session(tmp_path):
    """A session that never launched a browser.

    The existing `session` fixture starts Chrome eagerly and is session-scoped;
    this one is the counterpart for everything that should work without one.
    """
    return BrowserSession(profile=tmp_path, headless=True, action_timeout=3.0)


@pytest.fixture
def unstarted_client(unstarted_session):
    from fastapi.testclient import TestClient

    with TestClient(create_app(unstarted_session)) as test_client:
        yield test_client
