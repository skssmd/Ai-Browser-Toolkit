"""A session reopens the pages it had open when its browser comes back."""

from __future__ import annotations

from types import SimpleNamespace

from abt.browser import Attach, BrowserSession
from abt.tabs import TabGate, TabRegistry


def session_with(tmp_path, pages, current_url):
    """A shared session whose Chrome lists `pages`: (target, owner, url)."""
    registry = TabRegistry("default")
    gate = TabGate(registry, "a")
    for target, owner, _ in pages:
        TabGate(registry, owner).opened(target)
    rows = [{"id": target, "url": url} for target, _, url in pages]
    attach = Attach(connect=lambda: "", disconnect=lambda: None, list_targets=lambda: rows, gate=gate)
    browser = BrowserSession(profile=tmp_path, headless=True, attach=attach)
    browser._driver = SimpleNamespace(current_url=current_url)
    return browser


def test_the_snapshot_is_this_sessions_web_pages_in_tab_order(tmp_path):
    browser = session_with(tmp_path, [
        ("T1", "a", "https://a.example/"),
        ("T2", "a", "about:blank"),
        ("T3", "a", "https://b.example/x"),
        ("T4", "b", "https://someone-else.example/"),
    ], "https://b.example/x")
    snap = browser.page_snapshot()
    # Its own tabs only, web pages only, and the active one marked.
    assert snap == {"urls": ["https://a.example/", "https://b.example/x"], "active": 1}


def test_restoring_reopens_each_page_and_returns_to_the_active_one(tmp_path, monkeypatch):
    browser = BrowserSession(profile=tmp_path, headless=True, attach=Attach(
        connect=lambda: "", disconnect=lambda: None, list_targets=lambda: [],
        gate=TabGate(TabRegistry("default"), "a")))
    browser.pages_to_restore = lambda: {"urls": ["https://a.example/", "https://blocked.example/",
                                                 "https://c.example/", "chrome://settings"], "active": 2}
    done = []

    def goto(url):
        done.append(("goto", url))

    def new_tab(url, activate):
        if "blocked" in url:
            raise RuntimeError("url_blocked")
        done.append(("tab", url))
        return f"tab_{len(done)}"

    monkeypatch.setattr(browser, "goto", goto)
    monkeypatch.setattr(browser, "new_tab", new_tab)
    monkeypatch.setattr(BrowserSession, "active_tab", property(lambda self: "tab_0"))
    monkeypatch.setattr(browser, "switch_tab", lambda tab: done.append(("switch", tab)))
    browser._restore_pages()
    # The blocked one is skipped, not fatal; chrome:// pages are not restored.
    assert done == [("goto", "https://a.example/"), ("tab", "https://c.example/"), ("switch", "tab_2")]


def restoring(tmp_path, monkeypatch, pages, driver=None):
    browser = BrowserSession(profile=tmp_path, headless=True, attach=Attach(
        connect=lambda: "", disconnect=lambda: None, list_targets=lambda: [],
        gate=TabGate(TabRegistry("default"), "a")))
    browser._driver = driver
    browser.pages_to_restore = lambda: pages
    done = []
    monkeypatch.setattr(browser, "goto", lambda url: done.append(("goto", url)))
    monkeypatch.setattr(browser, "new_tab", lambda url, activate: done.append(("tab", url)) or url)
    monkeypatch.setattr(BrowserSession, "active_tab", property(lambda self: "first"))
    monkeypatch.setattr(browser, "switch_tab", lambda tab: done.append(("switch", tab)))
    browser._restore_pages()
    return done


def test_a_page_open_several_times_is_reopened_once(tmp_path, monkeypatch):
    """Seen live: one store page remembered four times, and reopened four times."""
    done = restoring(tmp_path, monkeypatch, {"urls": [
        "https://s.example/", "https://s.example/", "https://g.example/", "https://s.example/"],
        "active": 2})
    assert done == [("goto", "https://s.example/"), ("tab", "https://g.example/"),
                    ("switch", "https://g.example/")]


def test_nothing_is_reopened_when_its_tabs_were_taken_back(tmp_path, monkeypatch):
    """Reconnecting to a browser that still has the session's tabs: they are the pages."""
    done = restoring(tmp_path, monkeypatch, {"urls": ["https://s.example/"], "active": 0},
                     driver=SimpleNamespace(reused_tabs=True))
    assert done == []


def test_nothing_to_restore_is_a_no_op(tmp_path, monkeypatch):
    browser = BrowserSession(profile=tmp_path, headless=True, attach=Attach(
        connect=lambda: "", disconnect=lambda: None, list_targets=lambda: [],
        gate=TabGate(TabRegistry("default"), "a")))
    browser.pages_to_restore = lambda: {}
    monkeypatch.setattr(browser, "goto", lambda url: (_ for _ in ()).throw(AssertionError("no goto")))
    browser._restore_pages()


def registry_with_session(tmp_path):
    from abt.profiles import ProfileRegistry
    from abt.sessions import SessionRegistry, SessionStore

    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"), ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
    )
    registry.create("s")
    return registry, registry.get("s")


def test_a_dead_browser_keeps_the_list_but_tabs_closed_by_hand_are_forgotten(tmp_path):
    """A browser that died lists nothing (snapshot None): keep the last good
    list. A live one listing nothing means the person closed the tabs: those
    stay closed -- they used to come back at the next restart."""
    from abt.sessions import SessionStore

    registry, sess = registry_with_session(tmp_path)
    one = {"urls": ["https://a.example/"], "active": 0}
    snaps = iter([one, None, {"urls": [], "active": 0}])
    sess.browser.page_snapshot = lambda: next(snaps)
    registry.remember_pages(sess)
    registry.remember_pages(sess)  # died
    assert sess.record.pages == one
    registry.remember_pages(sess)  # alive, every tab closed by hand
    assert sess.record.pages == {"urls": [], "active": 0}
    assert SessionStore(tmp_path / "sessions").load()["s"].pages == {"urls": [], "active": 0}


def test_pages_come_back_only_for_a_session_in_the_middle_of_its_work(tmp_path):
    import time

    from abt import sessions

    registry, sess = registry_with_session(tmp_path)
    sess.record.pages = {"urls": ["https://a.example/"], "active": 0}
    restore = sess.browser.pages_to_restore
    assert restore() is None  # never used since the server started: start clean
    sess.activity = {"at": time.time() - sessions.RESTORE_WITHIN_SECONDS - 60}
    assert restore() is None  # idle an hour: start clean
    sess.activity = {"at": time.time() - 30}
    assert restore() == {"urls": ["https://a.example/"], "active": 0}  # a crash mid-task
