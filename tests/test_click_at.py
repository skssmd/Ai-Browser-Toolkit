"""Coordinate clicks: the escape hatch for what the DOM cannot address.

Written after a canvas PDF annotator left the toolkit able to see a control and
unable to act on it.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def canvas(client, base_url):
    client.post("/command", json={"op": "goto", "url": f"{base_url}/canvas.html"})
    return client


def text_of(client, css):
    return client.post("/command", json={"op": "get_text", "css": css}).json()["result"]


def test_a_click_inside_a_canvas_lands_where_asked(canvas):
    body = canvas.post(
        "/command", json={"op": "click", "css": "#pad", "at": [120, 80]}
    ).json()
    assert body["ok"] is True, body
    assert text_of(canvas, "#log") == "hit 120,80"


def test_the_offset_is_relative_to_the_element_not_the_page(canvas):
    """The whole point: [0,0] is the element's corner, wherever the page sits."""
    canvas.post("/command", json={"op": "click", "css": "#pad", "at": [5, 5]})
    assert text_of(canvas, "#log") == "hit 5,5"


def test_an_element_below_the_fold_is_scrolled_to_first(canvas):
    body = canvas.post(
        "/command", json={"op": "click", "css": "#low", "at": [40, 30]}
    ).json()
    assert body["ok"] is True, body
    assert text_of(canvas, "#lowlog") == "low: 40,30"


def test_the_response_says_what_it_hit(canvas):
    body = canvas.post(
        "/command", json={"op": "click", "css": "#pad", "at": [10, 10]}
    ).json()
    assert body["result"]["hit"] == "canvas#pad"
    assert body["result"]["relative_to"] == "css='#pad'"


def test_a_bare_point_is_a_viewport_coordinate(canvas):
    """No target: the numbers mean the viewport."""
    rect = canvas.post(
        "/command",
        json={
            "op": "run_js",
            "script": "const r=document.getElementById('pad').getBoundingClientRect();"
            "return [Math.round(r.left), Math.round(r.top)];",
        },
    ).json()["result"]["value"]
    body = canvas.post(
        "/command", json={"op": "click", "at": [rect[0] + 60, rect[1] + 40]}
    ).json()
    assert body["result"]["relative_to"] == "viewport"
    # Layout positions are fractional and a mouse can only be at whole pixels,
    # so a viewport coordinate is good to about a pixel. That rounding is
    # exactly why the element-relative form above is the one to reach for.
    x, y = (int(n) for n in text_of(canvas, "#log").removeprefix("hit ").split(","))
    assert abs(x - 60) <= 1 and abs(y - 40) <= 1


def test_a_point_off_screen_is_refused(canvas):
    body = canvas.post("/command", json={"op": "click", "at": [99999, 40]}).json()
    assert body["ok"] is False
    assert body["error"]["type"] == "not_interactable"
    assert "viewport" in body["error"]["message"]


def test_a_click_still_needs_a_target_or_a_point(client):
    body = client.post("/command", json={"op": "click"}).json()
    assert body["error"]["type"] == "invalid_op"
    assert "at" in body["error"]["message"]


def test_at_cannot_be_combined_with_force_or_new_tab(client):
    for extra in ({"force": True}, {"new_tab": True}):
        body = client.post(
            "/command", json={"op": "click", "css": "#pad", "at": [1, 1], **extra}
        ).json()
        assert body["error"]["type"] == "invalid_op"


def test_a_coordinate_click_is_a_real_mouse_event(canvas):
    """Not a dispatched event: a page cannot tell it from a person."""
    canvas.post(
        "/command",
        json={
            "op": "run_js",
            "script": "window.__trusted = null;"
            "document.getElementById('pad').addEventListener('click',"
            "  e => { window.__trusted = e.isTrusted; }, {once: true});",
        },
    )
    canvas.post("/command", json={"op": "click", "css": "#pad", "at": [50, 50]})
    trusted = canvas.post(
        "/command", json={"op": "run_js", "script": "return window.__trusted;"}
    ).json()["result"]["value"]
    assert trusted is True
