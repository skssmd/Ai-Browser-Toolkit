"""The desktop app as something to click: a launcher per platform, per user."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from abt import shortcut

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))


def test_linux_gets_an_app_menu_entry(tmp_path):
    where = shortcut.install(platform="linux", home=tmp_path)
    assert where == tmp_path / ".local" / "share" / "applications" / "aibrowsertoolkit.desktop"
    entry = where.read_text(encoding="utf-8")
    assert f'Exec="{shortcut.gui_python()}" -m abt app' in entry
    assert "Terminal=false" in entry and "Name=AI Browser Toolkit" in entry
    assert "logo-white-256.png" in entry  # the icon, by its full path
    assert shortcut.remove(platform="linux", home=tmp_path) == where and not where.exists()


def test_macos_gets_an_app_in_applications(tmp_path):
    where = shortcut.install(platform="darwin", home=tmp_path)
    assert where == tmp_path / "Applications" / "AI Browser Toolkit.app"
    launcher = where / "Contents" / "MacOS" / "AI Browser Toolkit"
    assert f'exec "{shortcut.gui_python()}" -m abt app' in launcher.read_text(encoding="utf-8")
    plist = (where / "Contents" / "Info.plist").read_text(encoding="utf-8")
    assert "<key>CFBundleExecutable</key><string>AI Browser Toolkit</string>" in plist
    shortcut.install(platform="darwin", home=tmp_path)  # replacing it is fine
    assert shortcut.remove(platform="darwin", home=tmp_path) and not where.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows' shortcut maker")
def test_windows_gets_a_start_menu_shortcut(tmp_path):
    where = shortcut.install(platform="win32", home=tmp_path)
    assert where.name == "AI Browser Toolkit.lnk" and "Start Menu" in str(where)
    assert where.is_file() and where.stat().st_size > 0
    assert shortcut.remove(platform="win32", home=tmp_path) and not where.exists()


def test_the_app_opens_without_a_console_on_windows():
    if sys.platform == "win32":
        assert shortcut.gui_python().name.lower() == "pythonw.exe"


def test_a_checkout_is_not_given_one_unasked(monkeypatch):
    made = []
    monkeypatch.setattr(shortcut, "install", lambda *a, **k: made.append(1))
    shortcut.ensure(echo=lambda *_: None)
    assert made == []  # these tests run from the checkout


def test_first_run_adds_one_when_nothing_else_did(monkeypatch, tmp_path):
    from abt import paths

    monkeypatch.setattr(paths, "in_source_checkout", lambda *a: False)
    monkeypatch.setattr(shortcut, "managed_elsewhere", lambda: False)
    monkeypatch.setattr(shortcut, "exists", lambda: False)
    monkeypatch.setattr(shortcut, "install", lambda: tmp_path / "x.desktop")
    said = []
    shortcut.ensure(echo=said.append)
    assert said and "added AI Browser Toolkit" in said[0]


# -- the packages that add it themselves --------------------------------------------


def test_the_linux_packages_install_the_menu_entry_and_icon():
    nfpm = (ROOT / "packaging" / "nfpm.yaml").read_text(encoding="utf-8")
    assert "dst: /usr/share/applications/aibrowsertoolkit.desktop" in nfpm
    assert "dst: /usr/share/icons/hicolor/256x256/apps/aibrowsertoolkit.png" in nfpm
    pkgbuild = (ROOT / "packaging" / "aur" / "PKGBUILD.template").read_text(encoding="utf-8")
    assert "/usr/share/applications/aibrowsertoolkit.desktop" in pkgbuild
    entry = (ROOT / "assets" / "aibrowsertoolkit.desktop").read_text(encoding="utf-8")
    assert "Exec=/usr/bin/abt app" in entry and "Icon=aibrowsertoolkit" in entry
    for source in ("assets/aibrowsertoolkit.desktop", "assets/logo-white-256.png"):
        assert (ROOT / source).is_file()  # both ship in every bundle's assets/


def test_scoop_adds_a_start_menu_shortcut():
    manifest = json.loads((ROOT / "packaging" / "scoop" / "manifest.json.template").read_text(encoding="utf-8"))
    target, name, args, icon = manifest["shortcuts"][0]
    assert (target, name, args) == ("python\\pythonw.exe", "AI Browser Toolkit", "-m abt app")
    assert (ROOT / icon.replace("\\", "/")).is_file()
