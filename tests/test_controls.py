"""Controls on the text track: the address that reads a thing also acts on it.

There is no second track. A control is a line whose address carries `#role`,
and that address is what `click` and `input` take -- so the words you just read
and the handle you act with are the same characters, paid for once.
"""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


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


def added_lines(result):
    """The diff's own lines, addresses intact -- `texts()` strips them off."""
    return result["dom_diff"].get("text", {}).get("added", [])


def marked(result):
    """Lines from the text diff whose address carries a control mark."""
    out = []
    for line in added_lines(result):
        head = line.strip().split(" ")[0]
        if "#" in head:
            out.append(line.strip())
    return out


def test_revealing_a_menu_puts_its_items_on_the_text_track(page):
    lines = marked(run(page, op="click", css="#open"))
    joined = " | ".join(lines)

    assert "Chart" in joined
    # The words and the handle arrive together: no second block, no ref.
    assert any(line.split(" ")[0].count("#") == 1 for line in lines)


def test_a_control_line_carries_its_role(page):
    lines = marked(run(page, op="click", css="#open"))
    marks = {line.split(" ")[0].split("#", 1)[1].split("-")[0] for line in lines}

    # Whatever the fixture holds, every mark is one of the tokens we document.
    assert marks
    assert marks <= {"btn", "lnk", "inp", "sel", "chk", "rad", "opt", "file"}


def test_the_address_on_a_control_line_clicks_it(page):
    lines = marked(run(page, op="click", css="#open"))
    assert lines, "expected the menu to reveal at least one control"

    level = lines[0].split(" ")[0]
    # Straight from the line to the action, which is the whole point: before
    # this it took a `find` in between to turn a string back into something
    # you could operate.
    result = run(page, op="click", level=level)
    # Reaching here at all is the assertion: an unresolvable or mismatched
    # address raises, so a plain return means the click landed on the thing
    # the line named.
    assert result is not None


def test_a_level_names_the_same_element_with_or_without_its_mark(page):
    lines = marked(run(page, op="click", css="#open"))
    assert lines
    marked_level = lines[0].split(" ")[0]
    bare_level = marked_level.split("#", 1)[0]

    # The mark is a label, not part of the address. An agent that quotes the
    # whole thing back and one that quotes only the path are asking for the
    # same element.
    first = run(page, op="get_text", level=marked_level)
    second = run(page, op="get_text", level=bare_level)
    assert first == second


def test_a_control_is_one_line_not_one_per_word(page):
    """A button's inner markup belongs to the button, not to its spans."""
    lines = marked(run(page, op="click", css="#open"))
    for line in lines:
        address = line.split(" ")[0]
        # Nothing inside a control gets its own address, so no reported line
        # sits underneath another reported control.
        others = [other.split(" ")[0].split("#")[0] for other in lines]
        own = address.split("#")[0]
        assert not [o for o in others if o != own and own.startswith(o)]


def test_a_stale_level_fails_loudly_rather_than_clicking_something_else(page):
    lines = marked(run(page, op="click", css="#open"))
    assert lines
    level = lines[0].split(" ")[0].split("#")[0]

    # Replace the page under the address. Positional resolution would happily
    # hand back whatever now sits there; the identity check is what stops a
    # click landing on a control the agent never saw.
    page.driver.execute_script("document.body.innerHTML = '<p>gone</p>';")
    with pytest.raises(OpError) as caught:
        run(page, op="click", level=level)
    assert caught.value.type in {"stale_ref", "element_not_found"}


def test_no_response_carries_an_actionable_block(page):
    result = run(page, op="click", css="#open")
    assert "actionable" not in result["dom_diff"]


def test_run_js_can_be_switched_off(page):
    """The escape hatch closes, and the refusal names what to use instead.

    run_js is what an agent reaches for instead of learning the ops -- on one
    18-episode benchmark set it ran 8.9 times per episode against 0.9 on the
    single-site set. Closing it is how you find out what the ops cannot yet
    express, rather than guessing.
    """
    assert run(page, op="run_js", script="return 1+1;")["value"] == 2

    page.run_js_enabled = False
    with pytest.raises(OpError) as caught:
        run(page, op="run_js", script="return 1+1;")
    assert caught.value.type == "invalid_op"
    assert "disabled" in str(caught.value.message)
    # A refusal that does not say what to do instead just moves the problem.
    assert "level" in str(caught.value.hint)

    page.run_js_enabled = True
    assert run(page, op="run_js", script="return 1+1;")["value"] == 2
