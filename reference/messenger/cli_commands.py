"""Reference only: the `abt messenger` commands from src/abt/cli.py.

Nothing imports this. The group was registered beside the other sub-apps.
See README.md.
"""

messenger = typer.Typer(add_completion=False, help="Send and read on messenger.com.")
app.add_typer(messenger, name="messenger")


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


