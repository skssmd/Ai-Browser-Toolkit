"""The two lifecycle tests that genuinely need a browser."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from abt.browser import BrowserSession


@pytest.fixture
def own_session():
    """A session this test owns outright, so stopping it breaks nothing else."""
    profile = Path(tempfile.mkdtemp(prefix="abt-lifecycle-"))
    built = BrowserSession(profile=profile, headless=True, action_timeout=3.0)
    yield built
    built.stop()


def test_a_stopped_browser_comes_back_clean(own_session, base_url):
    own_session.start()
    own_session.goto(f"{base_url}/cards.html")
    first_tab = own_session.active_tab
    # Give it state worth losing. `goto` alone does not record a baseline --
    # only dispatch does that for DOM-touching ops -- so set one by hand.
    own_session.set_baseline()
    assert own_session.baseline() is not None

    stopped = own_session.stop()
    assert stopped["stopped"] is True
    assert own_session.is_running is False
    assert own_session._baselines == {}

    own_session.start()
    own_session.goto(f"{base_url}/cards.html")

    # A fresh browser deserves tab_0, and nothing from before may survive.
    assert own_session.active_tab == "tab_0" == first_tab
    assert own_session.refs.count(own_session.active_tab) == 0
    assert own_session.baseline() is None


def test_back_to_back_restarts_survive_the_profile_handoff(own_session, base_url):
    """The regression test for the hand-off.

    Without the wait in stop(), the second browser attaches to the dying first
    one and this goto fails -- and it fails looking like a flaky network rather
    than a lifecycle bug, which is why it is worth spending a live test on.
    """
    own_session.start()
    own_session.restart()
    own_session.restart()

    own_session.goto(f"{base_url}/cards.html")
    assert own_session.is_running is True
    assert "cards" in own_session.driver.current_url
