"""Each session's uploads and downloads folders, and the rule that guards them.

A page's file input takes only files the person put in the session's uploads
folder. The AI sees names and paths, never contents, and no spelling of a path
-- `..`, an absolute path elsewhere, a home-relative one -- reaches outside.
No browser here: the checks run before a page is touched.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from abt.browser import BrowserSession
from abt.errors import OpError
from abt.ops import dispatch
from abt.profiles import ProfileRegistry
from abt.schema import parse_command
from abt.screencast import upload_paths
from abt.server import create_app
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def registry(tmp_path):
    return SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a),
        operator_token="op",
        files_root=tmp_path / "files",
    )


@pytest.fixture
def work(registry, tmp_path):
    registry.create("work")
    browser = registry.get("work").browser
    browser.uploads_dir.mkdir(parents=True)
    (browser.uploads_dir / "cv.pdf").write_bytes(b"%PDF")
    secret = tmp_path / "home" / ".ssh"
    secret.mkdir(parents=True)
    (secret / "id_rsa").write_text("PRIVATE", encoding="utf-8")
    return browser, secret / "id_rsa"


def test_each_session_has_its_own_folders(registry, tmp_path):
    registry.create("work")
    browser = registry.get("work").browser
    assert browser.uploads_dir == tmp_path / "files" / "work" / "uploads"
    assert browser.downloads_dir == tmp_path / "files" / "work" / "downloads"


def test_a_file_in_the_uploads_folder_is_accepted(work):
    browser, _ = work
    assert browser.check_upload(str(browser.uploads_dir / "cv.pdf")).endswith("cv.pdf")
    assert browser.check_upload("cv.pdf").endswith("cv.pdf")  # relative to the folder


@pytest.mark.parametrize("spelling", ["absolute", "dotdot", "missing"])
def test_nothing_outside_the_uploads_folder_gets_through(work, spelling):
    browser, secret = work
    value = {
        "absolute": str(secret),
        "dotdot": str(browser.uploads_dir / ".." / ".." / ".." / "home" / ".ssh" / "id_rsa"),
        "missing": str(browser.uploads_dir / "nope.pdf"),
    }[spelling]
    with pytest.raises(OpError) as exc:
        browser.check_upload(value)
    assert exc.value.type == "file_blocked"


def test_one_bad_file_among_several_refuses_them_all(work):
    browser, secret = work
    with pytest.raises(OpError):
        browser.check_upload(f"{browser.uploads_dir / 'cv.pdf'}\n{secret}")


def test_default_keeps_its_old_freedom_unless_the_chat_is_driving(registry, tmp_path):
    browser = registry.get(None).browser
    outside = tmp_path / "anything.txt"
    outside.write_text("x", encoding="utf-8")
    assert browser.check_upload(str(outside)) == str(outside)
    with pytest.raises(OpError):
        browser.check_upload(str(outside), strict=True)


def test_the_setting_turns_it_on_or_off(registry, tmp_path):
    registry.create("loose", settings={"uploads_only": False})
    outside = tmp_path / "anything.txt"
    outside.write_text("x", encoding="utf-8")
    assert registry.get("loose").browser.check_upload(str(outside)) == str(outside)


def test_the_files_op_lists_names_and_paths_not_contents(registry, work):
    browser, _ = work
    out = dispatch(browser, parse_command({"op": "files"}))
    [row] = out["uploads"]["files"]
    assert row["name"] == "cv.pdf" and row["size"] == 4 and "content" not in row
    assert out["downloads"]["files"] == []


def test_an_upload_lands_in_the_folder_whatever_its_name_says(registry, tmp_path):
    registry.create("work")
    with TestClient(create_app(registry=registry)) as client:
        body = {"name": "../../../evil.txt", "data": base64.b64encode(b"hi").decode()}
        out = client.post("/app/upload", json=body, headers={"X-ABT-Session": "work"}).json()["result"]
    assert out["name"] == "evil.txt"
    assert (tmp_path / "files" / "work" / "uploads" / "evil.txt").read_bytes() == b"hi"
    assert not (tmp_path / "evil.txt").exists()


def test_the_page_can_only_be_handed_uploaded_files(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"x")
    assert upload_paths({"paths": [str(root / "a.pdf")]}, root) == [str((root / "a.pdf").resolve())]
    assert upload_paths({"paths": [str(tmp_path / "other.pdf")]}, root) is None
    assert upload_paths({"paths": [str(root / "a.pdf")]}, None) is None
