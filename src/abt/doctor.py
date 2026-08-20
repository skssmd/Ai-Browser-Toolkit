"""What this toolkit needs that it cannot carry: a browser.

The bundle ships its own CPython and every Python package, and Playwright's
Node driver rides inside the wheel. So there is exactly one runtime
dependency, and this is where it is found and -- sometimes -- installed.

Detection never launches anything: starting Chrome to find out whether Chrome
exists costs two minutes on a persistent profile.

Pure, with `kind`, `home`, `exists` and `which` injectable, so all three
platforms are checked from whichever one the tests run on. Same shape as
`autostart.plan()`, and for the same reason.

**The elevation rule.** `--install-browser` runs a package manager only where
it needs nothing of us: winget on Windows raises its own UAC prompt, and a
Homebrew cask on macOS needs no `sudo` at all. Every route to Chrome on Linux
needs root, so there we print the command and run nothing.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import paths

CHROME_URL = "https://www.google.com/chrome/"

# Order is preference order: chrome first, because it is `abt serve`'s default
# and the channel pwdriver reaches for.
_WINDOWS = (
    ("chrome", r"Google\Chrome\Application\chrome.exe"),
    ("edge", r"Microsoft\Edge\Application\msedge.exe"),
)
_MACOS = (
    ("chrome", "Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
)
# chromium is deliberately absent. It is the one browser actually in Debian's,
# Fedora's and Arch's repositories, which makes it the tempting answer -- but
# SUPPORTED_BROWSERS is ("chrome", "edge") and pwdriver knows only the chrome
# and msedge channels. Accepting it would pass this check and fail at launch.
_LINUX = (
    ("chrome", ("google-chrome", "google-chrome-stable")),
    ("edge", ("microsoft-edge", "microsoft-edge-stable")),
)


@dataclass(frozen=True)
class Browser:
    name: str
    path: Path


@dataclass(frozen=True)
class InstallPlan:
    argv: list[str] | None
    run: bool
    message: str


def _defaults(
    kind: str | None,
    home: Path | None,
    exists: Callable[[Path], bool] | None,
    which: Callable[[str], str | None] | None,
) -> tuple[str, Path, Callable, Callable]:
    return (
        kind or paths.current_kind(),
        Path(home) if home is not None else Path.home(),
        exists or (lambda p: Path(p).exists()),
        which or shutil.which,
    )


def find_browsers(
    kind: str | None = None,
    home: Path | None = None,
    exists: Callable[[Path], bool] | None = None,
    which: Callable[[str], str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Browser]:
    kind, home, exists, which = _defaults(kind, home, exists, which)
    env = os.environ if env is None else env
    found: list[Browser] = []

    if kind == "windows":
        roots = [
            env.get("ProgramFiles", r"C:\Program Files"),
            env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            env.get("LOCALAPPDATA", str(home / "AppData" / "Local")),
        ]
        for name, tail in _WINDOWS:
            for root in roots:
                candidate = Path(root) / tail
                if exists(candidate):
                    found.append(Browser(name, candidate))
                    break
    elif kind == "macos":
        roots = [Path("/Applications"), home / "Applications"]
        for name, tail in _MACOS:
            for root in roots:
                candidate = root / tail
                if exists(candidate):
                    found.append(Browser(name, candidate))
                    break
    else:
        for name, binaries in _LINUX:
            for binary in binaries:
                hit = which(binary)
                if hit:
                    found.append(Browser(name, Path(hit)))
                    break

    return found


def default_browser(
    kind: str | None = None,
    home: Path | None = None,
    exists: Callable[[Path], bool] | None = None,
    which: Callable[[str], str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    browsers = find_browsers(kind, home, exists, which, env)
    return browsers[0].name if browsers else None


def install_plan(
    kind: str, which: Callable[[str], str | None] | None = None
) -> InstallPlan:
    which = which or shutil.which

    if kind == "windows":
        if which("winget"):
            return InstallPlan(
                argv=["winget", "install", "-e", "--id", "Google.Chrome"],
                run=True,
                message="Installing Google Chrome with winget.",
            )
        return InstallPlan(
            argv=None,
            run=False,
            message=f"winget is not available. Install Chrome from {CHROME_URL}",
        )

    if kind == "macos":
        if which("brew"):
            return InstallPlan(
                argv=["brew", "install", "--cask", "google-chrome"],
                run=True,
                message="Installing Google Chrome with Homebrew.",
            )
        return InstallPlan(
            argv=None,
            run=False,
            message=f"Homebrew is not available. Install Chrome from {CHROME_URL}",
        )

    # Linux: print, never run. Every one of these needs root, and this design
    # does not invoke sudo on anyone's behalf.
    if which("apt") or which("apt-get"):
        how = (
            "  wget https://dl.google.com/linux/direct/"
            "google-chrome-stable_current_amd64.deb\n"
            "  sudo dpkg -i google-chrome-stable_current_amd64.deb"
        )
    elif which("dnf"):
        how = (
            "  sudo dnf install fedora-workstation-repositories\n"
            "  sudo dnf config-manager --set-enabled google-chrome\n"
            "  sudo dnf install google-chrome-stable"
        )
    elif which("pacman"):
        how = "  yay -S google-chrome    # Chrome is AUR-only on Arch"
    else:
        how = f"  Install Chrome from {CHROME_URL}"
    return InstallPlan(
        argv=None,
        run=False,
        message="Installing Chrome on Linux needs root, so run this yourself:\n" + how,
    )


def report(
    kind: str | None = None,
    home: Path | None = None,
    exists: Callable[[Path], bool] | None = None,
    which: Callable[[str], str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    kind, home, exists, which = _defaults(kind, home, exists, which)
    browsers = find_browsers(kind, home, exists, which, env)
    profile = paths.default_profile()
    return {
        "platform": kind,
        "browsers": [{"name": b.name, "path": str(b.path)} for b in browsers],
        "default_browser": browsers[0].name if browsers else None,
        "profile": str(profile),
        "profile_writable": _writable(profile),
    }


def _writable(profile: Path) -> bool:
    """Whether the profile could be created. Walks up to the nearest directory
    that exists -- a fresh install has none of this yet, and reporting "not
    writable" for a path that simply is not there would be a lie."""
    probe = profile
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return os.access(probe, os.W_OK)
