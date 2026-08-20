"""The bundle's shape, checked without downloading a 30MB interpreter.

What is worth asserting here is the part that silently breaks: the launcher
must reach the bundled interpreter by a path relative to itself, because the
bundle is built in one directory and installed in another.

`packaging/bundle.py` is loaded by file path rather than imported as
`packaging.bundle`. `packaging` is a real installed distribution that pip and
setuptools import, and `python -m pytest` puts the repo root on sys.path -- a
top-level `packaging` package here would shadow it for the whole session.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parent.parent / "packaging" / "bundle.py"
    spec = importlib.util.spec_from_file_location("abt_bundle_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle = _load()


def test_five_targets_exactly():
    assert set(bundle.TARGETS) == {
        "linux-x86_64",
        "linux-aarch64",
        "macos-arm64",
        "macos-x86_64",
        "windows-x86_64",
    }


def test_stem_carries_version_and_target():
    assert bundle.bundle_stem("0.2.0", "linux-x86_64") == "aibrowsertoolkit-0.2.0-linux-x86_64"


def test_host_target_is_one_we_ship():
    """Also the guard against a typo in TARGETS: a host that maps to a name
    not in the table would fail only on a release runner."""
    assert bundle.host_target() in bundle.TARGETS


def test_target_names_end_in_the_arch_the_aur_will_ask_for():
    """PKGBUILD resolves the unpacked directory using $CARCH, which is x86_64
    or aarch64. The target names must match or package() looks in the wrong
    place."""
    assert bundle.TARGETS["linux-x86_64"].startswith("x86_64")
    assert bundle.TARGETS["linux-aarch64"].startswith("aarch64")


@pytest.mark.parametrize("target", sorted(bundle.TARGETS))
def test_the_shim_never_hardcodes_a_build_path(target):
    _, body = bundle.shim_for(target)
    assert "/home/runner" not in body
    assert "C:\\Users" not in body


@pytest.mark.parametrize("target", sorted(bundle.TARGETS))
def test_the_shim_runs_the_module_not_a_console_script(target):
    """Generated console scripts carry an absolute shebang. The shim exists to
    avoid them."""
    _, body = bundle.shim_for(target)
    assert "-m abt" in body


def test_windows_shim_is_a_cmd_at_the_root():
    path, body = bundle.shim_for("windows-x86_64")
    assert path == "abt.cmd"
    assert "%~dp0" in body


def test_unix_shim_lives_in_bin_and_dereferences_symlinks():
    """Homebrew installs the tree in libexec and symlinks bin/abt to it. A shim
    using $0 without readlink resolves against the symlink and misses python."""
    path, body = bundle.shim_for("linux-x86_64")
    assert path == "bin/abt"
    assert "readlink" in body


def test_a_foreign_target_is_refused_rather_than_built_wrong(tmp_path):
    """uv installs an interpreter for the host only. Cross-building would
    produce a bundle that is silently wrong rather than one that fails."""
    foreign = next(t for t in bundle.TARGETS if t != bundle.host_target())
    with pytest.raises(SystemExit):
        bundle._fetch_python(foreign, tmp_path)


def test_abt_reports_a_version():
    """Every channel's smoke test is `abt --version`: the Inno verification,
    smoke.sh, the Homebrew formula's test block and docs/packaging.md. It has
    to answer with no server running and no browser installed."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "abt", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
