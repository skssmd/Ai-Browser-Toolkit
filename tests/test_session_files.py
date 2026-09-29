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


def test_folders_belong_to_the_profile_and_its_sessions_share_them(registry, tmp_path):
    registry.profiles.create("team")
    registry.create("work")                  # on the default profile
    registry.create("chat-a", profile="team")
    registry.create("chat-b", profile="team")
    work = registry.get("work").browser
    assert work.uploads_dir == tmp_path / "files" / "default" / "uploads"
    assert work.downloads_dir == tmp_path / "files" / "default" / "downloads"
    a, b = registry.get("chat-a").browser, registry.get("chat-b").browser
    assert a.uploads_dir == b.uploads_dir == tmp_path / "files" / "team" / "uploads"
    assert a.downloads_dir == b.downloads_dir != work.downloads_dir


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
    assert (tmp_path / "files" / "default" / "uploads" / "evil.txt").read_bytes() == b"hi"
    assert not (tmp_path / "evil.txt").exists()


def test_the_page_can_only_be_handed_uploaded_files(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"x")
    assert upload_paths({"paths": [str(root / "a.pdf")]}, root) == [str((root / "a.pdf").resolve())]
    assert upload_paths({"paths": [str(tmp_path / "other.pdf")]}, root) is None
    assert upload_paths({"paths": [str(root / "a.pdf")]}, None) is None


# --- save_file: documents the AI writes, into the chat's downloads folder ---------


def test_a_document_is_saved_into_the_profiles_downloads(registry):
    registry.create("work")
    browser = registry.get("work").browser
    out = browser.save_file("report.md", "# Findings\n\nAll good.")
    assert out["saved"] == "report.md"
    saved = browser.downloads_dir / "report.md"
    assert saved.read_text(encoding="utf-8") == "# Findings\n\nAll good."
    assert out["path"] == str(saved.resolve())
    # Every session on the profile finds it; another profile does not.
    registry.create("other")
    assert (registry.get("other").browser.downloads_dir / "report.md").exists()
    registry.profiles.create("team")
    registry.create("elsewhere", profile="team")
    assert not (registry.get("elsewhere").browser.downloads_dir / "report.md").exists()


def test_an_existing_file_is_kept_unless_asked(registry):
    registry.create("work")
    browser = registry.get("work").browser
    browser.save_file("notes.md", "one")
    assert browser.save_file("notes.md", "two")["saved"] == "notes (2).md"
    assert browser.save_file("notes.md", "three")["saved"] == "notes (3).md"
    assert (browser.downloads_dir / "notes.md").read_text(encoding="utf-8") == "one"
    browser.save_file("notes.md", "replaced", overwrite=True)
    assert (browser.downloads_dir / "notes.md").read_text(encoding="utf-8") == "replaced"


@pytest.mark.parametrize("name", [
    "../escape.md", r"..\escape.md", "sub/notes.md", r"C:\temp\x.md", "/etc/x.md", "", "  ", "..",
])
def test_a_name_that_is_a_path_is_refused(registry, name):
    registry.create("work")
    with pytest.raises(OpError) as exc:
        registry.get("work").browser.save_file(name, "x")
    assert exc.value.type == "file_blocked"


@pytest.mark.parametrize("name", ["run.exe", "script.bat", "a.ps1", "page.js", "noext", "x.md.exe"])
def test_only_text_documents_can_be_saved(registry, name):
    registry.create("work")
    with pytest.raises(OpError) as exc:
        registry.get("work").browser.save_file(name, "x")
    assert exc.value.type == "file_blocked"


def test_a_document_over_the_limit_is_refused(registry):
    registry.create("work")
    browser = registry.get("work").browser
    with pytest.raises(OpError):
        browser.save_file("big.txt", "x" * (browser.SAVE_MAX_BYTES + 1))
    assert not (browser.downloads_dir / "big.txt").exists()


def test_save_file_needs_no_browser(registry):
    """It writes a file; starting Chrome for it would be waste, and slow."""
    registry.create("work")
    with TestClient(create_app(registry=registry)) as client:
        body = client.post(
            "/command-list",
            json={"op": "save_file", "name": "summary.md", "content": "hi"},
            headers={"X-ABT-Session": "work"},
        ).json()
    assert body["ok"] is True, body
    assert registry.get("work").browser.is_running is False
    assert (registry.get("work").browser.downloads_dir / "summary.md").exists()
