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
    assert len(own) == 2, rows
    # Another session reads the page list from Chrome's own /json/list, which
    # can trail the owning connection by a moment on a loaded runner (seen on
    # Windows CI). Wait for it the same way, and say what was seen if not.
    deadline = time.monotonic() + 5
    while True:
        seen = send(client, "s3", {"op": "tab_list"})["result"]
        locked = [r for r in seen if r.get("locked") == "s1"]
        if len(locked) == 2 or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert len(locked) == 2, seen


def test_a_sealed_session_over_http(env):
    registry, client = env
    token = registry.create("sealed", profile="p2", sealed=True)["token"]
    assert send(client, "sealed", {"op": "status"})["error"]["type"] == "session_sealed"
    assert send(client, "sealed", {"op": "status"}, token=token)["ok"] is True


def test_a_crashed_profile_comes_back_on_its_own(env, base_url):
    """It used to fail, and need a browser_restart. Now the session re-attaches --
    relaunching the profile's Chrome -- and the goto is simply run again."""
    registry, client = env
    start(client, "s1")
    registry.profiles.running("p1").process.kill()
    registry.profiles.running("p1")  # noticed dead and forgotten
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/cards.html"})["ok"] is True
    # A deliberate restart is still there for whoever asks for one.
    assert send(client, "s1", {"op": "browser_restart"})["ok"] is True


def test_idle_profiles_are_stopped_and_can_start_again(env):
    registry, client = env
    start(client, "s2")
    registry.profiles.idle_seconds = 0.01
    time.sleep(0.05)
    assert "p2" in registry.reap_idle()
    assert send(client, "s2", {"op": "status"})["result"]["running"] is False
    start(client, "s2")


def test_an_idle_session_does_not_freeze_the_others_new_tabs(env, base_url):
    """Seen live: an agent's new tab froze -- `goto` timed out, then the 60s
    watchdog ended its connection -- while another session on the same Chrome
    sat idle. Playwright's sync API reads a connection's messages only during
    a call; an idle one stopped reading, its backlog filled, and it could no
    longer let Chrome start the new tab, which every connection must."""
    _, client = env
    start(client, "s1", "s3")
    # s1's page makes requests non-stop -- each an event for s1's connection.
    # They fail at once against a closed port, so no server is loaded by them.
    busy = "setInterval(() => fetch('http://127.0.0.1:9/x').catch(() => 0), 5); 1"
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True
    assert send(client, "s1", {"op": "run_js", "script": busy})["ok"] is True
    time.sleep(5)  # s1 idle while its events pile up
    started = time.monotonic()
    opened = send(client, "s3", {"op": "tab_new"})
    assert opened["ok"] is True, opened
    loaded = send(client, "s3", {"op": "goto", "url": f"{base_url}/cards.html"})
    assert loaded["ok"] is True, loaded
    assert time.monotonic() - started < 15


def kill_connection(registry, name):
    """End a session's Playwright connection exactly as the watchdog does when a
    call gets no answer: the driver process is terminated and the driver marked."""
    driver = registry.get(name).browser._driver
    driver._hung = True
    driver._end_driver()


def test_a_session_whose_connection_died_mends_itself_with_its_tabs(env, base_url):
    """Seen live: after one hung call every later command said browser_dead for
    good -- `status` still said running and `browser_start` said a browser was
    already running -- and an agent sat in that for twenty minutes. Chrome and
    the tabs were fine; only the connection was gone."""
    registry, client = env
    start(client, "s1", "s3")
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True
    assert send(client, "s1", {"op": "tab_new"})["ok"] is True
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/cards.html"})["ok"] is True
    before = sorted(r["tab_id"] for r in send(client, "s1", {"op": "tab_list"})["result"]
                    if "locked" not in r and "unowned" not in r)
    assert len(before) == 2

    kill_connection(registry, "s1")
    assert registry.get("s1").browser.is_dead is True
    out = send(client, "s1", {"op": "current_url"})  # the next command mends it
    assert out["ok"] is True, out
    # Back on the tab it was on -- a fresh connection starts on the first one.
    assert "cards.html" in (out["result"]["url"] if isinstance(out["result"], dict) else out["result"])
    after = sorted(r["tab_id"] for r in send(client, "s1", {"op": "tab_list"})["result"]
                   if "locked" not in r and "unowned" not in r)
    assert after == before  # the same tabs, none reopened and none lost
    assert registry.get("s1").browser.is_dead is False
    assert send(client, "s3", {"op": "current_url"})["ok"] is True  # nobody else was touched


def test_start_and_status_on_a_dead_connection_mend_it_rather_than_refuse(env):
    registry, client = env
    start(client, "s1")
    kill_connection(registry, "s1")
    status = send(client, "s1", {"op": "browser_status"})
    assert status["ok"] is True and status["result"]["running"] is True
    assert "connected" not in status["result"]  # mended by being asked, so no longer lost
    kill_connection(registry, "s1")
    started = send(client, "s1", {"op": "browser_start"})
    assert started["ok"] is True and started["result"]["reconnected"] is True, started
    assert send(client, "s1", {"op": "current_url"})["ok"] is True


def test_restarting_one_session_leaves_the_others_and_their_chrome_alone(env, base_url):
    """Several agents share one Chrome. A restart of one -- by an agent, or by the
    app answering browser_dead -- closes that session's own tabs and nothing
    else: the browser stays up for as long as any other session is on it."""
    registry, client = env
    start(client, "s1", "s3")  # both on p1
    for name, page in (("s1", "form.html"), ("s3", "cards.html")):
        assert send(client, name, {"op": "goto", "url": f"{base_url}/{page}"})["ok"] is True
    pid = registry.profiles._running["p1"].process.pid
    theirs = send(client, "s3", {"op": "status"})["result"]["active_tab"]

    restarted = send(client, "s1", {"op": "browser_restart"})
    assert restarted["ok"] is True, restarted

    assert registry.profiles._running["p1"].process.pid == pid  # the same Chrome, never relaunched
    assert send(client, "s3", {"op": "status"})["result"]["active_tab"] == theirs
    where = send(client, "s3", {"op": "current_url"})  # s3's own page, untouched
    assert where["ok"] is True and "cards.html" in str(where["result"]), where
    assert send(client, "s3", {"op": "get_text", "css": "body"})["ok"] is True  # and still driveable
    assert send(client, "s1", {"op": "current_url"})["ok"] is True  # s1 is back, on a page of its own


# -- a running browser is attached to, never refused; nothing says "restart" ----------


def test_start_on_a_browser_that_is_up_attaches_instead_of_refusing(env, base_url):
    registry, client = env
    start(client, "s1")
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})["ok"] is True
    pid = registry.profiles._running["p1"].process.pid
    tabs = send(client, "s1", {"op": "tab_list"})["result"]

    again = send(client, "s1", {"op": "browser_start"})
    assert again["ok"] is True, again
    assert again["result"]["already_running"] is True and again["result"]["reconnected"] is False
    assert registry.profiles._running["p1"].process.pid == pid  # no second Chrome
    assert send(client, "s1", {"op": "tab_list"})["result"] == tabs  # nothing opened or closed

    # An override it cannot apply is reported, not quietly dropped -- and not refused.
    asked = send(client, "s1", {"op": "browser_start", "headless": False})
    assert asked["ok"] is True and "not applied: headless=False" in asked["result"]["note"], asked


def test_a_chrome_that_went_away_is_reattached_and_goto_is_not_even_noticed(env, base_url):
    """The Chrome itself is gone, not only the connection: re-attaching relaunches
    the profile's browser. A `goto` names its whole destination, so it is simply
    run again; anything that depended on the lost page is told what happened.
    Nobody is ever asked to restart anything."""
    registry, client = env
    start(client, "s1")
    old = registry.profiles._running["p1"].process
    old.kill()
    old.wait(timeout=15)
    out = send(client, "s1", {"op": "goto", "url": f"{base_url}/form.html"})
    assert out["ok"] is True, out
    assert registry.profiles._running["p1"].process.pid != old.pid
    assert "form.html" in str(send(client, "s1", {"op": "current_url"})["result"])

    # A read of a page that was lost with the browser is reported, not guessed at.
    again = registry.profiles._running["p1"].process
    again.kill()
    again.wait(timeout=15)
    told = send(client, "s1", {"op": "get_text", "css": "body"})
    assert told["ok"] is False and told["error"]["type"] == "timeout"
    assert "re-established" in told["error"]["message"] and "restart" not in str(told).lower()
    assert send(client, "s1", {"op": "goto", "url": f"{base_url}/cards.html"})["ok"] is True


def test_start_on_a_dead_browser_is_never_a_refusal(env):
    registry, client = env
    start(client, "s1")
    registry.profiles._running["p1"].process.kill()
    out = send(client, "s1", {"op": "browser_start"})
    assert out["ok"] is True, out
    assert send(client, "s1", {"op": "current_url"})["ok"] is True
