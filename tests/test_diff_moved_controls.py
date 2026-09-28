"""A control whose address changed is news, even when its text did not.

Found in a live chat session: a leave request's side panel had a Decline
button; clicking it opened a confirmation dialog whose own confirm button also
said Decline. The diff aligns on text alone, so the two read as one unchanged
line and the dialog's button was withheld. The agent, shown only Cancel,
clicked Cancel four times and reported the requests declined.
"""

from __future__ import annotations

from abt.diff import diff_text


def test_a_control_that_moved_is_reported_at_its_new_address():
    before = [("AECAAAAA", "test staff 1"), ("AECACAA#btn", "Decline")]
    after = [
        ("AEAA", "Decline Leave Request"),
        ("AEBBB#inp", "□"),
        ("AECA#btn", "Cancel"),
        ("AECB#btn", "Decline"),
    ]
    added = diff_text(before, after)["added"]
    assert "AECB#btn Decline" in added
    assert "AECA#btn Cancel" in added


def test_a_control_that_stayed_put_stays_quiet():
    before = [("AA#btn", "Save"), ("AB", "x")]
    after = [("AA#btn", "Save"), ("AB", "y")]
    added = diff_text(before, after)["added"]
    assert not any("Save" in line for line in added)


def test_the_same_text_at_a_new_address_is_a_change():
    """The tree is the page as laid out: moved text is somewhere new."""
    before = [("AA", "Heading"), ("AB", "Body")]
    after = [("AA", "Banner"), ("AB", "Heading"), ("AC", "Body")]
    out = diff_text(before, after, include_removed=True)
    # Siblings group under their parent when rendered.
    assert out["added"] == ["A", "  A Banner", "  B Heading", "  C Body"]
    assert out["removed_count"] == 2


def test_same_text_same_address_is_the_only_match():
    before = [("AA", "Add to cart"), ("AB", "Add to cart")]
    after = [("AA", "Add to cart"), ("AB", "Add to cart"), ("AC", "Add to cart")]
    assert diff_text(before, after)["added"] == ["AC Add to cart"]
