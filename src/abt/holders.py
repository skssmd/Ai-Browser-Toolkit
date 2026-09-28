"""Finding, and ending, the browsers that hold a profile folder.

Chrome allows one browser per profile folder. A server that dies without
closing its browsers -- killed from Task Manager, a crash, a forced restart --
leaves them running, hidden, still holding their profiles, and the next server
cannot start a browser on any of them.

`find` names those processes by their command line. `ours_only` narrows it to
the ones abt itself starts (see `profiles.launch_argv`): the profile folder
*and* `--remote-debugging-port=0`, which a Chrome window a person opened does
not carry. Those are safe to end without asking. Anything else holding the
folder -- a real Chrome window somebody is using -- is only ended when the
person says so (`force_close`).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WINDOWS else {}

# What abt's own launches carry and a person's Chrome does not.
OURS = "--remote-debugging-port=0"


def _processes() -> list[tuple[int, str]]:
    """(pid, command line) for every process we may look at."""
    try:
        if IS_WINDOWS:
            script = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
                "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
            )
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=30, **_NO_WINDOW,
            )
            rows = json.loads(done.stdout or "[]")
            if isinstance(rows, dict):
                rows = [rows]
            return [(int(r["ProcessId"]), r.get("CommandLine") or "") for r in rows]
        done = subprocess.run(
            ["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=30
        )
        out = []
        for line in done.stdout.splitlines():
            pid, _, args = line.strip().partition(" ")
            if pid.isdigit():
                out.append((int(pid), args))
        return out
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def _names(command: str, directory: Path) -> bool:
    """Whether this command line runs a browser on exactly this folder."""
    want = os.path.normcase(str(Path(directory).resolve()))
    for part in (f"--user-data-dir={want}", f'--user-data-dir="{want}"'):
        if part in os.path.normcase(command):
            rest = os.path.normcase(command).split(part, 1)[1]
            # Not a longer folder that merely starts with this one.
            if not rest or rest[0] in ' "':
                return True
    return False


def find(directory: Path, ours_only: bool = True, processes=None) -> list[int]:
    """Pids of the browser processes holding `directory`."""
    rows = _processes() if processes is None else processes
    return [
        pid
        for pid, command in rows
        if pid != os.getpid() and _names(command, directory) and (not ours_only or OURS in command)
    ]


def kill(pids: list[int]) -> int:
    """End these processes and their children. Returns how many were asked to."""
    ended = 0
    for pid in pids:
        try:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=30, **_NO_WINDOW,
                )
            else:
                os.kill(pid, signal.SIGKILL)
            ended += 1
        except (OSError, subprocess.SubprocessError):
            pass
    return ended
