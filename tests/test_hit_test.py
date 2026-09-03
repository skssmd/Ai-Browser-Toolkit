"""Known issue #7: a click that reports ok and does nothing.

Selenium judges an element by its own state, not by what is painted over it, so
an overlay could swallow a click while the op reported success. "Succeeded and
changed nothing" is the worst answer an agent can be handed.
"""

from __future__ import annotations

import pytest
from conftest import texts

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


def test_a_covered_click_is_dispatched_and_says_it_was(page):
    """Since 0.4.0 ordinary overlap is reported, not refused.

    The rule that matters is still "never succeed silently", but refusing was a
    blunt way to keep it. A Magento save button covered by its own split-button
    dropdown cost an agent a turn to a refusal, when the click would have
    reached exactly the element it named. So a non-modal cover is now clicked
    through, and the result says what was in the way. A dialog still stops it --
    see the dialog tests below -- because something there is waiting on an
    answer.
    """
    run(page, op="click", css="#reveal-overlay")
    result = run(page, op="click", css="#under")

    assert result["clicked"]
    assert result["forced"] is True
    assert result["forced_past"]


def test_the_result_names_what_would_have_received_the_click(page):
    """The obstacle is still named; it is now an observation, not a refusal."""
    run(page, op="click", css="#reveal-overlay")
    result = run(page, op="click", css="#under")
    assert "blocker" in result["forced_past"]


def test_force_still_clicks_through_an_overlay(page):
    """force exists for exactly this, so the test must not block it."""
    run(page, op="click", css="#reveal-overlay")
    result = run(page, op="click", css="#under", force=True)
    assert result["clicked"]


def test_an_uncovered_click_is_unaffected(page):
    result = run(page, op="click", css="#open")
    assert result["forced"] is False
    assert "Chart" in texts(result["dom_diff"]["text"]["added"])


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
    assert "Chart" in texts(result["dom_diff"]["text"]["added"])


def test_a_cover_that_stays_still_is_reported_not_ignored(page):
    """Patience must not become blindness.

    The check still waits out an animation and still notices a cover that is
    genuinely there. What changed is the answer: the click goes through and the
    cover is named, rather than the command failing. What must never happen is
    the original bug -- succeeding while saying nothing at all.
    """
    run(page, op="click", css="#reveal-overlay")
    result = run(page, op="click", css="#under")
    assert result["forced"] is True
    assert result["forced_past"]


def test_a_click_behind_an_open_dialog_names_the_dialog(page):
    """The refusal is correct; the message is what needed fixing.

    Straight from a live session: an agent clicked Approve, which opened a
    confirmation dialog, then clicked the same ref twice more. Both refusals
    were right -- clicking through would have hit the overlay -- but the message
    read "covered by div.data-[state=open]:animate-in.data-[state=closed]:
    animate-out", which names a Tailwind animation and offers no next step.
    """
    run(page, op="click", css="#approve")
    with pytest.raises(OpError) as caught:
        run(page, op="click", css="#approve")

    message = caught.value.message
    assert caught.value.type == "not_interactable"
    assert "dialog" in message
    assert "Confirm approval" in message
    # The remedy, not just the diagnosis.
    assert "close it" in message


def test_closing_the_dialog_lets_the_click_through(page):
    """Patience must not become blindness, and neither must a better message:
    the block is real until the dialog is gone."""
    run(page, op="click", css="#approve")
    run(page, op="click", css="#modal-cancel")
    assert run(page, op="click", css="#approve")["clicked"]
