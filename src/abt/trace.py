"""Every step, timed: what is running now, and how long each finished step took.

A step is a span: a chat reply, a model call, a tool call, a browser command,
one call into Playwright's driver. Spans nest -- each knows the step it is part
of -- so a hang reads as a chain, e.g.

    chat.reply 320s > tool command_list 300s > command goto 300s > driver get 300s

and points at the step that is stuck.

- In flight: `active()` lists every span still running, oldest first.
- Finished: each is appended to `logs/trace/trace-YYYYMMDD.jsonl` with its
  duration and outcome, and kept in a short in-memory ring for `recent()`.
  Anything slower than SLOW_SECONDS is also printed to stderr (server.err).
- Driver calls are frequent: they always show in `active()`, but are written
  to the file only when slow or failed, so the file stays readable.

Cheap enough to leave on: a span is two dict operations and, for the ones
that are written, one short line appended to a file.
"""

from __future__ import annotations

import contextvars
import itertools
import json
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SLOW_SECONDS = 5.0
QUIET_KINDS = frozenset({"driver"})  # written only when slow or failed
QUIET_MIN_SECONDS = 0.25

_ids = itertools.count(1)
_current: contextvars.ContextVar[int | None] = contextvars.ContextVar("abt_span", default=None)
_lock = threading.Lock()
_active: dict[int, dict] = {}
_recent: deque = deque(maxlen=500)
_dir: Path | None = None


def configure(directory: Path | None) -> None:
    """Where finished spans are written. None keeps them in memory only."""
    global _dir
    _dir = Path(directory) if directory is not None else None
    if _dir is not None:
        _dir.mkdir(parents=True, exist_ok=True)


def _write(record: dict) -> None:
    if _dir is None:
        return
    path = _dir / f"trace-{time.strftime('%Y%m%d')}.jsonl"
    try:
        with open(path, "a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


class Span:
    """A running step. `note()` adds a field, e.g. the time to the first token."""

    def __init__(self, record: dict) -> None:
        self.record = record

    def note(self, **fields: Any) -> None:
        self.record.update(fields)

    def elapsed_ms(self) -> float:
        return round((time.time() - self.record["started"]) * 1000, 1)


@contextmanager
def span(kind: str, name: str = "", **fields: Any) -> Iterator[Span]:
    """Time one step. Nested spans record their parent automatically."""
    sid = next(_ids)
    record = {
        "id": sid,
        "parent": _current.get(),
        "kind": kind,
        "name": name,
        "started": time.time(),
        "thread": threading.current_thread().name,
        **{k: v for k, v in fields.items() if v is not None},
    }
    with _lock:
        _active[sid] = record
    token = _current.set(sid)
    ok, error = True, None
    try:
        yield Span(record)
    except BaseException as exc:
        ok, error = False, f"{type(exc).__name__}: {str(exc)[:200]}"
        raise
    finally:
        _current.reset(token)
        with _lock:
            _active.pop(sid, None)
        seconds = time.time() - record["started"]
        done = {**record, "ms": round(seconds * 1000, 1), "ok": ok}
        if error:
            done["error"] = error
        _recent.append(done)
        if kind not in QUIET_KINDS or seconds >= QUIET_MIN_SECONDS or not ok:
            _write(done)
        if seconds >= SLOW_SECONDS:
            print(f"[abt trace] slow {kind} {name} {seconds:.1f}s"
                  f"{' FAILED ' + error if error else ''} {_where(done)}", file=sys.stderr, flush=True)


def _where(record: dict) -> str:
    bits = [f"{k}={record[k]}" for k in ("session", "chat", "op", "model") if record.get(k)]
    return " ".join(bits)


def current() -> int | None:
    """The span this thread is inside, for work handed to another thread."""
    return _current.get()


def active() -> list[dict]:
    """Every step still running, oldest first, with its age and its chain."""
    now = time.time()
    with _lock:
        rows = [dict(r) for r in _active.values()]
    by_id = {r["id"]: r for r in rows}
    out = []
    for r in sorted(rows, key=lambda r: r["started"]):
        chain, node = [], r
        while node is not None:
            chain.append(f"{node['kind']} {node['name']}".strip())
            node = by_id.get(node.get("parent"))
        r["age_s"] = round(now - r["started"], 1)
        r["chain"] = " > ".join(reversed(chain))
        out.append(r)
    return out


def recent(limit: int = 100) -> list[dict]:
    """The most recently finished steps, newest last."""
    return list(_recent)[-limit:]
