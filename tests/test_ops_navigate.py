"""Navigation, plus the ref lifecycle that navigation drives."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.ops import dispatch
from abt.schema import parse_command


def run(session, **payload):
    return dispatch(session, parse_command(payload))


def test_goto_returns_url_and_title(clean_session, base_url):
    result = run(clean_session, op="goto", url=f"{base_url}/form.html")
    assert result["url"] == f"{base_url}/form.html"
    assert result["title"] == "Form"


def test_back_and_forward(clean_session, base_url):
    run(clean_session, op="goto", url=f"{base_url}/form.html")
    assert run(clean_session, op="back")["title"] == "Cards"
    assert run(clean_session, op="forward")["title"] == "Form"


def test_reload_keeps_the_page(clean_session):
    assert run(clean_session, op="reload")["title"] == "Cards"


def test_current_url_does_not_navigate(clean_session, base_url):
    assert run(clean_session, op="current_url")["url"] == f"{base_url}/cards.html"


def test_unreachable_url_is_navigation_failed(clean_session):
    # Chrome renders its own error page and reports success to the driver; the
    # session has to notice, or an agent reads the error page as if it were the site.
    with pytest.raises(OpError) as caught:
        run(clean_session, op="goto", url="http://127.0.0.1:9/nothing")
    assert caught.value.type == "navigation_failed"
    assert "ERR_" in caught.value.message


def test_a_real_page_is_not_mistaken_for_an_error_page(clean_session, base_url):
    assert run(clean_session, op="goto", url=f"{base_url}/links.html")["title"] == "Links"


def test_a_404_is_not_a_navigation_failure(clean_session, base_url):
    # The server answered; the agent should be free to read the 404 body.
    result = run(clean_session, op="goto", url=f"{base_url}/missing.html")
    assert result["url"].endswith("/missing.html")


def test_a_level_from_find_can_be_acted_on(clean_session, base_url):
    run(clean_session, op="goto", url=f"{base_url}/form.html")
    level = run(clean_session, op="find", css="#name")["matches"][0]["level"]
    assert run(clean_session, op="input", level=level, value="via-ref")["value"] == "via-ref"


def _number(ref: str) -> int:
    return int(ref.removeprefix("el_"))







