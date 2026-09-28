"""ProfileRegistry against a real Chrome: launch, list, stop."""

from __future__ import annotations

import httpx
import pytest

from abt.profiles import DEFAULT, ProfileRegistry


@pytest.fixture
def reg(tmp_path):
    registry = ProfileRegistry(root=tmp_path / "profiles")
    yield registry
    registry.stop_all()


def test_a_profile_launches_hidden_and_answers_cdp(reg):
    url = reg.attach(DEFAULT, "a")
    version = httpx.get(f"{url}/json/version", timeout=5).json()
    assert "webSocketDebuggerUrl" in version
    assert any(t["url"] == "about:blank" for t in reg.targets(DEFAULT))


def test_the_last_detach_stops_chrome(reg):
    reg.attach(DEFAULT, "a")
    process = reg.running(DEFAULT).process
    reg.detach(DEFAULT, "a")
    assert reg.running(DEFAULT) is None
    assert process.poll() is not None


def test_two_profiles_run_side_by_side(reg):
    reg.create("other")
    first = reg.attach(DEFAULT, "a")
    second = reg.attach("other", "b")
    assert first != second
