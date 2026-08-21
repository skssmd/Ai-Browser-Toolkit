"""Playbooks: layering, the trust boundary, and what must never ship.

The rule worth protecting is that a pulled playbook is inert until someone
trusts it. A playbook is instructions an agent will follow, so anything that
lets fetched content reach `read()` unapproved turns a website visit into a
way to change what agents do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abt import guidelines


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A machine with its own empty guidelines home and no checkout."""
    store = tmp_path / "store"
    monkeypatch.setattr(guidelines.paths, "guidelines_home", lambda: store / "guidelines")
    monkeypatch.setattr(guidelines.paths, "config_file", lambda: store / "config.json")
    monkeypatch.setattr(guidelines, "_packaged_root", lambda: None)
    return store


def write(root: Path, layer: str, domain: str, name: str, text: str, version: int = 1):
    directory = root / "guidelines" / layer / domain
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")
    (directory / "meta.json").write_text(json.dumps({"version": version}), encoding="utf-8")


# -- the trust boundary ---------------------------------------------------


def test_pending_is_listed_but_never_read(home):
    write(home, guidelines.PENDING, "example.com", "example.md", "pulled")

    assert guidelines.installed()["example.com"]["trusted"] is False
    with pytest.raises(KeyError):
        guidelines.read("example.com/example")


def test_pending_is_readable_only_when_asked_for_explicitly(home):
    write(home, guidelines.PENDING, "example.com", "example.md", "pulled")
    assert guidelines.read("example.com/example", allow_pending=True) == "pulled"


def test_trusting_moves_it_and_makes_it_readable(home):
    write(home, guidelines.PENDING, "example.com", "example.md", "pulled")
    guidelines.trust("example.com")

    assert guidelines.read("example.com/example") == "pulled"
    assert guidelines.installed()["example.com"]["source"] == guidelines.TRUSTED
    assert not (home / "guidelines" / "pending" / "example.com").exists()


def test_a_pending_update_never_displaces_the_trusted_copy(home):
    write(home, guidelines.TRUSTED, "example.com", "example.md", "old", version=1)
    write(home, guidelines.PENDING, "example.com", "example.md", "new", version=2)

    assert guidelines.read("example.com/example") == "old"
    entry = guidelines.installed()["example.com"]
    assert entry["source"] == guidelines.TRUSTED
    assert entry["pending_version"] == 2


# -- layering -------------------------------------------------------------


def test_local_beats_trusted(home):
    write(home, guidelines.TRUSTED, "example.com", "example.md", "theirs")
    write(home, guidelines.LOCAL, "example.com", "example.md", "mine")
    assert guidelines.read("example.com/example") == "mine"


def test_a_missing_playbook_raises_rather_than_returning_empty(home):
    with pytest.raises(KeyError):
        guidelines.read("nowhere.com/nothing")


# -- path traversal -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["../../../etc/passwd", "example.com/../../escape", "..\\..\\windows\\system32"],
)
def test_names_cannot_escape_the_guidelines_directory(home, name):
    """`name` arrives from an HTTP path parameter."""
    with pytest.raises(KeyError):
        guidelines.read(name)


# -- domains --------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.messenger.com/t/123", "messenger.com"),
        ("https://messenger.com", "messenger.com"),
        ("https://docs.google.com/spreadsheets/d/abc", "docs.google.com"),
        ("not a url", None),
        ("", None),
    ],
)
def test_domain_of(url, expected):
    assert guidelines.domain_of(url) == expected


# -- lookup is never fatal ------------------------------------------------


def test_lookup_returns_none_when_the_source_is_unreachable(home, monkeypatch):
    """A site visit must not fail because a playbook server is down."""
    def boom(*a, **kw):
        raise OSError("no network")

    monkeypatch.setattr(guidelines, "fetch_index", boom)
    assert guidelines.lookup("example.com") is None


def test_lookup_is_skipped_when_switched_off(home, monkeypatch):
    guidelines.set_config(guidelines_lookup=False)
    monkeypatch.setattr(
        guidelines, "fetch_index", lambda **kw: {"example.com": {"version": 1}}
    )
    assert guidelines.lookup("example.com") is None


def test_lookup_reports_an_update_without_pulling(home, monkeypatch):
    write(home, guidelines.TRUSTED, "example.com", "example.md", "old", version=1)
    monkeypatch.setattr(
        guidelines,
        "fetch_index",
        lambda **kw: {"example.com": {"version": 4, "files": ["example.md"]}},
    )
    found = guidelines.lookup("example.com")
    assert found["update_available"] is True
    assert found["held_version"] == 1
    assert found["available_version"] == 4
    # Reported only: nothing was written.
    assert not (home / "guidelines" / "pending").exists()


# -- what must never ship -------------------------------------------------


def test_client_playbooks_are_not_in_the_packaged_tree():
    """hatchling's `exclude` does not apply to `force-include`, so the whole
    guidelines directory ships verbatim. onehr names a real organisation, its
    routes and its staff records -- keeping it out is structural: it lives
    outside guidelines/ entirely, not behind a pattern.
    """
    packaged = Path(__file__).resolve().parent.parent / "guidelines"
    offenders = [p for p in packaged.rglob("*") if "onehr" in p.name.lower()]
    assert not offenders, offenders


def test_the_index_matches_the_files_on_disk():
    """A hand-edited index drifts the moment someone adds a playbook."""
    root = Path(__file__).resolve().parent.parent / "guidelines"
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))

    on_disk = {d.name for d in root.iterdir() if d.is_dir() and "." in d.name}
    assert set(index) == on_disk

    for domain, entry in index.items():
        assert entry["files"] == sorted(p.name for p in (root / domain).glob("*.md"))


def test_only_domain_folders_are_indexed():
    """The playbooks repository carries domain-specific content and nothing
    else. toolkit-workflow.md ships with the tool: it is how to drive the
    toolkit, not how to drive a site, so it is never fetched or versioned."""
    root = Path(__file__).resolve().parent.parent / "guidelines"
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))

    assert all("." in domain for domain in index), sorted(index)
    assert "toolkit-workflow" not in index
    assert (root / "toolkit-workflow.md").is_file()


def test_local_testing_playbooks_do_not_ship():
    """kayoanime and fojik were local testing targets, not something to
    publish. They live under private/, which is gitignored."""
    root = Path(__file__).resolve().parent.parent / "guidelines"
    names = " ".join(p.as_posix().lower() for p in root.rglob("*"))
    for excluded in ("kayoanime", "fojik", "onehr"):
        assert excluded not in names, excluded
