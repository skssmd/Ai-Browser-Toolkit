"""Append-only session logs.

One JSONL file per server run. Every command lands as one line carrying what was
asked, what came back, which tab it ran in, and which site was loaded at the time
-- so a session can be replayed or browsed after the fact, per tab or per site.

JSONL because it survives a crash: a killed server leaves every line up to the
kill intact, which a single JSON array would not.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Responses can carry whole pages. Keep the log readable and bounded on disk.
MAX_FIELD = 4000


def host_of(url: str | None) -> str:
    if not url:
        return "unknown"
    try:
        return urlparse(url).netloc or "unknown"
    except ValueError:
        return "unknown"


def truncate(value: Any, limit: int = MAX_FIELD) -> Any:
    """Shorten long strings in place, marking what was cut."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"… [{len(value) - limit} more chars]"
    if isinstance(value, dict):
        return {k: truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [truncate(v, limit) for v in value]
    return value


class SessionRecorder:
    """Writes one session's events. Safe to call from the server threadpool."""

    def __init__(self, root: Path, session_id: str | None = None) -> None:
        self.root = Path(root)
        self.session_id = session_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = self.root / self.session_id
        self.path = self.dir / "events.jsonl"
        self.meta_path = self.dir / "meta.json"
        self._lock = threading.Lock()
        self._seq = 0
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._write_meta({"events": 0, "ended_at": None})

    # --- writing --------------------------------------------------------------

    def record(
        self,
        request: Any,
        response: dict,
        tab_id: str | None,
        url: str | None,
        duration_ms: float,
    ) -> dict:
        op = request.get("op") if isinstance(request, dict) else None
        error = response.get("error") or {}
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "at": datetime.now(timezone.utc).isoformat(),
                "session_id": self.session_id,
                "tab_id": tab_id,
                "site": host_of(url),
                "url": url,
                "op": op,
                "ok": bool(response.get("ok")),
                "error_type": error.get("type"),
                "duration_ms": round(duration_ms, 1),
                "request": truncate(request),
                "response": truncate(response.get("result") if response.get("ok") else error),
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._write_meta({"events": self._seq, "ended_at": None})
        return event

    def close(self) -> None:
        with self._lock:
            self._write_meta(
                {"events": self._seq, "ended_at": datetime.now(timezone.utc).isoformat()}
            )

    def _write_meta(self, extra: dict) -> None:
        meta = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            **extra,
        }
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# --- reading ------------------------------------------------------------------


def read_events(root: Path, session_id: str) -> list[dict]:
    path = Path(root) / session_id / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # A half-written final line after a kill. Keep everything before it.
            continue
    return events


def list_sessions(root: Path) -> list[dict]:
    root = Path(root)
    if not root.exists():
        return []
    sessions = []
    for entry in sorted(root.iterdir(), reverse=True):
        meta_path = entry / "meta.json"
        if not entry.is_dir() or not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        events = read_events(root, entry.name)
        meta["sites"] = sorted({e["site"] for e in events if e.get("site")})
        meta["events"] = len(events)
        meta["errors"] = sum(1 for e in events if not e.get("ok"))
        sessions.append(meta)
    return sessions


def sites_index(root: Path) -> list[dict]:
    """Every site seen across every session, newest activity first."""
    tally: dict[str, dict] = {}
    for session in list_sessions(root):
        for event in read_events(root, session["session_id"]):
            site = event.get("site") or "unknown"
            row = tally.setdefault(
                site, {"site": site, "events": 0, "errors": 0, "sessions": set(), "last": ""}
            )
            row["events"] += 1
            row["errors"] += 0 if event.get("ok") else 1
            row["sessions"].add(event["session_id"])
            row["last"] = max(row["last"], event.get("at", ""))
    rows = []
    for row in tally.values():
        row["sessions"] = sorted(row["sessions"], reverse=True)
        rows.append(row)
    return sorted(rows, key=lambda r: r["last"], reverse=True)


def now_ms() -> float:
    return time.perf_counter() * 1000
