"""Content inside a frame is content. The snapshot must not go silent on it.

Found on linkedin.com/login. Google Identity Services draws "Continue with
Google" inside a cross-origin frame from accounts.google.com, and the One Tap
card in a second one. The button was plainly on screen -- a screenshot showed
it -- while `find text:"Google"` returned zero matches and `get_text` returned
a page with no Google anywhere in it.

Nothing failed. No error, no warning, no truncation notice: the toolkit was
asked what was on the page and confidently answered with a page that was
missing its primary control. That is worse than an error, because an error is
something an agent can react to and an empty answer is something it believes.

The cause is that a frame is a separate document. `document.body`'s TreeWalker
treats an `<iframe>` as a leaf, `innerText` stops at the boundary, and
`find_element` only ever searches the frame the driver is currently in -- so
every one of the three tracks was blind in the same place at the same time.

These tests cover both sides of the boundary, and the cross-origin ones are the
point: recursing into `contentDocument` from the snapshot script passes every
same-origin test here and still fails on the page this was reported from.
"""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def added(result):
    return result["dom_diff"]["text"]["added"]


@pytest.fixture
def one_tab(session):
    for tab in list(session.tabs()):
        if not tab["active"]:
            session.close_tab(tab["tab_id"])
    return session


@pytest.fixture
def framed(one_tab, base_url):
    run(one_tab, op="goto", url=f"{base_url}/frames.html")
    return one_tab


@pytest.fixture
def cross(one_tab, base_url, other_origin):
    run(one_tab, op="goto", url=f"{base_url}/frames_cross.html?origin={other_origin}")
    return one_tab


# --- is the hard case actually the hard case ----------------------------------


def test_the_cross_origin_fixture_is_genuinely_cross_origin(cross):
    """Guards the tests, not the code.

    Every cross-origin test below would also pass against a same-origin frame,
    and a same-origin frame can be read from the parent with four lines of
    JavaScript -- the fix that looks right, passes, and does nothing for the
    page this was reported from. So prove the boundary is real: if the browser
    ever let the parent read this frame, these tests would stop meaning what
    they say and this one would say so.
    """
    reachable = cross.driver.execute_script(
        "try { return !!document.querySelector('iframe').contentDocument; }"
        "catch (e) { return false; }"
    )
    assert reachable is False


@pytest.fixture
def swapped(one_tab, base_url):
    run(one_tab, op="goto", url=f"{base_url}/frames_order.html")
    return one_tab


def test_the_two_frame_orderings_really_do_disagree(swapped):
    """Guards the tests again: no mismatch, no test.

    If Chrome ever orders `window.frames` in document order, this fixture stops
    reproducing the LinkedIn failure and the test below starts passing for the
    wrong reason. Assert the premise rather than trust it.
    """
    slots = swapped.driver.execute_script(
        "return [...document.querySelectorAll('iframe')].map((f) => {"
        "  for (let k = 0; k < window.length; k++) {"
        "    if (window[k] === f.contentWindow) return k;"
        "  } return -1; });"
    )
    assert slots == [1, 0], f"expected the orders to be swapped, got {slots}"


def test_a_frame_is_entered_by_document_position_not_context_position(swapped):
    """The bug that survived every other test, found on the live page.

    A frame picked out in one ordering and entered in the other lands in a
    different document and says nothing about it -- here, the walk would skip
    the 0x0 boot frame, then enter it anyway and report its contents as the
    page while the real button stayed invisible.
    """
    text = run(swapped, op="get_text")

    assert "Continue with Google" in text
    assert "gis provider button boot" not in text


def test_a_ref_lands_in_the_right_document_when_the_orders_disagree(swapped):
    """And acting on it hits the button, not whatever else was at that index."""
    ref = run(swapped, op="find", css="#google")["matches"][0]["ref"]

    assert "Signed in as Shahariar" in added(run(swapped, op="click", ref=ref))


# --- the reported bug ---------------------------------------------------------


def test_find_reaches_a_control_inside_a_cross_origin_frame(cross):
    """The reported failure, exactly: zero matches for a visible button."""
    result = run(cross, op="find", css="#google")

    assert result["count"] == 1
    assert "Continue with Google" in run(cross, op="find_full", css="#google")[
        "matches"
    ][0]["html"]


def test_find_by_text_reaches_into_a_frame_too(cross):
    """Text is the anchor an agent actually has, so it must cross the boundary.

    An exact-text match picks up the ancestors whose whole text is that string
    as well -- the same on any page, frame or not -- so what matters here is
    that the search reached the other document at all.
    """
    assert run(cross, op="find", text="Continue with Google")["count"] >= 1


def test_get_text_reports_a_cross_origin_frames_content(cross):
    """`get_text` was the read that convinced me the button did not exist."""
    text = run(cross, op="get_text")

    assert "Continue with Google" in text
    assert "Sign in with Microsoft" in text  # the host document still reports


def test_a_cross_origin_frames_text_reaches_the_text_track(cross, base_url):
    """The diff is the thing being protected; it must see the boundary too."""
    text = added(run(cross, op="reload"))

    assert "Continue with Google" in text


# --- acting on what was found -------------------------------------------------


def test_a_ref_from_a_frame_can_be_clicked(cross):
    """Finding it is half the fix. A ref that cannot be acted on is a tease.

    The ref names an element in another document, so the click has to remember
    which frame that was and go back to it.
    """
    ref = run(cross, op="find", css="#google")["matches"][0]["ref"]

    result = run(cross, op="click", ref=ref)

    assert result["clicked"]
    assert "Signed in as Shahariar" in added(result)


def test_a_frame_can_be_clicked_by_text_without_a_ref(framed):
    """The other way round: target it directly, no find first."""
    result = run(framed, op="click", css="#google")

    assert result["clicked"]
    assert "Signed in as Shahariar" in added(result)


def test_a_ref_from_a_frame_still_dies_when_the_page_navigates(cross, base_url):
    """The stale_ref guarantee is not weaker inside a frame."""
    ref = run(cross, op="find", css="#google")["matches"][0]["ref"]
    run(cross, op="goto", url=f"{base_url}/cards.html")

    with pytest.raises(OpError) as caught:
        run(cross, op="click", ref=ref)
    assert caught.value.type == "stale_ref"


# --- the actionable track -----------------------------------------------------


# Give the 0x0 frame a size. Its document is already loaded, so its controls
# become reachable the moment it is on screen -- which is how a dialog or a
# dropdown drawn in a frame arrives in practice.
_REVEAL = (
    "const f = document.getElementById('preload');"
    "f.style.width = '420px'; f.style.height = '60px';"
)


def _controls(result):
    return result["dom_diff"].get("actionable", {}).get("added", [])


def test_a_control_inside_a_frame_reaches_the_actionable_track(framed):
    """Text says what appeared; actionable says which of it can be clicked."""
    result = run(framed, op="run_js", script=_REVEAL)

    assert "Continue with Google" in [e["name"] for e in _controls(result)]


def test_a_control_replaced_by_its_twin_in_a_frame_is_still_reported(
    one_tab, base_url
):
    """Which document a control is in is part of what identifies it.

    The page drops its own button and reveals the widget's identical one. Role,
    name and tag are the same on both, so if the key stops there the two are
    one control that never changed -- the diff reports nothing, hands out no
    ref, and the only button on the page is one the agent was never told about.

    Silence is the failure mode that matters here, which is why this asserts on
    a swap rather than on an appearance: revealing a second control alongside
    the first reports correctly either way, and proves nothing.
    """
    run(one_tab, op="goto", url=f"{base_url}/frames_swap.html")

    controls = _controls(run(one_tab, op="run_js", script="window.swap();"))

    ref = next(
        (e["ref"] for e in controls if e["name"] == "Continue with Google"), None
    )
    assert ref is not None, "the swap went unreported"
    # And the ref has to be the frame's button, not the one just removed.
    assert "Signed in as Shahariar" in added(run(one_tab, op="click", ref=ref))


def test_a_ref_from_the_actionable_track_clicks_the_right_element(framed):
    """A frame ref handed out by the diff must act like one handed out by find."""
    revealed = _controls(run(framed, op="run_js", script=_REVEAL))
    ref = next(e["ref"] for e in revealed if e["name"] == "Continue with Google")

    assert "Signed in as Shahariar" in added(run(framed, op="click", ref=ref))


# --- what must not be walked --------------------------------------------------


def test_a_zero_sized_frame_is_not_walked(framed):
    """Google mounts a 0x0 preload beside the real button; so does this page.

    Nobody can see or click it, and walking it costs a round trip to report a
    duplicate of the frame next to it.
    """
    assert framed.frame_paths() == [(0,)]


def test_only_the_visible_frames_control_is_offered(framed):
    """Two identical buttons exist; exactly one of them is reachable."""
    assert run(framed, op="find", css="#google")["count"] == 1


def test_the_host_document_is_reported_before_its_frames(framed):
    """Reading order is the page's order; a frame's content is not hoisted."""
    text = run(framed, op="get_text")

    assert text.index("Sign in with Microsoft") < text.index("Continue with Google")


# --- the diff must not regress ------------------------------------------------


def test_a_page_with_no_frames_is_unaffected(one_tab, base_url):
    """The frame walk costs nothing on the overwhelming majority of pages."""
    result = run(one_tab, op="goto", url=f"{base_url}/cards.html")
    assert result["dom_diff"]["text"]["added"]


def test_the_top_document_still_diffs_in_place(framed):
    """A change in the host document reports as before, not as a whole page."""
    result = run(
        framed,
        op="run_js",
        script="document.body.insertAdjacentHTML('beforeend', '<p>Two-factor required</p>');",
    )
    assert added(result) == ["Two-factor required"]


def test_the_driver_is_left_at_the_top_after_a_frame_walk(framed):
    """A leaked frame context would silently retarget every later command.

    Nothing in the ops layer says "and now go back"; if the walk does not put
    the driver back itself, the next `run_js` evaluates in whichever frame the
    snapshot happened to finish in.
    """
    run(framed, op="find", text="Continue with Google")
    where = run(framed, op="run_js", script="return document.title;")

    assert where["value"] == "a page whose controls are not all its own"


def test_frames_can_be_turned_off(framed):
    """An escape hatch, for a page whose frames are ads and cost real time."""
    framed.frames_enabled = False
    try:
        assert run(framed, op="find", text="Continue with Google")["count"] == 0
    finally:
        framed.frames_enabled = True
