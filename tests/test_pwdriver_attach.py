"""Two sessions, one Chrome: each connection sees only its own tabs."""

from __future__ import annotations

import time

import pytest

from abt.launch import LaunchConfig
from abt.profiles import DEFAULT, ProfileRegistry
from abt.pwdriver import PlaywrightDriver
from abt.tabs import TabGate


def handles_until(driver, count, timeout=5.0):
    """A popup reaches Playwright's page list a moment after window.open."""
    deadline = time.monotonic() + timeout
    while True:
        handles = driver.window_handles
        if len(handles) >= count or time.monotonic() > deadline:
            return handles
        time.sleep(0.05)


@pytest.fixture
def reg(tmp_path):
    registry = ProfileRegistry(root=tmp_path / "profiles")
    yield registry
    registry.stop_all()


@pytest.fixture
def pair(reg, tmp_path):
    tabs = reg.tabs(DEFAULT)
    config = LaunchConfig(profile=tmp_path / "profiles" / DEFAULT)
    drivers = {}
    for name in ("a", "b"):
        url = reg.attach(DEFAULT, name)
        drivers[name] = PlaywrightDriver(config, cdp_url=url, gate=TabGate(tabs, name))
    yield drivers, tabs
    for driver in drivers.values():
        try:
            driver.quit()
        except Exception:
            pass


def test_each_session_starts_on_a_page_of_its_own(pair):
    drivers, tabs = pair
    a, b = drivers["a"].window_handles, drivers["b"].window_handles
    assert len(a) == 1 and len(b) == 1
    assert a != b
    assert tabs.owner_of(a[0]) == "a"
    assert tabs.owner_of(b[0]) == "b"


def test_a_popup_joins_its_openers_session_only(pair):
    drivers, _ = pair
    drivers["a"].execute_script("window.open('about:blank')")
    assert len(handles_until(drivers["a"], 2)) == 2
    assert len(drivers["b"].window_handles) == 1


def test_a_dialog_on_one_session_does_not_kill_the_other(pair):
    drivers, _ = pair
    drivers["a"].execute_script("setTimeout(() => confirm('x'), 0)")
    drivers["a"].execute_script("return 1")
    assert drivers["b"].current_url == "about:blank"


def test_quitting_one_session_closes_only_its_tabs(pair):
    """Review focus 4."""
    drivers, tabs = pair
    kept = drivers["b"].window_handles
    drivers["a"].quit()
    assert drivers["b"].window_handles == kept
    assert tabs.owned_by("a") == []


def test_opener_of_names_the_popups_parent(pair):
    drivers, _ = pair
    parent = drivers["a"].current_window_handle
    drivers["a"].execute_script("window.open('about:blank')")
    popup = [h for h in handles_until(drivers["a"], 2) if h != parent][0]
    assert drivers["a"].opener_of(popup) == parent


def test_other_sessions_pages_hold_no_cdp_session_here(pair):
    """Asking a foreign page its target id must not keep a CDP session open
    on it for the life of this connection."""
    drivers, _ = pair
    for _ in range(3):
        drivers["b"].switch_to.new_window("tab")
    drivers["a"].window_handles
    own = {id(p) for p in drivers["a"]._pages}
    assert set(drivers["a"]._cdp) <= own


def test_a_new_connection_takes_its_sessions_open_tabs_back(pair, reg, tmp_path):
    """A connection that died leaves its tabs open. The session's next one used
    to open a fresh tab beside them, doubling its pages on every reconnect."""
    drivers, tabs = pair
    drivers["a"].switch_to.new_window("tab")
    before = sorted(handles_until(drivers["a"], 2))
    config = LaunchConfig(profile=tmp_path / "profiles" / DEFAULT)
    again = PlaywrightDriver(config, cdp_url=reg.attach(DEFAULT, "a"), gate=TabGate(tabs, "a"))
    try:
        assert again.reused_tabs is True
        assert sorted(again.window_handles) == before
        assert len(drivers["b"].window_handles) == 1
    finally:
        again.quit()
