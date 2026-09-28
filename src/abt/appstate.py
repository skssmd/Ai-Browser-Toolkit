"""What the desktop app keeps: its model settings, and each session's chats.

Both live beside the session records, owner-only, because the settings hold an
API key and the chats hold whatever the person typed.
"""

from __future__ import annotations

import json
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .errors import OpError
from .profiles import check_name
from .sessions import write_private

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AppSettings:
    """Endpoint, API key and model list. One file, read on every use."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {
            "endpoint": str(data.get("endpoint") or DEFAULT_ENDPOINT),
            "api_key": str(data.get("api_key") or ""),
            "models": [str(m) for m in data.get("models") or []],
        }

    def public(self) -> dict:
        """Settings as the page may see them: the key only as a hint."""
        data = self.load()
        key = data.pop("api_key")
        data["has_key"] = bool(key)
        data["key_hint"] = f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else "")
        return data

    def update(self, changes: Any) -> dict:
        if not isinstance(changes, dict):
            raise OpError("invalid_op", "settings must be an object")
        with self._lock:
            data = self.load()
            if "endpoint" in changes:
                endpoint = str(changes["endpoint"] or "").strip().rstrip("/")
                if not endpoint.startswith(("http://", "https://")):
                    raise OpError("invalid_op", "endpoint must be an http(s) URL")
                data["endpoint"] = endpoint
            if "api_key" in changes and changes["api_key"] is not None:
                data["api_key"] = str(changes["api_key"]).strip()
            if "models" in changes:
                models = changes["models"]
                if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
                    raise OpError("invalid_op", "models must be a list of strings")
                data["models"] = [m.strip() for m in models if m.strip()]
            write_private(self.path, json.dumps(data, indent=2))
        return self.public()


def free_models(endpoint: str, api_key: str = "", get=None) -> list[dict]:
    """Models at an OpenRouter-style endpoint that cost nothing and take tools.

    Tools are not optional here: the app drives the browser through tool
    calls, and a model without them can only talk about the page.
    """
    get = get or (lambda url, headers: httpx.get(url, headers=headers, timeout=20).json())
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        body = get(f"{endpoint.rstrip('/')}/models", headers)
    except Exception as exc:
        raise OpError("invalid_op", f"could not list models at {endpoint}: {exc}") from exc
    found = []
    for model in (body or {}).get("data", []):
        pricing = model.get("pricing") or {}
        free = all(str(pricing.get(k, "1")).strip() in ("0", "0.0") for k in ("prompt", "completion"))
        tools = "tools" in (model.get("supported_parameters") or [])
        if free and tools:
            found.append({
                "id": model.get("id"),
                "name": model.get("name") or model.get("id"),
                "context": model.get("context_length"),
            })
    return sorted(found, key=lambda m: -(m.get("context") or 0))


class ChatStore:
    """`<root>/<session>/<chat id>.json`, one conversation each."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _dir(self, session: str) -> Path:
        return self.root / check_name(session, "session")

    def _path(self, session: str, chat_id: str) -> Path:
        if not isinstance(chat_id, str) or not chat_id.isalnum() or len(chat_id) > 32:
            raise OpError("invalid_op", f"bad chat id {chat_id!r}")
        return self._dir(session) / f"{chat_id}.json"

    def list(self, session: str) -> list[dict]:
        directory = self._dir(session)
        if not directory.is_dir():
            return []
        rows = []
        for path in directory.glob("*.json"):
            try:
                chat = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            row = {k: chat.get(k) for k in ("id", "title", "created", "updated", "model")}
            # Lets the app skip empty chats when choosing which one to open.
            row["messages"] = len(chat.get("messages") or [])
            rows.append(row)
        return sorted(rows, key=lambda r: r.get("updated") or "", reverse=True)

    def create(self, session: str, model: str | None = None) -> dict:
        chat = {
            "id": secrets.token_hex(8),
            "title": "New chat",
            "created": _now(),
            "updated": _now(),
            "model": model,
            "messages": [],
        }
        self.save(session, chat)
        return chat

    def get(self, session: str, chat_id: str) -> dict:
        path = self._path(session, chat_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise OpError("invalid_op", f"no chat {chat_id!r} in session {session!r}")

    def save(self, session: str, chat: dict) -> None:
        chat["updated"] = _now()
        with self._lock:
            write_private(self._path(session, chat["id"]), json.dumps(chat, indent=1))

    def delete(self, session: str, chat_id: str) -> None:
        self._path(session, chat_id).unlink(missing_ok=True)

    def retire(self, session: str) -> None:
        """A removed session's chats move aside, like its logs, so a new
        session under the same name does not inherit them."""
        directory = self._dir(session)
        if directory.is_dir():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            target = self.root.parent / "removed-chats" / f"{session}-{stamp}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(directory), str(target))
