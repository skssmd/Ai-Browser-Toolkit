"""Page diffing: the manual `diff` op and the automatic dom_diff on commands.

Two tracks. `text` -- what appeared and disappeared on screen -- is always on
and needs no budget. `elements` -- the element-level unified diff -- is opt-in
per command and budgeted.
"""

from __future__ import annotations

import pytest
from conftest import texts


def words(added):
    """Link lines carry their target after an arrow; this is the text alone."""
    return [t.split(" → ")[0] for t in texts(added)]

from abt.ops import dispatch
from abt.schema import OP_NAMES, parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def mutate(session, script):
    """Change the DOM without going through a command, so the baseline holds."""
    session.driver.execute_script(script)


def test_diff_op_is_registered():
    assert "diff" in OP_NAMES


# --- the manual diff op -------------------------------------------------------


def test_diff_empty_right_after_reset(clean_session):
    run(clean_session, op="diff", reset=True)
    result = run(clean_session, op="diff")
    assert result["text"]["added"] == []
    assert result["text"]["removed"] == []
    assert result["text"]["removed_count"] == 0
    assert result["elements"]["added"] == 0
    assert result["elements"]["removed"] == 0
    assert result["elements"]["diff"] == ""
    assert result["elements"]["truncated"] is False


def test_diff_detects_added_element(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(
        clean_session,
        "const d=document.createElement('div'); d.id='fresh'; "
        "d.textContent='hello'; document.body.appendChild(d);",
    )
    result = run(clean_session, op="diff")
    assert words(result["text"]["added"]) == ["hello"]
    assert result["elements"]["added"] >= 1
    assert "div#fresh" in result["elements"]["diff"]


def test_diff_detects_attribute_and_text_change(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(
        clean_session,
        "document.getElementById('p1').setAttribute('data-x','42');"
        "document.getElementById('p1').firstElementChild.textContent='X';",
    )
    result = run(clean_session, op="diff")
    assert result["elements"]["added"] >= 1 and result["elements"]["removed"] >= 1
    assert "data-x" in result["elements"]["diff"]
    assert words(result["text"]["added"]) == ["X"]
    # The manual diff is explicit, so it lists removals by default.
    assert words(result["text"]["removed"]) == ["Cheap Widget"]


def test_manual_diff_can_skip_the_element_track(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(clean_session, "document.getElementById('p1').setAttribute('data-x','42');")
    result = run(clean_session, op="diff", element_diff=False)
    assert "elements" not in result
    assert "text" in result


def test_diff_op_rebases_after_page_change(clean_session, base_url):
    run(clean_session, op="diff", reset=True)
    clean_session.goto(f"{base_url}/form.html")
    result = run(clean_session, op="diff")
    assert result.get("navigation") is True


def test_diff_sets_baseline_when_none_exists(clean_session):
    clean_session.new_tab("about:blank", activate=True)
    result = run(clean_session, op="diff")
    assert result["baseline"] == "set"


def test_manual_diff_truncates_over_budget(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(
        clean_session,
        "for (let i=0;i<60;i++){const d=document.createElement('p');"
        "d.id='n'+i; d.textContent='xxxxxxxxxxxxxxxxxxxxxxxx';"
        "document.body.appendChild(d);}",
    )
    result = run(clean_session, op="diff", max_tokens=1)
    assert result["elements"]["truncated"] is True
    assert len(result["elements"]["diff"]) < 400


# --- the automatic diff on commands -------------------------------------------


def test_auto_diff_is_text_only_by_default(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="const d=document.createElement('div'); d.textContent='appeared';"
        "document.body.appendChild(d); return 7;",
    )
    assert result["value"] == 7
    assert words(result["dom_diff"]["text"]["added"]) == ["appeared"]
    assert "elements" not in result["dom_diff"]


def test_element_diff_is_opt_in(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="document.body.setAttribute('data-x','1'); return 1;",
        element_diff=True,
    )
    assert result["dom_diff"]["elements"]["added"] >= 1
    assert "data-x" in result["dom_diff"]["elements"]["diff"]


def test_attribute_only_change_is_invisible_to_the_text_track(clean_session):
    """The point of the text track: state churn with no visible text is not news."""
    result = run(
        clean_session,
        op="run_js",
        script="document.body.setAttribute('data-x','1'); return 1;",
    )
    assert result["dom_diff"]["text"] == {
        "added": [],
        "removed_count": 0,
        "truncated": False,
    }


def test_removed_text_is_counted_not_listed_by_default(clean_session):
    """A page that swaps its body would otherwise return the whole old document."""
    result = run(
        clean_session,
        op="run_js",
        script="document.getElementById('p1').remove(); return 1;",
    )
    text = result["dom_diff"]["text"]
    assert text["added"] == []
    assert text["removed_count"] == 2  # the heading and the price
    assert "removed" not in text


def test_removed_text_is_listed_on_request(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="document.getElementById('p1').remove(); return 1;",
        include_removed=True,
    )
    text = result["dom_diff"]["text"]
    # Two siblings under one parent group under it, so this reads the values
    # off the tree rather than the raw lines.
    assert words(text["removed"]) == ["Cheap Widget", "$4.99"]
    assert text["removed_count"] == 2


def test_hidden_text_does_not_count_as_on_screen(clean_session):
    """Text that exists but is not rendered has not appeared."""
    hidden = run(
        clean_session,
        op="run_js",
        script="const d=document.createElement('div'); d.textContent='ghost';"
        "d.style.display='none'; d.id='ghosty'; document.body.appendChild(d); return 1;",
    )
    assert hidden["dom_diff"]["text"]["added"] == []

    shown = run(
        clean_session,
        op="run_js",
        script="document.getElementById('ghosty').style.display=''; return 1;",
    )
    assert words(shown["dom_diff"]["text"]["added"]) == ["ghost"]


def test_each_element_contributes_its_own_text_separately(clean_session):
    """Sibling strings stay separate entries; they never merge into one blob."""
    result = run(
        clean_session,
        op="run_js",
        script="const w=document.createElement('div');"
        "w.innerHTML='<span>alpha</span><span>beta</span>';"
        "document.body.appendChild(w); return 1;",
    )
    assert words(result["dom_diff"]["text"]["added"]) == ["alpha", "beta"]


def test_text_track_reports_typed_input_values(clean_session, base_url):
    """A typed value is not in the DOM text, so it needs reading off the control."""
    clean_session.goto(f"{base_url}/form.html")
    result = run(clean_session, op="input", css="#name", value="ada")
    assert "ada" in texts(result["dom_diff"]["text"]["added"])


def test_text_track_never_captures_a_password(clean_session):
    run(
        clean_session,
        op="run_js",
        script="const i=document.createElement('input'); i.type='password';"
        "i.id='pw'; document.body.appendChild(i); return 1;",
    )
    result = run(
        clean_session,
        op="run_js",
        script="document.getElementById('pw').value='hunter2'; return 1;",
    )
    assert result["dom_diff"]["text"]["added"] == []


def test_text_track_follows_a_select(clean_session, base_url):
    clean_session.goto(f"{base_url}/form.html")
    result = run(
        clean_session, op="select", css="#size", by_text="Large", include_removed=True
    )
    assert "Large" in texts(result["dom_diff"]["text"]["added"])
    # the previous selection
    assert "Medium" in texts(result["dom_diff"]["text"]["removed"])


def test_auto_diff_shows_spa_click_change(clean_session, base_url):
    clean_session.goto(f"{base_url}/nav.html")
    run(clean_session, op="hover", css="#products")
    result = run(clean_session, op="click", css="#widgets")
    assert "widgets" in texts(result["dom_diff"]["text"]["added"])


def test_hover_revealing_a_menu_shows_up_as_added_text(clean_session, base_url):
    clean_session.goto(f"{base_url}/nav.html")
    result = run(clean_session, op="hover", css="#products")
    assert "Widgets" in words(result["dom_diff"]["text"]["added"])


def test_per_command_diff_false_suppresses(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="document.body.setAttribute('data-x','1'); return 1;",
        diff=False,
    )
    assert "dom_diff" not in result


def test_per_command_diff_true_forces_when_server_off(clean_session):
    clean_session.diff_enabled = False
    try:
        quiet = run(
            clean_session,
            op="run_js",
            script="document.body.setAttribute('data-x','1'); return 1;",
        )
        assert "dom_diff" not in quiet

        loud = run(
            clean_session,
            op="run_js",
            script="document.body.setAttribute('data-x','2'); return 1;",
            diff=True,
        )
        assert "dom_diff" in loud
    finally:
        clean_session.diff_enabled = True


def test_auto_element_diff_truncates_over_budget(clean_session):
    clean_session.diff_enabled = True
    clean_session.diff_max_tokens = 1
    result = run(
        clean_session,
        op="run_js",
        script="for (let i=0;i<60;i++){const d=document.createElement('p');"
        "d.id='n'+i; d.textContent='xxxxxxxxxxxxxxxxxxxxxxxx';"
        "document.body.appendChild(d);} return 1;",
        element_diff=True,
    )
    assert result["dom_diff"]["elements"]["truncated"] is True
    assert result["dom_diff"]["elements"]["added"] >= 60
    assert len(result["dom_diff"]["elements"]["diff"]) < 400


# --- navigation: a diff within the site, the page itself when you leave it ----


def test_goto_within_the_site_is_a_diff(clean_session, base_url):
    """Two pages of one site are the same template, so only the content differs.

    Both fixtures carry the same nav, masthead and footer. A navigation that
    handed back the whole destination would re-send all of it -- measured
    across the benchmark campaign that furniture was 38-60% of every page --
    and the agent is already looking at it.
    """
    run(clean_session, op="goto", url=f"{base_url}/site_one.html")
    result = run(clean_session, op="goto", url=f"{base_url}/site_two.html")
    text = result["dom_diff"]["text"]
    assert result["dom_diff"]["navigation"] is True

    body = texts(text["added"])
    assert "Only on page two" in body
    for furniture in ("Shared Masthead", "Shared footer text", "Reports"):
        assert furniture not in body, f"{furniture!r} was already on screen"

    # A diff, not a suppression summary: nothing is deferred to a later read.
    assert "unchanged_count" not in text


def test_goto_to_another_host_hands_back_the_page(clean_session, base_url):
    """Unrelated documents share nothing, so a path diff would report all of it.

    Same server, different netloc -- which is exactly what "a different site"
    means here.
    """
    other_host = base_url.replace("127.0.0.1", "localhost")
    run(clean_session, op="goto", url=f"{base_url}/site_one.html")
    result = run(clean_session, op="goto", url=f"{other_host}/site_two.html")
    text = result["dom_diff"]["text"]
    assert result["dom_diff"]["navigation"] is True
    # Matched on the string rather than the path, and summarised rather than
    # dropped, so the repeats are accounted for and reachable.
    assert text["unchanged_count"] > 0
    assert "Only on page two" in texts(text["added"])


def test_goto_returns_the_page_it_landed_on(clean_session, base_url):
    """Landing on a page hands you its content; no second read needed."""
    result = run(clean_session, op="goto", url=f"{base_url}/links.html")
    text = result["dom_diff"]["text"]
    assert result["dom_diff"]["navigation"] is True
    assert words(text["added"]) == ["Links", "Cards", "Form"]


def test_goto_counts_the_text_it_left_behind(clean_session, base_url):
    """cards.html has visible text; the count says how much went away."""
    result = run(clean_session, op="goto", url=f"{base_url}/links.html")
    assert result["dom_diff"]["text"]["removed_count"] > 0
    assert "removed" not in result["dom_diff"]["text"]


def test_goto_lists_the_old_page_on_request(clean_session, base_url):
    result = run(
        clean_session, op="goto", url=f"{base_url}/links.html", include_removed=True
    )
    assert "Catalogue" in texts(result["dom_diff"]["text"]["removed"])


def test_navigation_skips_the_element_track(clean_session, base_url):
    """Two unrelated documents have no meaningful unified diff."""
    result = run(
        clean_session, op="goto", url=f"{base_url}/links.html", element_diff=True
    )
    assert "elements" not in result["dom_diff"]


def test_back_and_forward_return_their_destination(clean_session, base_url):
    run(clean_session, op="goto", url=f"{base_url}/links.html")
    back = run(clean_session, op="back")
    assert "Catalogue" in texts(back["dom_diff"]["text"]["added"])
    forward = run(clean_session, op="forward")
    assert words(forward["dom_diff"]["text"]["added"]) == ["Links", "Cards", "Form"]


def test_reload_returns_the_page_it_reloaded(clean_session):
    """A reload is the same page, not a different one -- so nothing is withheld.

    Chrome-suppression compares against a genuinely different page: two pages
    of a site share their nav and footer, not their content. A reload lands
    back on this same document, so "the page you came from" and "the page you
    are looking at" are one and the same, and suppressing against it would
    hide exactly the content the caller reloaded to see. The reload got the
    full page once, before suppression existed, and gets it again now.
    """
    result = run(clean_session, op="reload")
    text = result["dom_diff"]["text"]
    assert "unchanged_count" not in text
    assert "Catalogue" in texts(text["added"])


def test_goto_can_suppress_the_page_text(clean_session, base_url):
    result = run(clean_session, op="goto", url=f"{base_url}/links.html", diff=False)
    assert "dom_diff" not in result
    assert result["title"] == "Links"


def test_a_click_that_redirects_returns_the_new_page(clean_session, base_url):
    """The whole point: a redirect answers 'what am I looking at now?'."""
    clean_session.goto(f"{base_url}/links.html")
    result = run(clean_session, op="click", css="#to-form")
    text = result["dom_diff"]["text"]
    assert result["dom_diff"]["navigation"] is True
    assert "Submit" in texts(text["added"])  # the form page
    assert text["removed_count"] == 3  # Links, Cards, Form
    assert "elements" not in result["dom_diff"]


def test_a_failed_navigation_still_raises(clean_session):
    from abt.errors import OpError

    with pytest.raises(OpError) as caught:
        run(clean_session, op="goto", url="http://127.0.0.1:9/nothing")
    assert caught.value.type == "navigation_failed"


def test_fragment_change_is_not_a_navigation(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="window.location.hash='top'; return 1;",
    )
    assert "dom_diff" in result
    assert "navigation" not in result["dom_diff"]


# --- budgets ------------------------------------------------------------------


def test_per_command_budget_overrides_the_server_default(clean_session):
    """A noisy command can ask for a cheaper element diff than the server default."""
    add_many = (
        "for (var i = 0; i < 200; i++) {"
        "  var d = document.createElement('div');"
        "  d.className = 'noise-' + i;"
        "  d.textContent = 'row number ' + i;"
        "  document.body.appendChild(d);"
        "}"
        "return 200;"
    )
    cheap = run(clean_session, op="run_js", script=add_many, diff_max_tokens=20)["dom_diff"]
    assert cheap["elements"]["truncated"] is True

    clean_session.driver.refresh()
    clean_session.set_baseline()
    rich = run(clean_session, op="run_js", script=add_many, diff_max_tokens=100_000)[
        "dom_diff"
    ]
    assert rich["elements"]["truncated"] is False
    assert len(rich["elements"]["diff"]) > len(cheap["elements"]["diff"])


def test_a_budget_implies_the_element_diff(clean_session):
    """Asking to budget something you never requested is a typo, not a no-op."""
    cmd = parse_command({"op": "click", "css": "a", "diff_max_tokens": 50})
    assert cmd.element_diff is True


def test_element_diff_defaults_off_and_budget_defaults_to_the_session_value():
    cmd = parse_command({"op": "click", "css": "a"})
    assert cmd.element_diff is False
    assert cmd.diff_max_tokens is None


def test_budget_must_be_positive():
    from abt.errors import OpError

    with pytest.raises(OpError) as caught:
        parse_command({"op": "click", "css": "a", "diff_max_tokens": 0})
    assert caught.value.type == "invalid_op"


# --- text diff internals ------------------------------------------------------


def test_text_diff_keeps_duplicate_strings_apart():
    from abt.diff import diff_text

    result = diff_text(["Buy", "Buy"], ["Buy", "Buy", "Buy"])
    assert result["added"] == ["Buy"]
    assert result["removed_count"] == 0


def test_removed_is_always_counted_even_when_not_listed():
    """The count is what tells you whether asking for the list is worth it."""
    from abt.diff import diff_text

    quiet = diff_text(["a", "b", "c"], ["d"])
    assert quiet["removed_count"] == 3
    assert "removed" not in quiet

    loud = diff_text(["a", "b", "c"], ["d"], include_removed=True)
    assert loud["removed"] == ["a", "b", "c"]
    assert loud["removed_count"] == 3


def test_text_diff_has_a_safety_ceiling():
    from abt.diff import diff_text

    result = diff_text([], ["x" * 100 for _ in range(50)], max_chars=1000)
    assert result["truncated"] is True
    assert "more, text diff hit its safety ceiling" in result["added"][-1]
