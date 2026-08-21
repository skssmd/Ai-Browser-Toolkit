"""`abt` -- starts the server, and acts as a thin HTTP client for it.

Every subcommand other than `serve` is a plain HTTP call, so anything the CLI
can do, curl can do too.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import typer

from . import paths

app = typer.Typer(add_completion=False, help="Selenium browser API for AI agents.")
messenger = typer.Typer(add_completion=False, help="Send and read on messenger.com.")
app.add_typer(messenger, name="messenger")
autostart_app = typer.Typer(
    add_completion=False, help="Start the server at login. Opt in, never automatic."
)
app.add_typer(autostart_app, name="autostart")
guidelines_app = typer.Typer(
    add_completion=False,
    help="Site playbooks. Nothing fetched is used until you say so.",
)
app.add_typer(guidelines_app, name="guidelines")

DEFAULT_PORT = 8765
HOST = "127.0.0.1"


def _version_callback(value: bool) -> None:
    if not value:
        return
    from importlib.metadata import PackageNotFoundError, version

    # paths.DIST_NAME, not a literal. The distribution was renamed to
    # ai-browser-toolkit when PyPI rejected the old spelling, and a literal
    # here survived that rename to fail on every channel at once -- this is
    # the lookup `abt --version` depends on, and `abt --version` is what the
    # smoke test, the Inno verification and the Homebrew test block all run.
    # A test asserts DIST_NAME equals pyproject's name.
    try:
        typer.echo(version(paths.DIST_NAME))
    except PackageNotFoundError:
        # Running from a source tree with nothing installed.
        typer.echo("unknown (not installed)")
    raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the version and exit.",
    ),
) -> None:
    """Browser API for AI agents, over HTTP.

    `--version` is eager so it answers before any subcommand is resolved --
    every packaging channel's smoke test is `abt --version`, and it has to
    work on a machine with no server running and no browser installed.
    """


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
        None,
        "--profile",
        help="Persistent browser user-data-dir. Defaults to this install's "
        "own per-user directory, or ./profiles/default inside a checkout.",
    ),
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p", help="Port to listen on."),
    headless: bool = typer.Option(False, "--headless", help="Run without a window."),
    start_browser: bool = typer.Option(
        False,
        "--start-browser/--no-start-browser",
        help="Launch the browser at startup instead of waiting for a "
        "browser_start command. Off by default: the server is useful "
        "immediately, and Chrome on a persistent profile can take two minutes.",
    ),
    action_timeout: float = typer.Option(
        5.0, "--action-timeout", help="Seconds to wait for an element before failing."
    ),
    log_dir: Path = typer.Option(
        None,
        "--log-dir",
        help="Where session logs are written. Defaults to this install's own "
        "per-user directory, or ./logs inside a checkout.",
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
    engine: str = typer.Option(
        "playwright",
        "--engine",
        help="Which driver backs the browser: selenium (default) or playwright. "
        "Both answer every op identically -- the whole suite passes on each -- "
        "so this changes what is underneath, never what a caller sees. "
        "Playwright needs its optional extra installed; see the README.",
    ),
) -> None:
    """Open Chrome or Edge and listen for commands until told to shut down."""
    import uvicorn

    from .browser import BrowserSession
    from .recorder import SessionRecorder
    from .server import create_app

    # Typer evaluates option defaults once, at definition time, which would
    # freeze whatever the working directory was at import. Resolve here.
    profile = profile or paths.default_profile()
    log_dir = log_dir or paths.default_log_dir()

    # Said once per install, to stderr so it can never contaminate a caller
    # parsing stdout. pip, Homebrew, the AUR and the deb all install without
    # asking anything; this is the only place they get to mention autostart.
    marker = paths.first_run_marker()
    if marker is not None and not marker.exists():
        typer.echo(
            "Tip: to start this server automatically at every logon, run\n"
            "    abt autostart install --browser chrome\n"
            "It is opt-in and user-level; `abt autostart uninstall` removes it.",
            err=True,
        )
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")

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
        engine=engine,
    )
    if start_browser:
        typer.echo(f"starting {browser} via {engine} (profile: {session.profile})")
        session.start()
    else:
        typer.echo(
            f"no browser running (default: {browser}, profile: {session.profile})"
        )
        typer.echo('start one with {"op": "browser_start"} or POST /browser/start')

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


def _healthy(base: str) -> bool:
    try:
        return httpx.get(f"{base}/health", timeout=3).json().get("ok") is True
    except Exception:
        return False


@app.command()
def up(
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p", help="Port to listen on."),
    browser: str = typer.Option(
        None, "--browser", help="Default browser for later browser_start calls."
    ),
    profile: Optional[Path] = typer.Option(None, "--profile"),
    headless: bool = typer.Option(False, "--headless"),
    wait: float = typer.Option(
        20.0, "--wait", help="Seconds to wait for the server to answer /health."
    ),
) -> None:
    """Start the server if it is not already up, and return immediately.

    Never blocks: the server is spawned so that it belongs to no job object of
    this process, which is what `abt serve` in a background job could not
    manage. Safe to run at any time -- it no-ops when a server already answers.
    """
    import time

    from .proc import spawn_detached

    base = f"http://{HOST}:{port}"
    if _healthy(base):
        typer.echo(f"[abt] already up on {HOST}:{port}")
        raise typer.Exit(0)

    repo = Path(__file__).resolve().parent.parent.parent
    suffix = "" if port == DEFAULT_PORT else f"-{port}"
    # --browser is always passed, never left to be prompted for. `serve` only
    # prompts when stdin is a tty, and a WMI-spawned process has a console, so
    # omitting it parks the server on a prompt nobody can answer.
    argv = [
        sys.executable, "-m", "abt.cli", "serve",
        "--port", str(port),
        "--browser", browser or "chrome",
    ]
    if profile:
        argv += ["--profile", str(profile)]
    if headless:
        argv += ["--headless"]

    mechanism = spawn_detached(
        argv, repo, repo / f"server{suffix}.log", repo / f"server{suffix}.err"
    )
    typer.echo(f"[abt] launched via {mechanism}; waiting for {base}/health")

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _healthy(base):
            typer.echo(f"[abt] up on {HOST}:{port}")
            raise typer.Exit(0)
        time.sleep(0.5)

    typer.secho(
        f"[abt] no answer from {base}/health within {wait}s; "
        f"check {repo / f'server{suffix}.err'}",
        fg="red",
        err=True,
    )
    raise typer.Exit(1)


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
def doctor(
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output."),
    print_browser: bool = typer.Option(
        False,
        "--print-browser",
        help="Print just the browser name and nothing else. For the Windows "
        "installer, whose Pascal has no JSON parser.",
    ),
    install_browser: bool = typer.Option(
        False,
        "--install-browser",
        help="Install Google Chrome with this platform's package manager. "
        "Runs nothing on Linux, where it would need root -- prints the "
        "command instead.",
    ),
) -> None:
    """Check the one thing this toolkit needs and cannot carry: a browser."""
    from . import doctor as doc

    info = doc.report()

    if install_browser and not info["browsers"]:
        plan = doc.install_plan(info["platform"])
        typer.echo(plan.message)
        if plan.run and plan.argv:
            subprocess.run(plan.argv, check=False)
            info = doc.report()

    if print_browser:
        typer.echo(info["default_browser"] or "")
    elif json_out:
        typer.echo(json.dumps(info, indent=2))
    else:
        if info["browsers"]:
            for found in info["browsers"]:
                typer.echo(f"  {found['name']:<7} {found['path']}")
            typer.echo(f"\nabt will use: {info['default_browser']}")
        else:
            typer.echo("No supported browser found. This toolkit drives an")
            typer.echo("existing Google Chrome or Microsoft Edge and bundles neither.")
            typer.echo("\n" + doc.install_plan(info["platform"]).message)
        typer.echo(f"\nprofile: {info['profile']}")
        if not info["profile_writable"]:
            typer.echo("  WARNING: that directory is not writable.")

    raise typer.Exit(0 if info["browsers"] else 1)


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




# --- autostart ----------------------------------------------------------------


@autostart_app.command("install")
def autostart_install(
    browser: str = typer.Option(
        "chrome", "--browser", help="Browser to drive: chrome or edge."
    ),
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p", help="Port to listen on."),
    profile: Path = typer.Option(
        None,
        "--profile",
        help="Persistent browser user-data-dir. Defaults to this install's "
        "own per-user directory, or ./profiles/default inside a checkout.",
    ),
    log_dir: Path = typer.Option(
        None,
        "--log-dir",
        help="Where session logs are written. Defaults to this install's own "
        "per-user directory, or ./logs inside a checkout.",
    ),
    engine: str = typer.Option(
        "playwright", "--engine", help="Driver backing the browser."
    ),
    headless: bool = typer.Option(False, "--headless", help="Run without a window."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be installed and change nothing. Worth doing "
        "first: the entry runs at every logon, so the command it holds is "
        "worth reading before it is written.",
    ),
) -> None:
    """Run the server at every login.

    `--browser` is required rather than prompted, and every path is resolved to
    an absolute one, because a logon entry has neither a terminal to answer a
    prompt nor a working directory to resolve against.
    """
    from . import autostart as auto

    profile = profile or paths.default_profile()
    log_dir = log_dir or paths.default_log_dir()

    try:
        spec = auto.plan(
            port=port,
            browser=_choose_browser(browser),
            profile=profile,
            log_dir=log_dir,
            engine=engine,
            headless=headless,
        )
    except auto.AutostartError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)

    typer.echo(f"{spec.kind}: {spec.name}")
    if spec.path:
        typer.echo(f"  file    {spec.path}")
    typer.echo("  runs    " + " ".join(spec.argv))
    for note in spec.notes:
        typer.echo(f"  note    {note}")

    if dry_run:
        typer.echo("\ndry run: nothing was written.")
        return
    try:
        auto.install(spec)
    except auto.AutostartError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)
    typer.echo("\ninstalled. It will start at your next login.")


@autostart_app.command("uninstall")
def autostart_uninstall() -> None:
    """Remove the login entry. Not an error when there is none."""
    from . import autostart as auto

    try:
        result = auto.uninstall()
    except auto.AutostartError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)
    typer.echo("removed." if result["removed"] else "nothing to remove.")


@autostart_app.command("status")
def autostart_status() -> None:
    """Whether a login entry exists. Starts nothing."""
    from . import autostart as auto

    try:
        info = auto.status()
    except auto.AutostartError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)
    typer.echo(f"{info['kind']}: {info['name']}")
    typer.echo(f"  installed  {info['installed']}")
    if "active" in info:
        typer.echo(f"  active     {info['active']}")
    if info.get("path"):
        typer.echo(f"  file       {info['path']}")


if __name__ == "__main__":
    app()


# -- guidelines ------------------------------------------------------------
#
# Two consents, deliberately separate. Pulling downloads text; using it means
# an agent follows those instructions. A single prompt would let "yes, fetch
# it so I can look" mean "yes, act on whatever it says".


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        # Non-interactive: refuse rather than assume. `abt serve` is routinely
        # launched detached, and a prompt nobody sees must not default to
        # trusting remote instructions.
        typer.echo("not interactive; re-run with --yes to confirm", err=True)
        return False
    return typer.confirm(question, default=False)


@guidelines_app.command("list")
def guidelines_list() -> None:
    """What this machine holds, and where each came from."""
    from . import guidelines as g

    held = g.installed()
    if not held:
        typer.echo("no site playbooks installed")
    for entry in held.values():
        line = f"  {entry['domain']:<24} v{entry['version']:<4} {entry['source']}"
        if entry.get("pending_version"):
            line += f"  (v{entry['pending_version']} pulled, not trusted)"
        typer.echo(line)

    general = g.general()
    if general:
        typer.echo("\nshipped with the toolkit:")
        for name in general:
            typer.echo(f"  {name}")


@guidelines_app.command("show")
def guidelines_show(
    name: str = typer.Argument(..., help="domain/file, or a shipped playbook's name."),
    pending: bool = typer.Option(
        False, "--pending", help="Read an untrusted copy. Prints a warning."
    ),
) -> None:
    """Print a playbook."""
    from . import guidelines as g

    try:
        text = g.read(name, allow_pending=pending)
    except KeyError:
        typer.echo(f"no playbook named {name}", err=True)
        raise typer.Exit(1)
    if pending:
        typer.echo("# UNTRUSTED: pulled and not trusted. Do not act on this.\n", err=True)
    typer.echo(text)


@guidelines_app.command("lookup")
def guidelines_lookup(
    domain: str = typer.Argument(None, help="Domain to check. Omit to just report."),
    on: bool = typer.Option(False, "--on", help="Turn lookup back on."),
    off: bool = typer.Option(False, "--off", help="Stop checking the source entirely."),
) -> None:
    """Ask the source what it has for a domain, or switch lookup off."""
    from . import guidelines as g

    if on or off:
        g.set_config(guidelines_lookup=bool(on))
        typer.echo(f"guideline lookup {'on' if on else 'off'}")
        return

    if domain is None:
        typer.echo(f"lookup is {'on' if g.lookup_enabled() else 'off'}")
        return

    found = g.lookup(domain)
    if found is None:
        typer.echo(f"nothing for {domain}")
        raise typer.Exit(1)
    typer.echo(json.dumps(found, indent=2))


@guidelines_app.command("search")
def guidelines_search(
    query: str = typer.Argument(..., help="A domain, a URL, or just a word."),
) -> None:
    """Find playbooks. Exact domains answer with everything they have."""
    from . import guidelines as g

    found = g.search(query)
    if not found["matches"]:
        typer.echo(f"nothing found for {query!r}")
        raise typer.Exit(1)
    for match in found["matches"]:
        held = (
            f"held v{match['held_version']}"
            if match["held_version"] is not None
            else "not installed"
        )
        typer.echo(
            f"  {match['domain']:<24} v{match['version']:<4} "
            f"{', '.join(match['files']):<32} {held}"
            + ("  UPDATE" if match["update_available"] else "")
        )
    if not found["exact"]:
        typer.echo("\n(fuzzy match -- name the domain exactly for everything it has)")


@guidelines_app.command("pull")
def guidelines_pull(
    query: str = typer.Argument(..., help="A domain, a URL, or a word to search for."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip every prompt."),
    all_files: bool = typer.Option(
        False, "--all", help="Take every file the domain has without asking per file."
    ),
) -> None:
    """Fetch playbooks, reviewing each file before it is trusted."""
    from . import guidelines as g

    found = g.search(query)
    if not found["matches"]:
        typer.echo(f"nothing found for {query!r}", err=True)
        raise typer.Exit(1)

    if len(found["matches"]) > 1:
        typer.echo("several domains match:")
        for match in found["matches"]:
            typer.echo(f"  {match['domain']:<24} {', '.join(match['files'])}")
        typer.echo("\nname one of them exactly.")
        raise typer.Exit(1)

    match = found["matches"][0]
    domain = match["domain"]
    typer.echo(f"  domain    {domain}")
    typer.echo(f"  version   {match['version']}")
    typer.echo(f"  files     {', '.join(match['files'])}")
    typer.echo(f"  source    {g.source_url()}/{domain}")
    if match["held_version"] is not None:
        typer.echo(f"  you hold  v{match['held_version']}")

    if not _confirm("\nFetch these for review?", yes):
        raise typer.Exit(1)

    # Fetched into pending first, then reviewed one file at a time. Reviewing
    # before fetching is not possible without fetching, so the boundary that
    # matters is the one before *trusting*, not before downloading.
    g.pull(domain, only=match["files"])

    keep: list[str] = []
    for filename in match["files"]:
        name = f"{domain}/{Path(filename).stem}"
        typer.echo(f"\n----- {domain}/{filename} -----")
        typer.echo(g.read(name, allow_pending=True))
        if all_files or _confirm(f"\nTrust {domain}/{filename}?", yes):
            keep.append(filename)

    if not keep:
        typer.echo("\nnothing trusted; the fetched copies stay in pending")
        raise typer.Exit(0)

    if len(keep) == len(match["files"]):
        g.trust(domain)
    else:
        g.trust_files(domain, keep)
    typer.echo(f"\ntrusted: {', '.join(keep)}")


@guidelines_app.command("trust")
def guidelines_trust(
    domain: str = typer.Argument(..., help="Domain whose pulled playbook to trust."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the prompt."),
) -> None:
    """Promote a pulled playbook so agents may use it."""
    from . import guidelines as g

    if not _confirm(f"Trust the pulled playbook for {domain}?", yes):
        raise typer.Exit(1)
    try:
        g.trust(domain)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(f"trusted {domain}")


@guidelines_app.command("update")
def guidelines_update(
    force: bool = typer.Option(False, "--force", help="Ignore the once-a-day limit."),
) -> None:
    """Report playbooks whose source version is ahead of yours. Pulls nothing."""
    from . import guidelines as g

    behind = g.check_updates(force=True if force else False)
    if not behind:
        typer.echo("nothing to update")
        return
    for entry in behind:
        typer.echo(
            f"  {entry['domain']:<24} v{entry['held_version']} -> "
            f"v{entry['available_version']}"
        )
    typer.echo("\n`abt guidelines pull <domain>` to fetch and review one.")


@guidelines_app.command("save")
def guidelines_save(
    domain: str = typer.Argument(..., help="Domain the playbook is about."),
    file: Path = typer.Argument(..., help="Markdown file to save."),
    name: str = typer.Option(None, "--name", help="Store it under a different name."),
) -> None:
    """Add a playbook of your own. A pull never overwrites it."""
    from . import guidelines as g

    if not file.is_file():
        typer.echo(f"no such file: {file}", err=True)
        raise typer.Exit(1)
    target = g.save(domain, name or file.name, file.read_text(encoding="utf-8"))
    typer.echo(f"saved {target}")


@guidelines_app.command("submit")
def guidelines_submit(
    domain: str = typer.Argument(..., help="Domain whose local playbook to submit."),
) -> None:
    """Print what to run to open a pull request against the playbook repo."""
    from . import guidelines as g

    try:
        root, branch = g.submission_paths(domain)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    repo = g.repo_url()
    typer.echo(f"local playbook: {root}")
    typer.echo(f"\n  git clone {repo} playbooks && cd playbooks")
    typer.echo(f"  git checkout -b {branch}")
    typer.echo(f"  cp -r '{root}' {domain}")
    typer.echo(f'  git add {domain} && git commit -m "Add a playbook for {domain}"')
    typer.echo(f"  git push -u origin {branch}")
    typer.echo(f"\nthen open a pull request at {repo}/compare/{branch}?expand=1")
