"""Console/network reading, segmented date inputs, and scroll-before-click.

Every case here comes from a real failure on a live site, not from imagination.
"""

from __future__ import annotations

import pytest

from abt.errors import ERROR_TYPES, OpError


@pytest.fixture
def page(client, base_url):
    client.post("/command", json={"op": "goto", "url": f"{base_url}/inspect.html"})
    return client


# --- segmented inputs (date/time/month/datetime-local) -------------------------


def test_a_date_input_gets_the_value_it_was_given(page):
    """The HR-form bug: send_keys made 2026-08-03 land as 60803-02-20."""
    body = page.post(
        "/command", json={"op": "input", "css": "#d", "value": "2026-08-03"}
    ).json()
    assert body["ok"] is True, body
    assert body["result"]["value"] == "2026-08-03"
    assert body["result"]["set_directly"] is True


def test_the_page_is_told_the_date_changed(page):
    """Setting .value silently is useless -- the framework must see the event."""
    page.post("/command", json={"op": "input", "css": "#d", "value": "2026-08-03"})
    text = page.post("/command", json={"op": "get_text", "css": "#echo"}).json()
    assert text["result"] == "d=2026-08-03"


@pytest.mark.parametrize(
    "css,value",
    [("#t", "14:30"), ("#m", "2026-08"), ("#dt", "2026-08-03T09:15")],
)
def test_every_segmented_type_round_trips(page, css, value):
    body = page.post("/command", json={"op": "input", "css": css, "value": value}).json()
    assert body["result"]["value"] == value


def test_a_date_input_rejects_a_value_it_cannot_parse(page):
    body = page.post(
        "/command", json={"op": "input", "css": "#d", "value": "03/08/2026"}
    ).json()
    assert body["ok"] is False
    assert body["error"]["type"] == "not_interactable"
    assert "YYYY-MM-DD" in body["error"]["message"]


def test_a_plain_text_input_is_still_typed_into(page):
    body = page.post(
        "/command", json={"op": "input", "css": "#plain", "value": "typed"}
    ).json()
    assert body["result"]["value"] == "typed"
    assert "set_directly" not in body["result"]


# --- scroll before click -------------------------------------------------------


def test_a_button_below_the_fold_is_scrolled_to_and_clicked(page):
    """This failed as not_interactable on hr.dataclans.com at y=1009."""
    body = page.post("/command", json={"op": "click", "css": "#low"}).json()
    assert body["ok"] is True, body
    text = page.post("/command", json={"op": "get_text", "css": "#clicked"}).json()
    assert text["result"] == "the low button was clicked"


def test_a_ref_below_the_fold_is_also_scrolled_to(page):
    found = page.post("/command", json={"op": "find", "css": "#low"}).json()
    ref = found["result"]["matches"][0]["ref"]
    assert page.post("/command", json={"op": "click", "ref": ref}).json()["ok"] is True


def test_present_does_not_scroll(page):
    """Asserting a thing exists should not move the page under you."""
    before = page.post(
        "/command", json={"op": "run_js", "script": "return window.scrollY;"}
    ).json()["result"]["value"]
    page.post("/command", json={"op": "wait_for", "css": "#low", "state": "present"})
    after = page.post(
        "/command", json={"op": "run_js", "script": "return window.scrollY;"}
    ).json()["result"]["value"]
    assert before == after


# --- console -------------------------------------------------------------------


def test_console_captures_what_the_page_logged_while_loading(page):
    body = page.post("/command", json={"op": "read_console"}).json()
    assert body["result"]["available"] is True
    texts = [m["text"] for m in body["result"]["messages"]]
    assert "page loaded" in texts
    assert any("boom" in t for t in texts)


def test_console_filters_by_level(page):
    body = page.post("/command", json={"op": "read_console", "levels": ["error"]}).json()
    levels = {m["level"] for m in body["result"]["messages"]}
    assert levels == {"error"}


def test_console_filters_by_pattern(page):
    body = page.post("/command", json={"op": "read_console", "pattern": "widget"}).json()
    assert body["result"]["count"] == 1
    assert "widget" in body["result"]["messages"][0]["text"]


def test_a_bad_console_pattern_is_a_typed_error(page):
    body = page.post("/command", json={"op": "read_console", "pattern": "("}).json()
    assert body["error"]["type"] == "invalid_op"


def test_console_survives_a_reload(page):
    """Capture is installed at document start, not injected after the fact."""
    page.post("/command", json={"op": "reload"})
    body = page.post("/command", json={"op": "read_console"}).json()
    assert "page loaded" in [m["text"] for m in body["result"]["messages"]]


def test_console_works_in_a_tab_opened_after_startup(client, base_url):
    """CDP arms one target at a time.

    Registering the init script once at startup left every later tab blind --
    which is every `tab_new`, every new_tab click, and every background send.
    """
    client.post(
        "/command", json={"op": "tab_new", "url": f"{base_url}/inspect.html"}
    )
    body = client.post("/command", json={"op": "read_console"}).json()
    assert body["result"]["available"] is True
    assert "page loaded" in [m["text"] for m in body["result"]["messages"]]


def test_console_works_after_switching_back_to_a_tab(client, base_url):
    first = client.get("/status").json()["result"]["active_tab"]
    client.post("/command", json={"op": "tab_new", "url": f"{base_url}/cards.html"})
    client.post("/command", json={"op": "tab_switch", "tab_id": first})
    client.post("/command", json={"op": "goto", "url": f"{base_url}/inspect.html"})
    body = client.post("/command", json={"op": "read_console"}).json()
    assert "page loaded" in [m["text"] for m in body["result"]["messages"]]


# --- network -------------------------------------------------------------------


def test_network_lists_requests_with_statuses(page):
    body = page.post("/command", json={"op": "read_network"}).json()
    assert body["result"]["count"] > 0
    assert any(r["url"].endswith("cards.html") for r in body["result"]["requests"])


def test_network_can_show_failures_only(page):
    """The R2 case: find the 404 without reading everything that worked."""
    body = page.post("/command", json={"op": "read_network", "failures_only": True}).json()
    urls = [r["url"] for r in body["result"]["requests"]]
    assert any("no-such-file-xyz" in u for u in urls)
    assert not any(u.endswith("cards.html") for u in urls)


def test_network_filters_by_url_pattern(page):
    body = page.post(
        "/command", json={"op": "read_network", "pattern": "no-such-file"}
    ).json()
    assert body["result"]["count"] == 1
    assert body["result"]["requests"][0]["status"] == 404


def test_network_min_status_selects_server_answers(page):
    body = page.post("/command", json={"op": "read_network", "min_status": 400}).json()
    assert all(r["status"] >= 400 for r in body["result"]["requests"])


# --- error plumbing ------------------------------------------------------------


def test_bad_browser_is_a_real_error_type():
    """It was raised but not registered, so it blew up as a ValueError."""
    assert "bad_browser" in ERROR_TYPES
    assert OpError("bad_browser", "nope").type == "bad_browser"


def test_an_unsupported_browser_fails_cleanly(tmp_path):
    from abt.browser import BrowserSession

    with pytest.raises(OpError) as exc:
        BrowserSession(profile=tmp_path, browser="firefox")
    assert exc.value.type == "bad_browser"
    assert "chrome" in exc.value.message


def test_status_and_shutdown_skip_the_health_check():
    from abt.ops import NO_HEALTH_CHECK

    assert {"shutdown", "status"} <= NO_HEALTH_CHECK


def test_status_answers_even_when_the_browser_is_gone(clean_session):
    """A dead browser must still be able to say it is dead."""
    from fastapi.testclient import TestClient
    from selenium.common.exceptions import InvalidSessionIdException

    from abt.server import create_app

    class Corpse:
        def __getattr__(self, name):
            raise InvalidSessionIdException("invalid session id")

    with TestClient(create_app(clean_session)) as client:
        original = clean_session._driver
        clean_session._driver = Corpse()
        try:
            body = client.get("/status").json()
        finally:
            clean_session._driver = original

    assert body["ok"] is False
    assert body["error"]["type"] == "browser_dead"


# --- what only a browser-level network log can answer -------------------------
#
# Resource Timing is a page API. Everything below is a question it cannot
# answer at all, which is why these are the reason the Playwright backend
# exists rather than a nicety on top of it.


def _native(client) -> bool:
    """Whether this engine keeps its own network log."""
    session = client.app.state.session if hasattr(client, "app") else None
    return session is not None and hasattr(session.driver, "network_log")


def _post(client, **payload):
    return client.post("/command", json=payload).json()["result"]


def test_a_cors_blocked_request_is_still_reported_as_a_failure(client, base_url, other_origin):
    """The status is genuinely unavailable, but the attempt is not.

    Resource Timing records what loaded, so a blocked request leaves no entry
    at all and the failure is invisible. The browser's own events at least say
    it happened and why.
    """
    if not _native(client):
        pytest.skip("native log only")
    _post(client, op="goto", url=f"{base_url}/cards.html")
    _post(
        client,
        op="run_js",
        script=f"return fetch('{other_origin}/blocked-xyz')"
        ".then(function () { return 1; })"
        ".catch(function () { return 1; });",
    )
    rows = _post(client, op="read_network", failures_only=True, pattern="blocked-xyz")
    assert rows["requests"], "a blocked request left no trace"
    assert rows["requests"][-1].get("error")


def test_the_method_is_recorded(client, base_url):
    """Not a field Resource Timing has. A GET and a POST to one URL are
    different events, and telling them apart used to be impossible."""
    if not _native(client):
        pytest.skip("Resource Timing has no method")
    _post(client, op="goto", url=f"{base_url}/cards.html")
    _post(
        client,
        op="run_js",
        script="return fetch('/echo-xyz', {method: 'POST', body: 'x'})"
        ".then(function () { return 1; })"
        ".catch(function () { return 1; });",
    )
    rows = _post(client, op="read_network", pattern="echo-xyz")["requests"]
    assert rows and rows[-1]["method"] == "POST"


def test_a_request_that_never_got_a_response_is_reported(client, base_url):
    """Resource Timing records what *loaded*. A refused connection produces no
    entry at all, so the failure is invisible -- and a request that never lands
    is precisely the one worth knowing about.

    It arrives with `status: null`, which `failures_only` already treats as a
    failure, so it surfaces where a caller looking for trouble is looking.
    """
    if not _native(client):
        pytest.skip("Resource Timing cannot see a refused connection")
    _post(client, op="goto", url=f"{base_url}/cards.html")
    _post(
        client,
        op="run_js",
        script="return fetch('http://127.0.0.1:1/gone-xyz')"
        ".then(function () { return 1; })"
        ".catch(function () { return 1; });",
    )
    rows = _post(client, op="read_network", failures_only=True, pattern="gone-xyz")
    assert rows["requests"], "a refused connection left no trace"
    entry = rows["requests"][-1]
    assert entry["status"] is None
    assert entry.get("error")


def test_the_log_is_cleared_when_the_page_navigates(client, base_url):
    """Resource Timing is per document, so `read_network` has always meant
    "this page". Keeping entries across a navigation would quietly change what
    the op answers."""
    if not _native(client):
        pytest.skip("native log only")
    _post(client, op="goto", url=f"{base_url}/cards.html")
    _post(client, op="goto", url=f"{base_url}/links.html")
    urls = [r["url"] for r in _post(client, op="read_network")["requests"]]
    assert not any(u.endswith("cards.html") for u in urls)


# --- credentials must not leave in a URL --------------------------------------
#
# `diff.py` already refuses to capture password field values, for the stated
# reason that diffs get written to session logs. Network rows go to the same
# file and are handed to a model besides. Watching the browser's own events
# sees more requests than the page ever did, so the rule matters more, not less.


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "https://api.example.com/v1/me?access_token=ya29.SECRET&pretty=1",
            "https://api.example.com/v1/me?access_token=REDACTED&pretty=1",
        ),
        (
            "https://cdn.example.com/f.pdf?sig=abc&Expires=99",
            "https://cdn.example.com/f.pdf?sig=REDACTED&Expires=99",
        ),
        (
            "https://example.com/cb?code=4/0AY0e&scope=email",
            "https://example.com/cb?code=REDACTED&scope=email",
        ),
        ("https://user:hunter2@example.com/x", "https://user:REDACTED@example.com/x"),
    ],
)
def test_a_credential_in_a_url_is_replaced(raw, expected):
    from abt.ops.inspect import redact

    assert redact(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/plain?page=2&q=hello",
        "https://example.com/no-query",
        "https://example.com/path/with/segments",
    ],
)
def test_an_ordinary_url_is_untouched(raw):
    """Redaction that rewrites innocent URLs would make every diagnosis harder
    and every log harder to trust."""
    from abt.ops.inspect import redact

    assert redact(raw) == raw


def test_the_status_survives_redaction(client, base_url):
    """The credential goes, the diagnosis stays: path, status and method are
    what a failure is read from, and none of them are secret."""
    if not _native(client):
        pytest.skip("native log only")
    _post(client, op="goto", url=f"{base_url}/cards.html")
    _post(
        client,
        op="run_js",
        script="return fetch('/guarded-xyz?token=SECRETVALUE&page=2')"
        ".then(function () { return 1; })"
        ".catch(function () { return 1; });",
    )
    rows = _post(client, op="read_network", pattern="guarded-xyz")["requests"]
    assert rows, "the request was not recorded"
    row = rows[-1]
    assert "SECRETVALUE" not in row["url"]
    assert "token=REDACTED" in row["url"]
    assert "page=2" in row["url"]
    assert row["status"] == 404
