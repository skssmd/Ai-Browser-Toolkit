"""The CLI carries the session on every call and manages sessions and profiles.

httpx.request is replaced, so no server is needed.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from abt import cli


class Reply:
    def json(self):
        return {"ok": True, "result": {}}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def request(method, url, json=None, headers=None, timeout=None):
        seen.append({"method": method, "url": url, "json": json, "headers": headers or {}})
        return Reply()

    monkeypatch.setattr(cli.httpx, "request", request)
    monkeypatch.delenv("ABT_SESSION", raising=False)
    monkeypatch.delenv("ABT_TOKEN", raising=False)
    return seen


def run(*args, env=None):
    return CliRunner().invoke(cli.app, list(args), env=env or {})


def test_the_session_rides_along(calls):
    run("--session", "a", "command-list", '{"op":"status"}')
    assert calls[-1]["headers"]["X-ABT-Session"] == "a"


def test_the_environment_names_the_session_and_token(calls):
    run("command-list", '{"op":"status"}', env={"ABT_SESSION": "b", "ABT_TOKEN": "t"})
    assert calls[-1]["headers"] == {"X-ABT-Session": "b", "X-ABT-Token": "t"}


def test_no_session_sends_no_header(calls):
    run("command-list", '{"op":"status"}')
    assert "X-ABT-Session" not in calls[-1]["headers"]


def test_session_management(calls):
    run("session", "new", "a", "--profile", "work", "--sealed")
    assert calls[-1]["method"] == "POST" and calls[-1]["url"].endswith("/sessions")
    assert calls[-1]["json"] == {"name": "a", "profile": "work", "sealed": True}
    run("session", "set", "a", "--profile", "home")
    assert calls[-1]["method"] == "PATCH" and calls[-1]["json"] == {"profile": "home"}
    run("session", "rm", "a", "--yes")
    assert calls[-1]["method"] == "DELETE" and calls[-1]["url"].endswith("/sessions/a")


def test_profile_management(calls):
    run("profile", "new", "work")
    assert calls[-1]["json"] == {"name": "work"}
    run("profile", "set", "work", "--headed")
    assert calls[-1]["method"] == "PATCH" and calls[-1]["json"] == {"headed": True}
    run("profile", "rm", "work", "--yes")
    assert calls[-1]["method"] == "DELETE"


def test_rules_and_switches(calls):
    run("session", "new", "a", "--rules", "app.x.com/admin, !app.x.com/api", "--no-run-js")
    assert calls[-1]["json"]["settings"] == {
        "rules": ["app.x.com/admin", "!app.x.com/api"],
        "run_js": False,
    }
    run("session", "set", "a", "--rules", "", "--strict")
    assert calls[-1]["json"] == {"settings": {"rules": [], "strict": True}}
