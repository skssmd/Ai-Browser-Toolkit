"""The audit filmstrip: which commands earn a frame, and how frames are stored.

The capture itself needs a browser and is covered in test_shots_live.py. Here
the policy and the storage are tested on their own, because those are the parts
that decide whether a long session costs five megabytes or five hundred.
"""

from __future__ import annotations

import pytest

from abt.recorder import SessionRecorder, read_events, shot_path
from abt.shots import wanted

JPEG = b"\xff\xd8\xff\xe0" + b"pretend jpeg" * 10
PNG = b"\x89PNG\r\n\x1a\n" + b"pretend png" * 10


@pytest.fixture
def root(tmp_path):
    return tmp_path / "logs"


def ok(result=None):
    return {"ok": True, "result": result or {}}


def err(type_="element_not_found"):
    return {"ok": False, "error": {"type": type_, "message": "nope", "op_index": 0}}


# --- which commands are worth a frame ----------------------------------------


@pytest.mark.parametrize("op", ["goto", "click", "input", "press", "select", "scroll"])
def test_state_changing_ops_are_captured(op):
    assert wanted(op, True)


@pytest.mark.parametrize("op", ["find", "get_text", "get_html", "read_console", "status"])
def test_reads_are_not_captured(op):
    """A read changes nothing, so its frame would duplicate the previous one."""
    assert not wanted(op, True)


@pytest.mark.parametrize("op", ["find", "get_text", "status", None])
def test_every_failure_is_captured_whatever_the_op(op):
    """Errors are the reason someone opens the log; never skip one."""
    assert wanted(op, False)


# --- storage ------------------------------------------------------------------


def test_a_frame_lands_next_to_the_event_that_made_it(root):
    rec = SessionRecorder(root)
    rec.record({"op": "click"}, ok(), "tab_0", "https://a.test/", 1.0,
               shot={"data": JPEG, "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}})

    event = read_events(root, rec.session_id)[0]
    assert event["shot"] == "00001.jpg"
    assert event["shot_box"]["w"] == 0.3
    assert (rec.shots_dir / "00001.jpg").read_bytes() == JPEG


def test_png_is_stored_under_its_own_extension(root):
    """The CDP path yields jpeg; the fallback yields png. Both must be servable."""
    rec = SessionRecorder(root)
    rec.record({"op": "goto"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": PNG})
    assert read_events(root, rec.session_id)[0]["shot"] == "00001.png"


def test_an_unchanged_frame_is_stored_once_and_shared(root):
    """Filling a form barely changes the page between commands -- the common case."""
    rec = SessionRecorder(root)
    for _ in range(3):
        rec.record({"op": "input"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": JPEG})

    events = read_events(root, rec.session_id)
    assert [e["shot"] for e in events] == ["00001.jpg"] * 3
    assert sorted(p.name for p in rec.shots_dir.iterdir()) == ["00001.jpg"]


def test_a_changed_frame_gets_its_own_file(root):
    rec = SessionRecorder(root)
    rec.record({"op": "goto"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": JPEG})
    rec.record({"op": "click"}, ok(), "tab_0", "https://a.test/", 1.0,
               shot={"data": JPEG + b"different"})
    assert [e["shot"] for e in read_events(root, rec.session_id)] == ["00001.jpg", "00002.jpg"]


def test_events_without_a_frame_say_nothing_about_one(root):
    rec = SessionRecorder(root)
    rec.record({"op": "find"}, ok({"count": 1}), "tab_0", "https://a.test/", 1.0)
    assert "shot" not in read_events(root, rec.session_id)[0]


def test_a_box_is_optional(root):
    rec = SessionRecorder(root)
    rec.record({"op": "goto"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": JPEG})
    event = read_events(root, rec.session_id)[0]
    assert event["shot"] == "00001.jpg"
    assert "shot_box" not in event


def test_capture_stops_at_the_size_cap_but_commands_keep_recording(root):
    """An unattended agent must not be able to fill a disk. Losing frames is
    acceptable; losing the log is not."""
    rec = SessionRecorder(root, max_shot_mb=len(JPEG) * 1.5 / (1024 * 1024))
    rec.record({"op": "goto"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": JPEG})
    rec.record({"op": "click"}, ok(), "tab_0", "https://a.test/", 1.0,
               shot={"data": JPEG + b"more"})

    events = read_events(root, rec.session_id)
    assert len(events) == 2
    assert events[0]["shot"] == "00001.jpg"
    assert "shot" not in events[1]


# --- serving ------------------------------------------------------------------


def test_shot_path_resolves_a_real_frame(root):
    rec = SessionRecorder(root)
    rec.record({"op": "goto"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": JPEG})
    assert shot_path(root, rec.session_id, "00001.jpg").read_bytes() == JPEG


@pytest.mark.parametrize(
    "name",
    ["../../events.jsonl", "..\\meta.json", "00001.jpg/../../meta.json", "meta.json",
     "00001.exe", "", "0001.jpg.exe"],
)
def test_shot_path_refuses_anything_it_did_not_write(root, name):
    """The name comes from a URL, so only the exact shape we produce is accepted."""
    rec = SessionRecorder(root)
    rec.record({"op": "goto"}, ok(), "tab_0", "https://a.test/", 1.0, shot={"data": JPEG})
    assert shot_path(root, rec.session_id, name) is None


def test_shot_path_refuses_a_session_id_with_separators(root):
    SessionRecorder(root, session_id="20260101-000000")
    assert shot_path(root, "../../etc", "00001.jpg") is None


def test_a_missing_frame_is_none_not_an_error(root):
    rec = SessionRecorder(root)
    assert shot_path(root, rec.session_id, "00042.jpg") is None
