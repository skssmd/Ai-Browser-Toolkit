"""Known issue #7: a click that reports ok and does nothing.

Selenium judges an element by its own state, not by what is painted over it, so
an overlay could swallow a click while the op reported success. "Succeeded and
changed nothing" is the worst answer an agent can be handed.
"""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.schema import parse_command
from abt.ops import dispatch


def run(session, **payload):
    return dispatch(session, parse_command(payload))


@pytest.fixture
def page(session, base_url):
    for tab in list(session.tabs()):
        if not tab["active"]:
            session.close_tab(tab["tab_id"])
    session.goto(f"{base_url}/actionable.html")
    session.set_baseline()
    return session


def test_a_covered_click_fails_loudly_instead_of_silently(page):
    run(page, op="click", css="#reveal-overlay")

    with pytest.raises(OpError) as caught:
        run(page, op="click", css="#under")

    assert caught.value.type == "not_interactable"
    assert "blocker" in caught.value.message


def test_the_error_names_what_would_have_received_the_click(page):
    run(page, op="click", css="#reveal-overlay")
    with pytest.raises(OpError) as caught:
        run(page, op="click", css="#under")
    assert "covered by" in caught.value.message


def test_force_still_clicks_through_an_overlay(page):
    """force exists for exactly this, so the test must not block it."""
    run(page, op="click", css="#reveal-overlay")
    result = run(page, op="click", css="#under", force=True)
    assert result["clicked"]


def test_an_uncovered_click_is_unaffected(page):
    result = run(page, op="click", css="#open")
    assert result["forced"] is False
    assert "Chart" in result["dom_diff"]["text"]["added"]


def test_a_cover_that_is_animating_away_does_not_fail_the_click(page):
    """The regression that cost a live run seven minutes.

    Component libraries animate dialogs and popovers out, so for a few hundred
    milliseconds the target really is behind an overlay -- one already leaving.
    Sampling elementFromPoint once turned every such transition into a failure
    that succeeded on the very next identical command. The check now polls, so
    it outlasts the animation instead of racing it.
    """
    run(page, op="click", css="#flash-overlay")
    result = run(page, op="click", css="#open")

    assert result["clicked"]
    assert "Chart" in result["dom_diff"]["text"]["added"]


def test_a_cover_that_stays_still_fails(page):
    """Patience must not become blindness: a real overlay still stops a click."""
    run(page, op="click", css="#reveal-overlay")
    with pytest.raises(OpError) as caught:
        run(page, op="click", css="#under")
    assert caught.value.type == "not_interactable"
    assert "still covered by" in caught.value.message
