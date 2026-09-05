"""XPath literal quoting has no escape character to lean on, so it gets its own test."""

from __future__ import annotations

from abt.targeting import xpath_literal


def test_plain_string():
    assert xpath_literal("hello") == "'hello'"


def test_string_with_apostrophe():
    assert xpath_literal("it's") == '"it\'s"'


def test_string_with_double_quote():
    assert xpath_literal('say "hi"') == "'say \"hi\"'"


def test_string_with_both_quotes():
    result = xpath_literal("he said \"it's fine\"")
    assert result.startswith("concat(")
    assert "\"'\"" in result


# --- near: qualifying a selector that matches many ----------------------------
#
# Driving a real admin app, an agent spent 14 of its 33 `run_js` calls stamping
# an attribute onto the right table row so it could click that row's Edit
# button by CSS -- and one of those attempts failed, leaving a selector that
# matched nothing, which it then retried ten times. `near` is that whole dance,
# as one field.

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


@pytest.fixture
def rows(session, base_url):
    session.goto(f"{base_url}/repeated.html")
    run(session, op="click", css="#show")
    return session


@pytest.mark.parametrize(
    "near, expected",
    [("Medication", "Medication"), ("Passport", "Passport"),
     ("Safeguarding policy", "Safeguarding policy")],
)
def test_near_picks_the_row_it_names(rows, near, expected):
    """Three buttons, one name, and the row is the only thing telling them
    apart -- which is exactly the case that used to need JavaScript."""
    run(rows, op="click", text="Edit", near=near)
    row = run(rows, op="run_js",
              script="return document.activeElement.closest('tr').firstElementChild.textContent;")
    assert row["value"] == expected


def test_near_works_without_a_table(rows):
    """The climb walks ancestors; it does not know what a row is."""
    run(rows, op="click", text="Open", near="Shipping")
    got = run(rows, op="run_js",
              script="return document.activeElement.closest('section')"
                     ".querySelector('h4').textContent;")
    assert got["value"] == "Shipping"


def test_a_near_that_matches_nothing_says_what_was_there(rows):
    """The error is the whole interface at that moment, so it lists the
    qualifiers that *do* exist rather than only reporting a miss."""
    with pytest.raises(OpError) as caught:
        run(rows, op="click", text="Edit", near="Dentistry")
    message = caught.value.message
    assert caught.value.type == "element_not_found"
    assert "Dentistry" in message
    assert "Medication" in message.lower() or "medication" in message.lower()



def test_near_combines_with_css_too(rows):
    """Not just text targeting -- any selector that matches too much."""
    run(rows, op="click", css="button", near="Billing")
    got = run(rows, op="run_js",
              script="return document.activeElement.closest('section')"
                     ".querySelector('h4').textContent;")
    assert got["value"] == "Billing"
