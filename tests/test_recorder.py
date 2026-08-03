"""Recorder storage and reading, with no browser involved."""

from __future__ import annotations

import json

import pytest

from abt.recorder import (
    MAX_FIELD,
    SessionRecorder,
    host_of,
    list_sessions,
    read_events,
    sites_index,
    truncate,
)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "logs"


def ok(result):
    return {"ok": True, "result": result}


def err(type_, message):
    return {"ok": False, "error": {"type": type_, "message": message, "op_index": 0}}


def test_host_extraction():
    assert host_of("https://example.com/a/b?c=1") == "example.com"
    assert host_of("") == "unknown"
    assert host_of(None) == "unknown"


def test_truncate_shortens_long_strings_and_marks_them():
    out = truncate("x" * (MAX_FIELD + 50))
    assert out.startswith("x" * 50)
    assert "50 more chars" in out


def test_truncate_walks_nested_structures():
    out = truncate({"a": ["y" * (MAX_FIELD + 1)], "b": 3})
    assert "more chars" in out["a"][0]
    assert out["b"] == 3


def test_records_one_line_per_command(root):
    rec = SessionRecorder(root)
    rec.record({"op": "goto", "url": "https://a.test/x"}, ok({"url": "https://a.test/x"}),
               "tab_0", "https://a.test/x", 12.34)
    rec.record({"op": "find", "css": ".a"}, ok({"count": 0}), "tab_0", "https://a.test/x", 5.0)

    lines = rec.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["seq"] == 1
    assert first["op"] == "goto"
    assert first["site"] == "a.test"
    assert first["tab_id"] == "tab_0"
    assert first["ok"] is True
    assert first["duration_ms"] == 12.3


def test_records_the_error_when_a_command_fails(root):
    rec = SessionRecorder(root)
    rec.record({"op": "click", "css": "#x"}, err("element_not_found", "nope"),
               "tab_0", "https://a.test/", 1.0)
    event = read_events(root, rec.session_id)[0]
    assert event["ok"] is False
    assert event["error_type"] == "element_not_found"
    assert event["response"]["message"] == "nope"


def test_sequence_numbers_increase(root):
    rec = SessionRecorder(root)
    for _ in range(5):
        rec.record({"op": "status"}, ok({}), "tab_0", "https://a.test/", 1.0)
    assert [e["seq"] for e in read_events(root, rec.session_id)] == [1, 2, 3, 4, 5]


def test_a_half_written_final_line_is_skipped(root):
    rec = SessionRecorder(root)
    rec.record({"op": "status"}, ok({}), "tab_0", "https://a.test/", 1.0)
    with rec.path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 2, "op": "clic')  # killed mid-write
    events = read_events(root, rec.session_id)
    assert len(events) == 1
    assert events[0]["seq"] == 1


def test_session_index_summarises(root):
    rec = SessionRecorder(root)
    rec.record({"op": "goto"}, ok({}), "tab_0", "https://a.test/", 1.0)
    rec.record({"op": "click"}, err("timeout", "slow"), "tab_0", "https://b.test/", 1.0)
    rec.close()

    listed = list_sessions(root)
    assert len(listed) == 1
    assert listed[0]["events"] == 2
    assert listed[0]["errors"] == 1
    assert listed[0]["sites"] == ["a.test", "b.test"]
    assert listed[0]["ended_at"] is not None


def test_sessions_are_listed_newest_first(root):
    SessionRecorder(root, session_id="20240101-000000")
    SessionRecorder(root, session_id="20250101-000000")
    assert [s["session_id"] for s in list_sessions(root)] == [
        "20250101-000000",
        "20240101-000000",
    ]


def test_sites_index_spans_sessions(root):
    a = SessionRecorder(root, session_id="20240101-000000")
    a.record({"op": "goto"}, ok({}), "tab_0", "https://shared.test/1", 1.0)
    b = SessionRecorder(root, session_id="20250101-000000")
    b.record({"op": "goto"}, ok({}), "tab_0", "https://shared.test/2", 1.0)
    b.record({"op": "click"}, err("timeout", "x"), "tab_0", "https://shared.test/2", 1.0)

    rows = {r["site"]: r for r in sites_index(root)}
    assert rows["shared.test"]["events"] == 3
    assert rows["shared.test"]["errors"] == 1
    assert len(rows["shared.test"]["sessions"]) == 2


def test_missing_root_is_empty_not_an_error(tmp_path):
    assert list_sessions(tmp_path / "nope") == []
    assert read_events(tmp_path / "nope", "whatever") == []
