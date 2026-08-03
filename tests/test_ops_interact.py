"""Clicking, typing, native selects, hover-driven menus, waiting, key presses."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


@pytest.fixture
def form(clean_session, base_url):
    clean_session.goto(f"{base_url}/form.html")
    return clean_session


@pytest.fixture
def nav(clean_session, base_url):
    clean_session.goto(f"{base_url}/nav.html")
    return clean_session


def test_input_then_click_updates_the_page(form):
    run(form, op="input", css="#name", value="ada")
    run(form, op="click", css="#go")
    assert run(form, op="get_text", css="#out") == "ada/m"


def test_input_clears_by_default(form):
    run(form, op="input", css="#name", value="first")
    result = run(form, op="input", css="#name", value="second")
    assert result["value"] == "second"


def test_input_can_append(form):
    run(form, op="input", css="#name", value="ab")
    result = run(form, op="input", css="#name", value="cd", clear=False)
    assert result["value"] == "abcd"


def test_input_replaces_text_in_a_contenteditable(form):
    # clear() does not apply to contenteditable, so without a fallback the second
    # write appends and the field silently accumulates.
    run(form, op="input", css="#rich", value="first")
    run(form, op="input", css="#rich", value="second")
    assert run(form, op="get_text", css="#rich") == "second"


def test_input_can_append_to_a_contenteditable(form):
    run(form, op="input", css="#rich", value="one")
    run(form, op="input", css="#rich", value="two", clear=False)
    assert run(form, op="get_text", css="#rich") == "onetwo"


def test_select_by_visible_text(form):
    result = run(form, op="select", css="#size", by_text="Large")
    assert result["selected"] == "Large"
    assert result["value"] == "l"


def test_select_by_value(form):
    assert run(form, op="select", css="#size", value="s")["selected"] == "Small"


def test_select_by_index(form):
    assert run(form, op="select", css="#size", option_index=0)["value"] == "s"


def test_select_flows_into_the_form_result(form):
    run(form, op="input", css="#name", value="bob")
    run(form, op="select", css="#size", value="l")
    run(form, op="click", css="#go")
    assert run(form, op="get_text", css="#out") == "bob/l"


def test_select_on_a_non_select_errors(form):
    with pytest.raises(OpError) as caught:
        run(form, op="select", css="#name", value="s")
    assert caught.value.type == "not_a_select"
    assert "hover then click" in caught.value.message


def test_select_unknown_option_errors(form):
    with pytest.raises(OpError) as caught:
        run(form, op="select", css="#size", value="xxl")
    assert caught.value.type == "element_not_found"


def test_press_enter_in_a_field(form):
    run(form, op="input", css="#name", value="x")
    run(form, op="press", css="#name", key="Enter")
    assert run(form, op="get_text", css="#keyed") == "entered"


def test_press_rejects_an_unknown_key_name(form):
    with pytest.raises(OpError) as caught:
        run(form, op="press", css="#name", key="Squiggle")
    assert caught.value.type == "invalid_op"


def test_clicking_a_disabled_button_is_not_interactable(form):
    with pytest.raises(OpError) as caught:
        run(form, op="click", css="#disabled-btn")
    assert caught.value.type == "not_interactable"


def test_clicking_a_missing_element_errors(form):
    with pytest.raises(OpError) as caught:
        run(form, op="click", css="#ghost")
    assert caught.value.type == "element_not_found"


def test_hover_reveals_a_dropdown_then_click_selects(nav):
    assert run(nav, op="find", css="#widgets", visible_only=True)["count"] == 0
    run(nav, op="hover", css="#products")
    assert run(nav, op="find", css="#widgets", visible_only=True)["count"] == 1
    run(nav, op="click", css="#widgets")
    assert run(nav, op="get_text", css="#chosen") == "widgets"


def test_wait_for_visible_on_delayed_content(clean_session, base_url):
    clean_session.goto(f"{base_url}/delayed.html")
    result = run(clean_session, op="wait_for", css="#late", state="visible", timeout=5)
    assert result["state"] == "visible"
    assert run(clean_session, op="get_text", css="#late") == "arrived"


def test_press_chord_applies_modifier(form):
    run(form, op="click", css="#name")
    run(form, op="press", key="shift+a")
    value = run(
        form,
        op="run_js",
        script="return document.getElementById('name').value;",
        diff=False,
    )["value"]
    assert value == "A"


def test_press_chord_with_unknown_modifier_errors(form):
    with pytest.raises(OpError) as caught:
        run(form, op="press", key="super+x")
    assert caught.value.type == "invalid_op"


def test_wait_for_absent(clean_session, base_url):
    clean_session.goto(f"{base_url}/delayed.html")
    result = run(clean_session, op="wait_for", css="#placeholder", state="absent", timeout=5)
    assert result["state"] == "absent"


def test_wait_for_times_out(clean_session):
    with pytest.raises(OpError) as caught:
        run(clean_session, op="wait_for", css="#never", state="visible", timeout=1)
    assert caught.value.type == "element_not_found"


def test_scroll_to_element_and_to_offset(clean_session):
    assert run(clean_session, op="scroll", css="#p2")["scrolled_to"] == "css='#p2'"
    assert run(clean_session, op="scroll", y=0)["scrolled_to"] == 0


def test_index_picks_a_later_match(clean_session):
    result = run(clean_session, op="get_html", css=".card", index=1)
    assert 'id="p2"' in result
