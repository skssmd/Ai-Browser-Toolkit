"""Messenger: one call sends a message to a thread.

Nothing here is beyond the generic ops -- `goto`, clear the composer, unhide the
file input, type, press Enter. But the *order* matters, and getting it wrong
sends half a message: a stale draft glued to your text, or an Enter that fires
before the upload finished. `guidelines/messenger.md` is the long form of why.
This module is that sequence, verified, behind one POST.

Two shapes:
  send(session, req)            -- in the current tab, caller waits for the result
  send_in_new_tab(session, req) -- opens a tab, sends, closes it, restores focus

The second is what the background job runs, so a send never disturbs whatever
page the caller was looking at.
"""

from __future__ import annotations

import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .browser import BrowserSession
from .engine import BACKSPACE, CONTROL, ENTER, ActionChains, By, EngineError
from .ops.interact import UNHIDE_FILE_INPUT_JS
from .errors import OpError

# This endpoint types into whatever it finds and then presses Enter. Pointing it
# at an arbitrary page is a footgun, so it only drives the two hosts that serve
# Messenger threads.
ALLOWED_HOSTS = ("messenger.com", "facebook.com")

COMPOSER_CSS = (
    'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"]',
)
ARTICLE_CSS = 'div[role="article"]'
OPTION_CSS = '[role="listbox"] [role="option"]'
REPLY_CSS = '[aria-label*="Reply" i]'


# --- request ------------------------------------------------------------------


class SendMessage(BaseModel):
    """The body of POST /messenger/sendmessage."""

    model_config = ConfigDict(extra="forbid")

    thread_url: str
    """https://www.messenger.com/t/<id>/ or /e2ee/t/<id>/."""

    message: str = ""
    attachments: list[str] = Field(default_factory=list)
    """Local absolute paths, or http(s) links that get downloaded first."""

    mentions: list[str] = Field(default_factory=list)
    """Names to turn into real @-mentions. Each must appear in `message` as
    `@<name>`; that occurrence is typed through Messenger's suggestion popup
    instead of as plain text."""

    reply_to: int | str | None = None
    """Which message to reply to: a substring of it (the most recent match
    wins), or an index into the thread (negative counts from the end)."""

    background: bool = False
    """Send in a new tab, and answer before it finishes."""

    timeout: float = Field(default=30.0, gt=0, le=300)
    attachment_timeout: float = Field(default=60.0, gt=0, le=600)
    confirm_attachments: bool = True
    """Wait for one preview per attachment before sending. Turn it off only for
    file types Messenger stages without rendering anything."""

    allow_any_host: bool = False
    """Drive a page that is not Messenger. For testing against a mock thread."""

    @model_validator(mode="after")
    def _something_to_send(self):
        if not self.message.strip() and not self.attachments:
            raise ValueError("supply a message, attachments, or both")
        if not self.allow_any_host and not _host_allowed(self.thread_url):
            raise ValueError(
                f"thread_url must be on {' or '.join(ALLOWED_HOSTS)}, got "
                f"{urlparse(self.thread_url).hostname!r}"
            )
        return self


def _host_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def parse_send(data: Any) -> SendMessage:
    """Validate a request body, or raise OpError('invalid_op')."""
    if not isinstance(data, dict):
        raise OpError(
            "invalid_op", f"body must be an object, got {type(data).__name__}"
        )
    try:
        return SendMessage(**data)
    except ValidationError as exc:
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
        raise OpError("invalid_op", "invalid send: " + "; ".join(parts)) from exc


# --- message composition ------------------------------------------------------


def segments(message: str, mentions: list[str]) -> list[tuple[str, str]]:
    """Split a message into plain text and mention pieces, in order.

    `"hi @Alice and @Bob"` with `["Alice", "Bob"]` becomes text/mention/text/
    mention. Longest names are matched first so `@Ann` never wins inside
    `@Anna`.
    """
    if not message:
        return []
    if not mentions:
        return [("text", message)]

    names = sorted(set(mentions), key=len, reverse=True)
    out: list[tuple[str, str]] = []
    buffer = ""
    seen: set[str] = set()
    index = 0
    while index < len(message):
        if message[index] == "@":
            hit = next(
                (n for n in names if message.startswith("@" + n, index)), None
            )
            if hit is not None:
                if buffer:
                    out.append(("text", buffer))
                    buffer = ""
                out.append(("mention", hit))
                seen.add(hit)
                index += len(hit) + 1
                continue
        buffer += message[index]
        index += 1
    if buffer:
        out.append(("text", buffer))

    missing = [n for n in mentions if n not in seen]
    if missing:
        raise OpError(
            "invalid_op",
            f"mentions {missing} do not appear in the message; write them as "
            f"'@{missing[0]}' where you want them to land",
        )
    return out


# --- attachments --------------------------------------------------------------


def resolve_attachments(links: list[str]) -> list[dict]:
    """Turn every link into a local file Selenium can hand to the file input.

    A URL cannot be attached directly -- `send_keys` on a file input takes a
    path -- so remote links are downloaded to a temp file first.
    """
    resolved = []
    scratch: Path | None = None
    for link in links:
        if link.lower().startswith(("http://", "https://")):
            if scratch is None:
                scratch = Path(tempfile.mkdtemp(prefix="abt-attach-"))
            path = _download(link, scratch)
        else:
            path = Path(link).expanduser()
            if not path.is_absolute():
                path = path.resolve()
            if not path.is_file():
                raise OpError("invalid_op", f"no such file to attach: {path}")
        resolved.append(
            {"link": link, "path": str(path), "bytes": path.stat().st_size}
        )
    return resolved


def _download(link: str, scratch: Path) -> Path:
    name = Path(unquote(urlparse(link).path)).name or "attachment"
    path = scratch / name
    try:
        with httpx.stream("GET", link, timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            with path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        raise OpError(
            "navigation_failed", f"could not download attachment {link!r}: {exc}"
        ) from exc
    return path


# --- page plumbing ------------------------------------------------------------

# Shared with the generic `input` op, which needs the same trick for any page
# that hides its upload behind a custom control.
_UNHIDE_JS = UNHIDE_FILE_INPUT_JS

# One probe for both halves of "is the upload done": how many attachment
# previews are staged, and is anything still spinning.
_PREVIEW_JS = """
// Every count is visibility-gated. Messenger keeps dismiss controls in the DOM
// while they are hidden -- the "Remove reply" button is one -- and counting
// those means the preview count never falls back to zero, so a send that
// worked perfectly never looks finished.
const visible = (el) => el.getClientRects().length > 0;
const seen = (css) => Array.from(document.querySelectorAll(css)).filter(visible).length;
const blobs = seen('img[src^="blob:"]');
const chips = seen('[aria-label*="Remove" i]');
const spinners = seen('[role="progressbar"], [class*="spinner" i]');
return {previews: Math.max(blobs, chips), spinners: spinners};
"""

_TEXT_JS = "return (arguments[0].innerText || '').trim();"


def _visible(elements) -> list:
    out = []
    for element in elements:
        try:
            if element.is_displayed():
                out.append(element)
        except EngineError:
            continue
    return out


def _composer(session: BrowserSession, timeout: float):
    """The contenteditable the thread types into.

    Messenger has no id, name, or stable class here -- role=textbox on a
    contenteditable div is the only durable handle, with a bare contenteditable
    as the fallback for the E2EE layout.
    """
    deadline = time.monotonic() + timeout
    while True:
        for css in COMPOSER_CSS:
            found = _visible(session.driver.find_elements(By.CSS, css))
            if found:
                return found[0]
        if time.monotonic() >= deadline:
            raise OpError(
                "element_not_found",
                f"no message composer appeared within {timeout}s; is "
                f"{session.driver.current_url!r} really an open thread?",
            )
        time.sleep(0.25)


def _clear(session: BrowserSession, composer) -> None:
    """Empty the composer.

    `input` appends, so a stale draft would end up glued to the message. React
    ignores execCommand and clear() raises on a contenteditable; real
    keystrokes are the only thing that works.
    """
    ActionChains(session.driver).click(composer).key_down(CONTROL).send_keys(
        "a"
    ).key_up(CONTROL).send_keys(BACKSPACE).perform()
    if session.driver.execute_script(_TEXT_JS, composer):
        raise OpError(
            "not_interactable",
            "the composer still holds a draft after ctrl+a backspace; refusing "
            "to type on top of it",
        )


def _attach(session: BrowserSession, files: list[dict], request: SendMessage) -> int:
    """Stage files on the hidden file input and wait for them to finish.

    The paperclip opens a native dialog WebDriver cannot see. The input itself
    is the only way in -- and send_keys on it is what fires React's change
    handler, which no amount of JS DataTransfer will do.
    """
    inputs = session.driver.find_elements(By.CSS, "input[type=file]")
    if not inputs:
        raise OpError(
            "element_not_found", "this page has no file input to attach through"
        )
    field = inputs[0]
    session.driver.execute_script(_UNHIDE_JS, field)
    try:
        field.send_keys("\n".join(f["path"] for f in files))
    except EngineError as exc:
        raise OpError(
            "not_interactable", f"could not stage attachments: {exc.msg or exc}"
        ) from exc

    if not request.confirm_attachments:
        return 0

    wanted = len(files)
    deadline = time.monotonic() + request.attachment_timeout
    previews = 0
    while time.monotonic() < deadline:
        state = session.driver.execute_script(_PREVIEW_JS)
        previews = int(state["previews"])
        if previews >= wanted and not state["spinners"]:
            return previews
        time.sleep(0.5)
    raise OpError(
        "timeout",
        f"only {previews} of {wanted} attachments were staged after "
        f"{request.attachment_timeout}s; nothing was sent, so the message is "
        "still a draft you can retry",
    )


def _type(session: BrowserSession, composer, pieces: list[tuple[str, str]]) -> list[str]:
    """Type the message, routing mentions through the suggestion popup."""
    mentioned = []
    for kind, value in pieces:
        if kind == "text":
            composer.send_keys(value)
            continue
        composer.send_keys("@" + value)
        mentioned.append(_accept_mention(session, value))
    return mentioned


def _accept_mention(session: BrowserSession, name: str, timeout: float = 8.0) -> str:
    """Pick `name` out of the mention popup.

    Clicked, not Entered: Enter takes whichever suggestion is highlighted, and
    if the popup never opened it sends the half-written message instead.
    """
    wanted = name.strip().lower()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        options = _visible(session.driver.find_elements(By.CSS, OPTION_CSS))
        for option in options:
            try:
                label = (option.text or "").strip()
                if wanted in label.lower():
                    option.click()
                    return label
            except EngineError:
                continue
        time.sleep(0.2)
    raise OpError(
        "element_not_found",
        f"no mention suggestion matched @{name}; nothing was sent, so the "
        "message is still a draft",
    )


def _article(session: BrowserSession, reply_to: int | str):
    articles = session.driver.find_elements(By.CSS, ARTICLE_CSS)
    if not articles:
        raise OpError("element_not_found", "this thread shows no messages to reply to")
    if isinstance(reply_to, int):
        try:
            return articles[reply_to]
        except IndexError:
            raise OpError(
                "element_not_found",
                f"no message at index {reply_to}; the thread shows {len(articles)}",
            ) from None
    wanted = reply_to.lower()
    matches = [a for a in articles if wanted in (a.text or "").lower()]
    if not matches:
        raise OpError(
            "element_not_found",
            f"no visible message contains {reply_to!r}; scroll the thread back "
            "first, or reply by index",
        )
    return matches[-1]  # the most recent match is the one you meant


def _open_reply(session: BrowserSession, reply_to: int | str, timeout: float) -> str:
    """Arm the composer to reply to one message.

    The action bar only exists while the row is hovered, so the hover is part of
    the click, not decoration.
    """
    article = _article(session, reply_to)
    quoted = (article.text or "").strip().replace("\n", " ")[:200]
    session.driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", article
    )
    ActionChains(session.driver).move_to_element(article).perform()

    deadline = time.monotonic() + timeout
    while True:
        for scope in (article, _parent(session, article)):
            if scope is None:
                continue
            buttons = _visible(scope.find_elements(By.CSS, REPLY_CSS))
            if buttons:
                buttons[0].click()
                return quoted
        if time.monotonic() >= deadline:
            raise OpError(
                "element_not_found",
                f"no reply control appeared on {quoted[:60]!r} within {timeout}s",
            )
        time.sleep(0.25)


def _parent(session: BrowserSession, element):
    try:
        return session.driver.execute_script("return arguments[0].parentElement;", element)
    except EngineError:
        return None


def _count_articles(session: BrowserSession) -> int:
    return len(session.driver.find_elements(By.CSS, ARTICLE_CSS))


def _in_thread(session: BrowserSession, needle: str) -> bool:
    return bool(
        session.driver.execute_script(
            "return Array.from(document.querySelectorAll(arguments[0]))"
            ".some(el => (el.innerText || '').includes(arguments[1]));",
            ARTICLE_CSS,
            needle,
        )
    )


# --- the send ------------------------------------------------------------------


def send(session: BrowserSession, request: SendMessage) -> dict:
    """Open the thread, compose, and send. Raises OpError on any failure.

    Every failure mode leaves the message unsent rather than half sent: the
    attachment wait, the mention popup, and the composer check all raise
    *before* Enter is pressed.
    """
    started = time.perf_counter()
    files = resolve_attachments(request.attachments)
    pieces = segments(request.message, request.mentions)

    session.goto(request.thread_url)
    composer = _composer(session, request.timeout)

    replied_to = None
    if request.reply_to is not None:
        replied_to = _open_reply(session, request.reply_to, request.timeout)
        composer = _composer(session, request.timeout)

    _clear(session, composer)

    staged = 0
    if files:
        staged = _attach(session, files, request)
        # Staging re-renders the composer area; the old handle may be detached.
        composer = _composer(session, request.timeout)

    mentioned = _type(session, composer, pieces)

    before = _count_articles(session)
    composer.click()
    composer.send_keys(ENTER)
    # Look for the longest plain stretch of the message, not the message: what
    # lands in the thread is "@Yaleed Haque", not the "@Yaleed" that was typed.
    needle = max(
        (value.strip() for kind, value in pieces if kind == "text"), key=len, default=""
    )[:60]
    confirmed = _confirm(session, request, before, len(files), needle)

    return {
        "thread_url": session.driver.current_url,
        "sent": True,
        "message": request.message,
        "mentions": mentioned,
        "attachments": files,
        "attachments_staged": staged,
        "replied_to": replied_to,
        "confirmed": confirmed,
        "articles_before": before,
        "articles_after": _count_articles(session),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _confirm(
    session: BrowserSession,
    request: SendMessage,
    before: int,
    attachments: int,
    needle: str = "",
) -> bool:
    """Wait for Messenger to accept the send.

    An emptied composer with its previews gone is the signal; the message
    showing up in the thread is the confirmation. Confirmation is by content,
    not by counting rows -- Messenger virtualises a long thread, so the number
    of rows on screen can *drop* while a message is being added to it.

    A message that never appears is reported, not raised: it may just be a slow
    upload. A composer that never empties is raised, because that means the
    send did not happen at all.
    """
    deadline = time.monotonic() + request.timeout
    composer_clear = False
    while time.monotonic() < deadline:
        composer = _composer(session, 1.0)
        text = session.driver.execute_script(_TEXT_JS, composer)
        previews = int(session.driver.execute_script(_PREVIEW_JS)["previews"])
        if not text and (not attachments or not previews):
            composer_clear = True
            if needle:
                if _in_thread(session, needle):
                    return True
            elif _count_articles(session) > before:
                return True
        time.sleep(0.3)

    if not composer_clear:
        raise OpError(
            "timeout",
            f"the composer still held the message after {request.timeout}s; it "
            "was not sent",
        )
    return False


def send_in_new_tab(session: BrowserSession, request: SendMessage) -> dict:
    """Send from a scratch tab, then close it and go back where we were."""
    origin = session.active_tab
    tab_id = session.new_tab(None, activate=True)
    try:
        result = send(session, request)
        result["tab_id"] = tab_id
        return result
    finally:
        try:
            session.close_tab(tab_id)
        except OpError:
            pass
        try:
            session.switch_tab(origin)
        except OpError:
            pass


# --- reading ------------------------------------------------------------------

# Sidebar rows are anchors to /t/<id>/ or /e2ee/t/<id>/. innerText carries the
# name, the preview, and the timestamp on separate lines -- no stable classes to
# key off, so the lines are the structure.
_THREADS_JS = """
const seen = new Set();
const out = [];
for (const a of document.querySelectorAll('a[href*="/t/"]')) {
  if (a.getClientRects().length === 0) continue;
  // The rail's own links (Chats, Marketplace, Requests, Archive) carry the
  // open thread's id too. Only a bare /t/<id>/ is a conversation.
  if (!/^\\/(e2ee\\/)?t\\/[^\\/]+\\/?$/.test(new URL(a.href).pathname)) continue;
  // A conversation is a row in the list. The rail's own links (Chats,
  // Marketplace, Archive) point at whichever thread is open, so they must be
  // dropped *before* the dedupe or they claim that thread's slot and the real
  // row gets skipped as a duplicate.
  const row = a.closest('[role="row"], [role="listitem"], li');
  if (!row) continue;
  const lines = (row.innerText || '')
    .split('\\n').map(s => s.trim()).filter(Boolean);
  if (!lines.length) continue;
  const url = a.href.split('?')[0];
  if (seen.has(url)) continue;
  seen.add(url);
  out.push({
    url: url,
    e2ee: url.includes('/e2ee/'),
    name: lines[0] || (a.getAttribute('aria-label') || '').trim(),
    preview: lines.length > 2 ? lines.slice(1, -1).join(' ') : (lines[1] || ''),
    time: lines.length > 1 ? lines[lines.length - 1] : '',
    unread: row.querySelectorAll('[aria-label*="unread" i]').length > 0,
  });
  if (out.length >= arguments[0]) break;
}
return out;
"""

_MESSAGES_JS = """
const out = [];
for (const el of document.querySelectorAll('div[role="article"]')) {
  const text = (el.innerText || '').trim();
  if (text) out.push({text: text, label: el.getAttribute('aria-label') || ''});
}
return out.slice(-arguments[0]);
"""

_SENT_BY = re.compile(
    r"Message sent\s+(?:at\s+)?([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?)\s*by\s+([^:\n]+)",
    re.IGNORECASE,
)


def list_threads(
    session: BrowserSession, limit: int = 50, timeout: float = 15.0
) -> dict:
    """The sidebar: every visible thread with its preview, time, and URL.

    Waits for the list to render. Messenger answers `goto` long before the
    sidebar exists, so scraping it straight away reliably finds nothing.
    """
    deadline = time.monotonic() + timeout
    while True:
        rows = session.driver.execute_script(_THREADS_JS, limit) or []
        if rows or time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    return {"url": session.driver.current_url, "count": len(rows), "threads": rows}


def _parse_message(row: dict) -> dict:
    """Pull sender and time out of a row's text.

    A row reads roughly "<body>\\nMessage sent HH:MM by <name>: <body>" -- the
    body twice, once for the eye and once for a screen reader. Keep the first.
    """
    raw = row["text"]
    match = _SENT_BY.search(raw)
    body = raw.split("Message sent")[0].strip() or raw
    sender = match.group(2).strip() if match else None
    # The visible half opens with the sender's name and closes with the label
    # of the reply button that only exists on hover. Neither is the message.
    if sender and body.startswith(sender):
        body = body[len(sender) :].strip()
    body = re.sub(r"\s*Enter,?\s*$", "", body).strip()
    return {
        "text": body,
        "sender": match.group(2).strip() if match else None,
        "time": match.group(1).strip() if match else None,
        "raw": raw,
    }


def read_messages(
    session: BrowserSession,
    thread_url: str | None = None,
    limit: int = 50,
    since_last: bool = False,
    cursors: "MessageCursors | None" = None,
) -> dict:
    """The messages on screen, newest last.

    With `since_last`, only what arrived since the previous read of this thread
    -- the cheap way to poll a conversation without re-reading it every time.
    """
    if thread_url is not None:
        session.goto(thread_url)
        _composer(session, 20.0)
    rows = session.driver.execute_script(_MESSAGES_JS, limit) or []
    messages = [_parse_message(row) for row in rows]
    url = session.driver.current_url
    payload = {"url": url, "count": len(messages), "messages": messages}

    if since_last:
        if cursors is None:
            raise OpError("invalid_op", "this server has no message cursor store")
        new = set(cursors.advance(url, [m["raw"] for m in messages]))
        payload["messages"] = [m for m in messages if m["raw"] in new]
        payload["new"] = len(payload["messages"])
        payload["count"] = len(payload["messages"])
        payload["total_on_screen"] = len(messages)
    return payload


class MessageCursors:
    """What each thread looked like last time it was read.

    Keyed by URL path, so the fragment a hash router leaves behind never splits
    one conversation into two cursors.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, list[str]] = {}

    @staticmethod
    def key(url: str) -> str:
        parts = urlparse(url)
        return f"{parts.netloc}{parts.path}"

    def advance(self, url: str, rows: list[str]) -> list[str]:
        """Return the rows that are new, and remember the full set.

        Compared by content, not by index: Messenger trims the top of a long
        thread as it grows, so position tells you nothing.
        """
        key = self.key(url)
        with self._lock:
            previous = self._seen.get(key)
            self._seen[key] = list(rows)
        if previous is None:
            return list(rows)
        seen = set(previous)
        return [row for row in rows if row not in seen]

    def reset(self, url: str) -> None:
        with self._lock:
            self._seen.pop(self.key(url), None)


# --- background jobs ------------------------------------------------------------


class JobRegistry:
    """The state of fire-and-forget sends, newest last.

    In memory on purpose: a job outliving the browser that was sending it is
    meaningless, and the session log already has the durable record.
    """

    def __init__(self, limit: int = 100) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def create(self, request: SendMessage) -> dict:
        job = {
            "job_id": uuid.uuid4().hex[:12],
            "state": "queued",
            "thread_url": request.thread_url,
            "message": request.message,
            "attachments": len(request.attachments),
            "queued_at": _now(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job["job_id"]] = job
            for stale in list(self._jobs)[: max(0, len(self._jobs) - self.limit)]:
                del self._jobs[stale]
        return dict(job)

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(fields)

    def start(self, job_id: str) -> None:
        self._update(job_id, state="running", started_at=_now())

    def finish(self, job_id: str, result: dict) -> None:
        self._update(job_id, state="sent", finished_at=_now(), result=result)

    def fail(self, job_id: str, error: dict) -> None:
        self._update(job_id, state="failed", finished_at=_now(), error=error)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(job) for job in self._jobs.values()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
