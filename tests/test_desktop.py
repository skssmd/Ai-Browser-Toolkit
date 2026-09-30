"""The app window's icon is found, in a checkout and in an installed package."""

from __future__ import annotations

from abt import desktop


def test_the_window_has_an_icon():
    path = desktop.icon_path()
    assert path is not None and path.is_file()
    assert path.suffix in (".ico", ".png")


def test_the_wheel_ships_the_icon():
    """pyproject's force-include is what puts it inside an installed package."""
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    assert '"assets/logo-white.ico" = "abt/assets/logo-white.ico"' in pyproject


def test_the_app_starts_a_server_whose_browsers_are_hidden(monkeypatch):
    """The app shows every session's pages, so a server it starts runs every
    browser hidden -- CLI and MCP agents too. `abt up` keeps windows."""
    from typer.testing import CliRunner

    from abt import cli

    started = []
    monkeypatch.setattr(cli, "_healthy", lambda base: False)
    monkeypatch.setattr(cli, "up", lambda **kw: started.append(kw["headless"]))
    monkeypatch.setattr(desktop, "open_window", lambda base: "window")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["app"]).exit_code == 0
    assert runner.invoke(cli.app, ["app", "--headed"]).exit_code == 0
    assert started == [True, False]


def test_the_window_tells_the_page_its_bridge_is_coming(monkeypatch, tmp_path):
    """On Linux, pywebview's GTK and Qt backends attach the bridge seconds after
    the page loads. Not knowing one was coming, the page gave up after 1.5s and
    asked for the access token by hand, inside the desktop app."""
    import sys
    from types import SimpleNamespace

    opened = {}
    fake = SimpleNamespace(
        create_window=lambda title, url, **kw: opened.update(url=url, api=kw.get("js_api")),
        start=lambda **kw: None,
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(desktop, "close_browsers", lambda base, api: None)
    monkeypatch.setattr(desktop, "sessions_dir", lambda base: tmp_path)
    assert desktop.open_window("http://127.0.0.1:1") == "window"
    assert opened["url"] == "http://127.0.0.1:1/app?desktop=1" and opened["api"] is not None
    # No token files to hand over: no promise of a bridge either.
    monkeypatch.setattr(desktop, "sessions_dir", lambda base: None)
    desktop.open_window("http://127.0.0.1:1")
    assert opened["url"] == "http://127.0.0.1:1/app" and opened["api"] is None
