"""The whole thing, over HTTP, against real Chrome.

The timing tests use the fixture server's `?delay=` so each goto waits two
seconds on the server. A goto over HTTP also settles and reads the page back,
so its wall time is measured first rather than assumed, and each goto gets its
own URL so Chrome cannot answer one from cache.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def env(tmp_path, budgets):
    profiles = ProfileRegistry(root=tmp_path / "profiles")
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        profiles,
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        operator_token="op",
    )
    profiles.create("p1")
    profiles.create("p2")
    registry.create("s1", profile="p1")
    registry.create("s2", profile="p2")
    registry.create("s3", profile="p1")
    with TestClient(create_app(registry=registry)) as client:
        yield registry, client
    registry.close_all()


def send(client, session, body, token=None):
    headers = {"X-ABT-Session": session}
    if token:
        headers["X-ABT-Token"] = token
    return client.post("/command-list", json=body, headers=headers).json()



def compare(client, first, second, base_url):
    """(one goto alone, two at once), each on a URL no one has loaded yet."""
    url = lambda tag: f"{base_url}/form.html?delay=2&n={tag}"
    started = time.monotonic()
    assert send(client, first, {"op": "goto", "url": url("alone")})["ok"] is True
    alone = time.monotonic() - started
    out = {}
    threads = [
        threading.Thread(
            target=lambda s=s: out.__setitem__(s, send(client, s, {"op": "goto", "url": url(s)}))
        )
        for s in (first, second)
    ]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    together = time.monotonic() - started
    assert all(r["ok"] for r in out.values())
    return alone, together


def start(client, *sessions):
    for s in sessions:
        assert send(client, s, {"op": "browser_start"})["ok"] is True


def test_two_profiles_run_in_parallel(env, base_url):
    _, client = env
    start(client, "s1", "s2")
    alone, together = compare(client, "s1", "s2", base_url)
    # Serial would be about 2x. Parallel is about 1x, plus scheduling noise.
    assert together < alone * 1.5, (alone, together)


def test_two_sessions_on_one_profile_run_in_parallel(env, base_url):
    _, client = env
    start(client, "s1", "s3")
    alone, together = compare(client, "s1", "s3", base_url)
    assert together < alone * 1.5, (alone, together)


def test_isolation_across_and_within_profiles(env, base_url):
    _, client = env
    start(client, "s1", "s2", "s3")
    send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})
    mine = send(client, "s1", {"op": "status"})["result"]["active_tab"]
    shared = send(client, "s3", {"op": "tab_list"})["result"]
    assert {"tab_id": mine, "locked": "s1"} in shared
    refused = send(client, "s3", {"op": "tab_switch", "tab_id": mine})
    assert refused["error"]["type"] == "tab_locked"
    other = send(client, "s2", {"op": "tab_list"})["result"]
    assert all("form.html" not in (row.get("url") or "") for row in other)


def test_a_popup_stays_with_its_session(env, base_url):
    _, client = env
    start(client, "s1", "s3")
    send(client, "s1", {"op": "run_js", "script": f"window.open('{base_url}/cards.html')"})
    # A popup reaches Playwright's page list a moment after window.open.
    deadline = time.monotonic() + 5
    while True:
        rows = send(client, "s1", {"op": "tab_list"})["result"]
        own = [r for r in rows if "locked" not in r and "unowned" not in r]
        if len(own) == 2 or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert len(own) == 2
    locked = [r for r in send(client, "s3", {"op": "tab_list"})["result"] if r.get("locked") == "s1"]
    assert len(locked) == 2


def test_a_sealed_session_over_http(env):
    registry, client = env
    token = registry.create("sealed", profile="p2", sealed=True)["token"]
    assert send(client, "sealed", {"op": "status"})["error"]["type"] == "session_sealed"
    assert send(client, "sealed", {"op": "status"}, token=token)["ok"] is True


def test_a_crashed_profile_comes_back_on_restart(env, base_url):
    registry, client = env
    start(client, "s1")
    registry.profiles.running("p1").process.kill()
    registry.profiles.running("p1")  # noticed dead and forgotten
    dead = send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})
    assert dead["ok"] is False
    assert send(client, "s1", {"op": "browser_restart"})["ok"] is True
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True


def test_idle_profiles_are_stopped_and_can_start_again(env):
    registry, client = env
    start(client, "s2")
    registry.profiles.idle_seconds = 0.01
    time.sleep(0.05)
    assert "p2" in registry.reap_idle()
    assert send(client, "s2", {"op": "status"})["result"]["running"] is False
    start(client, "s2")
