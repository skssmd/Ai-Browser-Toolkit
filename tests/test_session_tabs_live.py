"""Two BrowserSessions on one Chrome: listing, locks, claim and release."""

from __future__ import annotations

import pytest

from abt.browser import Attach, BrowserSession
from abt.errors import OpError
from abt.profiles import DEFAULT, ProfileRegistry
from abt.tabs import TabGate


@pytest.fixture
def reg(tmp_path):
    registry = ProfileRegistry(root=tmp_path / "profiles")
    yield registry
    registry.stop_all()


def make(reg, name, budgets):
    attach = Attach(
        connect=lambda: reg.attach(DEFAULT, name),
        disconnect=lambda: reg.detach(DEFAULT, name),
        list_targets=lambda: reg.targets(DEFAULT),
        gate=TabGate(reg.tabs(DEFAULT), name),
    )
    return BrowserSession(profile=reg.path(DEFAULT), headless=True, attach=attach, **budgets)


@pytest.fixture
def ab(reg, budgets):
    a, b = make(reg, "a", budgets), make(reg, "b", budgets)
    a.start()
    b.start()
    yield a, b
    for s in (a, b):
        s.stop()


def test_another_sessions_tab_is_listed_locked_without_its_page(ab, base_url):
    a, b = ab
    a.goto(f"{base_url}/form.html")
    rows = b.tabs() + b.foreign_tabs()
    locked = [r for r in rows if r.get("locked") == "a"]
    assert len(locked) == 1
    assert "url" not in locked[0]


def test_switching_to_it_is_refused(ab):
    a, b = ab
    with pytest.raises(OpError) as exc:
        b.check_tab(a.active_tab)
    assert exc.value.type == "tab_locked"


def test_release_then_claim_moves_a_tab(ab):
    a, b = ab
    given = a.new_tab(None, activate=False)
    a.release_tab(given)
    assert given not in [t["tab_id"] for t in a.tabs()]
    b.claim_tab(given)
    assert given in [t["tab_id"] for t in b.tabs()]


def test_releasing_the_last_tab_is_refused(ab):
    a, _ = ab
    with pytest.raises(OpError) as exc:
        a.release_tab(None)
    assert exc.value.type == "last_tab"


def test_stopping_one_session_leaves_the_other(ab):
    a, b = ab
    before = b.tabs()
    a.stop()
    assert b.tabs() == before
