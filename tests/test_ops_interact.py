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


@pytest.fixture
def controlled(clean_session, base_url):
    clean_session.goto(f"{base_url}/controlled.html")
    return clean_session


def test_input_replaces_text_in_a_controlled_input(controlled):
    # clear() fires `change` and no `input`, so a component that tracks the
    # field from `input` events never learns it was emptied -- it re-renders the
    # old text back before the first keystroke lands, and the typing appends to
    # text that was supposed to be gone. Traced live on LinkedIn's industry
    # field, where every retry silently concatenated onto the last one.
    result = run(controlled, op="input", css="#controlled", value="typed")
    assert result["value"] == "typed"
    assert run(controlled, op="get_text", css="#state") == "typed"


def test_input_replaces_text_when_only_real_keystrokes_count(clean_session, base_url):
    # Some components ignore anything with isTrusted false, which defeats the
    # scripted clear too. What is left is the concatenation -- old text plus new
    # -- and typing it again through keystrokes is the only way out.
    clean_session.goto(f"{base_url}/controlled_trusted.html")
    result = run(clean_session, op="input", css="#controlled", value="typed")
    assert result["value"] == "typed"
    assert run(clean_session, op="get_text", css="#state") == "typed"


def test_input_can_still_append_to_a_controlled_input(controlled):
    result = run(controlled, op="input", css="#controlled", value="more", clear=False)
    assert result["value"] == "presetmore"


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


def test_input_reports_the_value_it_wrote_to_a_contenteditable(form):
    # A div has no value attribute, so a successful write must not report null.
    result = run(form, op="input", css="#rich", value="written")
    assert result["value"] == "written"


def test_input_still_reports_value_for_form_controls(form):
    assert run(form, op="input", css="#name", value="plain")["value"] == "plain"


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


# --- input sets whatever a control holds ---------------------------------------
#
# `input` is the one op for "put this value in there". It used to mean only
# "type this text", so on a <select> it fell through to send_keys -- which the
# browser answers with its own typeahead, landing on the wrong option for a
# value that prefixes two of them and on nothing for one spelled differently,
# while the op reported the value as written either way. A box and a radio were
# worse: nothing happened at all, still reported as success. Silent wrong
# beats loud wrong nowhere, so each of these now either sets the value or says
# it could not.


@pytest.fixture
def valued(clean_session, base_url):
    clean_session.goto(f"{base_url}/valued.html")
    return clean_session


def test_input_sets_a_select_by_option_text(valued):
    result = run(valued, op="input", css="#country", value="Germany")
    assert result["selected"] == "Germany"
    assert result["value"] == "de"


def test_input_sets_a_select_by_underlying_value(valued):
    """A caller holding the code rather than the label is still understood."""
    assert run(valued, op="input", css="#country", value="uk")["selected"] == (
        "United Kingdom"
    )


def test_input_on_a_select_names_the_options_it_has(valued):
    with pytest.raises(OpError) as caught:
        run(valued, op="input", css="#country", value="Atlantis")
    assert caught.value.type == "element_not_found"
    assert "United Kingdom" in caught.value.hint


def test_input_ticks_a_checkbox(valued):
    result = run(valued, op="input", css="#agree", value="true")
    assert (result["checked"], result["changed"]) == (True, True)


def test_input_unticks_a_checkbox(valued):
    assert run(valued, op="input", css="#preset", value="false")["checked"] is False


def test_setting_a_checkbox_to_what_it_already_is_does_nothing(valued):
    """Clicking unconditionally would turn off the box it was asked to turn on."""
    result = run(valued, op="input", css="#preset", value="true")
    assert (result["checked"], result["changed"]) == (True, False)


def test_input_selects_a_radio(valued):
    assert run(valued, op="input", css="#ship-fast", value="true")["checked"] is True


def test_a_radio_cannot_be_switched_off(valued):
    with pytest.raises(OpError) as caught:
        run(valued, op="input", css="#ship-std", value="false")
    assert caught.value.type == "invalid_op"
    assert "Set the radio you do want" in caught.value.hint


def test_a_box_is_not_a_text_field(valued):
    with pytest.raises(OpError) as caught:
        run(valued, op="input", css="#agree", value="ada")
    assert caught.value.type == "invalid_op"
    assert '"true" or "false"' in caught.value.hint
