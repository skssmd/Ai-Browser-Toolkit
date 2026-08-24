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


# -- consent --------------------------------------------------------------


def test_consent_is_refused_when_nobody_is_there_to_give_it(monkeypatch):
    """`abt serve` is routinely launched detached. A prompt nobody sees must
    not default to trusting remote instructions."""
    from abt import cli

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli._confirm("trust this?", assume_yes=False) is False


def test_explicit_yes_still_works_without_a_terminal(monkeypatch):
    """Scripted use is legitimate; it just has to be stated."""
    from abt import cli

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli._confirm("trust this?", assume_yes=True) is True


def test_the_pulled_copy_records_where_it_came_from(home, monkeypatch):
    """A version says the author thinks something changed; a ref says exactly
    which upstream state this copy is."""
    monkeypatch.setattr(
        guidelines,
        "fetch_index",
        lambda **kw: {"example.com": {"version": 2, "files": ["a.md"]}},
    )
    monkeypatch.setattr(guidelines, "source_ref", lambda **kw: "abc123")

    class Response:
        text = "body"

        def raise_for_status(self):
            pass

    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: Response())
    guidelines.pull("example.com")

    meta = json.loads(
        (home / "guidelines" / "pending" / "example.com" / "meta.json").read_text()
    )
    assert meta["version"] == 2
    assert meta["ref"] == "abc123"
    assert meta["source"].endswith("ABT-Playbooks/main")
    assert meta["pulled_at"]


# -- the server surface ---------------------------------------------------


def test_the_server_lists_and_reads_but_cannot_trust(unstarted_client):
    """Pulling and trusting stay on the CLI, where a person is present. An
    endpoint that could trust a playbook would let anything able to reach
    loopback decide what instructions agents follow."""
    routes = {r.path for r in unstarted_client.app.routes}
    assert "/guidelines" in routes
    assert "/guidelines/{name:path}" in routes
    assert not any("trust" in path or "pull" in path for path in routes)


def test_reading_a_missing_playbook_over_http_is_a_clean_error(unstarted_client):
    response = unstarted_client.get("/guidelines/nowhere.com/nothing")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_the_server_never_serves_an_untrusted_playbook(unstarted_client, monkeypatch):
    from abt import guidelines as g

    monkeypatch.setattr(g, "read", lambda name, allow_pending=False: (_ for _ in ()).throw(
        AssertionError("allow_pending was set") if allow_pending else KeyError(name)
    ))
    response = unstarted_client.get("/guidelines/example.com/example")
    assert response.json()["ok"] is False


# -- fuzzy search ---------------------------------------------------------


@pytest.fixture
def index(monkeypatch):
    data = {
        "docs.google.com": {"version": 1, "files": ["docs.md", "sheets.md"]},
        "script.google.com": {"version": 2, "files": ["forms-apps-script.md"]},
        "messenger.com": {"version": 1, "files": ["messenger.md"]},
    }
    monkeypatch.setattr(guidelines, "fetch_index", lambda **kw: data)
    return data


def test_an_exact_domain_answers_with_everything_it_has(home, index):
    """The fast path. An agent that just landed somewhere should not need a
    second round trip to find out which files exist."""
    found = guidelines.search("docs.google.com")
    assert found["exact"] is True
    assert len(found["matches"]) == 1
    assert found["matches"][0]["files"] == ["docs.md", "sheets.md"]


def test_a_full_url_is_treated_as_its_domain(home, index):
    found = guidelines.search("https://www.docs.google.com/spreadsheets/d/abc")
    assert found["exact"] is True
    assert found["matches"][0]["domain"] == "docs.google.com"


def test_a_bare_word_matches_a_file_inside_a_domain(home, index):
    """`sheets` should find docs.google.com/sheets.md."""
    found = guidelines.search("sheets")
    assert found["exact"] is False
    assert found["matches"][0]["domain"] == "docs.google.com"
    assert found["matches"][0]["files"] == ["sheets.md"]
    assert found["matches"][0]["matched_on"] == "file:sheets.md"


def test_a_partial_domain_matches_several(home, index):
    names = [m["domain"] for m in guidelines.search("google")["matches"]]
    assert "docs.google.com" in names
    assert "script.google.com" in names


def test_domain_slash_file_narrows_within_that_domain(home, index):
    found = guidelines.search("docs.google.com/sheets")
    assert found["exact"] is True
    assert found["matches"][0]["files"] == ["sheets.md"]


def test_search_survives_an_unreachable_source(home, monkeypatch):
    monkeypatch.setattr(
        guidelines, "fetch_index", lambda **kw: (_ for _ in ()).throw(OSError())
    )
    assert guidelines.search("anything")["matches"] == []


# -- partial trust --------------------------------------------------------


def test_declining_one_file_actually_leaves_it_out(home):
    """Reviewing file by file only means something if a refusal sticks."""
    pending = home / "guidelines" / "pending" / "example.com"
    pending.mkdir(parents=True)
    (pending / "keep.md").write_text("wanted", encoding="utf-8")
    (pending / "skip.md").write_text("unwanted", encoding="utf-8")
    (pending / "meta.json").write_text(json.dumps({"version": 1}), encoding="utf-8")

    guidelines.trust_files("example.com", ["keep.md"])

    assert guidelines.read("example.com/keep") == "wanted"
    with pytest.raises(KeyError):
        guidelines.read("example.com/skip")
    assert (pending / "skip.md").is_file()


# -- the startup check ----------------------------------------------------


def test_the_startup_check_runs_in_the_background(monkeypatch):
    """The server must listen in about a second. A network call on the
    critical path is how this feature gets switched off."""
    from abt import cli

    started = {}
    monkeypatch.setattr(
        cli, "_start_guideline_check", lambda disabled: started.update(disabled=disabled)
    )
    cli._start_guideline_check(False)
    assert started["disabled"] is False


def test_the_startup_check_can_be_switched_off_for_one_run(monkeypatch):
    from abt import cli
    from abt import guidelines as g

    called = []
    monkeypatch.setattr(g, "check_updates", lambda *a, **kw: called.append(1) or [])
    cli._start_guideline_check(disabled=True)
    assert called == []


def test_the_startup_check_never_raises(monkeypatch):
    """A playbook source being unreachable is not a reason for a browser
    server to say anything alarming at boot."""
    from abt import cli
    from abt import guidelines as g

    monkeypatch.setattr(
        g, "check_updates", lambda *a, **kw: (_ for _ in ()).throw(OSError("down"))
    )
    cli._start_guideline_check(disabled=False)  # must not raise


def test_the_daily_limit_holds(home, monkeypatch):
    """Once a day, not once a launch. A toolkit that reaches out on every
    start is a toolkit people turn off."""
    import time as clock

    guidelines.set_config(guidelines_checked_at=clock.time())
    monkeypatch.setattr(
        guidelines, "fetch_index", lambda **kw: (_ for _ in ()).throw(AssertionError)
    )
    assert guidelines.check_updates() == []


# -- CLI input handling ---------------------------------------------------


def test_json_can_arrive_on_stdin(monkeypatch, capsys):
    """Passing JSON as a shell argument is genuinely hard on Windows.
    PowerShell 5.1 strips inner quotes from a single-quoted string and splits
    a long double-quoted one on spaces, so the same command that works in bash
    arrives as invalid JSON or 'unexpected extra argument'."""
    import io

    from abt import cli

    monkeypatch.setattr(cli.sys, "stdin", io.StringIO('{"op":"status"}'))
    assert cli._load("-") == {"op": "status"}


def test_json_can_arrive_as_a_file(tmp_path):
    from abt import cli

    path = tmp_path / "cmd.json"
    path.write_text('{"op":"status"}', encoding="utf-8")
    assert cli._load(str(path)) == {"op": "status"}


def test_inline_json_still_works():
    from abt import cli

    assert cli._load('{"op":"status"}') == {"op": "status"}


def test_a_document_prints_even_when_the_console_cannot_encode_it(capsys):
    """Windows consoles default to cp1252 and the playbooks are full of arrows
    and em-dashes. Losing a glyph is acceptable; losing the document is not."""
    from abt import cli

    cli._echo_document("an arrow \u2192 and an em-dash \u2014 here")
    assert "here" in capsys.readouterr().out


# -- the two-step start ---------------------------------------------------


def test_browser_lifecycle_is_reachable_from_the_cli():
    """`abt up` starts the server; the browser is a separate step. Until these
    existed, the error telling you so pointed at a JSON payload -- no help to
    somebody holding a command line, which is exactly where an agent got stuck.
    """
    from abt import cli

    names = {c.name for c in cli.browser_app.registered_commands}
    assert names == {"start", "stop", "restart", "status"}


def test_the_epilog_leads_with_the_start_sequence():
    """An agent reads this before anything else. The two-step start is the
    thing it gets wrong, so it goes first."""
    from abt import cli

    epilog = cli.AGENT_EPILOG
    assert "abt up" in epilog
    assert "abt browser start" in epilog
    assert "SEPARATE step" in epilog
    # `abt goto` was the third step until the browsing subcommands were
    # collapsed into exec; the ordering assertion is what matters, not the
    # spelling of the command being ordered.
    assert epilog.index("abt up") < epilog.index("abt browser start")
    assert epilog.index("abt browser start") < epilog.index('"op":"goto"')


# -- errors teach ---------------------------------------------------------


def test_every_error_type_carries_a_hint():
    """An agent that hits browser_dead and is told only 'browser is not
    reachable' restarts the server, hits it again, and guesses. That is a real
    session; it cost four commands to get moving."""
    from abt.errors import ERROR_TYPES, HINTS, OpError

    assert set(HINTS) == set(ERROR_TYPES)
    for kind in sorted(ERROR_TYPES):
        hint = OpError(kind, "something went wrong").to_dict()["hint"]
        assert hint and len(hint) > 30, kind


def test_a_hint_says_what_to_do_not_what_happened():
    """The message already says what happened."""
    from abt.errors import OpError

    hint = OpError("browser_dead", "no active page").hint
    assert "abt browser start" in hint
    assert "abt browser restart" in hint


def test_an_explicit_hint_beats_the_type_default():
    """Some failures know more about the remedy than their type does."""
    from abt.errors import OpError

    assert OpError("timeout", "slow", hint="specific advice").hint == "specific advice"


def test_the_op_vocabulary_is_in_the_help():
    """The agent never ran `abt ops`, so the ops have to be where it already
    looks."""
    from abt import cli

    for op in ("goto", "find", "click", "input", "run_js", "tab_new", "wait_for"):
        assert op in cli.AGENT_EPILOG, op
    assert "abt ops" in cli.AGENT_EPILOG
