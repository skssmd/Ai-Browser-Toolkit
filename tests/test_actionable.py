"""The actionable track: refs and roles riding along with the text diff.

Text stays the anchor. Everything here is a decoration on a string the text
track already reported, so an entry that carries no text is a bug, not a
feature -- with exactly one deliberate exception, the hidden file input.
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


def actionable(result):
    return result["dom_diff"].get("actionable", {}).get("added", [])


def test_revealing_a_menu_reports_its_items_with_refs(page):
    added = actionable(run(page, op="click", css="#open"))
    names = [item["name"] for item in added]

    assert "Chart" in names
    assert "Pivot table" in names
    for item in added:
        assert item["ref"].startswith("el_")
        assert item["role"]


def test_every_entry_is_anchored_to_text_the_diff_also_reported(page):
    """The contract: nothing is handed out that the agent cannot tie to text."""
    result = run(page, op="click", css="#open")
    shown = texts(result["dom_diff"]["text"]["added"])

    for item in actionable(result):
        assert item["name"], "an entry with no text has nothing to anchor to"
        if item["role"] != "file":  # the one exception, covered below
            assert item["name"] in shown


def test_a_ref_from_the_diff_is_directly_usable(page):
    """The whole point: act on what appeared without a find in between."""
    added = actionable(run(page, op="click", css="#open"))
    chart = next(item for item in added if item["name"] == "Chart")

    assert run(page, op="get_text", ref=chart["ref"]) == "Chart"


def test_non_controls_never_appear(page):
    added = actionable(run(page, op="click", css="#open"))
    assert "Not a control" not in [item["name"] for item in added]
    assert "Static paragraph" not in [item["name"] for item in added]


def test_a_control_with_no_name_is_dropped(page):
    """The nameless button in the menu has no text, so it is noise."""
    added = actionable(run(page, op="click", css="#open"))
    assert all(item["name"] for item in added)


def test_disabled_controls_are_flagged_not_hidden(page):
    added = actionable(run(page, op="click", css="#open"))
    macro = next((item for item in added if item["name"] == "Macro"), None)
    assert macro is not None
    assert macro["disabled"] is True


def test_nothing_appearing_means_no_actionable_key(page):
    result = run(page, op="click", css="#plain")
    assert "actionable" not in result["dom_diff"]


def test_a_hidden_file_input_is_reported_anyway(page):
    """The one exception to 'must be rendered'.

    The real input is display:none behind a custom uploader, so if the track
    skipped it there would be no way to address it at all.
    """
    state = page.snapshot()
    uploads = [e for e in state["actionable"] if e["role"] == "file"]
    names = [e["name"] for e in uploads]

    assert "Attach a photo" in names, "should take the name from its <label for>"
    assert "bare_upload" in names, "unlabelled: falls back to what identifies it"

    labelled = next(e for e in uploads if e["name"] == "Attach a photo")
    assert labelled.get("multiple") is True


def test_typing_a_path_into_a_hidden_file_input_works(page, tmp_path):
    """Surfacing the ref is useless if `input` still refuses to write to it."""
    upload = tmp_path / "photo.png"
    upload.write_bytes(bytes.fromhex("89504e470d0a1a0a"))

    run(page, op="input", css="#upload", value=str(upload))
    assert run(page, op="run_js", script="return document.getElementById('upload').files.length;")["value"] == 1


def test_a_hidden_file_input_accepts_its_own_ref(page, tmp_path):
    """The ref the actionable track hands out must be usable.

    Found in the wild: `input` resolved a ref straight from the cache without a
    visibility check, so a hidden upload never raised, never reached the
    fallback, and died on send_keys instead. The one path the actionable track
    exists to provide was the one path that did not work.
    """
    upload = tmp_path / "photo.png"
    upload.write_bytes(bytes.fromhex("89504e470d0a1a0a"))

    ref = run(page, op="find", css="#upload")["matches"][0]["ref"]
    run(page, op="input", ref=ref, value=str(upload))

    staged = run(page, op="run_js",
                 script="return document.getElementById('upload').files.length;")
    assert staged["value"] == 1


def test_a_genuinely_missing_field_still_reports_the_real_error(page):
    """The file-input exemption must not swallow ordinary failures."""
    with pytest.raises(OpError) as caught:
        run(page, op="input", css="#does-not-exist", value="x")
    assert caught.value.type == "element_not_found"


def test_baseline_holds_no_live_elements(page):
    """A stored baseline outlives its command; a WebElement in it would rot."""
    run(page, op="click", css="#open")
    baseline = page.baseline()
    assert "elements" not in baseline
    assert all(isinstance(e, dict) for e in baseline["actionable"])


# --- disambiguating repeated names ------------------------------------------
#
# `role` + `name` + `ref` identifies a control only while names are distinct.
# A table of rows whose action buttons are all called "Edit" hands back N refs
# and nothing to choose between them, which is the one place this track stops
# being an answer. Driving a real admin app, 39 of 51 `run_js` calls existed
# solely to work out which "Edit" belonged to which row -- and the DOM-walking
# that replaced it once opened the wrong row's dialog while reporting success.


@pytest.fixture
def rows(session, base_url):
    for tab in list(session.tabs()):
        if not tab["active"]:
            session.close_tab(tab["tab_id"])
    session.goto(f"{base_url}/repeated.html")
    session.set_baseline()
    return session


def by_name(added, name):
    return [item for item in added if item["name"] == name]


def test_repeated_names_carry_the_text_that_tells_them_apart(rows):
    added = actionable(run(rows, op="click", css="#show"))
    edits = by_name(added, "Edit")

    assert len(edits) == 3
    assert [item.get("near") for item in edits] == [
        "Medication",
        "Passport",
        "Safeguarding policy",
    ]


def test_a_unique_name_gets_no_context(rows):
    """Nothing to disambiguate, so nothing is added.

    The cost of this feature is a round trip, and it is only worth paying when
    the names genuinely collide. A page of distinctly-named controls must come
    back exactly as it did before.
    """
    added = actionable(run(rows, op="click", css="#show"))
    save = by_name(added, "Save Changes")

    assert len(save) == 1
    assert "near" not in save[0]


def test_context_does_not_depend_on_table_structure(rows):
    """The climb walks ancestors, it does not know what a row is."""
    added = actionable(run(rows, op="click", css="#show"))
    opens = by_name(added, "Open")

    assert len(opens) == 2
    assert [item.get("near") for item in opens] == ["Billing", "Shipping"]


def test_context_never_repeats_the_name_it_qualifies(rows):
    """A `near` equal to the name is noise -- it distinguishes nothing."""
    added = actionable(run(rows, op="click", css="#show"))
    for item in added:
        if "near" in item:
            assert item["near"] != item["name"]


def test_every_context_entry_belongs_to_a_repeated_name(rows):
    """The whole feature is conditional. Anything else is payload nobody asked
    for, on every diffed command on every page."""
    added = actionable(run(rows, op="click", css="#show"))
    counts: dict[str, int] = {}
    for item in added:
        counts[item["name"]] = counts.get(item["name"], 0) + 1
    for item in added:
        if "near" in item:
            assert counts[item["name"]] > 1, item
