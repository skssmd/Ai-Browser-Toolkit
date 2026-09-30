"""`abt update`: move to the newest release in place, whichever way abt was installed.

Incremental: only the toolkit's own package is replaced -- a few hundred KB
from the release's wheel -- not the bundled Python, Chrome drivers or the
dependencies, which stay as they are. The same one command works for a pip
install and for the installer's bundle (which has no pip at all).

The wheel is checked against the release's checksums.txt before anything is
touched, and the swap is two renames, so an update that fails part way leaves
the old version in place. When the new release needs a dependency this install
does not have, only pip can add it: with pip that is what runs, without it the
update stops and says to reinstall.

Installs a package manager owns -- Homebrew, Scoop, the AUR, .deb, .rpm, .apk -- are left to it:
replacing its files behind its back leaves it believing an old version is
installed. A source checkout is updated with git.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import io
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import paths

REPO = "skssmd/Ai-Browser-Toolkit"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
PACKAGE = "abt"


class UpdateError(Exception):
    """Why an update did not happen. Nothing was changed when this is raised."""


@dataclass
class Release:
    version: str
    url: str  # the release page, for people
    wheel: str  # the wheel's download URL
    wheel_name: str
    checksums: str | None  # checksums.txt's download URL


def latest(client: httpx.Client | None = None) -> Release:
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        response = client.get(LATEST, headers={"Accept": "application/vnd.github+json"})
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UpdateError(f"could not reach GitHub to check for updates: {exc}") from exc
    if response.status_code != 200 or not isinstance(body, dict):
        raise UpdateError(f"GitHub answered HTTP {response.status_code} for the latest release")
    assets = {a["name"]: a["browser_download_url"] for a in body.get("assets") or []}
    wheel = next((n for n in assets if n.endswith(".whl")), None)
    if wheel is None:
        raise UpdateError(f"release {body.get('tag_name')} has no wheel to update from")
    return Release(
        version=str(body.get("tag_name") or "").lstrip("v"),
        url=body.get("html_url") or f"https://github.com/{REPO}/releases/latest",
        wheel=assets[wheel],
        wheel_name=wheel,
        checksums=assets.get("checksums.txt"),
    )


# --- versions ----------------------------------------------------------------------


def _parts(version: str) -> tuple:
    """1.10.2 > 1.9, with a pre-release (1.0rc1) before its release."""
    out = []
    for piece in re.split(r"[.+-]", version):
        match = re.match(r"(\d+)(.*)", piece)
        if match:
            out.append((int(match.group(1)), 0 if match.group(2) else 1, match.group(2)))
        else:
            out.append((-1, 0, piece))
    return tuple(out)


def newer(candidate: str, current: str) -> bool:
    return _parts(candidate) > _parts(current)


def _satisfies(installed: str, spec: str) -> bool:
    """Does `installed` meet a specifier like ">=1.50,<2"? Unknown forms say no."""
    try:
        from packaging.specifiers import SpecifierSet

        return SpecifierSet(spec).contains(installed, prereleases=True)
    except ImportError:
        pass
    for clause in filter(None, (c.strip() for c in spec.split(","))):
        match = re.match(r"(>=|<=|==|!=|>|<)\s*([\w.]+)$", clause)
        if not match:
            return False
        op, wanted = match.groups()
        a, b = _parts(installed), _parts(wanted)
        ok = {">=": a >= b, "<=": a <= b, "==": a == b, "!=": a != b, ">": a > b, "<": a < b}[op]
        if not ok:
            return False
    return True


def missing_requirements(requires: list[str]) -> list[str]:
    """The wheel's requirements this install does not meet. Extras are ignored."""
    missing = []
    for line in requires:
        requirement, _, marker = line.partition(";")
        if "extra" in marker:
            continue
        match = re.match(r"\s*([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*\(?([^)]*)\)?", requirement)
        if not match:
            continue
        name, spec = match.group(1), match.group(2).strip()
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(requirement.strip())
            continue
        if spec and not _satisfies(have, spec):
            missing.append(requirement.strip())
    return missing


# --- how this copy was installed ---------------------------------------------------------


def install_kind(package_dir: Path | None = None) -> tuple[str, str | None]:
    """(kind, what to run instead) -- kind is "inplace", or who owns the files."""
    here = Path(package_dir or Path(__file__).resolve().parent)
    text = str(here).replace("\\", "/")
    if paths.in_source_checkout(here.parents[1]) or (here.parents[1] / ".git").exists():
        return "checkout", "git pull"
    direct = ""
    if package_dir is None:
        try:
            direct = metadata.distribution(paths.DIST_NAME).read_text("direct_url.json") or ""
        except metadata.PackageNotFoundError:
            pass
    if '"editable": true' in direct:
        return "checkout", "git pull (this is an editable install)"
    if "/Cellar/" in text or "/homebrew/" in text.lower():
        return "brew", "brew upgrade aibrowsertoolkit"
    if "/scoop/apps/" in text.lower():
        return "scoop", "scoop update aibrowsertoolkit"
    if text.startswith("/opt/aibrowsertoolkit/"):  # the AUR, .deb, .rpm and .apk all put it here
        return "system package", ("your package manager: sudo apt upgrade, sudo dnf upgrade, "
                                  "sudo apk upgrade, or yay -Syu aibrowsertoolkit-bin")
    return "inplace", None


def has_pip() -> bool:
    try:
        import pip  # noqa: F401
    except ImportError:
        return False
    return True


# --- the update itself -------------------------------------------------------------


def verify(data: bytes, name: str, checksums: str) -> None:
    """Refuse a wheel that is not the one the release lists."""
    want = None
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            want = parts[0].lower()
    if want is None:
        raise UpdateError(f"checksums.txt does not list {name}")
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise UpdateError(f"{name} does not match its checksum; nothing was changed")


def wheel_requires(wheel: zipfile.ZipFile) -> list[str]:
    meta = next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
    text = wheel.read(meta).decode("utf-8")
    return [line[len("Requires-Dist:"):].strip() for line in text.splitlines()
            if line.startswith("Requires-Dist:")]


def swap_in(wheel: zipfile.ZipFile, site: Path, old_dist_info: Path | None) -> None:
    """Replace the package and its dist-info with the wheel's, by renaming.

    Staged beside the old copy (same disk, so the renames are instant), then
    moved into place; the old copy is removed last, and put back if the move
    fails. On Windows a file held open by a running process refuses the
    rename -- then the new files are copied over the old ones instead.
    """
    stage = Path(tempfile.mkdtemp(prefix=".abt-update-", dir=site))
    try:
        wheel.extractall(stage)
        new_pkg = stage / PACKAGE
        new_info = next(stage.glob("*.dist-info"))
        live_pkg = site / PACKAGE
        aside = site / f".abt-previous-{stage.name}"
        try:
            live_pkg.rename(aside)
            try:
                new_pkg.rename(live_pkg)
            except OSError:
                aside.rename(live_pkg)
                raise
            shutil.rmtree(aside, ignore_errors=True)
        except OSError:
            shutil.copytree(new_pkg, live_pkg, dirs_exist_ok=True)
            fresh = {p.relative_to(new_pkg) for p in new_pkg.rglob("*.py")}
            for stale in list(live_pkg.rglob("*.py")):
                if stale.relative_to(live_pkg) not in fresh:
                    stale.unlink(missing_ok=True)
        if old_dist_info is not None and old_dist_info.exists():
            shutil.rmtree(old_dist_info, ignore_errors=True)
        target = site / new_info.name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        new_info.rename(target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def installed_version() -> str:
    """The running package's own version: an editable install's metadata goes stale."""
    from . import __version__

    return __version__


def installed_files() -> tuple[Path, Path | None]:
    """(the site-packages directory abt is in, its dist-info directory)."""
    dist = metadata.distribution(paths.DIST_NAME)
    info = getattr(dist, "_path", None)
    return Path(dist.locate_file("")).resolve(), Path(info) if info else None


def update(check_only: bool = False, force: bool = False, echo=print,
           client: httpx.Client | None = None) -> dict:
    """Bring this install to the newest release. Returns what happened."""
    current = installed_version()
    release = latest(client)
    out = {"current": current, "latest": release.version, "release": release.url}
    if not newer(release.version, current) and not force:
        echo(f"abt {current} is the newest release.")
        return {**out, "updated": False}
    echo(f"abt {release.version} is out (you have {current}): {release.url}")
    kind, instead = install_kind()
    if kind != "inplace":
        echo(f"This copy is managed by {kind}; update it with: {instead}")
        return {**out, "updated": False, "managed_by": kind, "run": instead}
    if check_only:
        return {**out, "updated": False}

    if release.checksums is None:
        raise UpdateError("the release has no checksums.txt; nothing was changed")
    http = client or httpx.Client(timeout=120, follow_redirects=True)
    echo(f"Downloading {release.wheel_name}...")
    try:
        data = http.get(release.wheel).raise_for_status().content
        sums = http.get(release.checksums).raise_for_status().text
    except httpx.HTTPError as exc:
        raise UpdateError(f"download failed ({exc}); nothing was changed") from exc
    verify(data, release.wheel_name, sums)
    try:
        wheel = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UpdateError(f"{release.wheel_name} is not a valid wheel; nothing was changed") from exc

    site, old_info = installed_files()
    missing = missing_requirements(wheel_requires(wheel))
    if missing:
        if not has_pip():
            raise UpdateError(f"{release.version} needs {', '.join(missing)}, which this install does not "
                f"have and cannot add (it has no pip). Install it afresh from {release.url}.",
            )
        echo(f"{release.version} needs {', '.join(missing)}: installing with pip...")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / release.wheel_name
            path.write_bytes(data)
            done = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", str(path)])
            if done.returncode != 0:
                raise UpdateError(f"pip could not install {release.version} (exit {done.returncode})")
    else:
        try:
            swap_in(wheel, site, old_info)
        except PermissionError as exc:
            raise UpdateError(f"cannot write to {site} ({exc}). Run the update as the user who installed abt.",
            ) from exc
    echo(f"Updated to {release.version}. Restart the server (and the app) to use it: "
         "`abt shutdown`, then `abt up` or open the app.")
    return {**out, "updated": True}
