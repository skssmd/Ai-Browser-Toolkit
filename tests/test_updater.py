"""`abt update`: the newest release's package, swapped in place. No network here."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from abt import updater

WHEEL = "ai_browser_toolkit-9.9.9-py3-none-any.whl"


def make_wheel(files: dict[str, str], requires=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
        meta = "Metadata-Version: 2.1\nName: ai-browser-toolkit\nVersion: 9.9.9\n"
        meta += "".join(f"Requires-Dist: {r}\n" for r in requires)
        z.writestr("ai_browser_toolkit-9.9.9.dist-info/METADATA", meta)
    return buf.getvalue()


@pytest.mark.parametrize("a,b,expected", [
    ("0.7.10", "0.7.9", True), ("0.8.0", "0.7.4", True), ("0.7.4", "0.7.4", False),
    ("0.7.3", "0.7.4", False), ("0.8.0", "0.8.0rc1", True), ("0.8.0rc1", "0.8.0", False),
])
def test_versions_compare_as_numbers(a, b, expected):
    assert updater.newer(a, b) is expected


def test_only_unmet_requirements_are_missing():
    missing = updater.missing_requirements([
        "httpx>=0.1", "httpx>=999", "no-such-package-abt>=1",
        'pywebview>=5.0; extra == "app"',
    ])
    assert missing == ["httpx>=999", "no-such-package-abt>=1"]


def test_a_wheel_that_is_not_the_released_one_is_refused():
    data = b"wheel bytes"
    good = f"{hashlib.sha256(data).hexdigest()}  {WHEEL}\n"
    updater.verify(data, WHEEL, good)
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.verify(b"tampered", WHEEL, good)
    with pytest.raises(updater.UpdateError, match="does not list"):
        updater.verify(data, WHEEL, "abc  other.whl\n")


def site_with_old_copy(tmp_path: Path) -> Path:
    site = tmp_path / "site-packages"
    (site / "abt").mkdir(parents=True)
    (site / "abt" / "__init__.py").write_text("old = True\n")
    (site / "abt" / "gone.py").write_text("# removed in the new release\n")
    (site / "ai_browser_toolkit-0.0.1.dist-info").mkdir()
    (site / "ai_browser_toolkit-0.0.1.dist-info" / "METADATA").write_text("Version: 0.0.1\n")
    (site / "other_package").mkdir()
    return site


def test_the_package_is_swapped_and_nothing_else_is_touched(tmp_path):
    site = site_with_old_copy(tmp_path)
    wheel = zipfile.ZipFile(io.BytesIO(make_wheel({"abt/__init__.py": "new = True\n", "abt/added.py": ""})))
    updater.swap_in(wheel, site, site / "ai_browser_toolkit-0.0.1.dist-info")
    assert (site / "abt" / "__init__.py").read_text() == "new = True\n"
    assert (site / "abt" / "added.py").exists() and not (site / "abt" / "gone.py").exists()
    assert (site / "ai_browser_toolkit-9.9.9.dist-info" / "METADATA").exists()
    assert not (site / "ai_browser_toolkit-0.0.1.dist-info").exists()
    assert (site / "other_package").exists()
    assert sorted(p.name for p in site.iterdir()) == [
        "abt", "ai_browser_toolkit-9.9.9.dist-info", "other_package"]  # no staging left behind


def serve_release(data: bytes, checksums: str | None = "match") -> httpx.Client:
    if checksums == "match":
        checksums = f"{hashlib.sha256(data).hexdigest()}  {WHEEL}\n"
    assets = [{"name": WHEEL, "browser_download_url": "https://dl.test/w.whl"}]
    if checksums is not None:
        assets.append({"name": "checksums.txt", "browser_download_url": "https://dl.test/sums"})

    def answer(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"tag_name": "v9.9.9", "html_url": "https://rel.test",
                                             "assets": assets})
        if request.url.path == "/w.whl":
            return httpx.Response(200, content=data)
        return httpx.Response(200, text=checksums)

    return httpx.Client(transport=httpx.MockTransport(answer))


@pytest.fixture
def installed(tmp_path, monkeypatch):
    site = site_with_old_copy(tmp_path)
    monkeypatch.setattr(updater, "installed_version", lambda: "0.0.1")
    monkeypatch.setattr(updater, "installed_files",
                        lambda: (site, site / "ai_browser_toolkit-0.0.1.dist-info"))
    # Never the real pip, whatever a test's wheel asks for.
    monkeypatch.setattr(updater, "has_pip", lambda: False)
    monkeypatch.setattr(updater, "install_kind", lambda: ("inplace", None))
    return site


def test_update_replaces_the_package_from_the_release(installed):
    data = make_wheel({"abt/__init__.py": "new = True\n"}, requires=["httpx>=0.1"])
    out = updater.update(echo=lambda *_: None, client=serve_release(data))
    assert out["updated"] is True and out["latest"] == "9.9.9"
    assert (installed / "abt" / "__init__.py").read_text() == "new = True\n"


def test_check_only_changes_nothing(installed):
    data = make_wheel({"abt/__init__.py": "new = True\n"})
    out = updater.update(check_only=True, echo=lambda *_: None, client=serve_release(data))
    assert out["updated"] is False and out["latest"] == "9.9.9"
    assert (installed / "abt" / "__init__.py").read_text() == "old = True\n"


def test_a_new_dependency_without_pip_stops_before_touching_anything(installed, monkeypatch):
    monkeypatch.setattr(updater, "has_pip", lambda: False)
    data = make_wheel({"abt/__init__.py": "new = True\n"}, requires=["no-such-package-abt>=1"])
    with pytest.raises(updater.UpdateError, match="Install it afresh"):
        updater.update(echo=lambda *_: None, client=serve_release(data))
    assert (installed / "abt" / "__init__.py").read_text() == "old = True\n"


def test_a_release_without_checksums_is_not_installed(installed):
    data = make_wheel({"abt/__init__.py": "new = True\n"})
    with pytest.raises(updater.UpdateError, match="checksums"):
        updater.update(echo=lambda *_: None, client=serve_release(data, checksums=None))
    assert (installed / "abt" / "__init__.py").read_text() == "old = True\n"


def test_a_package_manager_install_is_pointed_at_its_manager(installed, monkeypatch):
    monkeypatch.setattr(updater, "install_kind", lambda: ("scoop", "scoop update aibrowsertoolkit"))
    data = make_wheel({"abt/__init__.py": "new = True\n"})
    out = updater.update(echo=lambda *_: None, client=serve_release(data))
    assert out["updated"] is False and out["run"] == "scoop update aibrowsertoolkit"
    assert (installed / "abt" / "__init__.py").read_text() == "old = True\n"


@pytest.mark.parametrize("where,kind", [
    ("C:/Users/x/scoop/apps/aibrowsertoolkit/current/python/Lib/site-packages/abt", "scoop"),
    ("/opt/homebrew/Cellar/aibrowsertoolkit/0.7.4/libexec/python/lib/python3.12/site-packages/abt", "brew"),
    ("/opt/aibrowsertoolkit/python/lib/python3.12/site-packages/abt", "system package"),
    ("C:/Users/x/AppData/Local/Programs/AIBrowserToolkit/python/Lib/site-packages/abt", "inplace"),
    ("/home/x/.venv/lib/python3.12/site-packages/abt", "inplace"),
])
def test_who_owns_the_files_is_read_from_where_they_are(where, kind):
    assert updater.install_kind(Path(where))[0] == kind


def test_this_checkout_is_updated_with_git():
    assert updater.install_kind(Path(updater.__file__).resolve().parent)[0] == "checkout"


def test_the_latest_release_names_its_wheel():
    data = make_wheel({})
    release = updater.latest(serve_release(data))
    assert release.version == "9.9.9" and release.wheel_name == WHEEL
    assert release.checksums == "https://dl.test/sums"
    assert json.dumps(release.__dict__)  # plain data
