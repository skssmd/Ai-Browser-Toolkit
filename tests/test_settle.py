"""A navigation must report the page, not the page's spinner.

`driver.get` returns when the document has loaded, which on a single-page app
is the instant a spinner mounts and nothing else exists yet. Found in the wild
on hr.dataclans.com: every `goto` came back with 17 strings of navigation
chrome plus "Loading dashboard..." and "Please wait while we process your
request", so agents correctly learned to distrust the diff and re-read the body
after every navigation -- the exact round trip the diff exists to remove.

It survived 253 passing tests because every other fixture is complete at load.
"""

from __future__ import annotations

import pytest
from conftest import texts

from abt.schema import parse_command
from abt.ops import dispatch


def run(session, **payload):
    return dispatch(session, parse_command(payload))


@pytest.fixture
def clean(session, base_url):
    for tab in list(session.tabs()):
        if not tab["active"]:
            session.close_tab(tab["tab_id"])
    return session


def added(result):
    # These tests ask whether late content arrived, not where it landed.
    return texts(result["dom_diff"]["text"]["added"])


def test_goto_waits_for_late_content(clean, base_url):
    text = added(run(clean, op="goto", url=f"{base_url}/late.html"))

    assert "Quarterly report" in text
    assert "Revenue: $42,000" in text


def test_goto_does_not_report_the_spinner_as_the_page(clean, base_url):
    """The failure exactly as it appeared in production."""
    text = added(run(clean, op="goto", url=f"{base_url}/late.html"))

    assert "Loading dashboard..." not in text
    assert "Please wait while we process your request." not in text


def test_reload_settles_too(clean, base_url):
    run(clean, op="goto", url=f"{base_url}/late.html")
    assert "Quarterly report" in added(run(clean, op="reload"))


def test_back_settles_too(clean, base_url):
    run(clean, op="goto", url=f"{base_url}/late.html")
    run(clean, op="goto", url=f"{base_url}/cards.html")
    assert "Quarterly report" in added(run(clean, op="back"))


def test_a_click_that_redirects_settles(clean, base_url):
    """A click that leaves the page lands on a rendering document too."""
    run(clean, op="goto", url=f"{base_url}/cards.html")
    result = run(clean, op="goto", url=f"{base_url}/late.html")
    assert "Quarterly report" in added(result)


def test_settle_reports_failure_rather_than_hanging(clean, base_url):
    """A page that never stops moving costs the timeout, then proceeds."""
    run(clean, op="goto", url=f"{base_url}/late.html")
    clean.driver.execute_script(
        "window.__t = setInterval(() => document.body.appendChild("
        "document.createTextNode('x')), 10);"
    )
    try:
        assert clean.settle(timeout=0.6) is False
    finally:
        clean.driver.execute_script("clearInterval(window.__t);")


def test_a_static_page_settles_immediately(clean, base_url):
    """The cost on an ordinary page is a few samples, not the timeout."""
    import time

    run(clean, op="goto", url=f"{base_url}/cards.html")
    started = time.monotonic()
    assert clean.settle() is True
    assert time.monotonic() - started < 1.0


def test_a_render_that_waits_on_fetch_is_not_reported_as_the_spinner(clean, base_url):
    """The case a DOM-only check gets wrong.

    While a request is outstanding the DOM holds perfectly still, so "nothing
    changed for a while" reads as ready. Only the in-flight count separates a
    page that is waiting from a page that is done.
    """
    text = added(run(clean, op="goto", url=f"{base_url}/slowfetch.html"))

    assert "Fetched report" in text
    assert "Revenue: $88,000" in text
    assert "Loading dashboard..." not in text


def test_chained_requests_do_not_settle_in_the_gap(clean, base_url):
    """The counter dips to zero between two chained fetches; that is not idle."""
    text = added(run(clean, op="goto", url=f"{base_url}/slowfetch.html"))
    assert "Please wait while we process your request." not in text


def test_the_network_probe_survives_navigation(clean, base_url):
    """It is a document-start script, so every new document must get it."""
    run(clean, op="goto", url=f"{base_url}/cards.html")
    run(clean, op="goto", url=f"{base_url}/slowfetch.html")
    present = clean.driver.execute_script("return !!window.__abtNet;")
    assert present is True


def test_a_gap_between_chained_requests_is_not_mistaken_for_done(clean, base_url):
    """Reported from a live app: fetch a URL, process it, fetch that URL.

    Between the two the in-flight count is zero and the DOM is still, so a
    short grace period settles mid-chain and the diff goes out holding the
    spinner. Nothing observable separates "between requests" from "finished"
    except waiting longer than the gap.
    """
    text = added(run(clean, op="goto", url=f"{base_url}/chainfetch.html"))

    assert "Chained report" in text
    assert "Revenue: $17,500" in text
    assert "Loading dashboard..." not in text


def test_the_grace_period_is_tunable(session):
    """No fixed value fits every app, so the knob has to exist and be wired."""
    assert session.settle_network_grace > 0
    from abt.browser import BrowserSession
    from pathlib import Path

    tuned = BrowserSession(profile=Path("."), settle_network_grace=2.5)
    assert tuned.settle_network_grace == 2.5
