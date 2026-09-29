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
