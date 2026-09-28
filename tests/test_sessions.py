"""Sessions: creation, sealing, persistence, and the legacy single session.

No browser: every BrowserSession here is built and never started.
"""

from __future__ import annotations

import json

import pytest

from abt.browser import BrowserSession
from abt.errors import OpError
from abt.profiles import ProfileRegistry
from abt.sessions import SessionRegistry, SessionStore, SingleSessionRegistry


@pytest.fixture
def parts(tmp_path):
    profiles = ProfileRegistry(root=tmp_path / "profiles")
    store = SessionStore(tmp_path / "sessions")

    def make_browser(directory, attach):
        return BrowserSession(profile=directory, headless=True, attach=attach)

    return profiles, store, make_browser


@pytest.fixture
def reg(parts):
    profiles, store, make_browser = parts
    return SessionRegistry(store, profiles, make_browser, operator_token="op")


def test_default_always_exists(reg):
    assert reg.get(None).name == "default"
    assert reg.get("default").browser.shared is True


def test_an_unknown_session_is_an_error_not_a_fallback(reg):
    with pytest.raises(OpError) as exc:
        reg.get("typo")
    assert exc.value.type == "unknown_session"


def test_create_open_session(reg):
    reg.profiles.create("work")
    out = reg.create("a", profile="work")
    assert out["profile"] == "work"
    assert "token" not in out
    assert reg.get("a").record.profile == "work"
    with pytest.raises(OpError) as exc:
        reg.create("a")
    assert exc.value.type == "session_exists"


@pytest.mark.parametrize("bad", ["../x", "a/b", "C:\\x", ".hidden", ""])
def test_a_session_name_that_is_a_path_writes_nothing(reg, tmp_path, bad):
    """Review focus 1."""
    with pytest.raises(OpError) as exc:
        reg.create(bad)
    assert exc.value.type == "invalid_op"
    assert sorted(p.name for p in (tmp_path / "sessions").glob("*")) == []


def test_a_session_on_a_missing_profile_is_refused(reg):
    with pytest.raises(OpError) as exc:
        reg.create("a", profile="ghost")
    assert exc.value.type == "profile_not_found"


def test_sealed_needs_its_token(reg, tmp_path):
    token = reg.create("s", sealed=True)["token"]
    for wrong in (None, "nope"):
        with pytest.raises(OpError) as exc:
            reg.get("s", wrong)
        assert exc.value.type == "session_sealed"
    assert reg.get("s", token).name == "s"
    assert (tmp_path / "sessions" / "s.token").read_text(encoding="utf-8") == token
    saved = json.loads((tmp_path / "sessions" / "s.json").read_text(encoding="utf-8"))
    assert token not in json.dumps(saved)


def test_a_sealed_token_survives_a_restart(parts):
    """Review focus 3."""
    profiles, store, make_browser = parts
    token = SessionRegistry(store, profiles, make_browser).create("s", sealed=True)["token"]
    again = SessionRegistry(store, profiles, make_browser)
    assert again.get("s", token).name == "s"
    with pytest.raises(OpError):
        again.get("s", "wrong")


def test_settings_merge_delete_and_keep_unknown_keys(parts):
    profiles, store, make_browser = parts
    reg = SessionRegistry(store, profiles, make_browser)
    reg.create("a", settings={"future": {"x": 1}, "gone": True})
    reg.update("a", settings={"gone": None, "added": 2})
    again = SessionRegistry(store, profiles, make_browser)
    assert again.get("a").record.settings == {"future": {"x": 1}, "added": 2}


def test_changing_profile_replaces_the_browser_and_warns(reg):
    reg.profiles.create("work")
    reg.create("a")
    before = reg.get("a").browser
    out = reg.update("a", profile="work")
    assert reg.get("a").browser is not before
    assert reg.get("a").browser.profile == reg.profiles.path("work")
    assert "warning" in out


def test_default_keeps_the_default_profile(reg):
    reg.profiles.create("work")
    with pytest.raises(OpError) as exc:
        reg.update("default", profile="work")
    assert exc.value.type == "invalid_op"


def test_remove(reg, tmp_path):
    with pytest.raises(OpError):
        reg.remove("default")
    token = reg.create("s", sealed=True)["token"]
    with pytest.raises(OpError) as exc:
        reg.remove("s")
    assert exc.value.type == "session_sealed"
    reg.remove("s", token)
    assert not (tmp_path / "sessions" / "s.json").exists()
    assert not (tmp_path / "sessions" / "s.token").exists()


def test_list_hides_a_sealed_sessions_settings(reg):
    reg.create("s", sealed=True, settings={"secret": 1})
    row = next(r for r in reg.list() if r["name"] == "s")
    assert row["sealed"] is True
    assert "settings" not in row


def test_a_profile_in_use_cannot_be_removed(reg):
    reg.profiles.create("work")
    reg.create("a", profile="work")
    with pytest.raises(OpError) as exc:
        reg.remove_profile("work")
    assert exc.value.type == "profile_in_use"


def test_the_operator_token(reg):
    assert reg.is_operator("op") is True
    assert reg.is_operator("no") is False
    assert reg.is_operator(None) is False


def test_reaping_skips_a_busy_session(reg, monkeypatch):
    stopped = []
    monkeypatch.setattr(reg.profiles, "idle", lambda: ["default"])
    monkeypatch.setattr(reg.profiles, "stop", lambda name: stopped.append(name) or True)
    session = reg.get(None)
    session.browser._driver = object()  # looks connected, so the reaper must lock it
    monkeypatch.setattr(session.browser, "stop", lambda: None)
    session.lock.acquire()
    try:
        assert reg.reap_idle() == []
    finally:
        session.lock.release()
    assert reg.reap_idle() == ["default"]
    assert stopped == ["default"]


def test_the_legacy_registry_has_only_default(tmp_path):
    browser = BrowserSession(profile=tmp_path, headless=True)
    reg = SingleSessionRegistry(browser, None)
    assert reg.get(None).browser is browser
    with pytest.raises(OpError) as exc:
        reg.get("other")
    assert exc.value.type == "unknown_session"
    with pytest.raises(OpError) as exc:
        reg.create("x")
    assert exc.value.type == "invalid_op"
