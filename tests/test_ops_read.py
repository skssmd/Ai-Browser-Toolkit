"""Reading ops against real pages, including the shell-vs-full distinction."""

from __future__ import annotations

import base64

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def test_get_html_returns_whole_document(clean_session):
    html = run(clean_session, op="get_html")
    assert "<h1>Catalogue</h1>" in html
    assert 'id="p1"' in html


def test_get_html_of_one_element(clean_session):
    html = run(clean_session, op="get_html", css="#p1")
    assert html.startswith('<div class="card" id="p1"')
    assert "Cheap Widget" in html


def test_get_text_strips_markup(clean_session):
    text = run(clean_session, op="get_text", css="#p1")
    assert "Cheap Widget" in text
    assert "$4.99" in text
    assert "<" not in text


def test_find_shell_drops_inner_content(clean_session):
    result = run(clean_session, op="find", css=".card")
    assert result["count"] == 3
    assert result["truncated"] is False
    shells = [m["html"] for m in result["matches"]]
    assert shells[0] == '<div class="card" id="p1" data-price="4.99"></div>'
    for shell in shells:
        assert "Widget" not in shell
        assert "$" not in shell


def test_find_full_keeps_inner_content(clean_session):
    result = run(clean_session, op="find_full", css=".card")
    assert "Cheap Widget" in result["matches"][0]["html"]
    assert "$4.99" in result["matches"][0]["html"]


def test_find_mode_full_matches_find_full(clean_session):
    a = run(clean_session, op="find", css="#p1", mode="full")
    b = run(clean_session, op="find_full", css="#p1")
    assert a["matches"][0]["html"] == b["matches"][0]["html"]


def test_find_reports_visibility(clean_session):
    result = run(clean_session, op="find", css=".card")
    visible = {m["html"]: m["visible"] for m in result["matches"]}
    assert [v for k, v in visible.items() if 'id="p3"' in k] == [False]


def test_visible_only_filters_hidden(clean_session):
    result = run(clean_session, op="find", css=".card", visible_only=True)
    assert result["count"] == 2


def test_limit_truncates_and_flags(clean_session):
    result = run(clean_session, op="find", css=".card", limit=2)
    assert result["count"] == 2
    assert result["truncated"] is True


def test_find_by_exact_text(clean_session):
    result = run(clean_session, op="find", text="Cheap Widget")
    assert result["count"] >= 1
    assert "h2" in result["matches"][-1]["html"]


def test_find_by_text_containing_both_quote_types(clean_session):
    result = run(clean_session, op="find", text="He said \"it's fine\" loudly")
    assert result["count"] == 1
    assert result["matches"][0]["html"] == '<p id="quoted"></p>'


def test_find_no_match_is_empty_not_an_error(clean_session):
    result = run(clean_session, op="find", css=".nope")
    assert result == {"count": 0, "truncated": False, "matches": []}


def test_get_html_missing_element_errors(clean_session):
    with pytest.raises(OpError) as caught:
        run(clean_session, op="get_html", css=".nope")
    assert caught.value.type == "element_not_found"


def test_screenshot_names_a_file_rather_than_inlining_one(clean_session):
    """The default reply carries no image, on purpose.

    An agent reading tool output as text cannot see an inlined image, and a
    viewport frame is 100KB-1MB before base64 adds a third -- one observed
    session spent six minutes chewing through a single frame and ended with
    the agent trying to save the image itself. The server writes a frame for
    every command anyway, so the op points at that file instead of carrying
    its own copy. `path` is added by the server, which owns the recorder, so
    it is absent at this layer.
    """
    result = run(clean_session, op="screenshot")
    assert result["format"] == "jpeg"
    assert "base64" not in result


def test_screenshot_still_inlines_when_asked(clean_session):
    """base64 is opt-in now, and is still PNG when it is."""
    result = run(clean_session, op="screenshot", base64=True)
    assert result["format"] == "png"
    assert base64.b64decode(result["base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_element_screenshot(clean_session):
    result = run(clean_session, op="screenshot", css="#p1", base64=True)
    assert base64.b64decode(result["base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_element_screenshot_without_base64_still_frames_the_element(clean_session):
    """A target with no base64 is not a no-op.

    Resolving it scrolls the element into view and sets last_target, so the
    frame the server records shows the element and carries a box saying
    where in the frame it is.
    """
    result = run(clean_session, op="screenshot", css="#p1")
    assert result["format"] == "jpeg"
    assert "base64" not in result
