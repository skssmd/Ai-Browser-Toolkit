"""DOM diffing: the manual `diff` op and the automatic dom_diff on commands."""

from __future__ import annotations

import pytest

from abt.ops import dispatch
from abt.schema import OP_NAMES, parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def mutate(session, script):
    """Change the DOM without going through a command, so the baseline holds."""
    session.driver.execute_script(script)


def test_diff_op_is_registered():
    assert "diff" in OP_NAMES


def test_diff_empty_right_after_reset(clean_session):
    run(clean_session, op="diff", reset=True)
    result = run(clean_session, op="diff")
    assert result["added"] == 0
    assert result["removed"] == 0
    assert result["diff"] == ""
    assert result["truncated"] is False


def test_diff_detects_added_element(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(
        clean_session,
        "const d=document.createElement('div'); d.id='fresh'; "
        "d.textContent='hello'; document.body.appendChild(d);",
    )
    result = run(clean_session, op="diff")
    assert result["added"] >= 1
    assert "div#fresh" in result["diff"]
    assert "hello" in result["diff"]


def test_diff_detects_attribute_and_text_change(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(
        clean_session,
        "document.getElementById('p1').setAttribute('data-x','42');"
        "document.getElementById('p1').firstElementChild.textContent='X';",
    )
    result = run(clean_session, op="diff")
    assert result["added"] >= 1 and result["removed"] >= 1
    assert "data-x" in result["diff"]


def test_diff_op_rebases_after_page_change(clean_session, base_url):
    run(clean_session, op="diff", reset=True)
    clean_session.goto(f"{base_url}/form.html")
    result = run(clean_session, op="diff")
    assert result.get("navigation") is True


def test_diff_sets_baseline_when_none_exists(clean_session):
    clean_session.new_tab("about:blank", activate=True)
    result = run(clean_session, op="diff")
    assert result["baseline"] == "set"


def test_auto_diff_attached_to_interactive_ops_by_default(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="document.body.setAttribute('data-x','1'); return 7;",
    )
    assert result["value"] == 7
    assert result["dom_diff"]["added"] >= 1
    assert "data-x" in result["dom_diff"]["diff"]
    assert result["dom_diff"]["truncated"] is False


def test_auto_diff_shows_spa_click_change(clean_session, base_url):
    clean_session.goto(f"{base_url}/nav.html")
    run(clean_session, op="hover", css="#products")
    result = run(clean_session, op="click", css="#widgets")
    assert "dom_diff" in result
    assert result["dom_diff"]["added"] >= 1
    assert "widgets" in result["dom_diff"]["diff"]


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


def test_auto_diff_truncates_over_budget(clean_session):
    clean_session.diff_enabled = True
    clean_session.diff_max_tokens = 1
    result = run(
        clean_session,
        op="run_js",
        script="for (let i=0;i<60;i++){const d=document.createElement('p');"
        "d.id='n'+i; d.textContent='xxxxxxxxxxxxxxxxxxxxxxxx';"
        "document.body.appendChild(d);} return 1;",
    )
    assert result["dom_diff"]["truncated"] is True
    assert result["dom_diff"]["added"] >= 60
    assert len(result["dom_diff"]["diff"]) < 400


def test_manual_diff_truncates_over_budget(clean_session):
    run(clean_session, op="diff", reset=True)
    mutate(
        clean_session,
        "for (let i=0;i<60;i++){const d=document.createElement('p');"
        "d.id='n'+i; d.textContent='xxxxxxxxxxxxxxxxxxxxxxxx';"
        "document.body.appendChild(d);}",
    )
    result = run(clean_session, op="diff", max_tokens=1)
    assert result["truncated"] is True
    assert len(result["diff"]) < 400


def test_fragment_change_is_not_a_navigation(clean_session):
    result = run(
        clean_session,
        op="run_js",
        script="window.location.hash='top'; return 1;",
    )
    assert "dom_diff" in result
    assert "navigation" not in result["dom_diff"]
