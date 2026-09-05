"""Tab ids must stay stable and each tab keeps its own refs."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def test_new_tab_with_url_becomes_active(clean_session, base_url):
    result = run(clean_session, op="tab_new", url=f"{base_url}/form.html")
    assert len(result["tabs"]) == 2
    assert run(clean_session, op="current_url")["title"] == "Form"


def test_new_tab_without_activate_leaves_you_put(clean_session, base_url):
    run(clean_session, op="tab_new", url=f"{base_url}/form.html", activate=False)
    assert run(clean_session, op="current_url")["title"] == "Cards"


def test_tab_list_marks_exactly_one_active(clean_session, base_url):
    run(clean_session, op="tab_new", url=f"{base_url}/form.html")
    tabs = run(clean_session, op="tab_list")
    assert [t["active"] for t in tabs].count(True) == 1
    assert {t["title"] for t in tabs} == {"Cards", "Form"}


def test_switch_between_tabs(clean_session, base_url):
    first = clean_session.active_tab
    second = run(clean_session, op="tab_new", url=f"{base_url}/form.html")["tab_id"]
    assert run(clean_session, op="tab_switch", tab_id=first)["title"] == "Cards"
    assert run(clean_session, op="tab_switch", tab_id=second)["title"] == "Form"



def test_close_tab_activates_a_neighbour(clean_session, base_url):
    second = run(clean_session, op="tab_new", url=f"{base_url}/form.html")["tab_id"]
    result = run(clean_session, op="tab_close", tab_id=second)
    assert result["active_tab"] != second
    assert len(result["tabs"]) == 1


def test_close_defaults_to_the_active_tab(clean_session, base_url):
    run(clean_session, op="tab_new", url=f"{base_url}/form.html")
    assert len(run(clean_session, op="tab_close")["tabs"]) == 1


def test_closing_the_last_tab_is_refused(clean_session):
    with pytest.raises(OpError) as caught:
        run(clean_session, op="tab_close")
    assert caught.value.type == "last_tab"


def test_switching_to_an_unknown_tab_errors(clean_session):
    with pytest.raises(OpError) as caught:
        run(clean_session, op="tab_switch", tab_id="tab_999")
    assert caught.value.type == "tab_not_found"
