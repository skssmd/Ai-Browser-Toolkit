"""URL rules against a real Chrome: the network guard, not just the op check.

Two origins from the fixture server -- the same files on two ports. The
session may reach the first and not the second, and every way of reaching the
second has to fail: a navigation, a fetch() from run_js, a popup.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def env(tmp_path, budgets, base_url):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
    )
    allowed = urlsplit(base_url).netloc
    registry.create("s", settings={"rules": [allowed]})
    with TestClient(create_app(registry=registry)) as client:
        assert send(client, {"op": "browser_start"})["ok"] is True
        yield registry, client
    registry.close_all()


# no-cors, so the browser's own cross-origin rules cannot fail the request:
# only the guard can. An opaque response still resolves.
FETCH = "return fetch(%r, {mode: 'no-cors'}).then(() => 'reached', () => 'blocked')"


def send(client, body):
    return client.post("/command-list", json=body, headers={"X-ABT-Session": "s"}).json()


def js(client, script):
    body = send(client, {"op": "run_js", "script": script, "diff": False})
    assert body["ok"] is True, body
    return body["result"]["value"]


def test_an_allowed_page_loads_and_a_blocked_goto_is_refused(env, base_url, other_origin):
    _, client = env
    assert send(client, {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True
    body = send(client, {"op": "goto", "url": f"{other_origin}/form.html"})
    assert body["error"]["type"] == "url_blocked"


def test_run_js_cannot_fetch_around_the_rules(env, base_url, other_origin):
    _, client = env
    send(client, {"op": "goto", "url": f"{base_url}/form.html"})
    assert js(client, FETCH % f"{other_origin}/form.html") == "blocked"
    assert js(client, FETCH % f"{base_url}/form.html") == "reached"


def test_a_navigation_by_the_page_is_stopped(env, base_url, other_origin):
    _, client = env
    send(client, {"op": "goto", "url": f"{base_url}/form.html"})
    # Deferred, so the script returns before its own page goes away.
    js(client, "setTimeout(() => { location.href = %r }, 50); return 1" % f"{other_origin}/cards.html")
    time.sleep(1.0)
    assert not js(client, "return location.href").startswith(other_origin)


def test_a_popup_to_a_blocked_url_does_not_load_it(env, base_url, other_origin):
    registry, client = env
    send(client, {"op": "goto", "url": f"{base_url}/form.html"})
    js(client, "window.open(%r); return 1" % f"{other_origin}/cards.html")
    deadline = time.monotonic() + 5
    urls = []
    while time.monotonic() < deadline:
        urls = [t.get("url", "") for t in registry.profiles.targets("default")]
        if len(urls) >= 3:
            break
        time.sleep(0.1)
    time.sleep(1.0)
    urls = [t.get("url", "") for t in registry.profiles.targets("default")]
    assert not any(u.startswith(other_origin) for u in urls), urls


def test_lifting_the_rules_lets_it_through(env, base_url, other_origin):
    registry, client = env
    send(client, {"op": "goto", "url": f"{base_url}/form.html"})
    assert js(client, FETCH % f"{other_origin}/form.html") == "blocked"
    registry.update("s", settings={"rules": []})
    assert js(client, FETCH % f"{other_origin}/form.html") == "reached"
