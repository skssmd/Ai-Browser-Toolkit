"""The workflows parse, and the two invariants that cannot be tested by running.

A broken workflow is only discoverable by pushing, which costs a round trip
and a runner. Two of these were written by hand into YAML and corrupted by
shell quoting before anyone could have noticed:

    /DPayloadDir=%CD%\\payload<TAB>ree
    packaging\\windows<BEL>bt.iss

Both parsed as valid YAML. Only looking for control characters found them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_the_workflow_parses(name):
    assert load(name)["jobs"]


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_no_control_characters_survived_the_shell(name):
    """A tab or a bell inside a command is invisible in review and fatal on
    the runner. Tabs are illegal for YAML indentation anyway, but these
    appeared mid-line inside a run: block, where YAML permits them."""
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        bad = [c for c in line if ord(c) < 32]
        assert not bad, f"{name}:{number} contains {bad!r}: {line!r}"


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_no_stray_backslash_n_from_a_mangled_continuation(name):
    r"""A line continuation that lost its newline leaves a literal \n in the
    middle of a shell command, which runs as the argument "\n"."""
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert "\\n " not in text, r"literal '\n ' found -- a continuation was mangled"


def test_publishing_needs_both_a_tag_and_a_real_run():
    """dry_run must actually prevent publishing.

    Gating on the ref alone made a branch dispatch safe by accident, while a
    *tag* dispatch with dry_run set would have published anyway -- an input
    that does not do what it says.
    """
    jobs = load("release.yml")["jobs"]
    for name in ("release", "pypi"):
        condition = jobs[name]["if"]
        assert "refs/tags/" in condition, name
        assert "dry_run" in condition, name


def test_the_installer_is_built_even_on_a_dry_run():
    """The point of a rehearsal is to find out the installer does not compile
    before a tag exists, not after."""
    assert "if" not in load("release.yml")["jobs"]["installer"]


def test_the_release_waits_for_every_artifact_it_publishes():
    """Shipping a partial release is worse than failing: each downstream
    publisher pins a URL, and a missing asset gives it a 404 to point at."""
    release = load("release.yml")["jobs"]["release"]
    assert set(release["needs"]) == {"wheel", "bundle", "installer"}
