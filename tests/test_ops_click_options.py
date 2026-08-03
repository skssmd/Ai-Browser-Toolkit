"""click's two opt-in behaviours: force past an overlay, and open in a new tab."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


@pytest.fixture
def overlay(clean_session, base_url):
    clean_session.goto(f"{base_url}/overlay.html")
    return clean_session


@pytest.fixture
def links(clean_session, base_url):
    clean_session.goto(f"{base_url}/links.html")
    return clean_session


# --- force --------------------------------------------------------------------


def test_plain_click_reports_interception(overlay):
    with pytest.raises(OpError) as caught:
        run(overlay, op="click", css="#link")
    assert caught.value.type == "not_interactable"
    assert "hijack" in caught.value.message


def test_the_overlay_really_would_have_stolen_the_click(overlay):
    # Proves the fixture reproduces the hijack rather than merely failing.
    run(overlay, op="click", css="#hijack")
    assert run(overlay, op="get_text", css="#out") == "hijacked"


def test_force_click_reaches_the_covered_link(overlay):
    result = run(overlay, op="click", css="#link", force=True)
    assert result["forced"] is True
    assert run(overlay, op="get_text", css="#out") == "link"


def test_force_is_not_used_when_the_click_lands_normally(links):
    result = run(links, op="click", css="#to-cards", force=True)
    assert result["forced"] is False
    assert result["title"] == "Cards"


def test_force_still_refuses_a_disabled_control(overlay):
    with pytest.raises(OpError) as caught:
        run(overlay, op="click", css="#disabled-btn", force=True)
    assert caught.value.type == "not_interactable"
    assert run(overlay, op="get_text", css="#out") == ""


def test_force_defaults_off():
    assert parse_command({"op": "click", "css": "a"}).force is False


def test_plain_click_refuses_a_visually_hidden_control(overlay):
    # Google's signup radios look like this: real input hidden, styled proxy shown.
    with pytest.raises(OpError) as caught:
        run(overlay, op="click", css="#fancy")
    assert caught.value.type in ("not_interactable", "element_not_found")


def test_force_clicks_a_visually_hidden_control(overlay):
    # force must skip the visibility gate, not just retry after a failed click --
    # a zero-size input never becomes "clickable", so the gate is where it dies.
    result = run(overlay, op="click", css="#fancy", force=True)
    assert result["forced"] is True
    assert run(overlay, op="get_text", css="#out") == "fancy"


def test_force_still_reports_a_missing_element(overlay):
    with pytest.raises(OpError) as caught:
        run(overlay, op="click", css="#not-here", force=True)
    assert caught.value.type == "element_not_found"


# --- new_tab ------------------------------------------------------------------


def test_new_tab_opens_the_link_beside_the_current_page(links):
    origin = links.active_tab
    result = run(links, op="click", css="#to-cards", new_tab=True)

    assert result["tab_id"] != origin
    assert result["title"] == "Cards"
    tabs = {t["tab_id"]: t for t in run(links, op="tab_list")}
    assert len(tabs) == 2
    assert tabs[origin]["title"] == "Links"  # the original page is untouched


def test_new_tab_without_activate_leaves_you_on_the_page(links):
    origin = links.active_tab
    run(links, op="click", css="#to-cards", new_tab=True, activate=False)
    assert links.active_tab == origin
    assert run(links, op="current_url")["title"] == "Links"


def test_new_tab_needs_an_href(links):
    with pytest.raises(OpError) as caught:
        run(links, op="click", css="h1", new_tab=True)
    assert caught.value.type == "not_interactable"
    assert "href" in caught.value.message


def test_new_tab_sidesteps_an_overlay_without_force(overlay):
    # Reading the href never touches the hijack layer.
    result = run(overlay, op="click", css="#link", new_tab=True)
    assert result["tab_id"] is not None
    assert result["url"].endswith("#reached")


def test_new_tab_and_force_are_mutually_exclusive():
    from abt.errors import OpError as E

    with pytest.raises(E) as caught:
        parse_command({"op": "click", "css": "a", "new_tab": True, "force": True})
    assert caught.value.type == "invalid_op"
