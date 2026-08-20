"""Start the server at login. Opt in, never installed by default.

The toolkit is only useful when it is already up: an agent that has to start a
server first pays for the start, and one that starts it wrongly wedges itself.
A logon entry removes that, so `GET /status` answers from the moment you sit
down.

**This is only safe because the server no longer launches a browser.** It
listens in about a second and waits for `browser_start`. Installed against the
older behaviour it would open Chrome on the persistent profile at every logon
and cost roughly two minutes of every boot -- which is why this was parked
behind the browser/server decoupling rather than merely after it.

## Three mechanisms, one shape

| Platform | What gets written |
|---|---|
| Windows | a Task Scheduler logon task, via `schtasks` |
| macOS | a launchd `LaunchAgent` plist under `~/Library/LaunchAgents` |
| Linux | a systemd **user** unit under `~/.config/systemd/user` |

A user-level entry throughout: no elevation, no system service, and the browser
profile stays in the account that owns the logins. A system service would run as
another user and find none of them.

## What the plan has to get right

Three things that are invisible until they bite, all of them observed:

* **An absolute interpreter and absolute paths.** A logon entry has no working
  directory of its own and no venv on `PATH`. A relative `./profiles/default` resolves
  against whatever the launcher's cwd happens to be -- on Windows that is
  `C:\\Windows\\System32` -- so the server would quietly build a second, empty
  profile there and none of your logins would be in it.

* **`--browser` stated explicitly.** `abt serve` prompts when the flag is
  missing and stdin is a tty. A Task Scheduler task gets a console, so it
  prompts, and then waits forever with nobody to answer. The only evidence is
  one line in the log reading `Select browser to use [chrome]:`. Windows also
  gets `< NUL` for the same reason, belt and braces.

* **Never `--start-browser`.** See above; this is the whole reason the feature
  is sane.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .proc import windows_command_line

# One name per platform, in that platform's convention. Stable, because
# uninstall finds the entry by name and a rename would orphan the old one.
WINDOWS_TASK = "AI Browser Toolkit server"
MACOS_LABEL = "com.aibrowsertoolkit.server"
LINUX_UNIT = "abt-server.service"


class AutostartError(RuntimeError):
    """Something the caller can act on: a missing tool, a refused command."""


@dataclass(frozen=True)
class Plan:
    """Exactly what `install` would do, decided without touching the system.

    Separated from the doing so the hard part -- the command line, the paths,
    the unit text -- is testable on any machine, including the two platforms
    the test runner is not on.
    """

    kind: str
    name: str
    argv: list[str]
    path: Path | None = None
    content: str | None = None
    notes: list[str] = field(default_factory=list)


def current_platform() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    raise AutostartError(f"no autostart support for {system!r}")


def executable() -> str:
    """The `abt` to run at logon, as an absolute path.

    The console script is preferred because it is what the user types, but it
    only exists for an installed package. Falling back to `python -m abt.cli`
    keeps a source checkout working, and `sys.executable` is already absolute.
    """
    found = shutil.which("abt")
    if found:
        return str(Path(found).resolve())
    return sys.executable


def serve_argv(
    *,
    port: int,
    browser: str,
    profile: Path,
    log_dir: Path,
    engine: str = "playwright",
    headless: bool = False,
    exe: str | None = None,
) -> list[str]:
    """The command the logon entry runs.

    Every path is resolved here rather than at run time, because at run time
    there is no cwd worth resolving against.
    """
    exe = exe or executable()
    argv = [exe]
    # A source checkout has no console script, so the module has to be named.
    if Path(exe).stem.lower() not in ("abt",):
        argv += ["-m", "abt.cli"]
    argv += [
        "serve",
        "--browser",
        browser,
        "--port",
        str(port),
        "--profile",
        str(Path(profile).expanduser().resolve()),
        "--log-dir",
        str(Path(log_dir).expanduser().resolve()),
        "--engine",
        engine,
    ]
    if headless:
        argv.append("--headless")
    # Deliberately no --start-browser. See the module docstring.
    return argv


# `KeepAlive` restarts the server if it dies; `RunAtLoad` starts it at login.
# `ProcessType: Background` keeps macOS from deprioritising it the way it does
# an idle GUI app.
_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
{arguments}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>WorkingDirectory</key><string>{cwd}</string>
  <key>StandardOutPath</key><string>{stdout}</string>
  <key>StandardErrorPath</key><string>{stderr}</string>
</dict>
</plist>
"""

# `default.target` rather than `multi-user.target`: this is a user unit, and
# user units have their own target graph. Restart=on-failure covers a crash
# without fighting an intentional shutdown, which exits 0.
_UNIT = """[Unit]
Description=AI Browser Toolkit server
After=default.target

[Service]
Type=simple
ExecStart={command}
WorkingDirectory={cwd}
Restart=on-failure
RestartSec=5
StandardOutput=append:{stdout}
StandardError=append:{stderr}

[Install]
WantedBy=default.target
"""


def _quote_plist(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def plan(
    *,
    port: int,
    browser: str,
    profile: Path,
    log_dir: Path,
    engine: str = "playwright",
    headless: bool = False,
    kind: str | None = None,
    exe: str | None = None,
    home: Path | None = None,
) -> Plan:
    """What would be installed, without installing it."""
    kind = kind or current_platform()
    home = Path(home) if home is not None else Path.home()
    argv = serve_argv(
        port=port,
        browser=browser,
        profile=profile,
        log_dir=log_dir,
        engine=engine,
        headless=headless,
        exe=exe,
    )
    cwd = Path(profile).expanduser().resolve().parent
    out = Path(log_dir).expanduser().resolve() / "autostart.log"
    err = Path(log_dir).expanduser().resolve() / "autostart.err"

    if kind == "windows":
        return Plan(
            kind=kind,
            name=WINDOWS_TASK,
            argv=argv,
            content=windows_command_line(argv, out, err),
            notes=[
                "Runs at logon for this account only, at normal privilege.",
                "Remove it by hand with: schtasks /delete /tn "
                f'"{WINDOWS_TASK}" /f',
            ],
        )

    if kind == "macos":
        arguments = "\n".join(
            f"    <string>{_quote_plist(part)}</string>" for part in argv
        )
        return Plan(
            kind=kind,
            name=MACOS_LABEL,
            argv=argv,
            path=home / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist",
            content=_PLIST.format(
                label=MACOS_LABEL,
                arguments=arguments,
                cwd=_quote_plist(str(cwd)),
                stdout=_quote_plist(str(out)),
                stderr=_quote_plist(str(err)),
            ),
            notes=["KeepAlive is on, so launchd restarts the server if it dies."],
        )

    if kind == "linux":
        return Plan(
            kind=kind,
            name=LINUX_UNIT,
            argv=argv,
            path=home / ".config" / "systemd" / "user" / LINUX_UNIT,
            content=_UNIT.format(
                command=" ".join(_shell_quote(part) for part in argv),
                cwd=str(cwd),
                stdout=str(out),
                stderr=str(err),
            ),
            notes=[
                "A user unit starts at login and stops at logout. For a server "
                "that survives logout, run: loginctl enable-linger $USER",
            ],
        )

    raise AutostartError(f"unknown platform {kind!r}")


def _shell_quote(value: str) -> str:
    """systemd's ExecStart is not a shell, but it does split on spaces and
    honour double quotes, so a path with a space still has to be quoted."""
    if not value or any(ch.isspace() for ch in value) or '"' in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _run(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AutostartError(f"could not run {argv[0]!r}: {exc}") from exc


def install(spec: Plan) -> dict:
    """Write the entry and enable it. Idempotent: re-installing replaces."""
    if spec.kind == "windows":
        done = _run(
            [
                "schtasks", "/create", "/tn", spec.name, "/tr", spec.content or "",
                "/sc", "onlogon", "/rl", "limited", "/f",
            ]
        )
        if done.returncode != 0:
            raise AutostartError(
                f"schtasks refused to create the task: "
                f"{(done.stderr or done.stdout).strip()}"
            )
        return {"installed": True, "kind": spec.kind, "name": spec.name}

    if spec.path is None or spec.content is None:
        raise AutostartError(f"nothing to write for {spec.kind!r}")
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    spec.path.write_text(spec.content, encoding="utf-8")

    if spec.kind == "macos":
        # `bootstrap` is the modern form; `load -w` is what older systems have.
        # Try the new one and fall back rather than picking by version number.
        target = f"gui/{os.getuid()}"
        done = _run(["launchctl", "bootstrap", target, str(spec.path)])
        if done.returncode != 0:
            done = _run(["launchctl", "load", "-w", str(spec.path)])
            if done.returncode != 0:
                raise AutostartError(
                    f"launchctl refused the agent: "
                    f"{(done.stderr or done.stdout).strip()}"
                )
    else:
        _run(["systemctl", "--user", "daemon-reload"])
        done = _run(["systemctl", "--user", "enable", "--now", spec.name])
        if done.returncode != 0:
            raise AutostartError(
                f"systemctl refused the unit: "
                f"{(done.stderr or done.stdout).strip()}"
            )
    return {
        "installed": True,
        "kind": spec.kind,
        "name": spec.name,
        "path": str(spec.path),
    }


def uninstall(kind: str | None = None, home: Path | None = None) -> dict:
    """Remove the entry. Not an error when there is nothing to remove."""
    kind = kind or current_platform()
    home = Path(home) if home is not None else Path.home()

    if kind == "windows":
        done = _run(["schtasks", "/delete", "/tn", WINDOWS_TASK, "/f"])
        return {"removed": done.returncode == 0, "kind": kind, "name": WINDOWS_TASK}

    if kind == "macos":
        path = home / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        if path.exists():
            _run(["launchctl", "bootout", f"gui/{os.getuid()}/{MACOS_LABEL}"])
            _run(["launchctl", "unload", "-w", str(path)])
            path.unlink()
            return {"removed": True, "kind": kind, "name": MACOS_LABEL}
        return {"removed": False, "kind": kind, "name": MACOS_LABEL}

    path = home / ".config" / "systemd" / "user" / LINUX_UNIT
    if path.exists():
        _run(["systemctl", "--user", "disable", "--now", LINUX_UNIT])
        path.unlink()
        _run(["systemctl", "--user", "daemon-reload"])
        return {"removed": True, "kind": kind, "name": LINUX_UNIT}
    return {"removed": False, "kind": kind, "name": LINUX_UNIT}


def status(kind: str | None = None, home: Path | None = None) -> dict:
    """Whether an entry exists, reported without starting anything."""
    kind = kind or current_platform()
    home = Path(home) if home is not None else Path.home()

    if kind == "windows":
        done = _run(["schtasks", "/query", "/tn", WINDOWS_TASK])
        return {
            "kind": kind,
            "name": WINDOWS_TASK,
            "installed": done.returncode == 0,
        }

    if kind == "macos":
        path = home / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        return {
            "kind": kind,
            "name": MACOS_LABEL,
            "installed": path.exists(),
            "path": str(path),
        }

    path = home / ".config" / "systemd" / "user" / LINUX_UNIT
    info = {
        "kind": kind,
        "name": LINUX_UNIT,
        "installed": path.exists(),
        "path": str(path),
    }
    if path.exists():
        done = _run(["systemctl", "--user", "is-active", LINUX_UNIT], timeout=15)
        info["active"] = (done.stdout or "").strip() == "active"
    return info
