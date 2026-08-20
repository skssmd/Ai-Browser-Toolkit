"""The one runtime dependency, found without launching anything.

Detection is pure so all three platforms are checkable from whichever one the
tests run on -- the same reason `autostart.plan()` takes a `kind`.

The rule worth protecting here is the elevation line: we run a package manager
only where it needs nothing of us. Every route to Chrome on Linux needs root,
so Linux prints and runs nothing, and a test says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abt import doctor


WINDOWS_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
WINDOWS_EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def fake_fs(*present: Path):
    found = {str(p) for p in present}
    return lambda p: str(p) in found


def fake_which(*available: str):
    have = set(available)
    return lambda name: f"/usr/bin/{name}" if name in have else None


def test_nothing_installed_means_no_default(tmp_path):
    assert doctor.default_browser(
        kind="linux", home=tmp_path, exists=fake_fs(), which=fake_which()
    ) is None


def test_chrome_is_preferred_over_edge(tmp_path):
    names = [
        b.name
        for b in doctor.find_browsers(
            kind="linux",
            home=tmp_path,
            exists=fake_fs(),
            which=fake_which("google-chrome", "microsoft-edge-stable"),
        )
    ]
    assert names == ["chrome", "edge"]


def test_edge_alone_is_a_valid_default(tmp_path):
    """Edge ships with Windows. Defaulting to chrome regardless is what makes
    an installer write a logon task that fails at every boot."""
    got = doctor.default_browser(
        kind="windows", home=tmp_path, exists=fake_fs(WINDOWS_EDGE), which=fake_which()
    )
    assert got == "edge"


def test_linux_finds_either_edge_binary_name(tmp_path):
    for binary in ("microsoft-edge", "microsoft-edge-stable"):
        got = doctor.default_browser(
            kind="linux", home=tmp_path, exists=fake_fs(), which=fake_which(binary)
        )
        assert got == "edge", binary


def test_chromium_is_not_accepted_as_chrome(tmp_path):
    """chromium IS in Debian's, Fedora's and Arch's repos, which makes it the
    tempting answer. But SUPPORTED_BROWSERS is (chrome, edge) and pwdriver
    knows only the chrome and msedge channels -- accepting it would pass the
    check and then fail at launch."""
    got = doctor.default_browser(
        kind="linux", home=tmp_path, exists=fake_fs(), which=fake_which("chromium")
    )
    assert got is None


def test_windows_installs_through_winget():
    plan = doctor.install_plan("windows", which=fake_which("winget"))
    assert plan.run is True
    assert plan.argv[:2] == ["winget", "install"]
    assert "Google.Chrome" in plan.argv


def test_windows_without_winget_falls_back_to_the_download_page():
    plan = doctor.install_plan("windows", which=fake_which())
    assert plan.run is False
    assert "google.com/chrome" in plan.message


def test_macos_installs_through_a_brew_cask():
    plan = doctor.install_plan("macos", which=fake_which("brew"))
    assert plan.run is True
    assert plan.argv == ["brew", "install", "--cask", "google-chrome"]


@pytest.mark.parametrize("manager", ["apt", "dnf", "pacman"])
def test_linux_never_runs_anything(manager):
    """Every route to Chrome on Linux needs root, and this design does not
    invoke sudo on anyone's behalf."""
    plan = doctor.install_plan("linux", which=fake_which(manager))
    assert plan.run is False
    assert plan.argv is None
    assert plan.message.strip() != ""


def test_linux_names_the_right_manager():
    assert "dpkg" in doctor.install_plan("linux", which=fake_which("apt")).message
    assert "dnf" in doctor.install_plan("linux", which=fake_which("dnf")).message


def test_report_is_json_serialisable(tmp_path):
    import json

    got = doctor.report(
        kind="linux", home=tmp_path, exists=fake_fs(), which=fake_which("google-chrome")
    )
    json.dumps(got)
    assert got["default_browser"] == "chrome"
    assert got["browsers"][0]["name"] == "chrome"


def test_windows_candidates_are_built_with_windows_separators(tmp_path):
    r"""Regression: `Path(root) / tail` uses the *host's* flavour, so on Linux
    a backslash tail was joined with a forward slash --
    "C:\Program Files (x86)/Microsoft\Edge\..." -- matching nothing.

    This assertion is trivially true on Windows and only bites on Linux and
    macOS. That is the point: the bug was invisible on the developer's machine
    and failed five of six CI cells.
    """
    seen: list[str] = []

    def record(candidate):
        seen.append(str(candidate))
        return False

    doctor.find_browsers(
        kind="windows", home=tmp_path, exists=record, which=fake_which(), env={}
    )

    assert seen, "no candidates were probed at all"
    assert all("/" not in s for s in seen), seen
    assert any(s.endswith(r"Microsoft\Edge\Application\msedge.exe") for s in seen), seen
