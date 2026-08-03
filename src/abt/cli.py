"""`abt` -- starts the server, and acts as a thin HTTP client for it.

Every subcommand other than `serve` is a plain HTTP call, so anything the CLI
can do, curl can do too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
import typer

app = typer.Typer(add_completion=False, help="Selenium browser API for AI agents.")

DEFAULT_PORT = 8765
HOST = "127.0.0.1"


def _port_option() -> int:
    return typer.Option(DEFAULT_PORT, "--port", "-p", help="Server port.")


def _call(port: int, path: str, payload: Any = None, method: str = "POST") -> None:
    url = f"http://{HOST}:{port}{path}"
    try:
        if method == "GET":
            response = httpx.get(url, timeout=300)
        else:
            response = httpx.post(url, json=payload, timeout=300)
    except httpx.ConnectError:
        typer.secho(
            f"No server on {HOST}:{port}. Start one with `abt serve`.",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)

    try:
        body = response.json()
    except ValueError:
        typer.secho(response.text, fg="red", err=True)
        raise typer.Exit(1)

    typer.echo(json.dumps(body, indent=2))
    raise typer.Exit(0 if body.get("ok") else 1)


@app.command()
def serve(
    profile: Path = typer.Option(
        Path("./profile"), "--profile", help="Persistent Chrome user-data-dir."
    ),
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p", help="Port to listen on."),
    headless: bool = typer.Option(False, "--headless", help="Run without a window."),
    action_timeout: float = typer.Option(
        5.0, "--action-timeout", help="Seconds to wait for an element before failing."
    ),
    log_dir: Path = typer.Option(
        Path("./logs"), "--log-dir", help="Where session logs are written."
    ),
    no_log: bool = typer.Option(False, "--no-log", help="Disable session logging."),
) -> None:
    """Open Chrome and listen for commands until told to shut down."""
    import uvicorn

    from .browser import BrowserSession
    from .recorder import SessionRecorder
    from .server import create_app

    session = BrowserSession(
        profile=profile, headless=headless, action_timeout=action_timeout
    )
    typer.echo(f"starting chrome (profile: {session.profile})")
    session.start()

    recorder = None if no_log else SessionRecorder(log_dir)
    if recorder is not None:
        typer.echo(f"recording session {recorder.session_id} -> {recorder.path}")

    holder: dict[str, Any] = {}
    application = create_app(
        session,
        request_stop=lambda: holder["server"].__setattr__("should_exit", True),
        recorder=recorder,
    )
    config = uvicorn.Config(
        application, host=HOST, port=port, log_level="warning", access_log=False
    )
    holder["server"] = uvicorn.Server(config)

    typer.echo(f"listening on http://{HOST}:{port}  (POST /command, /commands)")
    if recorder is not None:
        typer.echo(f"log viewer at http://{HOST}:{port}/viewer")
    typer.echo("send {\"op\": \"shutdown\"} to stop")
    try:
        holder["server"].run()
    except KeyboardInterrupt:
        pass
    finally:
        session.quit()
    typer.echo("stopped")


@app.command("exec")
def exec_(
    command: str = typer.Argument(..., help="A command as a JSON object."),
    port: int = _port_option(),
) -> None:
    """Send one raw JSON command."""
    _call(port, "/command", _load(command))


@app.command("exec-batch")
def exec_batch(
    file: Optional[Path] = typer.Argument(
        None, help="File holding a JSON array of commands. Omit to read stdin."
    ),
    continue_on_error: bool = typer.Option(
        False, "--continue-on-error", help="Run every command even if one fails."
    ),
    port: int = _port_option(),
) -> None:
    """Send a list of commands, run in order."""
    raw = file.read_text(encoding="utf-8") if file else sys.stdin.read()
    commands = _load(raw)
    if not isinstance(commands, list):
        typer.secho("expected a JSON array of commands", fg="red", err=True)
        raise typer.Exit(2)
    _call(
        port,
        "/commands",
        {"commands": commands, "continue_on_error": continue_on_error},
    )


@app.command()
def goto(url: str, port: int = _port_option()) -> None:
    """Load a URL in the active tab."""
    _call(port, "/command", {"op": "goto", "url": url})


@app.command()
def find(
    selector: str = typer.Argument(..., help="CSS selector."),
    full: bool = typer.Option(
        False, "--full", help="Include inner content instead of tag shells only."
    ),
    limit: int = typer.Option(100, "--limit"),
    visible_only: bool = typer.Option(False, "--visible-only"),
    port: int = _port_option(),
) -> None:
    """Search the page and return matching elements."""
    _call(
        port,
        "/command",
        {
            "op": "find",
            "css": selector,
            "mode": "full" if full else "shell",
            "limit": limit,
            "visible_only": visible_only,
        },
    )


@app.command()
def click(
    ref: Optional[str] = typer.Option(None, "--ref", help="A ref from find."),
    css: Optional[str] = typer.Option(None, "--css"),
    force: bool = typer.Option(
        False, "--force", help="Fall back to a JS click if an overlay intercepts."
    ),
    new_tab: bool = typer.Option(
        False, "--new-tab", help="Open the target's href in a new tab instead."
    ),
    background: bool = typer.Option(
        False, "--background", help="With --new-tab, stay on the current page."
    ),
    port: int = _port_option(),
) -> None:
    """Click an element."""
    payload = {"op": "click", **_target(ref, css)}
    if force:
        payload["force"] = True
    if new_tab:
        payload["new_tab"] = True
        payload["activate"] = not background
    _call(port, "/command", payload)


@app.command("input")
def input_(
    value: str = typer.Argument(..., help="Text to type."),
    ref: Optional[str] = typer.Option(None, "--ref"),
    css: Optional[str] = typer.Option(None, "--css"),
    keep: bool = typer.Option(False, "--keep", help="Append instead of clearing."),
    port: int = _port_option(),
) -> None:
    """Type into a field."""
    _call(
        port,
        "/command",
        {"op": "input", "value": value, "clear": not keep, **_target(ref, css)},
    )


@app.command()
def tabs(port: int = _port_option()) -> None:
    """List open tabs."""
    _call(port, "/command", {"op": "tab_list"})


@app.command()
def status(port: int = _port_option()) -> None:
    """Show current URL, tabs, and live refs."""
    _call(port, "/status", method="GET")


@app.command()
def ops(port: int = _port_option()) -> None:
    """List every supported op."""
    _call(port, "/ops", method="GET")


@app.command()
def logs(
    session_id: Optional[str] = typer.Argument(None, help="Session id. Omit to list."),
    site: Optional[str] = typer.Option(None, "--site", help="Only this host."),
    tab: Optional[str] = typer.Option(None, "--tab", help="Only this tab."),
    errors_only: bool = typer.Option(False, "--errors", help="Only failed commands."),
    sites: bool = typer.Option(False, "--sites", help="List sites instead."),
    port: int = _port_option(),
) -> None:
    """Browse recorded session logs."""
    if sites:
        _call(port, "/logs/sites", method="GET")
    if session_id is None:
        _call(port, "/logs", method="GET")
    query = []
    if site:
        query.append(f"site={site}")
    if tab:
        query.append(f"tab={tab}")
    if errors_only:
        query.append("errors_only=true")
    suffix = ("?" + "&".join(query)) if query else ""
    _call(port, f"/logs/{session_id}{suffix}", method="GET")


@app.command()
def shutdown(port: int = _port_option()) -> None:
    """Close the browser and stop the server."""
    _call(port, "/command", {"op": "shutdown"})


def _target(ref: Optional[str], css: Optional[str]) -> dict:
    if (ref is None) == (css is None):
        typer.secho("supply exactly one of --ref or --css", fg="red", err=True)
        raise typer.Exit(2)
    return {"ref": ref} if ref else {"css": css}


def _load(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.secho(f"invalid JSON: {exc}", fg="red", err=True)
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
