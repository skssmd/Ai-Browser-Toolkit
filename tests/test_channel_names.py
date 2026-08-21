"""Names that must agree across files, pinned so a rename cannot half-land.

Every channel hardcodes a filename or an identifier produced somewhere else,
and nothing checks the two ends against each other. A rename that updates one
side is invisible until a release runs, and by then the manifest is public.

The distribution name is deliberately NOT the asset name. PyPI rejected
`aibrowsertoolkit` as too similar to an existing project -- it strips `-`, `_`
and `.` before comparing -- so the distribution is `ai-browser-toolkit` while
the bundles, installer and distro packages keep the old spelling. That is a
real, permanent divergence, and it is exactly the sort of thing that rots.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
VERSION = "9.9.9"  # a stand-in, so these never depend on the current version


def _load_bundle():
    spec = importlib.util.spec_from_file_location(
        "abt_bundle_builder", ROOT / "packaging" / "bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle = _load_bundle()
pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
release = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
)


def read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


# -- the distribution name ------------------------------------------------


def test_paths_knows_the_distribution_name():
    """paths.py identifies this checkout by matching pyproject's name. If they
    drift, an installed copy thinks it is the checkout and resolves its
    profile against the working directory -- the exact bug paths.py exists to
    prevent."""
    from abt import paths

    assert paths.DIST_NAME == pyproject["project"]["name"]


def test_the_distribution_name_is_the_one_pypi_accepted():
    assert pyproject["project"]["name"] == "ai-browser-toolkit"


def test_the_project_page_will_not_be_blank():
    """Without a readme PyPI renders a stub carrying only the summary."""
    assert pyproject["project"]["readme"] == "README.md"


# -- asset names ----------------------------------------------------------


def test_asset_names_keep_the_old_spelling():
    """Renaming the assets would break the winget manifest, which pins an
    installer URL by name, and every already-published Scoop, Homebrew and
    AUR manifest along with it."""
    assert bundle.bundle_stem(VERSION, "linux-x86_64") == (
        f"aibrowsertoolkit-{VERSION}-linux-x86_64"
    )


def test_the_workflow_builds_the_paths_bundle_py_produces():
    """The smoke test and the upload both name the bundle directory by hand."""
    steps = release["jobs"]["bundle"]["steps"]
    text = "".join(str(s.get("run", "")) + str(s.get("with", "")) for s in steps)
    expected = "aibrowsertoolkit-${{ needs.wheel.outputs.version }}-"
    assert expected in text


def test_the_installer_filename_matches_what_winget_looks_for():
    """abt.iss decides the installer's name; the winget job finds it with a
    regex. A rename on either side means winget silently matches nothing."""
    iss = read("packaging", "windows", "abt.iss")
    base = re.search(r"OutputBaseFilename=(\S+)", iss).group(1)
    produced = base.replace("{#AppVersion}", VERSION)
    assert produced == f"aibrowsertoolkit-{VERSION}-windows-x86_64-setup"

    winget = next(
        s for s in release["jobs"]["winget"]["steps"] if "winget-releaser" in str(s)
    )
    pattern = winget["with"]["installers-regex"]
    assert re.search(pattern, produced + ".exe")


# -- per-channel manifests ------------------------------------------------


def test_scoop_extracts_the_directory_the_zip_actually_contains():
    """extract_dir must equal the archive's single top-level directory, or
    scoop installs an empty shim."""
    manifest = read("packaging", "scoop", "manifest.json.template")
    assert '"extract_dir": "aibrowsertoolkit-@VERSION@-windows-x86_64"' in manifest
    assert bundle.bundle_stem("@VERSION@", "windows-x86_64") == (
        "aibrowsertoolkit-@VERSION@-windows-x86_64"
    )


def test_homebrew_points_at_the_arm64_tarball_that_is_built():
    formula = read("packaging", "homebrew", "formula.rb.template")
    assert f"{bundle.bundle_stem('@VERSION@', 'macos-arm64')}.tar.gz" in formula
    # The Intel bundle is not built, so the formula must refuse up front
    # rather than 404 on a download. Checked against `url` lines only --
    # the comment above them names macos-x86_64 to explain why it is absent.
    assert "depends_on arch: :arm64" in formula
    urls = [line for line in formula.splitlines() if line.strip().startswith("url ")]
    assert urls, "the formula has no url line at all"
    assert not any("macos-x86_64" in line for line in urls), urls


def test_aur_sources_match_the_linux_bundles_and_carch():
    """PKGBUILD resolves the unpacked directory with $CARCH, which is x86_64
    or aarch64 -- so the target names have to end in exactly those."""
    pkgbuild = read("packaging", "aur", "PKGBUILD.template")
    for target in ("linux-x86_64", "linux-aarch64"):
        assert f"aibrowsertoolkit-${{pkgver}}-{target}.tar.gz" in pkgbuild
    assert 'aibrowsertoolkit-${pkgver}-linux-${CARCH}' in pkgbuild


def test_the_winget_identifier_is_the_one_that_was_submitted():
    """winget-releaser only updates an identifier that already exists
    upstream. If this changes, every future release silently updates nothing
    -- or fails with 'does not exist in the winget-pkgs repository'."""
    winget = next(
        s for s in release["jobs"]["winget"]["steps"] if "winget-releaser" in str(s)
    )
    assert winget["with"]["identifier"] == "skssmd.AIBrowserToolkit"


def test_the_winget_fork_is_the_org_not_the_redirect():
    """skssmd/winget-pkgs redirects to The-Graft-Project/winget-pkgs after the
    fork was transferred, and the action does not follow redirects."""
    winget = next(
        s for s in release["jobs"]["winget"]["steps"] if "winget-releaser" in str(s)
    )
    assert winget["with"]["fork-user"] == "The-Graft-Project"
