"""`abt shortcut`: the desktop app as something to click, not a command to type.

The Windows installer, Scoop and the Linux system packages put the app in the
menu themselves. A pip or Homebrew install has only the `abt` command, so the
app never showed up anywhere -- this adds it, for the current user:

* Linux: a `.desktop` entry in ~/.local/share/applications (the app menu, and
  the dock once pinned).
* macOS: a small `AI Browser Toolkit.app` in ~/Applications (Launchpad,
  Spotlight, the Dock).
* Windows: a Start-menu shortcut.

Each runs this same interpreter's `abt app`, so it opens whichever copy made
it. `abt app` adds it on its first run; `abt shortcut --remove` takes it away.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "AI Browser Toolkit"
ID = "aibrowsertoolkit"
COMMENT = "Watch and drive AI agents in a real browser"


def _asset(name: str) -> Path | None:
    here = Path(__file__).resolve().parent
    for candidate in (here / "assets" / name, here.parents[1] / "assets" / name):
        if candidate.is_file():
            return candidate
    return None


def gui_python() -> Path:
    """The interpreter to launch the app with: pythonw on Windows, so no console opens."""
    python = Path(sys.executable)
    if sys.platform == "win32" and python.name.lower() == "python.exe":
        windowless = python.with_name("pythonw.exe")
        if windowless.exists():
            return windowless
    return python


def location(platform: str | None = None, home: Path | None = None) -> Path:
    """Where the launcher lives for this user."""
    platform = platform or sys.platform
    home = Path(home or Path.home())
    if platform == "win32":
        start = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return start / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{NAME}.lnk"
    if platform == "darwin":
        return home / "Applications" / f"{NAME}.app"
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return data / "applications" / f"{ID}.desktop"


def desktop_entry(python: Path, icon: Path | None) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={NAME}",
        f"Comment={COMMENT}",
        f'Exec="{python}" -m abt app',
        f"Icon={icon}" if icon else f"Icon={ID}",
        "Terminal=false",
        "Categories=Network;Development;",
        f"StartupWMClass={NAME}",
        "",
    ])


def mac_bundle(target: Path, python: Path, icon_png: Path | None) -> None:
    contents = target / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(parents=True, exist_ok=True)
    launcher = contents / "MacOS" / NAME
    launcher.write_text(f'#!/bin/sh\nexec "{python}" -m abt app\n', encoding="utf-8")
    launcher.chmod(0o755)
    icon_line = ""
    if icon_png is not None and shutil.which("sips"):
        # sips ships with macOS and writes an .icns straight from a PNG.
        done = subprocess.run(
            ["sips", "-s", "format", "icns", str(icon_png), "--out", str(contents / "Resources" / "icon.icns")],
            capture_output=True,
        )
        if done.returncode == 0:
            icon_line = "  <key>CFBundleIconFile</key><string>icon</string>\n"
    (contents / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"  <key>CFBundleName</key><string>{NAME}</string>\n"
        f"  <key>CFBundleDisplayName</key><string>{NAME}</string>\n"
        f"  <key>CFBundleIdentifier</key><string>io.github.skssmd.{ID}</string>\n"
        f"  <key>CFBundleExecutable</key><string>{NAME}</string>\n"
        "  <key>CFBundlePackageType</key><string>APPL</string>\n"
        f"{icon_line}"
        "</dict></plist>\n",
        encoding="utf-8",
    )


def windows_shortcut(target: Path, python: Path, icon: Path | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    def quoted(value) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + quoted(target) + ");"
        f"$s.TargetPath = {quoted(python)};"
        "$s.Arguments = '-m abt app';"
        f"$s.WorkingDirectory = {quoted(Path.home())};"
        f"$s.Description = {quoted(COMMENT)};"
        + (f"$s.IconLocation = {quoted(icon)};" if icon else "")
        + "$s.Save()"
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0 or not target.exists():
        raise OSError(f"could not create the shortcut: {done.stderr.strip() or done.stdout.strip()}")


def exists(platform: str | None = None, home: Path | None = None) -> bool:
    return location(platform, home).exists()


def install(platform: str | None = None, home: Path | None = None) -> Path:
    """Add the launcher (replacing an older one). Returns where it went."""
    platform = platform or sys.platform
    target = location(platform, home)
    python = gui_python()
    if platform == "win32":
        windows_shortcut(target, python, _asset("logo-white.ico"))
    elif platform == "darwin":
        if target.exists():
            shutil.rmtree(target)
        mac_bundle(target, python, _asset("logo-white-256.png"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(desktop_entry(python, _asset("logo-white-256.png")), encoding="utf-8")
        target.chmod(0o755)
    return target


def remove(platform: str | None = None, home: Path | None = None) -> Path | None:
    target = location(platform, home)
    if not target.exists():
        return None
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return target


def managed_elsewhere() -> bool:
    """Installs whose own installer already put the app in the menu."""
    here = str(Path(__file__).resolve()).replace("\\", "/").lower()
    return (
        "/programs/aibrowsertoolkit/" in here  # the Windows installer
        or "/scoop/apps/" in here  # Scoop's manifest adds one
        or here.startswith("/opt/aibrowsertoolkit/")  # the Linux system packages
    )


def ensure(echo=print) -> None:
    """Add the launcher the first time the app is opened, if nothing else did."""
    from . import paths

    checkout = paths.in_source_checkout(Path(__file__).resolve().parents[2])
    if checkout or managed_elsewhere() or exists():
        return
    try:
        where = install()
    except OSError:
        return  # a convenience; never the reason the app does not open
    echo(f"[abt] added {NAME} to your apps: {where}")
