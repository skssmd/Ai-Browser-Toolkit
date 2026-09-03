"""Shared fixtures: a local static file server and one headless Chrome session."""

from __future__ import annotations

import functools
import http.server
import os
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from abt.browser import BrowserSession
from abt.server import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def texts(added: list[str]) -> list[str]:
    """The strings a diff reported, with the positions taken off.

    Since 0.4.0 every entry arrives with where it sits: `"ACBa Widgets"`, or a
    bare path introducing members written as `"  a Widgets"`. A test that cares
    *what* appeared reads through this; a test about the tree itself asserts on
    the raw lines instead, which is the point of keeping this a helper rather
    than changing what the ops return.

    Group headers own no text, and the line summarising what a navigation did
    not repeat is not something the page said, so neither comes back.
    """
    out: list[str] = []
    for line in added:
        stripped = line.strip()
        if not stripped or stripped.startswith("…") or " " not in stripped:
            continue
        out.append(stripped.partition(" ")[2])
    return out


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


def pytest_addoption(parser):
    """`--engine playwright` runs the whole suite against the other driver.

    The point of the migration is that these tests cannot tell which engine is
    underneath. Making that a flag rather than a fork means the claim is checked
    by running the same 485 assertions, not by reading a diff.
    """
    parser.addoption(
        "--engine",
        action="store",
        default="playwright",
        choices=("selenium", "playwright"),
        help="which driver the browser-backed fixtures use",
    )
    parser.addoption(
        "--slowdown",
        action="store",
        type=float,
        default=float(os.environ.get("ABT_TEST_SLOWDOWN", "1")),
        help="multiply every browser-fixture time budget by this. The "
        "defaults suit a developer machine; a loaded CI runner is several "
        "times slower and blows a different one each run -- first a click "
        "timeout, then a settle grace. One multiplier says the true thing "
        "(this machine is slower) instead of hardcoding three numbers.",
    )


@pytest.fixture(scope="session")
def engine(request):
    return request.config.getoption("--engine")


# Budgets a developer machine is comfortable with, scaled by --slowdown. An
# unscaled run reproduces exactly what these fixtures did before the knob
# existed: 3.0 was the fixtures' own tighter choice, while 5.0 and 0.5 are
# BrowserSession's defaults (browser.py:102 and _SETTLE_NETWORK_GRACE), which
# the fixtures previously inherited by not passing them.
BASE_ACTION_TIMEOUT = 3.0
BASE_SETTLE_TIMEOUT = 5.0
BASE_SETTLE_NETWORK_GRACE = 0.5

# Ceilings scale with --slowdown; the network grace does not, past this. See
# the comment in `budgets` -- grace is charged on every navigation rather than
# only on failures, so it is the one that turns a slower budget into a slower
# suite.
GRACE_SCALE_CAP = 2.0


@pytest.fixture(scope="session")
def slowdown(request):
    return request.config.getoption("--slowdown")


@pytest.fixture(scope="session")
def budgets(slowdown):
    """Every browser-fixture time budget, scaled together.

    Scaled together on purpose: settle_network_grace is the subtle one. The
    slowfetch fixture chains two requests, so the in-flight count drops to
    zero between them; if the grace is shorter than that gap the page is
    called idle mid-load and the snapshot catches the spinner. Raising only
    the timeout would not have fixed that.
    """
    return {
        # Both of these are ceilings: they are paid only when a wait actually
        # fails or a page never settles, so scaling them hard is free on a
        # green run.
        "action_timeout": BASE_ACTION_TIMEOUT * slowdown,
        "settle_timeout": BASE_SETTLE_TIMEOUT * slowdown,
        # This one is not a ceiling. Settle waits for this much network
        # silence before calling a page idle, so it is paid in full on *every
        # navigation in the suite*. Scaling it by 5 alongside the others took
        # CI from 10 minutes to 26. Capped at double, which is ample for the
        # gap it exists to tolerate -- the chained fetches in slowfetch.html
        # are a microtask apart, not a second.
        "settle_network_grace": BASE_SETTLE_NETWORK_GRACE
        * min(slowdown, GRACE_SCALE_CAP),
    }


@pytest.fixture(scope="session")
def session(engine, budgets):
    profile = Path(tempfile.mkdtemp(prefix="abt-test-profile-"))
    browser = BrowserSession(
        profile=profile, headless=True, engine=engine, **budgets
    )
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
def unstarted_session(tmp_path, engine, budgets):
    """A session that never launched a browser.

    The existing `session` fixture starts Chrome eagerly and is session-scoped;
    this one is the counterpart for everything that should work without one.
    """
    return BrowserSession(
        profile=tmp_path, headless=True, engine=engine, **budgets
    )


@pytest.fixture
def unstarted_client(unstarted_session):
    from fastapi.testclient import TestClient

    with TestClient(create_app(unstarted_session)) as test_client:
        yield test_client
