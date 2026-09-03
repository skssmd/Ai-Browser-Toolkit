"""Shadow roots: counted always, walked on request.

The second place page content hides. A shadow root is a separate tree, so the
TreeWalker, `innerText` and every selector stop at the host exactly as they
stopped at an iframe -- and just as quietly.

Frames were folded into the tracks because a page that has them almost always
has content in them. Shadow roots are different: most pages have no author
roots at all, and walking every one on every snapshot would charge all of them
for the few that need it. On the LinkedIn page that started this, there was one
host and nothing in it -- paying for that walk all session would have bought
exactly nothing.

So the deal is: the snapshot *counts* hosts without looking inside, which costs
one property check on a walk that is already happening, and turns "empty diff"
from a silence into a signpost. `shadow: true` is what actually looks. That
gives a search a bottom rung, which is what lets the guideline finally say
"if it is not there, it is not there" without lying.
"""

from __future__ import annotations

import pytest
from conftest import texts

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def added(result):
    # Whether a shadow root was walked, not where its text sat.
    return texts(result["dom_diff"]["text"]["added"])


@pytest.fixture
def page(session, base_url):
    for tab in list(session.tabs()):
        if not tab["active"]:
            session.close_tab(tab["tab_id"])
    run(session, op="goto", url=f"{base_url}/shadow.html")
    return session


# --- the default: cheap, and never silent -------------------------------------


def test_shadow_content_stays_out_of_the_diff_tracks(page):
    """The whole point of opting in: most pages must not pay for this.

    The snapshot walks the light DOM, so a component's internals never bloat
    the diff that every command carries.
    """
    state = page.snapshot()

    assert "Upload a recent resume" in state["text"]
    assert "Choose file" not in state["text"]
    assert "Drop your resume here" not in state["text"]


def test_get_text_does_see_open_shadow_content(page):
    """And this is why the ladder has a rung between the diff and the API.

    `get_text` reports *rendered* text, which follows the composed tree, so
    open shadow content is in it already -- no flag, no extra call. Discovery
    is therefore free: read the page and the component's text is simply there.
    `shadow: true` is only needed to turn what you read into a ref you can act
    on, which is a much narrower thing to pay for.

    The closed root stays absent, because nothing renders its text into reach.
    """
    text = run(page, op="get_text")

    assert "Choose file" in text
    assert "Drop your resume here" in text
    assert "Sealed away" not in text


def test_a_navigation_says_that_it_did_not_look(page, base_url):
    """Landing on a page reports its full text -- so it must admit what is missing.

    Without this an agent reads the whole page, sees no upload control, and
    concludes there is none. The count is the difference between "nothing there"
    and "nothing I looked at".
    """
    result = run(page, op="goto", url=f"{base_url}/shadow.html")

    shadow = result["dom_diff"].get("shadow")
    assert shadow is not None
    assert shadow["hosts"] >= 2


def test_an_empty_diff_says_whether_there_was_anywhere_else_to_look(page):
    """The silence that traps agents. An empty diff plus hosts is a signpost."""
    result = run(
        page,
        op="run_js",
        script="document.getElementById('widget').shadowRoot"
        ".getElementById('pick').textContent = 'Choose a different file';",
    )

    assert added(result) == []  # the change was inside a root nobody walked
    assert result["dom_diff"]["shadow"]["hosts"] >= 2


def test_an_ordinary_diff_is_not_cluttered_with_it(page):
    """It is a signpost for silence, not a field on every response."""
    result = run(
        page,
        op="run_js",
        script="document.body.insertAdjacentHTML('beforeend', '<p>Saved</p>');",
    )

    assert added(result) == ["Saved"]
    assert "shadow" not in result["dom_diff"]


def test_a_page_with_no_shadow_roots_never_mentions_them(session, base_url):
    """Nearly every page. It must cost them nothing, including a line of noise."""
    result = run(session, op="goto", url=f"{base_url}/cards.html")

    assert "shadow" not in result["dom_diff"]


# --- opting in ------------------------------------------------------------------


def test_find_reaches_into_an_open_shadow_root(page):
    """The bottom rung of the ladder."""
    assert run(page, op="find", css="#resume")["count"] == 0

    result = run(page, op="find", css="#resume", shadow=True)

    assert result["count"] == 1
    assert result["matches"][0]["shadow"] is True


def test_a_shadow_ref_can_be_acted_on(page):
    """Finding it is half a fix; a ref that cannot be clicked is no fix at all."""
    ref = run(page, op="find", css="#pick", shadow=True)["matches"][0]["ref"]

    result = run(page, op="click", ref=ref)

    assert result["clicked"]


def test_the_walk_recurses_into_nested_roots(page):
    """A root inside a root is still reachable."""
    assert run(page, op="find", css="#deep", shadow=True)["count"] == 1


def test_a_hidden_file_input_is_reachable_this_way(page):
    """The case that started it: an upload input behind a component boundary."""
    found = run(page, op="find", css="input[type=file]", shadow=True)

    assert found["count"] == 1


def test_text_targeting_works_through_a_shadow_root_too(page):
    """Text is the anchor everywhere else, so it cannot stop being one here."""
    assert run(page, op="find", text="Buried control", shadow=True)["count"] >= 1


def test_ordinary_matches_still_come_back_when_shadow_is_on(page):
    """Opting in widens the search; it does not move it."""
    assert run(page, op="find", css="h1", shadow=True)["count"] == 1


# --- the honest limit -----------------------------------------------------------


def test_a_closed_root_is_not_found_and_not_pretended_about(page):
    """`mode: "closed"` makes `.shadowRoot` null, so nothing can read it.

    Documented rather than papered over: the rule this enables says "nothing
    reachable has it", not "it does not exist". Promising more than the DOM
    allows would just move the silent wrong answer somewhere new.
    """
    assert run(page, op="find", css="#invisible", shadow=True)["count"] == 0


def test_a_zero_result_search_says_where_it_has_not_looked(page):
    """The moment an agent decides to give up, it must know what it skipped.

    A bare `count: 0` is what sent a live agent through fifteen commands of
    escalating run_js scans. With the count attached, zero is either an answer
    or an instruction, and it says which.
    """
    result = run(page, op="find", css="#resume")

    assert result["count"] == 0
    assert result["shadow_hosts"] >= 2


def test_a_zero_result_with_shadow_on_is_final(page):
    """Having looked, it must not keep suggesting there is somewhere left."""
    result = run(page, op="find", css="#nonexistent", shadow=True)

    assert result["count"] == 0
    assert "shadow_hosts" not in result


def test_xpath_cannot_pierce_a_shadow_root_and_says_so(page):
    """querySelectorAll is the only way in, and it does not speak xpath."""
    with pytest.raises(OpError) as caught:
        run(page, op="find", xpath="//button", shadow=True)

    assert caught.value.type == "invalid_op"
    assert "css" in caught.value.message or "text" in caught.value.message
