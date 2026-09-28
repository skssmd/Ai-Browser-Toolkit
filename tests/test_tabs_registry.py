"""Tab ownership per profile. Pure bookkeeping, no browser."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.tabs import LOCKED, OWN, UNOWNED, TabGate, TabRegistry


@pytest.fixture
def reg():
    return TabRegistry("work")


def test_labels_are_stable_and_never_reissued(reg):
    assert reg.label("T1") == "tab_0"
    assert reg.label("T1") == "tab_0"
    assert reg.label("T2") == "tab_1"
    reg.forget("T1")
    assert reg.target_of("tab_0") is None
    assert reg.label("T3") == "tab_2"
    reg.clear()
    assert reg.label("T4") == "tab_3"


def test_a_tab_a_session_opened_is_its_own(reg):
    assert reg.opened("T1", "a") == "tab_0"
    assert reg.access("T1", "a") == OWN
    assert reg.access("T1", "b") == LOCKED


def test_opening_a_tab_someone_else_owns_is_refused(reg):
    reg.opened("T1", "a")
    with pytest.raises(OpError) as exc:
        reg.opened("T1", "b")
    assert exc.value.type == "tab_locked"
    assert "'a'" in exc.value.message


def test_a_popup_follows_its_openers_owner(reg):
    reg.opened("T1", "a")
    assert reg.adopt("POP", opener="T1") == "a"
    assert reg.owned_by("a") == ["T1", "POP"]


def test_a_page_with_no_owned_opener_starts_unowned(reg):
    assert reg.adopt("T9", opener=None) is None
    assert reg.access("T9", "a") == UNOWNED


def test_adopt_never_moves_a_placed_tab(reg):
    reg.opened("T1", "a")
    reg.opened("T2", "b")
    assert reg.adopt("T1", opener="T2") == "a"


def test_an_unowned_tab_can_be_claimed(reg):
    reg.adopt("T9", None)
    assert reg.claim("T9", "a") == "tab_0"
    assert reg.owner_of("T9") == "a"


def test_claiming_a_locked_tab_names_the_owner(reg):
    reg.opened("T1", "a")
    with pytest.raises(OpError) as exc:
        reg.claim("T1", "b")
    assert exc.value.type == "tab_locked"


def test_nobody_can_claim_someone_elses_popup_first(reg):
    """The window between a popup appearing and its owner noticing it."""
    reg.opened("T1", "a")
    with pytest.raises(OpError) as exc:
        reg.claim("POP", "b", opener="T1")
    assert exc.value.type == "tab_locked"
    assert reg.owner_of("POP") == "a"


def test_only_the_owner_can_release(reg):
    reg.opened("T1", "a")
    with pytest.raises(OpError):
        reg.release("T1", "b")
    reg.release("T1", "a")
    assert reg.owner_of("T1") is None


def test_the_operator_overrides_without_checks(reg):
    reg.opened("T1", "a")
    reg.set_owner("T1", "b")
    assert reg.owner_of("T1") == "b"


def test_gate_check_refuses_locked_and_unowned_and_passes_unknown(reg):
    reg.opened("T1", "a")
    reg.adopt("T2", None)
    gate = TabGate(reg, "b")
    for label in ("tab_0", "tab_1"):
        with pytest.raises(OpError) as exc:
            gate.check(label)
        assert exc.value.type == "tab_locked"
    gate.check("tab_99")  # unknown here: the session reports it as not found
    TabGate(reg, "a").check("tab_0")


def test_gate_sees_only_its_own(reg):
    reg.opened("T1", "a")
    assert TabGate(reg, "a").sees("T1", None) is True
    assert TabGate(reg, "b").sees("T1", None) is False
    assert TabGate(reg, "b").sees("POP", "T1") is False
    assert TabGate(reg, "a").sees("POP", "T1") is True
