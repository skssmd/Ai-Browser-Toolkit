"""One-tap connect: give an agent harness its own session, and tell it how to reach it.

Each supported harness -- Claude Code, Codex, Cursor, VS Code, Gemini CLI,
OpenCode, Windsurf -- keeps its MCP servers in a file of its own. Connecting
writes one entry, named `abt`, that runs `abt mcp --session <harness>`: the
harness gets a session of its own, so its tabs, rules and log are apart from
every other agent's, and it shows in the app's Agents view like any other.

Only that one entry is ever touched. The file is copied to `<file>.abt-backup`
before the first change, and one that does not parse is left alone -- the
caller is told what to add by hand instead. Claude Code's own `claude mcp`
command is used when it is installed, since `~/.claude.json` is a large file
Claude Code rewrites while it runs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import OpError

ENTRY = "abt"
IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WINDOWS else {}


def mcp_command(session: str, api: str) -> list[str]:
    """How a harness starts ABT's MCP bridge for `session`.

    The interpreter running this server, so the bridge is the same install.
    pythonw has no console streams to speak MCP over; its python sibling does.
    """
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe" and (python.parent / "python.exe").exists():
        python = python.parent / "python.exe"
    return [str(python), "-m", "abt", "mcp", "--session", session, "--api", api]


# --- the file formats --------------------------------------------------------------


def _read_json(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise OpError(
            "invalid_op",
            f"{path} is not plain JSON (comments?), so it was left alone: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise OpError("invalid_op", f"{path} does not hold a JSON object; left alone")
    return data


def _backup(path: Path) -> None:
    copy = path.with_name(path.name + ".abt-backup")
    if path.exists() and not copy.exists():
        shutil.copy2(path, copy)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    tmp = path.with_name(path.name + ".abt-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _json_section(section: str, shape: Callable[[list[str]], dict]):
    """A JSON config holding its servers under `section`, each shaped by `shape`."""

    def is_connected(path: Path) -> str | None:
        try:
            entry = (_read_json(path).get(section) or {}).get(ENTRY)
        except OpError:
            return None
        return _session_in(entry)

    def add(path: Path, command: list[str]) -> None:
        data = _read_json(path)
        servers = data.get(section)
        if not isinstance(servers, dict):
            servers = {}
        servers[ENTRY] = shape(command)
        data[section] = servers
        _write_json(path, data)

    def remove(path: Path) -> None:
        if not path.exists():
            return
        data = _read_json(path)
        servers = data.get(section)
        if isinstance(servers, dict) and ENTRY in servers:
            del servers[ENTRY]
            _write_json(path, data)

    return is_connected, add, remove


def _session_in(entry) -> str | None:
    """The session an `abt` entry is bound to, whatever the file's shape."""
    if not isinstance(entry, dict):
        return None
    words = entry.get("args") or []
    if isinstance(entry.get("command"), list):  # OpenCode keeps it all in one list
        words = entry["command"]
    words = [str(w) for w in words]
    if "--session" in words and words.index("--session") + 1 < len(words):
        return words[words.index("--session") + 1]
    return None


_TOML_HEADER = re.compile(r"^\[mcp_servers\.abt\]\s*$", re.M)


def _toml_section(command: list[str]) -> str:
    quote = lambda s: json.dumps(s)  # a TOML basic string is JSON-compatible
    return (
        "[mcp_servers.abt]\n"
        f"command = {quote(command[0])}\n"
        f"args = [{', '.join(quote(a) for a in command[1:])}]\n"
    )


def _toml_strip(text: str) -> str:
    """Remove the `[mcp_servers.abt]` table: its header up to the next header."""
    match = _TOML_HEADER.search(text)
    if not match:
        return text
    rest = text[match.end():]
    nxt = re.search(r"^\[", rest, re.M)
    end = match.end() + (nxt.start() if nxt else len(rest))
    return (text[: match.start()] + text[end:]).rstrip() + "\n"


def _codex_connected(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = _TOML_HEADER.search(text)
    if not match:
        return None
    body = text[match.end():]
    nxt = re.search(r"^\[", body, re.M)
    body = body[: nxt.start()] if nxt else body
    found = re.search(r'"--session",\s*"([^"]+)"', body)
    return found.group(1) if found else None


def _codex_add(path: Path, command: list[str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = _toml_strip(text) if text else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    sep = "\n" if text and not text.endswith("\n\n") else ""
    path.write_text(text + sep + _toml_section(command), encoding="utf-8")


def _codex_remove(path: Path) -> None:
    if path.exists() and _TOML_HEADER.search(path.read_text(encoding="utf-8")):
        _backup(path)
        path.write_text(_toml_strip(path.read_text(encoding="utf-8")), encoding="utf-8")


# --- the harnesses -------------------------------------------------------------


@dataclass(frozen=True)
class Harness:
    id: str
    name: str
    config: Callable[[Path], Path]  # home -> the file its MCP servers live in
    marker: Callable[[Path], list[Path]]  # home -> paths whose presence means installed
    command: str | None  # an executable on PATH that also means installed
    connected: Callable[[Path], str | None]
    add: Callable[[Path, list[str]], None]
    remove: Callable[[Path], None]


def _appdata(home: Path) -> Path:
    return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")


_std = lambda cmd: {"command": cmd[0], "args": cmd[1:]}
_json_std = _json_section("mcpServers", _std)
_vscode = _json_section("servers", lambda cmd: {"type": "stdio", "command": cmd[0], "args": cmd[1:]})
_opencode = _json_section("mcp", lambda cmd: {"type": "local", "command": cmd, "enabled": True})
_claude_json = _json_section("mcpServers", lambda cmd: {"type": "stdio", "command": cmd[0], "args": cmd[1:], "env": {}})


def _claude_cli() -> str | None:
    return shutil.which("claude")


def _claude_add(path: Path, command: list[str]) -> None:
    cli = _claude_cli()
    if cli:
        subprocess.run([cli, "mcp", "remove", "--scope", "user", ENTRY],
                       capture_output=True, timeout=60, **_NO_WINDOW)
        spec = json.dumps({"type": "stdio", "command": command[0], "args": command[1:]})
        done = subprocess.run([cli, "mcp", "add-json", "--scope", "user", ENTRY, spec],
                              capture_output=True, text=True, timeout=60, **_NO_WINDOW)
        if done.returncode == 0:
            return
    _claude_json[1](path, command)


def _claude_remove(path: Path) -> None:
    cli = _claude_cli()
    if cli:
        done = subprocess.run([cli, "mcp", "remove", "--scope", "user", ENTRY],
                              capture_output=True, timeout=60, **_NO_WINDOW)
        if done.returncode == 0:
            return
    _claude_json[2](path)


HARNESSES: tuple[Harness, ...] = (
    Harness("claude-code", "Claude Code", lambda h: h / ".claude.json",
            lambda h: [h / ".claude.json", h / ".claude"], "claude",
            _claude_json[0], _claude_add, _claude_remove),
    Harness("codex", "Codex", lambda h: h / ".codex" / "config.toml",
            lambda h: [h / ".codex"], "codex",
            _codex_connected, _codex_add, _codex_remove),
    Harness("cursor", "Cursor", lambda h: h / ".cursor" / "mcp.json",
            lambda h: [h / ".cursor"], "cursor", *_json_std),
    Harness("vscode", "VS Code", lambda h: _appdata(h) / "Code" / "User" / "mcp.json",
            lambda h: [_appdata(h) / "Code" / "User"], "code", *_vscode),
    Harness("gemini", "Gemini CLI", lambda h: h / ".gemini" / "settings.json",
            lambda h: [h / ".gemini"], "gemini", *_json_std),
    Harness("opencode", "OpenCode", lambda h: h / ".config" / "opencode" / "opencode.json",
            lambda h: [h / ".config" / "opencode"], "opencode", *_opencode),
    Harness("windsurf", "Windsurf", lambda h: h / ".codeium" / "windsurf" / "mcp_config.json",
            lambda h: [h / ".codeium" / "windsurf"], "windsurf", *_json_std),
)


def find(harness_id: str) -> Harness:
    for harness in HARNESSES:
        if harness.id == harness_id:
            return harness
    raise OpError("invalid_op", f"unknown harness {harness_id!r}; known: {', '.join(h.id for h in HARNESSES)}")


def status(home: Path | None = None, which: Callable[[str], str | None] = shutil.which) -> list[dict]:
    home = Path(home or Path.home())
    rows = []
    for harness in HARNESSES:
        installed = any(p.exists() for p in harness.marker(home)) or bool(
            harness.command and which(harness.command)
        )
        rows.append({
            "id": harness.id,
            "name": harness.name,
            "installed": installed,
            "config": str(harness.config(home)),
            "session": harness.connected(harness.config(home)),
        })
    return rows


def connect(harness_id: str, session: str, api: str, home: Path | None = None) -> dict:
    harness = find(harness_id)
    home = Path(home or Path.home())
    path = harness.config(home)
    command = mcp_command(session, api)
    harness.add(path, command)
    return {"id": harness.id, "name": harness.name, "session": session, "config": str(path),
            "command": command}


def disconnect(harness_id: str, home: Path | None = None) -> dict:
    harness = find(harness_id)
    home = Path(home or Path.home())
    harness.remove(harness.config(home))
    return {"id": harness.id, "name": harness.name, "session": None}
