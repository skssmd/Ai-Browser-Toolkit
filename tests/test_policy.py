"""Session URL rules: grammar, matching, precedence. No browser.

The server-side checks at the bottom run with sessions that never start a
browser: a blocked `goto` must fail before anything is touched.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.errors import OpError
from abt.policy import Policy, parse_rule, validate_settings
from abt.profiles import ProfileRegistry
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


def test_an_allow_rule_makes_an_allow_list():
    p = Policy(["app.example.com/admin"])
    assert p.allows("https://app.example.com/admin")
    assert p.allows("https://app.example.com/admin/users?x=1")
    assert not p.allows("https://app.example.com/")
    assert not p.allows("https://other.example.com/admin")


def test_paths_match_on_segment_boundaries():
    p = Policy(["a.com/admin"])
    assert p.allows("http://a.com/admin/")
    assert not p.allows("http://a.com/administrator")


def test_deny_wins():
    p = Policy(["app.example.com", "!app.example.com/api"])
    assert p.allows("https://app.example.com/admin")
    assert not p.allows("https://app.example.com/api/users")
    assert p.verdict("https://app.example.com/api")[1] == "!app.example.com/api"


def test_only_denies_allow_everything_else():
    p = Policy(["!ads.example.com"])
    assert p.allows("https://news.example.org/")
    assert not p.allows("https://ads.example.com/x")


def test_wildcard_covers_the_domain_and_its_subdomains():
    p = Policy(["*.example.com"])
    assert p.allows("https://example.com/")
    assert p.allows("https://deep.a.example.com/")
    assert not p.allows("https://example.com.evil.net/")


def test_hosts_are_case_insensitive_and_scheme_is_ignored():
    p = Policy(["https://App.Example.com/x"])
    assert p.allows("http://app.example.COM/x/y")


def test_a_port_counts_only_when_written():
    p = Policy(["localhost:8080"])
    assert p.allows("http://localhost:8080/")
    assert not p.allows("http://localhost:9090/")
    assert Policy(["localhost"]).allows("http://localhost:9090/")


def test_inert_schemes_pass_and_others_are_blocked():
    p = Policy(["a.com"])
    for url in ("about:blank", "data:text/html,x", "blob:https://a.com/uuid"):
        assert p.allows(url)
    for url in ("file:///etc/passwd", "chrome://settings", "ftp://a.com/"):
        assert not p.allows(url)


def test_no_rules_means_no_restriction():
    assert Policy().allows("file:///anything")
    assert not Policy()


def test_only_documents_and_api_calls_unless_strict():
    assert Policy(["a.com"]).guards("Document")
    assert Policy(["a.com"]).guards("Fetch")
    assert not Policy(["a.com"]).guards("Image")
    assert Policy(["a.com"], strict=True).guards("Image")


@pytest.mark.parametrize("bad", ["", "!", "a b.com", "/path-only", "a..com", 5])
def test_malformed_rules_are_refused(bad):
    with pytest.raises(OpError) as exc:
        parse_rule(bad)
    assert exc.value.type == "invalid_op"


@pytest.mark.parametrize(
    "bad", ["rules", {"rules": "a.com"}, {"rules": ["ok.com", "bad host"]}, {"run_js": "no"}]
)
def test_malformed_settings_are_refused(bad):
    with pytest.raises(OpError) as exc:
        validate_settings(bad)
    assert exc.value.type == "invalid_op"


def test_check_names_the_rule():
    with pytest.raises(OpError) as exc:
        Policy(["a.com", "!a.com/api"]).check("https://a.com/api/x")
    assert exc.value.type == "url_blocked"
    assert "!a.com/api" in exc.value.message


# --- in the server, without a browser ---------------------------------------------


@pytest.fixture
def client(tmp_path):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
    )
    with TestClient(create_app(registry=registry)) as c:
        yield c


def test_bad_settings_are_a_400_not_a_500(client):
    r = client.post("/sessions", json={"name": "a", "settings": {"rules": "a.com"}})
    assert r.status_code == 400
    r = client.post("/sessions", json={"name": "b", "settings": "nope"})
    assert r.status_code == 400


def test_run_js_off_hides_it_and_refuses_it(client):
    client.post("/sessions", json={"name": "a", "settings": {"run_js": False}})
    names = client.get("/ops", params={"names": True, "session": "a"}).json()["result"]
    assert "run_js" not in names
    client.patch("/sessions/a", json={"settings": {"run_js": True}})
    names = client.get("/ops", params={"names": True, "session": "a"}).json()["result"]
    assert "run_js" in names


def test_a_rule_change_applies_to_the_next_command(client):
    client.post("/sessions", json={"name": "a", "settings": {"rules": ["a.com"]}})
    # Blocked before the browser is ever asked -- none is running.
    body = client.post(
        "/command-list",
        json={"op": "goto", "url": "https://b.com/"},
        headers={"X-ABT-Session": "a"},
    ).json()
    assert body["error"]["type"] == "url_blocked"


def test_all_allows_every_site_and_limits_nothing():
    policy = Policy(["all"], only_listed=True)
    assert not policy  # no guard needed
    assert policy.allows("https://anything.example/x")
    assert not Policy(["*"])


def test_all_with_a_block_is_everything_but_that():
    policy = Policy(["all", "!app.example.com/api"], only_listed=True)
    assert policy
    assert policy.allows("https://example.org/")
    assert policy.allows("https://app.example.com/admin")
    assert not policy.allows("https://app.example.com/api/users")


def test_only_listed_with_nothing_listed_reaches_nothing():
    policy = Policy([], only_listed=True)
    assert policy
    assert not policy.allows("https://example.com/")
    assert policy.allows("about:blank")
    with pytest.raises(OpError, match="allowed-sites list is empty"):
        policy.check("https://example.com/")
    # Only blocks, and nothing allowed: still nothing.
    assert not Policy(["!evil.example"], only_listed=True).allows("https://example.com/")


def test_without_only_listed_an_empty_list_still_means_no_limit():
    """Sessions made before `only_listed` keep working as they did."""
    assert not Policy([])
    assert Policy([]).allows("https://example.com/")
    assert Policy(["!evil.example"]).allows("https://example.com/")


def test_only_listed_must_be_a_boolean():
    with pytest.raises(OpError):
        validate_settings({"only_listed": "yes"})
