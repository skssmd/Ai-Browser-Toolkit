"""A shared BrowserSession's rules that need no browser."""

from __future__ import annotations

import pytest

from abt.browser import Attach, BrowserSession
from abt.errors import OpError
from abt.tabs import TabGate, TabRegistry


def shared(tmp_path, connects):
    gate = TabGate(TabRegistry("default"), "a")
    attach = Attach(
        connect=lambda: connects.append(1) or "http://127.0.0.1:1",
        disconnect=lambda: None,
        list_targets=lambda: [],
        gate=gate,
    )
    return BrowserSession(profile=tmp_path, headless=True, attach=attach)


def test_a_session_cannot_start_on_another_profile(tmp_path):
    connects = []
    session = shared(tmp_path, connects)
    with pytest.raises(OpError) as exc:
        session.start(profile=str(tmp_path / "elsewhere"))
    assert exc.value.type == "invalid_op"
    assert connects == []


def test_naming_its_own_profile_is_not_a_change(tmp_path):
    session = shared(tmp_path, [])
    session.refuse_other_profile(str(tmp_path))


def test_attach_needs_playwright(tmp_path):
    with pytest.raises(ValueError):
        BrowserSession(
            profile=tmp_path,
            engine="selenium",
            attach=Attach(lambda: "", lambda: None, lambda: [], TabGate(TabRegistry("p"), "a")),
        )


def test_tab_ownership_ops_need_sessions(tmp_path):
    legacy = BrowserSession(profile=tmp_path, headless=True)
    for call in (lambda: legacy.claim_tab("tab_0"), lambda: legacy.release_tab(None)):
        with pytest.raises(OpError) as exc:
            call()
        assert exc.value.type == "invalid_op"
    assert legacy.foreign_tabs() == []
    legacy.check_tab("tab_0")  # a no-op without sessions


def test_check_tab_refuses_another_sessions_tab(tmp_path):
    session = shared(tmp_path, [])
    session._attach.gate.registry.opened("T1", "b")
    with pytest.raises(OpError) as exc:
        session.check_tab("tab_0")
    assert exc.value.type == "tab_locked"


def test_the_new_ops_are_registered():
    from abt.ops import REGISTRY
    from abt.schema import parse_command

    assert parse_command({"op": "tab_claim", "tab_id": "tab_1"}).tab_id == "tab_1"
    assert parse_command({"op": "tab_release"}).tab_id is None
    assert {"tab_claim", "tab_release"} <= set(REGISTRY)
