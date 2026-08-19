"""Starting a process that outlives the one that asked for it.

On Windows a process started by a shell joins that shell's *job object*. A
harness that waits on the job blocks until every member exits, so `nohup`,
`start /b`, and redirecting stdio all fail to help -- which is why
`start-server.bat` never fixed this. CREATE_BREAKAWAY_FROM_JOB is the
documented escape and silently fails when the job forbids breakaway, which is
precisely the case that needs escaping.

So ask someone else to do the spawning. A process created through WMI is a
child of WmiPrvSE.exe, and one created through Task Scheduler is a child of the
scheduler service; either way it belongs to no job of ours and nothing in the
calling session can wait on it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def powershell_single_quote(value: str) -> str:
    """Wrap a value as a PowerShell literal string. Doubling escapes a quote."""
    return "'" + str(value).replace("'", "''") + "'"


def windows_command_line(argv: list[str], stdout: Path, stderr: Path) -> str:
    """A cmd.exe line that runs argv with its output redirected to files.

    WMI cannot redirect, so the redirection has to be part of the command. The
    outer `cmd.exe /c "..."` wrapper keeps cmd's own quoting rules happy when
    any of the paths contain spaces, which on Windows they usually do.

    stdin comes from NUL, and that is not decoration. WMI hands the new process
    a console, so `sys.stdin.isatty()` is True there -- which is exactly the
    condition `abt serve` uses to decide it may prompt for a browser. Observed:
    the server sat forever on "Select browser to use [chrome]:" with nobody to
    answer, and the only evidence was that one line in server.log.
    """
    inner = subprocess.list2cmdline(argv)
    return f'cmd.exe /c "{inner} < NUL > "{stdout}" 2> "{stderr}""'


def _spawn_wmi(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> bool:
    command = windows_command_line(argv, stdout, stderr)
    script = (
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine="
        + powershell_single_quote(command)
        + "; CurrentDirectory="
        + powershell_single_quote(str(cwd))
        + "}; exit $r.ReturnValue"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _spawn_schtasks(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> bool:
    """Fallback: a one-shot scheduled task, run immediately and deleted.

    Slower and leaves a task behind for a moment, but works where WMI is
    blocked by security software.
    """
    name = f"abt-up-{os.getpid()}"
    command = windows_command_line(argv, stdout, stderr)
    try:
        created = subprocess.run(
            [
                "schtasks", "/create", "/tn", name, "/tr", command,
                "/sc", "once", "/st", "00:00", "/f",
            ],
            capture_output=True,
            timeout=60,
        )
        if created.returncode != 0:
            return False
        run = subprocess.run(
            ["schtasks", "/run", "/tn", name], capture_output=True, timeout=60
        )
        return run.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            subprocess.run(
                ["schtasks", "/delete", "/tn", name, "/f"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _spawn_windows_detached(
    argv: list[str], cwd: Path, stdout: Path, stderr: Path
) -> bool:
    """Last resort. Escapes the console but not necessarily the job object."""
    flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )
    try:
        with open(stdout, "ab") as out, open(stderr, "ab") as err:
            subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
        return True
    except OSError:
        return False


def _spawn_posix(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> bool:
    try:
        with open(stdout, "ab") as out, open(stderr, "ab") as err:
            subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        return True
    except OSError:
        return False


def spawn_detached(argv: list[str], cwd: Path, stdout: Path, stderr: Path) -> str:
    """Start argv so it outlives this process. Returns the mechanism that worked."""
    if not argv:
        raise ValueError("nothing to spawn: argv is empty")
    cwd = Path(cwd)
    stdout = Path(stdout)
    stderr = Path(stderr)
    stdout.parent.mkdir(parents=True, exist_ok=True)
    stderr.parent.mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS:
        attempts = (
            ("wmi", _spawn_wmi),
            ("schtasks", _spawn_schtasks),
            ("detached", _spawn_windows_detached),
        )
    else:
        attempts = (("setsid", _spawn_posix),)

    for name, attempt in attempts:
        if attempt(argv, cwd, stdout, stderr):
            return name
    raise OSError("could not start the server detached; see the log files")
