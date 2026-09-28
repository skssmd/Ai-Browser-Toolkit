"""Uploads and downloads against a real Chrome, in a session's own folders."""

from __future__ import annotations

import time

import pytest

from abt.browser import BrowserSession
from abt.errors import OpError
from abt.ops import dispatch
from abt.profiles import ProfileRegistry
from abt.schema import parse_command
from abt.sessions import SessionRegistry, SessionStore


@pytest.fixture
def work(tmp_path, budgets):
    registry = SessionRegistry(
        SessionStore(tmp_path / "sessions"),
        ProfileRegistry(root=tmp_path / "profiles"),
        lambda d, a: BrowserSession(profile=d, headless=True, attach=a, **budgets),
        files_root=tmp_path / "files",
    )
    registry.create("work")
    browser = registry.get("work").browser
    browser.start()
    yield browser, tmp_path
    registry.close_all()


def run(browser, **cmd):
    return dispatch(browser, parse_command(cmd))


def test_a_file_from_the_uploads_folder_reaches_the_page(work, base_url):
    browser, _ = work
    browser.uploads_dir.mkdir(parents=True, exist_ok=True)
    (browser.uploads_dir / "cv.pdf").write_bytes(b"%PDF-1.4")
    run(browser, op="goto", url=f"{base_url}/download.html")
    run(browser, op="input", css="#doc", value=str(browser.uploads_dir / "cv.pdf"))
    assert browser.driver.execute_script("return document.getElementById('picked').textContent") == "cv.pdf"


def test_a_key_outside_the_folder_never_reaches_the_page(work, base_url):
    browser, tmp_path = work
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE", encoding="utf-8")
    run(browser, op="goto", url=f"{base_url}/download.html")
    with pytest.raises(OpError) as exc:
        run(browser, op="input", css="#doc", value=str(secret))
    assert exc.value.type == "file_blocked"
    assert browser.driver.execute_script("return document.getElementById('doc').files.length") == 0


def test_a_download_lands_in_the_sessions_downloads_folder(work, base_url):
    browser, _ = work
    run(browser, op="goto", url=f"{base_url}/download.html")
    run(browser, op="click", css="#dl")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        # Any call lets the connection hand over the download event.
        names = [f["name"] for f in run(browser, op="files")["downloads"]["files"]]
        if names:
            break
        time.sleep(0.3)
    assert names == ["catalogue.html"]


def test_a_file_picker_is_dismissed_and_the_ai_told_what_to_do(work, base_url):
    """No picker ever opens in a session: the click that tried says so, and
    points at the uploads folder and `input` -- the only route that works."""
    browser, _ = work
    run(browser, op="goto", url=f"{base_url}/download.html")
    started = time.monotonic()
    result = run(browser, op="click", css="#doc")
    assert time.monotonic() - started < 15, "the picker hung the click"
    assert "file_chooser" in result
    assert '"op": "files"' in result["file_chooser"]
    # The note is given once, for the picker that opened, not on every command.
    assert "file_chooser" not in run(browser, op="current_url")
    # And the route it points at works.
    browser.uploads_dir.mkdir(parents=True, exist_ok=True)
    (browser.uploads_dir / "cv.pdf").write_bytes(b"%PDF")
    path = run(browser, op="files")["uploads"]["files"][0]["path"]
    run(browser, op="input", css="input[type=file]", value=path)
    assert browser.driver.execute_script("return document.getElementById('picked').textContent") == "cv.pdf"
