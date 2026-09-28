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
    assert '"assets/logo.ico" = "abt/assets/logo.ico"' in pyproject
