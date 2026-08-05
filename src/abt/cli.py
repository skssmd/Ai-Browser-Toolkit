"""`abt` -- starts the server, and acts as a thin HTTP client for it.

Every subcommand other than `serve` is a plain HTTP call, so anything the CLI
can do, curl can do too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import typer

app = typer.Typer(add_completion=False, help="Selenium browser API for AI agents.")
messenger = typer.Typer(add_completion=False, help="Send and read on messenger.com.")
app.add_typer(messenger, name="messenger")

DEFAULT_PORT = 8765
HOST = "127.0.0.1"


def _port_option() -> int:
    return typer.Option(DEFAULT_PORT, "--port", "-p", help="Server port.")


def _choose_browser(browser: str | None) -> str:
    """Resolve the browser choice, prompting interactively when omitted.

    Only prompt when someone is there to answer. `abt serve` is routinely
    launched detached -- `nohup abt serve &`, `Start-Process`, an agent starting
    its own server -- and a prompt with no stdin hangs or aborts the launch.
    """
    if browser is not None:
        chosen = browser.strip().lower()
    elif not sys.stdin.isatty():
        chosen = "chrome"
    else:
        chosen = typer.prompt(
            "Select browser to use", default="chrome", type=str
        ).strip().lower()
    if chosen not in ("chrome", "edge"):
        raise typer.BadParameter(f"choose from: chrome, edge (got {chosen!r})")
    return chosen


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
    browser: str = typer.Option(
        None,
        "--browser",
        help="Browser to drive: chrome or edge. Prompts when omitted.",
    ),
    profile: Path = typer.Option(
        Path("./profile"), "--profile", help="Persistent browser user-data-dir."
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
    no_diff: bool = typer.Option(
        False,
        "--no-diff/--diff",
        help="Disable/enable the automatic dom_diff on interactive commands.",
    ),
    diff_max_tokens: int = typer.Option(
        1000, "--diff-max-tokens", help="Budget for dom_diff, in tokens."
    ),
    settle_timeout: float = typer.Option(
        5.0,
        "--settle-timeout",
        help="Seconds to wait for a page to finish rendering after a navigation "
        "before snapshotting it.",
    ),
    settle_network_grace: float = typer.Option(
        0.5,
        "--settle-network-grace",
        help="Seconds of network silence that count as idle. Raise it for an app "
        "that pauses between chained requests; the gap looks like being finished.",
    ),
    no_frames: bool = typer.Option(
        False,
        "--no-frames/--frames",
        help="Stop reading inside iframes. Frames cost nothing on a page that has "
        "none, so turn this off only for a page whose frames are all ads.",
    ),
    max_frames: int = typer.Option(
        8, "--max-frames", help="Most frames to read per snapshot."
    ),
    max_frame_depth: int = typer.Option(
        2, "--max-frame-depth", help="How far to descend into nested frames."
    ),
    no_shots: bool = typer.Option(
        False,
        "--no-shots",
        help="Stop capturing the screenshot beside each logged command.",
    ),
    shot_quality: int = typer.Option(
        60, "--shot-quality", help="JPEG quality for captured frames (1-100)."
    ),
    shot_width: int = typer.Option(
        1280, "--shot-width", help="Downscale captured frames to this width."
    ),
    shots_max_mb: float = typer.Option(
        200.0,
        "--shots-max-mb",
        help="Stop capturing once one session's frames reach this size.",
    ),
) -> None:
    """Open Chrome or Edge and listen for commands until told to shut down."""
    import uvicorn

    from .browser import BrowserSession
    from .recorder import SessionRecorder
    from .server import create_app

    browser = _choose_browser(browser)
    session = BrowserSession(
        profile=profile,
        browser=browser,
        headless=headless,
        action_timeout=action_timeout,
        diff_enabled=not no_diff,
        diff_max_tokens=diff_max_tokens,
        settle_timeout=settle_timeout,
        settle_network_grace=settle_network_grace,
        frames_enabled=not no_frames,
        max_frames=max_frames,
        max_frame_depth=max_frame_depth,
    )
    typer.echo(f"starting {browser} (profile: {session.profile})")
    session.start()

    recorder = None if no_log else SessionRecorder(log_dir, max_shot_mb=shots_max_mb)
    if recorder is not None:
        typer.echo(f"recording session {recorder.session_id} -> {recorder.path}")
        if not no_shots:
            typer.echo(f"capturing frames -> {recorder.shots_dir}")

    holder: dict[str, Any] = {}
    application = create_app(
        session,
        request_stop=lambda: holder["server"].__setattr__("should_exit", True),
        recorder=recorder,
        shots=not no_shots,
        shot_quality=shot_quality,
        shot_width=shot_width,
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
    elements: bool = typer.Option(
        False, "--elements", help="Add the element diff to the text diff."
    ),
    removed: bool = typer.Option(
        False, "--removed", help="List the text that left the screen, not just count it."
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
    if elements:
        payload["element_diff"] = True
    if removed:
        payload["include_removed"] = True
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
def diff(
    reset: bool = typer.Option(
        False, "--reset", help="Set the baseline to the current page instead."
    ),
    text_only: bool = typer.Option(
        False, "--text-only", help="Skip the element diff and return text alone."
    ),
    added_only: bool = typer.Option(
        False, "--added-only", help="Count removed text instead of listing it."
    ),
    max_tokens: int = typer.Option(
        1000, "--max-tokens", help="Element diff budget, in tokens."
    ),
    port: int = _port_option(),
) -> None:
    """Diff the current page against the last known state."""
    payload = {"op": "diff"}
    if reset:
        payload["reset"] = True
    if text_only:
        payload["element_diff"] = False
    if added_only:
        payload["include_removed"] = False
    if max_tokens != 1000:
        payload["max_tokens"] = max_tokens
    _call(port, "/command", payload)


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
def mcp(
    api: str = typer.Option(
        "http://127.0.0.1:8765", "--api", help="Where the toolkit server is listening."
    ),
) -> None:
    """Speak MCP on stdin/stdout, forwarding to a running toolkit server.

    Meant to be spawned by an MCP client, not run by hand. It owns nothing:
    `abt serve` keeps the browser, so this can come and go with your editor
    while the session, tabs and logins stay put.
    """
    from . import mcp as mcp_module

    mcp_module.serve(api)


@app.command()
def shutdown(port: int = _port_option()) -> None:
    """Close the browser and stop the server."""
    _call(port, "/command", {"op": "shutdown"})


@messenger.command("send")
def messenger_send(
    message: str = typer.Argument("", help="The message. Write mentions as @Name."),
    thread: str = typer.Option(..., "--thread", "-t", help="Thread URL."),
    mention: list[str] = typer.Option(
        [], "--mention", "-m", help="Turn @Name in the message into a real mention."
    ),
    attach: list[str] = typer.Option(
        [], "--attach", "-a", help="A local path or an http(s) link. Repeatable."
    ),
    reply_to: Optional[str] = typer.Option(
        None, "--reply-to", help="Substring of the message you are answering."
    ),
    reply_index: Optional[int] = typer.Option(
        None, "--reply-index", help="Index of that message instead; -1 is the last."
    ),
    background: bool = typer.Option(
        False, "--async", help="Queue it in a new tab and return a job id."
    ),
    no_confirm: bool = typer.Option(
        False,
        "--no-confirm-attachments",
        help="Skip the preview wait, for files Messenger stages invisibly.",
    ),
    port: int = _port_option(),
) -> None:
    """Send a message, with mentions, attachments, and replies."""
    if reply_to is not None and reply_index is not None:
        typer.secho("supply --reply-to or --reply-index, not both", fg="red", err=True)
        raise typer.Exit(2)

    payload: dict[str, Any] = {"thread_url": thread, "message": message}
    if mention:
        payload["mentions"] = list(mention)
    if attach:
        payload["attachments"] = list(attach)
    if reply_to is not None:
        payload["reply_to"] = reply_to
    if reply_index is not None:
        payload["reply_to"] = reply_index
    if no_confirm:
        payload["confirm_attachments"] = False
    path = "/messenger/sendmessage/async" if background else "/messenger/sendmessage"
    _call(port, path, payload)


@messenger.command("threads")
def messenger_threads(
    url: Optional[str] = typer.Option(
        None, "--url", help="Navigate here first. Omit to read the sidebar on screen."
    ),
    limit: int = typer.Option(50, "--limit"),
    port: int = _port_option(),
) -> None:
    """List every thread in the sidebar."""
    query = {"limit": limit}
    if url:
        query["url"] = url
    _call(port, f"/messenger/threads?{urlencode(query)}", method="GET")


@messenger.command("read")
def messenger_read(
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Thread URL. Omit to read the open thread."
    ),
    limit: int = typer.Option(50, "--limit"),
    new: bool = typer.Option(
        False, "--new", help="Only what arrived since the last read of this thread."
    ),
    reset: bool = typer.Option(
        False, "--reset", help="Forget the cursor, so everything counts as new."
    ),
    port: int = _port_option(),
) -> None:
    """Read a thread's messages."""
    query: dict[str, Any] = {"limit": limit}
    if thread:
        query["thread_url"] = thread
    if new:
        query["since_last"] = "true"
    if reset:
        query["reset"] = "true"
    _call(port, f"/messenger/messages?{urlencode(query)}", method="GET")


@messenger.command("jobs")
def messenger_jobs(
    job_id: Optional[str] = typer.Argument(None, help="A job id. Omit to list all."),
    port: int = _port_option(),
) -> None:
    """Check how a queued send went."""
    suffix = f"/{job_id}" if job_id else ""
    _call(port, f"/messenger/jobs{suffix}", method="GET")


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
