"""Build one self-contained bundle.

Runs on a laptop as well as in CI, on purpose: a six-channel pipeline whose
build step exists only inside a workflow is one that gets debugged at ten
minutes per push.

    python packaging/bundle.py --version 0.2.0 \
        --wheel dist/aibrowsertoolkit-0.2.0-py3-none-any.whl --dest dist/

There is deliberately no virtualenv in the output. `uv venv --relocatable`
rewrites script shebangs but leaves `pyvenv.cfg`'s `home =` absolute, pointing
at the interpreter that built it -- so the bundle would work on the build
machine and nowhere else. Packages go straight into the standalone
interpreter's own site-packages instead; those distributions are relocatable by
construction.

This directory is deliberately not a Python package. `packaging` is a real
installed distribution that pip and setuptools import, and an `__init__.py`
here would shadow it whenever the repo root is on sys.path -- which it is
under `python -m pytest`. The tests load this file by path.
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.13"

# Bundle target -> the python-build-standalone triple that provides it. The
# linux names must stay as they are: the AUR PKGBUILD resolves the unpacked
# directory with $CARCH, which is x86_64 or aarch64.
TARGETS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
    "windows-x86_64": "x86_64-pc-windows-msvc",
}

PAYLOAD = ("LICENSE", "README.md", "guidelines")

UNIX_SHIM = """#!/bin/sh
# Resolve through symlinks: Homebrew puts the tree in libexec and symlinks to
# this file, so $0 alone points somewhere with no python/ beside it.
here=$(dirname "$(readlink -f "$0")")
exec "$here/../python/bin/python3" -m abt "$@"
"""

WINDOWS_SHIM = '@"%~dp0python\\python.exe" -m abt %*\r\n'


def bundle_stem(version: str, target: str) -> str:
    return f"aibrowsertoolkit-{version}-{target}"


def shim_for(target: str) -> tuple[str, str]:
    if target.startswith("windows"):
        return "abt.cmd", WINDOWS_SHIM
    return "bin/abt", UNIX_SHIM


def host_target() -> str:
    """Which of TARGETS this machine builds.

    Bundles are built natively, one runner per target, because the smoke test
    is the whole point of the matrix -- a cross-built bundle is never executed
    on the platform it is for, and Playwright's driver is exactly the thing
    most likely to break there.
    """
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    system = platform.system()
    if system == "Windows":
        return "windows-x86_64"
    if system == "Darwin":
        return "macos-arm64" if arm else "macos-x86_64"
    return "linux-aarch64" if arm else "linux-x86_64"


def _fetch_python(target: str, into: Path) -> Path:
    """Place a standalone CPython at `into/python`.

    `uv python install` is what knows how to find these builds.
    python-build-standalone's asset names embed a build date
    (`cpython-3.13.1+20241206-x86_64-unknown-linux-gnu-install_only.tar.gz`),
    so a hand-built "latest/download/..." URL resolves to nothing -- do not
    reintroduce one.

    uv installs for the host platform only, which is why this refuses a target
    that is not the host rather than producing something silently wrong.
    """
    if target != host_target():
        raise SystemExit(
            f"cannot build {target} on {host_target()}; bundles are built "
            f"natively, one runner per target"
        )
    into.mkdir(parents=True, exist_ok=True)

    # Install into a scratch directory rather than straight into the bundle:
    # uv also writes .gitignore, .lock and .temp into --install-dir, and none
    # of those belong in a shipped artifact.
    scratch = into / ".pythons"
    subprocess.run(
        [
            "uv",
            "python",
            "install",
            "--install-dir",
            str(scratch),
            "--managed-python",
            PYTHON_VERSION,
        ],
        check=True,
    )

    # uv leaves two directories per install: the concrete
    # `cpython-3.13.15-windows-x86_64-none` and a minor-version alias
    # `cpython-3.13-windows-x86_64-none` pointing at it. Take the concrete one
    # -- the alias is a link, and moving a link ships a dangling pointer.
    concrete = re.compile(r"^cpython-\d+\.\d+\.\d+-")
    candidates = [
        d
        for d in sorted(scratch.iterdir())
        if d.is_dir() and not d.name.startswith(".") and concrete.match(d.name)
    ]
    if not candidates:
        raise SystemExit(
            f"uv installed no concrete interpreter under {scratch}; "
            f"found {[p.name for p in scratch.iterdir()]}"
        )

    target_dir = into / "python"
    shutil.move(str(candidates[0]), str(target_dir))
    shutil.rmtree(scratch, ignore_errors=True)

    # uv stamps its managed interpreters with an EXTERNALLY-MANAGED marker
    # saying "managed by uv, do not modify". Having moved this copy out of
    # uv's control and into our bundle, that is no longer true -- and leaving
    # it would block both our own install below and any user who later wanted
    # to pip into the bundle. Removing it is more honest than passing
    # --break-system-packages to work around a claim we know to be stale.
    for marker in target_dir.rglob("EXTERNALLY-MANAGED"):
        marker.unlink()

    return target_dir


def _interpreter(python_root: Path, target: str) -> Path:
    if target.startswith("windows"):
        return python_root / "python.exe"
    return python_root / "bin" / "python3"


def build(version: str, target: str, wheel: Path, dest: Path) -> Path:
    stem = bundle_stem(version, target)
    staging = dest / stem
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    python_root = _fetch_python(target, staging)
    interpreter = _interpreter(python_root, target)

    subprocess.run(
        ["uv", "pip", "install", "--python", str(interpreter), str(wheel)],
        check=True,
    )

    rel, body = shim_for(target)
    shim = staging / rel
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(body, encoding="utf-8", newline="")
    if not target.startswith("windows"):
        shim.chmod(0o755)

    root = Path(__file__).resolve().parent.parent
    for item in PAYLOAD:
        src = root / item
        if src.is_dir():
            shutil.copytree(src, staging / item)
        else:
            shutil.copy2(src, staging / item)

    return _archive(staging, target)


def _archive(staging: Path, target: str) -> Path:
    """zip for Windows because Scoop wants one; tar.gz elsewhere because it
    preserves the executable bit on the shim."""
    if target.startswith("windows"):
        out = staging.parent / (staging.name + ".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                archive.write(path, path.relative_to(staging.parent))
        return out
    out = staging.parent / (staging.name + ".tar.gz")
    with tarfile.open(out, "w:gz") as archive:
        archive.add(staging, arcname=staging.name)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one self-contained bundle.")
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--target",
        default=host_target(),
        choices=sorted(TARGETS),
        help="Defaults to this machine's target; a different one is refused.",
    )
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args(argv)
    out = build(args.version, args.target, args.wheel, args.dest)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
