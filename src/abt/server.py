"""HTTP surface. The server process is the command loop.

Every request runs in a session. Each session owns a lock, and commands within
a session run in order under it -- a driver is not thread-safe -- while
different sessions never wait on each other. The blocking work is pushed to a
threadpool so a long command never stalls the event loop -- `GET /status`
stays answerable meanwhile.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import __version__
from . import screencast as screencast_util
from . import shots as shots_util
from . import trace as trace_util
from .browser import NO_BROWSER_MESSAGE, BrowserSession
from .engine import EngineError
from .errors import OpError
from .ops import NO_HEALTH_CHECK, dispatch
from .ops.control import browser_state, session_status
from .recorder import (
    SessionRecorder,
    list_sessions,
    now_ms,
    read_events,
    shot_path,
    sites_index,
)
from .schema import OP_NAMES, op_signatures, parse_command
from .profiles import DEFAULT
from .sessions import NO_SESSIONS, Session, SingleSessionRegistry
from .tabs import OWN
from .viewer import VIEWER_HTML
from .app_ui import APP_HTML

# How long /status will wait for the browser before answering without it. A
# status check is a question about liveness, so it has to come back while the
# thing it describes is still busy -- see the route.
STATUS_TIMEOUT = 5.0


def ok(result: Any) -> dict:
    return {"ok": True, "result": result}


def fail(error: OpError, op_index: int = 0) -> dict:
    return {"ok": False, "error": error.to_dict(op_index)}


def _is_shutdown(item: Any) -> bool:
    return isinstance(item, dict) and item.get("op") == "shutdown"


# What a failure says when the browser really is gone, rather than the page or
# an element having refused something. Playwright reports it in the message.
_GONE = (
    "target closed", "has been closed", "browser closed", "connection closed",
    "browser has disconnected", "cannot schedule new futures", "event loop is closed",
    "driver process exited", "stopped answering",
)


def _unmapped(exc: Exception) -> OpError:
    """Give an exception nobody translated the least wrong type available.

    Everything used to land on `browser_dead`, which is the most expensive
    wrong answer the toolkit can give: its hint tells the caller to restart
    the browser -- and the app does it for them -- so an agent stops working on
    the page and starts working on the toolkit. Seen live: a colour input's
    "Malformed value" was reported as a dead browser five times in a row.

    Only a browser that really is gone keeps that type. A page or an element
    refusing something is `not_interactable`; a navigation under a running read
    is `stale_ref`; and a fault in the toolkit's own code -- a KeyError, say --
    is `internal_error`, which says the browser is fine and not to restart it.

    Ops should translate their own failures; this is the net under them.
    """
    from . import engine

    name = type(exc).__name__
    detail = f"{name}: {exc}"
    lowered = str(exc).lower()
    module = type(exc).__module__ or ""

    if "Timeout" in name:
        return OpError("timeout", detail)
    if "NoSuchWindow" in name or isinstance(exc, engine.NoSuchWindow):
        # A shared session whose last tab was released or taken over has no
        # page at all. The browser is fine; the session needs a tab.
        return OpError(
            "tab_not_found",
            f"this session has no tab to act on ({detail})",
            hint="Open one with tab_new, or tab_claim an unowned tab from tab_list.",
        )

    # The browser itself.
    if (
        isinstance(exc, (engine.DeadSession, ConnectionError, EOFError))
        or module.startswith(("httpx", "httpcore", "websockets"))
        or "TargetClosed" in name
        or any(marker in lowered for marker in _GONE)
    ):
        return OpError("browser_dead", detail)

    # The page changed under a running read: what it held is gone, not the browser.
    if isinstance(exc, engine.StaleElement) or "execution context was destroyed" in lowered:
        return OpError(
            "stale_ref",
            detail,
            hint=(
                "The page navigated or re-rendered while this ran, so what it was "
                "working on is gone. The browser is fine: look again (`find` or "
                "`get_text`) and retry."
            ),
        )
    if isinstance(exc, (engine.NoSuchElement, engine.NoSuchFrame)):
        return OpError("element_not_found", detail)
    if isinstance(exc, engine.ScriptError):
        return OpError("js_error", detail)

    # The page or an element refused the action. The browser is still running.
    if isinstance(exc, engine.EngineError):
        return OpError(
            "not_interactable",
            detail,
            hint=(
                "The browser refused that action; it is still running. Read the "
                "message for what it objected to, and try another way to act on "
                "the element."
            ),
        )

    # Anything else is a fault in the toolkit's own code. Keep the traceback:
    # the reply carries only its last line.
    import sys
    import traceback

    traceback.print_exception(exc, file=sys.stderr)
    return OpError("internal_error", detail)


# Ops that are safe to run again once the connection is re-attached: they carry
# everything they need, and depend on no page state a relaunch could have lost.
RETRY_AFTER_REATTACH = frozenset({"goto"})


def _after_dropped_connection(browser: BrowserSession, response: dict, op_index: int) -> dict:
    """Re-attach a session whose connection died mid-command.

    The command itself failed, and may or may not have taken effect, so it is
    reported rather than silently retried. If re-attaching is not possible the
    original error stands.
    """
    try:
        browser.reconnect()
    except Exception:
        return response
    return fail(
        OpError(
            "timeout",
            "the browser connection dropped while this ran, and has been "
            "re-established; it may or may not have completed",
            hint=(
                "Look at where the page is now (`get_text` or `status`), then run "
                "it again if it did not take effect. Your tabs are all still there."
            ),
        ),
        op_index,
    )


def _strip(item: Any) -> tuple[Any, str | None, str | None]:
    """Take the transport fields off one command, leaving the command."""
    if isinstance(item, dict) and ("session" in item or "token" in item):
        item = dict(item)
        return item, item.pop("session", None), item.pop("token", None)
    return item, None, None


def _transport(headers: Any, body: Any) -> tuple[str | None, str | None, Any]:
    """(session, token, body without them).

    `session` and `token` say where a command runs, not what it does, so they
    come off before validation -- the command models forbid unknown fields and
    would otherwise reject every routed command. Headers win, then the batch
    envelope, then the first command that names one.
    """
    name = headers.get("x-abt-session") or None
    token = headers.get("x-abt-token") or None
    if isinstance(body, dict) and "op" in body:
        item, s, t = _strip(body)
        return name or s, token or t, item
    envelope = isinstance(body, dict)
    items = (body.get("commands") or body.get("command_list")) if envelope else body
    if not isinstance(items, list):
        return name, token, body
    cleaned, named, tokens = [], [], []
    for item in items:
        item, s, t = _strip(item)
        cleaned.append(item)
        if s:
            named.append(s)
        if t:
            tokens.append(t)
    chosen = (
        name
        or (body.get("session") if envelope else None)
        or (named[0] if named else None)
    )
    stray = sorted({n for n in named if n != chosen})
    if stray:
        # A batch is one sequence in one session. Switching part way through
        # would take and drop different locks mid-batch, which destroys the
        # one thing a batch promises: nothing else ran in between.
        raise OpError(
            "invalid_op",
            f"a command list runs in one session; this one also names {', '.join(stray)}",
        )
    chosen_token = (
        token
        or (body.get("token") if envelope else None)
        or (tokens[0] if tokens else None)
    )
    if not envelope:
        return chosen, chosen_token, cleaned
    rest = {k: v for k, v in body.items() if k not in ("session", "token")}
    rest["commands" if "commands" in body else "command_list"] = cleaned
    return chosen, chosen_token, rest


def _refused(exc: OpError) -> JSONResponse:
    """A request that could not be routed. Malformed is a 400; the rest are
    ordinary failures in the ordinary envelope, which is what agents branch on."""
    return JSONResponse(
        status_code=400 if exc.type == "invalid_op" else 200, content=fail(exc)
    )


def create_app(
    session: BrowserSession | None = None,
    request_stop: Callable[[], None] | None = None,
    recorder: SessionRecorder | None = None,
    shots: bool = True,
    shot_quality: int = shots_util.DEFAULT_QUALITY,
    shot_width: int = shots_util.DEFAULT_WIDTH,
    registry: Any = None,
) -> FastAPI:
    if registry is None:
        if session is None:
            raise ValueError("create_app needs a BrowserSession or a registry")
        registry = SingleSessionRegistry(session, recorder)
    app = FastAPI(title="aibrowsertoolkit", version=__version__)
    app.state.registry = registry
    # The default session's browser, for callers that predate sessions.
    app.state.session = registry.get(None).browser
    app.state.recorder = recorder
    def _session_for(request: Request) -> Session:
        name = request.headers.get("x-abt-session") or request.query_params.get("session")
        token = request.headers.get("x-abt-token") or request.query_params.get("token")
        return registry.get(name or None, token or None)

    def run_one(sess: Session, data: Any, op_index: int) -> dict:
        """Validate then execute one command. Never raises."""
        browser = sess.browser
        started = now_ms()
        browser.last_target = None
        op = str(data.get("op", "")) if isinstance(data, dict) else ""
        def attempt() -> dict:
            try:
                cmd = parse_command(data)
                return ok(dispatch(browser, cmd))
            except OpError as exc:
                return fail(exc, op_index)
            except Exception as exc:  # an unmapped driver surprise
                return fail(_unmapped(exc), op_index)

        with trace_util.span("command", op, session=sess.name, op=op) as step:
            response = attempt()
            if not response.get("ok"):
                step.note(result=(response.get("error") or {}).get("type"))
                gone = (response.get("error") or {}).get("type") == "browser_dead"
                if browser.is_running and (browser.is_dead or gone):
                    # The connection died during this very command -- or the
                    # Chrome behind it went away, which Playwright reports at
                    # once, without ever marking the connection hung. Re-attach
                    # now, so the next call -- from the agent, the app or the
                    # activity log -- finds it working; the agent is told what
                    # happened, and never asked to do anything about it.
                    mended = _after_dropped_connection(browser, response, op_index)
                    if mended is not response and op in RETRY_AFTER_REATTACH:
                        # Nothing to lose by going again: `goto` names its whole
                        # destination, so the caller never sees the drop.
                        mended = attempt()
                    response = mended
        if sess.recorder is not None:
            # Logging takes a screenshot: timed apart, since it can be slow too.
            with trace_util.span("log", op, session=sess.name):
                event = _record(sess, data, response, now_ms() - started)
                _attach_shot(sess, data, response, event)
        return response

    def _attach_shot(sess: Session, data: Any, response: dict, event: dict | None) -> None:
        """Point a `screenshot` reply at the frame just written for it.

        The recorder is the thing that writes frames, and it lives out here
        rather than in the op, so this is where the filename becomes known.
        A screenshot with nowhere to point says so and names the reason --
        silently returning a frameless success would leave a caller waiting
        for an image that is never coming.
        """
        op = data.get("op") if isinstance(data, dict) else None
        if op != "screenshot" or not response.get("ok"):
            return
        result = response.get("result")
        if not isinstance(result, dict) or "base64" in result:
            return
        recorder = sess.recorder
        name = (event or {}).get("shot")
        if not name:
            result["path"] = None
            result["note"] = (
                "no frame was written: screenshots are off (`--no-shots`), the "
                "session's frame budget is spent, or the browser refused to be "
                "captured. Ask for `base64: true` if your client renders images "
                "inline."
            )
            return
        result["path"] = str((recorder.shots_dir / name).resolve())
        url = f"/logs/{recorder.session_id}/shots/{name}"
        # The default session's logs are what /logs serves unqualified.
        result["url"] = url if sess.name == "default" else f"{url}?session={sess.name}"
        if event.get("shot_box"):
            # Where the targeted element sits in the frame, as fractions.
            result["box"] = event["shot_box"]

    def _record(sess: Session, data: Any, response: dict, elapsed: float) -> dict | None:
        """Logging must never be able to fail a command."""
        session = sess.browser
        recorder = sess.recorder
        tab_id = url = None
        try:
            tab_id = session.active_tab
            url = session.driver.current_url
        except Exception:
            pass
        shot = None
        if shots:
            # Captured after the command, so the frame shows what it produced --
            # including the error page, when it produced one.
            try:
                op = data.get("op") if isinstance(data, dict) else None
                shot = shots_util.take(
                    session, op, bool(response.get("ok")), shot_quality, shot_width
                )
            except Exception:
                shot = None
        try:
            return recorder.record(data, response, tab_id, url, elapsed, shot=shot)
        except Exception:
            return None

    @contextmanager
    def _locked(sess: Session):
        """The session's lock, with the wait for it timed on its own: a command
        queued behind another shows as waiting, not as slow."""
        with trace_util.span("lock.wait", sess.name, session=sess.name):
            sess.lock.acquire()
        try:
            yield
        finally:
            sess.lock.release()

    def execute(sess: Session, items: list[Any], continue_on_error: bool) -> list[dict]:
        with _locked(sess):
            if sess.closed:
                return [fail(OpError("unknown_session", f"session {sess.name!r} was removed"))]
            registry.touch(sess)
            results = []
            for index, item in enumerate(items):
                if (
                    _is_shutdown(item)
                    and registry.profiles is not None
                    and sess.name != DEFAULT
                ):
                    # `shutdown` stops every session on the server. A model in
                    # one session must not be able to end everyone else's work.
                    response = fail(
                        OpError(
                            "invalid_op",
                            "shutdown stops the whole server; send it from the "
                            "default session, or run `abt shutdown`",
                        ),
                        index,
                    )
                else:
                    response = run_one(sess, item, index)
                note = getattr(registry, "note_activity", None)
                if note is not None and isinstance(item, dict):
                    note(sess, str(item.get("op", "")), bool(response.get("ok")), time.time())
                results.append(response)
                if response["ok"] and _is_shutdown(item):
                    break
                if not response["ok"] and not continue_on_error:
                    break
            # Where it is now, for a restart to come back to.
            remember = getattr(registry, "remember_pages", None)
            if remember is not None:
                try:
                    with trace_util.span("remember.pages", sess.name, session=sess.name):
                        remember(sess)
                except Exception:
                    pass
            return results

    def teardown() -> None:
        # Let the response flush before the process goes away.
        time.sleep(0.25)
        stop_all_runs()
        registry.close_all()
        if request_stop is not None:
            request_stop()

    async def _command_list(request: Request, background: BackgroundTasks):
        """The one endpoint. Takes a command, or a list of them.

        Named for the plural on purpose. There were two endpoints -- /command
        and /commands -- and a caller that found the singular first had no
        reason to look for the other, so it sent one op per request forever.
        Watching real agents, that is exactly what happened: a fixed pair like
        type-then-Enter paid as two round trips, twice per episode.
        One endpoint whose name is a list makes the batch the obvious shape and
        the single command a special case of it, rather than the reverse.

        A bare object is accepted because refusing it would only teach callers
        to wrap things, not to batch them.
        """
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body
        try:
            name, token, body = _transport(request.headers, body)
            sess = registry.get(name, token)
        except OpError as exc:
            return _refused(exc)

        # One command, sent bare. Answered in the same shape it was sent, so a
        # caller that sends one thing gets one thing back.
        if isinstance(body, dict) and "op" in body:
            results = await run_in_threadpool(execute, sess, [body], False)
            response = results[0]
            if response["ok"] and _is_shutdown(body):
                background.add_task(teardown)
            return response

        if isinstance(body, dict):
            items = body.get("commands") or body.get("command_list")
            continue_on_error = bool(body.get("continue_on_error", False))
        else:
            items, continue_on_error = body, False

        if not isinstance(items, list):
            return JSONResponse(
                status_code=400,
                content=fail(
                    OpError(
                        "invalid_op",
                        "send one command object, or a list of them. An object "
                        "with a 'commands' array and an optional "
                        "'continue_on_error' flag also works.",
                    )
                ),
            )

        results = await run_in_threadpool(execute, sess, items, continue_on_error)

        ran = len(results)
        if ran and results[-1]["ok"] and _is_shutdown(items[ran - 1]):
            background.add_task(teardown)

        failed = [r for r in results if not r["ok"]]
        payload: dict[str, Any] = {
            "ok": not failed,
            "results": results,
            "ran": ran,
            "total": len(items),
        }
        if failed:
            payload["error"] = failed[0]["error"]
        return payload

    # The only way in. There were once two -- /command and /commands -- and
    # keeping both taught the wrong lesson: a caller that met the singular
    # first had no reason to look for the other and sent one op per round trip
    # forever. One name, and it is the plural one, so the batching shape is
    # the shape you learn first.
    app.post("/command-list")(_command_list)

    @app.get("/status")
    async def status(request: Request):
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        session = sess.browser
        # Lock-free on purpose: usable while a long command is still running.
        #
        # Lock-free is not the same as instant, though. `session_status` asks
        # the browser where it is -- a `switch_to.window` plus a url and title
        # per tab -- and a driver runs one command at a time, so those queue
        # behind whatever is in flight. A status check during a slow `goto` sat
        # there for the client's whole timeout, which is the opposite of what
        # this route is for: the question is "is it alive and busy", and five
        # minutes of silence answers neither half.
        try:
            result = await asyncio.wait_for(
                run_in_threadpool(session_status, session), STATUS_TIMEOUT
            )
            return ok({"session": sess.name, **result})
        except asyncio.TimeoutError:
            return ok({
                "session": sess.name,
                "running": session.is_running,
                "busy": True,
                "note": (
                    f"the browser did not answer within {STATUS_TIMEOUT:g}s, so "
                    "where it is could not be read -- it is busy with a command, "
                    "not dead. /health answers without touching the browser at "
                    "all. If it never frees up, `browser_start` re-attaches"
                ),
            })
        except OpError as exc:
            return fail(exc)
        except EngineError as exc:
            # A dead browser must still answer /status -- that is how a caller
            # finds out it is dead. Without this the route 500s with a raw
            # traceback, which is the least useful thing it could do.
            return fail(
                OpError("browser_dead", f"browser is not reachable: {exc.msg or exc}")
            )
        except Exception as exc:
            # Anything else, too. A half-shut-down driver raises RuntimeError
            # ("cannot schedule new futures after shutdown"), not EngineError,
            # and /status answering `Internal Server Error` to that tells a
            # caller nothing about what to do next. Observed: an agent saw it,
            # could not tell the server was wedged, and guessed for four
            # commands. Re-attaching is the way out, and a command does it.
            return fail(
                OpError(
                    "browser_dead",
                    f"browser is not reachable ({type(exc).__name__}: {exc}). "
                    f"The next command re-attaches to it.",
                )
            )

    @app.get("/ops")
    async def ops(request: Request, names: bool = False):
        """Every op with its parameters -- which is what this always claimed.

        It returned bare names while `abt --help` advertised "every op and its
        exact parameters", so a caller that believed the documentation had to
        guess, and guessed `js` for `script`. `?names=true` keeps the old
        shape for anything that only wanted the list.
        """
        # An op the server will refuse has no business in the list it publishes.
        # Agents build their whole vocabulary from this: advertising run_js on a
        # server that has it closed spends turns on a refusal, and the point of
        # closing it is to find out what the ops cannot express, not to watch
        # something discover a locked door.
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        hidden = () if sess.browser.run_js_enabled else ("run_js",)
        if names:
            return ok([name for name in OP_NAMES if name not in hidden])
        return ok({
            name: signature
            for name, signature in op_signatures().items()
            if name not in hidden
        })

    # --- playbooks ------------------------------------------------------------
    #
    # Read-only over HTTP, deliberately. Pulling and trusting stay on the CLI,
    # where a person is present to consent -- an endpoint that could trust a
    # playbook would let anything able to reach loopback decide what
    # instructions agents follow.

    @app.get("/guidelines")
    async def guidelines_list():
        from . import guidelines as g

        return ok(
            {
                "installed": list(g.installed().values()),
                "general": g.general(),
                "source": g.source_url(),
                "lookup_enabled": g.lookup_enabled(),
            }
        )

    @app.get("/guidelines/lookup")
    async def guidelines_lookup(domain: str):
        from . import guidelines as g

        found = await run_in_threadpool(g.lookup, domain)
        if found is None:
            return fail(
                OpError(
                    "element_not_found",
                    f"no playbook for {domain}",
                    hint=(
                        "This is an exact-domain lookup. For anything else -- a "
                        "product name, a subdomain, a guess -- use "
                        "GET /guidelines/search?q=, which is fuzzy. A site with "
                        "no playbook is normal: drive it directly. If you have "
                        "not read it yet, GET /guidelines/toolkit-workflow is "
                        "the general workflow for driving this toolkit, and it "
                        "is worth reading before you start rather than after "
                        "something goes wrong. When you work this site out, "
                        "post a guidelines_note so the next run starts ahead."
                    ),
                )
            )
        return ok(found)

    @app.get("/guidelines/search")
    async def guidelines_search(q: str):
        """Fuzzy, and never an error: no match is an answer, not a failure."""
        from . import guidelines as g

        return ok(await run_in_threadpool(g.search, q))

    @app.get("/guidelines/{name:path}")
    async def guidelines_read(name: str):
        from . import guidelines as g

        try:
            # allow_pending stays False: an untrusted playbook is never served
            # to whatever is driving the browser. `abt guidelines show
            # --pending` is the reviewing path, and it warns.
            return ok({"name": name, "markdown": g.read(name)})
        except KeyError:
            return fail(
                OpError(
                    "element_not_found",
                    f"no playbook named {name}",
                    hint=(
                        "GET /guidelines lists what is installed and readable. "
                        "A playbook that was pulled but not trusted is not "
                        "served here at all -- `abt guidelines trust <domain>` "
                        "after a person has read it."
                    ),
                )
            )

    # --- browser lifecycle ----------------------------------------------------

    @app.get("/health")
    async def health():
        """Is the *server* up. Never touches the driver or the command lock.

        This is what launchers and readiness polls want. /status cannot serve
        that purpose once the browser is optional: a healthy server with no
        browser would look like a failure to whatever started it.
        """
        return {"ok": True, "running": registry.get(None).browser.is_running}

    @app.get("/browser")
    async def browser(request: Request):
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        return ok(browser_state(sess.browser))

    async def _lifecycle(request: Request, op: str) -> dict:
        """Run a lifecycle op through the normal path: one lock, one log entry.

        Serialized against in-flight commands on purpose -- a start that raced
        a running command would launch Chrome underneath it.
        """
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        payload: dict[str, Any] = {"op": op}
        if op in ("browser_start", "browser_restart", "browser_open_manual"):
            try:
                body = await request.json()
            except Exception:
                body = None
            fields = ("browser", "profile") if op == "browser_open_manual" else (
                "browser", "profile", "headless"
            )
            if isinstance(body, dict):
                for field in fields:
                    if body.get(field) is not None:
                        payload[field] = body[field]
        results = await run_in_threadpool(execute, sess, [payload], False)
        return results[0]

    @app.post("/browser/start")
    async def browser_start_route(request: Request):
        return await _lifecycle(request, "browser_start")

    @app.post("/browser/stop")
    async def browser_stop_route(request: Request):
        return await _lifecycle(request, "browser_stop")

    @app.post("/browser/restart")
    async def browser_restart_route(request: Request):
        return await _lifecycle(request, "browser_restart")

    @app.post("/browser/open-manual")
    async def browser_open_manual_route(request: Request):
        return await _lifecycle(request, "browser_open_manual")

    # --- session logs ---------------------------------------------------------

    # "session" in these routes' own names is a recorder run -- one server
    # lifetime. The session a request runs in picks *whose* runs they are.

    @app.get("/logs")
    async def logs(request: Request):
        """Every recorded session, newest first."""
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        root = sess.log_root
        if root is None:
            return ok({"recording": False, "sessions": []})
        current = sess.started_recorder
        return ok(
            {
                "recording": True,
                "current": current.session_id if current is not None else None,
                "sessions": await run_in_threadpool(list_sessions, root),
            }
        )

    @app.get("/logs/sites")
    async def logs_sites(request: Request):
        """Every site touched across every session."""
        try:
            root = _session_for(request).log_root
        except OpError as exc:
            return _refused(exc)
        if root is None:
            return ok([])
        return ok(await run_in_threadpool(sites_index, root))

    @app.get("/logs/{session_id}")
    async def logs_session(
        session_id: str,
        request: Request,
        site: str | None = None,
        tab: str | None = None,
        op: str | None = None,
        errors_only: bool = False,
    ):
        try:
            root = _session_for(request).log_root
        except OpError as exc:
            return _refused(exc)
        if root is None:
            return fail(OpError("invalid_op", "recording is disabled"))
        events = await run_in_threadpool(read_events, root, session_id)
        if not events and not (root / session_id).exists():
            return JSONResponse(
                status_code=404,
                content=fail(OpError("invalid_op", f"no session {session_id!r}")),
            )
        if site:
            events = [e for e in events if e.get("site") == site]
        if tab:
            events = [e for e in events if e.get("tab_id") == tab]
        if op:
            events = [e for e in events if e.get("op") == op]
        if errors_only:
            events = [e for e in events if not e.get("ok")]
        return ok(
            {
                "session_id": session_id,
                "count": len(events),
                "tabs": sorted({e["tab_id"] for e in events if e.get("tab_id")}),
                "sites": sorted({e["site"] for e in events if e.get("site")}),
                "events": events,
            }
        )

    @app.get("/logs/{session_id}/shots/{name}")
    async def logs_shot(session_id: str, name: str, request: Request):
        """One recorded frame. Named in the event that produced it."""
        try:
            root = _session_for(request).log_root
        except OpError as exc:
            return _refused(exc)
        path = None if root is None else shot_path(root, session_id, name)
        if path is None:
            return JSONResponse(
                status_code=404,
                content=fail(OpError("invalid_op", f"no frame {name!r}")),
            )
        return FileResponse(
            path,
            media_type="image/jpeg" if path.suffix == ".jpg" else "image/png",
            # A stored frame never changes, so the viewer should never refetch
            # one while scrolling a long session.
            headers={"cache-control": "public, max-age=31536000, immutable"},
        )

    @app.get("/viewer", response_class=HTMLResponse)
    async def viewer():
        return HTMLResponse(VIEWER_HTML)

    # --- sessions and profiles -------------------------------------------------
    #
    # Management, not commands: these never touch a page, so they take no
    # session lock of their own beyond what the registry takes.

    def _token(request: Request) -> str | None:
        return request.headers.get("x-abt-token") or request.query_params.get("token")

    async def _admin(work: Callable[[], Any]):
        try:
            return ok(await run_in_threadpool(work))
        except OpError as exc:
            return _refused(exc)

    async def _object(request: Request) -> Any:
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body
        if not isinstance(body, dict):
            return _refused(OpError("invalid_op", "body must be an object"))
        return body

    def _profiles():
        if registry.profiles is None:
            raise OpError("invalid_op", NO_SESSIONS)
        return registry.profiles

    @app.get("/sessions")
    async def sessions_list():
        return await _admin(registry.list)

    @app.post("/sessions")
    async def sessions_create(request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: registry.create(
            body.get("name"),
            body.get("profile") or DEFAULT,
            bool(body.get("sealed")),
            body.get("settings"),
        ))

    @app.get("/sessions/{name}")
    async def sessions_show(name: str, request: Request):
        return await _admin(lambda: registry.info(name, _token(request)))

    @app.patch("/sessions/{name}")
    async def sessions_update(name: str, request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: registry.update(
            name, _token(request), profile=body.get("profile"), settings=body.get("settings")
        ))

    @app.delete("/sessions/{name}")
    async def sessions_remove(name: str, request: Request):
        def work():
            registry.remove(name, _token(request))
            if chats is not None:
                chats.retire(name)
            return {"removed": name}

        return await _admin(work)

    @app.get("/profiles")
    async def profiles_list():
        return await _admin(lambda: _profiles().list())

    @app.post("/profiles")
    async def profiles_create(request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: _profiles().create(body.get("name")))

    @app.patch("/profiles/{name}")
    async def profiles_update(name: str, request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: _profiles().set_headed(name, bool(body.get("headed"))))

    @app.delete("/profiles/{name}")
    async def profiles_remove(name: str):
        return await _admin(lambda: registry.remove_profile(name) or {"removed": name})

    @app.post("/profiles/{name}/force-close")
    async def profiles_force_close(name: str, request: Request):
        """End every browser holding this profile, a person's own window too.

        Operator only: it can close a Chrome window somebody is using.
        """
        def work():
            if not registry.is_operator(_token(request)):
                raise OpError("session_sealed", "force-closing a browser needs the operator token")
            return _profiles().force_close(name)

        return await _admin(work)

    @app.post("/app/quit")
    async def app_quit(request: Request):
        """The app's window closed: close every browser it may have left open.

        They start again on demand, so a CLI agent on this server only notices
        a fresh browser. Operator only.
        """
        def work():
            if not registry.is_operator(_token(request)):
                raise OpError("session_sealed", "this needs the operator token")
            profiles = registry.profiles
            if profiles is None:
                return {"closed": []}
            return {"closed": profiles.sweep()}

        return await _admin(work)

    @app.post("/tabs/owner")
    async def tabs_owner(request: Request):
        """The operator hands a tab to a session, or frees it (session: null)."""
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body

        def work():
            if not registry.is_operator(_token(request)):
                raise OpError(
                    "session_sealed", "reassigning tabs needs the operator token"
                )
            profile = body.get("profile") or DEFAULT
            tabs = _profiles().tabs(profile)
            target = tabs.target_of(str(body.get("tab_id")))
            if target is None:
                for row in _profiles().targets(profile):
                    tabs.label(row["id"])
                target = tabs.target_of(str(body.get("tab_id")))
            if target is None:
                raise OpError(
                    "tab_not_found", f"no tab {body.get('tab_id')!r} on {profile}"
                )
            owner = body.get("session")
            if owner is not None:
                # unknown_session if there is no such session; and a tab can
                # only belong to a session on the profile it is open in.
                if registry.info(owner)["profile"] != profile:
                    raise OpError(
                        "invalid_op",
                        f"session {owner!r} is not on profile {profile!r}, where this tab is",
                    )
            return {"tab_id": tabs.set_owner(target, owner), "session": owner}

        return await _admin(work)

    # --- screencast --------------------------------------------------------------

    def _screencast_target(
        name: str | None, profile: str | None, tab: str | None, token: str | None
    ) -> tuple[str, str, int, Path | None]:
        profiles = _profiles()
        if not tab:
            raise OpError("invalid_op", "screencast needs ?tab=")
        uploads = None
        if registry.is_operator(token):
            # The human at the GUI: any tab, locks included.
            profile = profile or (registry.info(name)["profile"] if name else DEFAULT)
            watcher = None
            if name:
                # The operator is trusted with any session; this reads its
                # folder, not its commands.
                live = registry._live.get(name)
                uploads = live.browser.uploads_dir if live is not None else None
        else:
            sess = registry.get(name or None, token)
            profile, watcher = sess.record.profile, sess.name
            uploads = sess.browser.uploads_dir
        tabs = profiles.tabs(profile)
        target = tabs.target_of(tab)
        if target is None:
            for row in profiles.targets(profile):
                tabs.label(row["id"])
            target = tabs.target_of(tab)
        if target is None:
            raise OpError("tab_not_found", f"no tab {tab!r} on {profile}")
        if watcher is not None and tabs.access(target, watcher) != OWN:
            raise OpError("tab_locked", f"{tab} is not this session's")
        running = profiles.running(profile)
        if running is None:
            raise OpError("browser_dead", NO_BROWSER_MESSAGE)
        return profile, target, running.port, uploads

    def _local_origin(ws: WebSocket) -> bool:
        """Browsers apply no CORS to WebSockets, so without this any web page
        open anywhere on the machine could watch a logged-in tab, type into
        it, or drive a chat. The app's own page is served from here; nothing
        else has a reason to connect with an Origin at all."""
        origin = ws.headers.get("origin")
        return not origin or urlparse(origin).hostname in ("127.0.0.1", "localhost", "::1")

    @app.websocket("/screencast")
    async def screencast(ws: WebSocket):
        if not _local_origin(ws):
            await ws.close(code=1008)
            return
        params = ws.query_params
        token = ws.headers.get("x-abt-token") or params.get("token")
        await ws.accept()
        try:
            profile, target, port, uploads = await run_in_threadpool(
                _screencast_target,
                params.get("session"),
                params.get("profile"),
                params.get("tab"),
                token,
            )
        except OpError as exc:
            await ws.send_json(fail(exc))
            await ws.close(code=1008)
            return
        # The Live grid asks for small, view-only streams: many at once, so
        # each is sized down, and nothing it sends reaches the page.
        view_only = params.get("view") == "1"
        try:
            width = max(160, min(1600, int(params.get("w") or 1600)))
            quality = max(20, min(80, int(params.get("q") or 60)))
        except ValueError:
            width, quality = 1600, 60
        registry.profiles.watch(profile, +1)
        try:
            await screencast_util.relay(
                ws, f"ws://127.0.0.1:{port}/devtools/page/{target}",
                quality=quality, max_width=width,
                upload_root=None if view_only else uploads, view_only=view_only,
            )
        except Exception:
            pass
        finally:
            registry.profiles.watch(profile, -1)
            try:
                await ws.close()
            except Exception:
                pass

    # --- the desktop app ---------------------------------------------------------

    from . import agent as agent_util
    from .appstate import AppSettings, ChatStore, free_models
    from .mcp import to_op

    base = registry.store.directory if registry.profiles is not None else None
    app_settings = AppSettings(base / "app.json") if base else None
    chats = ChatStore(base / "chats") if base else None

    def _app_ready() -> None:
        if app_settings is None:
            raise OpError("invalid_op", NO_SESSIONS)

    def _operator(request: Request) -> None:
        _app_ready()
        if not registry.is_operator(_token(request)):
            raise OpError("session_sealed", "this needs the operator token")

    @app.get("/app", response_class=HTMLResponse)
    async def app_page():
        return HTMLResponse(APP_HTML)

    @app.get("/app/where")
    async def app_where():
        """Where the token files are, so the desktop shell can read them.

        A path, never a token: the shell reads the files itself, as the user.
        """
        return await _admin(lambda: _app_ready() or {"sessions_dir": str(base)})

    @app.get("/app/settings")
    async def app_settings_get(request: Request):
        return await _admin(lambda: _operator(request) or app_settings.public())

    @app.put("/app/settings")
    async def app_settings_put(request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: _operator(request) or app_settings.update(body))

    @app.get("/app/models/free")
    async def app_models_free(request: Request):
        def work():
            _operator(request)
            data = app_settings.load()
            return free_models(data["endpoint"], data["api_key"])

        return await _admin(work)

    def _chat_session(request: Request) -> Session:
        _app_ready()
        sess = _session_for(request)
        # The app shows a chat's page itself, so its browser needs no window:
        # a visible one only invited closing it, which took the chat's tabs
        # with it. Chats made before sessions carried `headless` get it the
        # first time the app touches them. `default` is shared with the CLI,
        # which keeps its window.
        if sess.name != DEFAULT and "headless" not in sess.record.settings:
            sess.record.settings = {**sess.record.settings, "headless": True}
            registry.store.save(sess.record)
        return sess

    @app.get("/app/chats")
    async def app_chats(request: Request):
        return await _admin(lambda: chats.list(_chat_session(request).name))

    @app.post("/app/chats")
    async def app_chats_new(request: Request):
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body
        return await _admin(lambda: chats.create(_chat_session(request).name, body.get("model")))

    @app.get("/app/chats/{chat_id}")
    async def app_chat_get(chat_id: str, request: Request):
        return await _admin(lambda: chats.get(_chat_session(request).name, chat_id))

    @app.delete("/app/chats/{chat_id}")
    async def app_chat_delete(chat_id: str, request: Request):
        def work():
            chats.delete(_chat_session(request).name, chat_id)
            return {"deleted": chat_id}

        return await _admin(work)

    def browser_gone(sess: Session) -> bool:
        """Whether this session's browser has died, as opposed to a command
        merely failing in a live one."""
        if registry.profiles is None:
            return False
        running = registry.profiles.running(sess.record.profile)
        if running is None:
            return True
        # Ask Chrome itself. The process can still look alive for a moment
        # after it was killed, and the driver's own health check passes on a
        # dead browser -- it answers from pages it has cached.
        import httpx

        try:
            httpx.get(f"{running.url}/json/version", timeout=2)
        except Exception:
            return True
        return False

    def call_tool(sess: Session, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool call from the chat, in the chat's session.

        The same path `/command-list` takes, so the session's lock, rules, tab
        locks and run_js switch all apply to the model exactly as to anyone.
        """
        from . import guidelines as g

        try:
            if name == "browser_session":
                # Not offered to the chat's model, but one may call it from
                # habit. Answer as a success so it moves on instead of looping
                # on "already running" -- the app keeps the browser up.
                state = "running" if sess.browser.is_running else "starting when needed"
                return json.dumps({"ok": True, "result": {
                    "browser": state,
                    "note": "The app manages the browser. Carry on with command_list.",
                }}), False
            if name == "browser_guidelines":
                try:
                    if args.get("name"):
                        body = ok({"name": args["name"], "markdown": g.read(args["name"])})
                    elif args.get("domain"):
                        body = ok(g.search(args["domain"]))
                    else:
                        body = ok({"installed": list(g.installed().values()), "general": g.general()})
                except KeyError:
                    body = fail(OpError("element_not_found", f"no playbook {args.get('name')!r}"))
            else:
                try:
                    payload = to_op(name, args)
                except KeyError:
                    return f"no such tool: {name}", True
                envelope = isinstance(payload, dict) and "commands" in payload
                items = payload["commands"] if envelope else [payload]
                if not isinstance(items, list):
                    raise OpError("invalid_op", "commands must be a list")
                # Transport fields are not the model's to set; the chat's
                # session is fixed.
                items = [_strip(item)[0] for item in items]
                if any(_is_shutdown(item) for item in items):
                    raise OpError("invalid_op", "shutdown is not available from the chat")
                keep_going = bool(envelope and payload.get("continue_on_error"))
                # The chat's model may hand a page only files from the
                # profile's uploads folder, whatever the session's setting.
                from .ops.interact import STRICT_UPLOADS

                STRICT_UPLOADS.set(True)
                # The person never presses "start": a chat that needs the page
                # gets a browser, and one that died under it gets a new one
                # and the same commands again, once.
                needs_page = any(
                    isinstance(item, dict)
                    and str(item.get("op", "")) not in NO_HEALTH_CHECK
                    for item in items
                )
                if needs_page and not sess.browser.is_running:
                    execute(sess, [{"op": "browser_start"}], False)
                results = execute(sess, items, keep_going)
                # A dead Chrome does not always say so: a goto into it fails
                # as navigation_failed. So on any failure, ask the browser
                # itself whether it is still there.
                if needs_page and any(not r["ok"] for r in results) and browser_gone(sess):
                    # Re-attach, relaunching the profile's Chrome if it is gone:
                    # the chat never restarts a browser to get out of a failure.
                    try:
                        with _locked(sess):
                            sess.browser.reconnect()
                        results = execute(sess, items, keep_going)
                    except OpError:
                        pass
                if envelope:
                    failed = [r for r in results if not r["ok"]]
                    body = {"ok": not failed, "results": results, "ran": len(results), "total": len(items)}
                    if failed:
                        body["error"] = failed[0]["error"]
                else:
                    body = results[0]
        except OpError as exc:
            body = fail(exc)
        return json.dumps(body, separators=(",", ":"), default=str), body.get("ok") is False

    # Chat replies run on the server, not on the page's socket. The page only
    # watches: switching profile or session, or reloading, leaves every reply
    # running, and coming back replays what was missed. Each chat runs one
    # reply at a time; different chats -- in any session, on any profile -- run
    # side by side, because each session has its own browser and lock.

    class ChatRun:
        def __init__(self, session: str, chat_id: str) -> None:
            self.session = session
            self.chat_id = chat_id
            self.events: list[dict] = []
            self.stop = threading.Event()
            self.finished = False
            # What the person sent while this runs, not yet read by the model.
            # Appended on the event loop, taken on the worker thread.
            self.steering: list[dict] = []
            self.steering_lock = threading.Lock()
            self.steer_count = 0
            # For a helper's run: the files it saved, and how it ended.
            self.reports: list[str] = []
            self.summary: str | None = None
            self.outcome: str | None = None
            # The chat's token totals so far, for the Agents grid while it runs.
            self.usage: dict | None = None

        def steer(self, text: str, update: bool = False) -> dict:
            with self.steering_lock:
                self.steer_count += 1
                item = {"id": f"s{self.steer_count}", "text": text}
                if update:
                    item["update"] = True
                self.steering.append(item)
            return item

        def take_steering(self) -> list[dict]:
            with self.steering_lock:
                taken, self.steering = self.steering, []
            return taken

    runs: dict[tuple[str, str], ChatRun] = {}
    watchers: dict[str, set] = {}  # session -> the queues of pages watching it
    # Agentic chats. A lead's plan, and whether the person has answered it:
    # helpers start only after they have. Keyed by the lead's session.
    plans: dict[str, dict] = {}
    # The helpers each lead started: [{id, role, task, chat_id, started}].
    helpers: dict[str, list[dict]] = {}
    # What reached a lead while it was not running: told on its next turn.
    pending_updates: dict[str, list[str]] = {}

    def stop_all_runs() -> None:
        """Tell every reply still running to stop at its next step.

        A reply runs on a worker thread. Left alone through a shutdown, it kept
        the process alive after the server stopped listening -- and kept
        driving its browser, restarting it whenever the next server took the
        profile, which then lost its own browser in turn.
        """
        for run in list(runs.values()):
            run.stop.set()

    app.router.on_shutdown.append(stop_all_runs)

    def publish(run: ChatRun, event: dict) -> None:
        """Called on the event loop. Buffer the event and hand it to watchers."""
        event = {**event, "chat_id": run.chat_id}
        # Streamed pieces go out live but are not kept: the finished message
        # follows as one "assistant" event, and that is what a page replays.
        if event["type"] not in ("done", "delta"):
            run.events.append(event)
        for queue in list(watchers.get(run.session, ())):
            queue.put_nowait(event)

    async def start_run(sess: Session, message: dict) -> str | None:
        """Begin a reply. Returns an error message, or None when started."""
        chat_id = str(message.get("chat_id"))
        key = (sess.name, chat_id)
        current = runs.get(key)
        text = str(message.get("text") or "").strip()
        if text and sess.name in plans:
            # The person answered the plan: yes, a change, or a no -- the
            # lead reads which. Helpers may start from here on.
            plans[sess.name]["approved"] = True
        if current is not None and not current.finished:
            # Sent while it works: it steers the run, read at the next step.
            if not text:
                return None
            item = current.steer(text)
            publish(current, {"type": "steer", **item})
            return None
        try:
            chat = await run_in_threadpool(chats.get, sess.name, chat_id)
        except OpError as exc:
            return exc.message
        settings = app_settings.load()
        models = [m for m in [message.get("model"), chat.get("model"), *settings["models"]] if m]
        # Helpers that finished while this lead was not running.
        for note in pending_updates.pop(sess.name, []):
            chat["messages"].append({"role": "user", "content": note, "steer": True, "update": True})
        chat["messages"].append({"role": "user", "content": text})
        if chat.get("title") in (None, "", "New chat"):
            chat["title"] = text[:60] or "New chat"
        # Saved now, not when the reply ends: the chat list reads the saved
        # chat, and showed "New chat" for as long as the first reply ran.
        await run_in_threadpool(chats.save, sess.name, chat)
        run = ChatRun(sess.name, chat_id)
        runs[key] = run
        loop = asyncio.get_running_loop()
        publish(run, {"type": "user", "text": text, "title": chat["title"]})

        def emit(event: dict) -> None:
            # Errors and notices are kept in the chat, so they are still
            # there after a reload -- they used to exist only on screen.
            if event.get("type") in ("error", "notice"):
                chat["messages"].append({"role": event["type"], "content": event.get("text", "")})
            loop.call_soon_threadsafe(publish, run, event)

        role = sess.record.settings.get("role")
        agentic = bool(sess.record.settings.get("agentic")) and not role

        def tool_call(name: str, args: dict) -> tuple[str, bool]:
            ops = [c.get("op") for c in (args.get("commands") or []) if isinstance(c, dict)]
            with trace_util.span("tool", name, session=sess.name, chat=chat_id,
                                 ops=",".join(str(o) for o in ops) or None) as step:
                if agentic and name in agent_util.ORCHESTRATION_NAMES:
                    text, failed = orchestrate(sess, run, chat, loop, name, args)
                else:
                    text, failed = call_tool(sess, name, args)
                    if '"saved"' in text:
                        run.reports.extend(_saved_paths(text))
                if failed:
                    step.note(result="failed")
                return text, failed

        def complete(model: str, msgs: list[dict]) -> dict:
            # The model call, timed: how long until the first word, and in all.
            with trace_util.span("model", model, session=sess.name, chat=chat_id,
                                 messages=len(msgs)) as step:
                first: list[float] = []

                def on_text(piece: str) -> None:
                    if not first:
                        first.append(step.elapsed_ms())
                        step.note(first_token_ms=first[0])
                    emit({"type": "delta", "text": piece})

                reply = agent_util.complete(
                    settings["endpoint"], settings["api_key"], model, msgs, tool_list,
                    on_text=on_text, should_stop=run.stop.is_set,
                )
                step.note(tool_calls=len(reply.get("tool_calls") or []))
                used = reply.pop("usage", None)
                if used:
                    # Kept on the chat, so its total survives a reload.
                    chat["usage"] = run.usage = agent_util.add_usage(chat.get("usage"), used)
                    step.note(tokens=int(used.get("total_tokens") or 0) or None)
                    emit({"type": "usage", "usage": chat["usage"]})
                return reply

        tool_list: list[dict] = []

        def work() -> None:
            tool_list.extend(agent_util.tools() + (agent_util.ORCHESTRATION_TOOLS if agentic else []))
            system = agent_util.system_prompt(
                sess.record.settings.get("rules"), sess.browser.run_js_enabled,
                bool(sess.record.settings.get("only_listed")),
                agentic=agentic, role=role, lead=sess.record.settings.get("lead"),
            )
            try:
                with trace_util.span("chat.reply", chat.get("title") or "", session=sess.name, chat=chat_id):
                    used = agent_util.run_turn(
                        chat["messages"],
                        models=models,
                        complete_fn=complete,
                        call_tool=tool_call,
                        emit=emit,
                        should_stop=run.stop.is_set,
                        take_steering=run.take_steering,
                        system=system,
                    )
                if used:
                    chat["model"] = used
            except Exception as exc:  # the chat must say so, not go quiet
                emit({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
            finally:
                # Sent too late for this run -- it stopped or failed first.
                # Kept in the chat, so the next message carries it along.
                for item in run.take_steering():
                    chat["messages"].append({"role": "user", "content": item["text"], "steer": True})
                chats.save(sess.name, chat)

                last = next((m.get("content") for m in reversed(chat["messages"])
                             if m.get("role") == "assistant" and m.get("content")), None)
                run.summary = (last or "")[:2000] or None
                failed = any(m.get("role") == "error" for m in chat["messages"][-3:])
                run.outcome = "stopped" if run.stop.is_set() else "failed" if failed else "done"

                def finish() -> None:
                    run.finished = True
                    publish(run, {"type": "done", "title": chat["title"]})
                    if role:
                        tell_lead(sess, run)

                loop.call_soon_threadsafe(finish)

        loop.run_in_executor(None, work)
        return None

    # --- agentic chats: helpers a lead starts, watches and reads ---------------------

    def _saved_paths(text: str) -> list[str]:
        """Paths a tool result says save_file wrote."""
        try:
            body = json.loads(text)
        except ValueError:
            return []
        found: list[str] = []

        def walk(node) -> None:
            if isinstance(node, dict):
                if "saved" in node and isinstance(node.get("path"), str):
                    found.append(node["path"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(body)
        return found

    def _helper_run(helper: dict) -> "ChatRun | None":
        return runs.get((helper["id"], helper["chat_id"]))

    def _helper_status(helper: dict) -> dict:
        run = _helper_run(helper)
        live = registry._live.get(helper["id"])
        activity = dict(live.activity) if live is not None else {}
        page = None
        if live is not None and live.browser.is_running:
            snap = live.browser.page_snapshot() or {}
            urls = snap.get("urls") or []
            page = urls[snap.get("active", 0)] if urls else None
        finished = run is None or run.finished
        row = {
            "worker": helper["id"],
            "role": helper["role"],
            "status": (run.outcome or "done") if finished and run is not None else "working",
            "steps": activity.get("steps", 0),
            "page": page,
            "reports": [Path(p).name for p in (run.reports if run else [])],
        }
        if finished and run is not None:
            row["summary"] = run.summary
        return row

    def tell_lead(helper_sess: Session, helper_run: "ChatRun") -> None:
        """A helper finished: tell its lead, now if it is running, else next turn."""
        lead = helper_sess.record.settings.get("lead")
        if not lead:
            return
        role = helper_sess.record.settings.get("role") or "helper"
        files = ", ".join(Path(p).name for p in helper_run.reports) or "no report file"
        ended = {"done": "finished", "stopped": "was stopped", "failed": "failed"}.get(
            helper_run.outcome or "done", "finished")
        note = (f"Helper {helper_sess.name} ({role}) {ended}. "
                f"Reports: {files}. Read them with read_report.")
        for (name, _cid), run in list(runs.items()):
            if name == lead and not run.finished:
                item = run.steer(note, update=True)
                publish(run, {"type": "steer", **item})
                return
        pending_updates.setdefault(lead, []).append(note)

    def orchestrate(lead: Session, lead_run: "ChatRun", lead_chat: dict, loop, name: str, args: dict) -> tuple[str, bool]:
        """The lead's own tools. Runs on the lead's worker thread."""

        def answer(result) -> tuple[str, bool]:
            return json.dumps({"ok": True, "result": result}), False

        def refuse(message: str) -> tuple[str, bool]:
            return json.dumps({"ok": False, "error": {"type": "invalid_op", "message": message}}), True

        mine = helpers.setdefault(lead.name, [])
        cap = agent_util.MAX_WORKERS

        if name == "propose_plan":
            workers = args.get("workers")
            if not isinstance(workers, list) or not workers:
                return refuse("propose_plan needs a list of workers, each a role and a task")
            if len(workers) > cap:
                return refuse(f"at most {cap} helpers")
            clean = []
            for w in workers:
                if not isinstance(w, dict) or not str(w.get("role", "")).strip() or not str(w.get("task", "")).strip():
                    return refuse("each worker needs a role and a task")
                clean.append({"role": str(w["role"]).strip()[:80], "task": str(w["task"]).strip()[:2000]})
            plans[lead.name] = {"workers": clean, "approved": False, "started": 0,
                                "summary": str(args.get("summary") or "")[:1000]}
            return answer({"shown": True, "helpers": len(clean),
                           "next": "End your turn now. The person will approve, change or decline the plan."})

        if name == "start_worker":
            plan = plans.get(lead.name)
            if plan is None:
                return refuse("propose a plan first with propose_plan, then wait for the person's go-ahead")
            if not plan["approved"]:
                return refuse("the person has not answered the plan yet: end your turn and wait")
            if plan["started"] >= max(len(plan["workers"]), 1) + 1 or len(mine) >= cap:
                return refuse(f"the plan's helpers are already started (at most {cap})")
            working = [h for h in mine if (r := _helper_run(h)) is not None and not r.finished]
            if len(working) >= cap:
                return refuse(f"{cap} helpers are already working; wait for one to finish")
            role = str(args.get("role") or "").strip()[:80]
            task = str(args.get("task") or "").strip()[:4000]
            if not role or not task:
                return refuse("start_worker needs a role and a task")
            st = lead.record.settings
            lead_rules = list(st.get("rules") or []) or ["all"]
            sites = [str(s).strip() for s in (args.get("sites") or []) if str(s).strip()]
            if sites:
                from .policy import Policy
                lead_policy = Policy(st.get("rules") or [], only_listed=bool(st.get("only_listed")))
                wider = [s for s in sites if not s.startswith("!") and not lead_policy.allows(
                    "https://" + s.split("/", 1)[0] + "/" + (s.split("/", 1)[1] if "/" in s else ""))]
                if wider:
                    return refuse(f"a helper may not go where you may not: {', '.join(wider)}")
                rules = sites + [r for r in lead_rules if r.startswith("!")]
            else:
                rules = lead_rules
            n = len(mine) + 1
            names = {row["name"] for row in registry.list()}
            while f"{lead.name}-w{n}" in names:
                n += 1
            helper_name = f"{lead.name}-w{n}"
            settings = {
                "headless": True, "only_listed": True, "rules": rules,
                "run_js": st.get("run_js", True), "strict": bool(st.get("strict")),
                "role": role, "lead": lead.name, "agentic": False,
            }
            try:
                made = registry.create(helper_name, profile=lead.record.profile, sealed=True, settings=settings)
                helper_sess = registry.get(helper_name, made.get("token"))
                helper_chat = chats.create(helper_name, lead_chat.get("model"))
                helper_chat["title"] = f"{role}: {task[:50]}"
                chats.save(helper_name, helper_chat)
                error = asyncio.run_coroutine_threadsafe(
                    start_run(helper_sess, {"chat_id": helper_chat["id"], "text": task,
                                            "model": lead_chat.get("model")}),
                    loop,
                ).result(timeout=30)
            except OpError as exc:
                return refuse(exc.message)
            if error:
                return refuse(error)
            mine.append({"id": helper_name, "role": role, "task": task,
                         "chat_id": helper_chat["id"], "started": time.time()})
            plan["started"] += 1
            return answer({"worker": helper_name, "role": role, "status": "working"})

        if name == "workers":
            return answer([_helper_status(h) for h in mine])

        if name == "wait_for_workers":
            try:
                limit = max(1.0, min(600.0, float(args.get("timeout_s") or 180)))
            except (TypeError, ValueError):
                limit = 180.0
            waiting = [h for h in mine if (r := _helper_run(h)) is not None and not r.finished]
            deadline = time.time() + limit
            while waiting and time.time() < deadline and not lead_run.stop.is_set():
                if any(_helper_run(h).finished for h in waiting):
                    break
                with lead_run.steering_lock:
                    if lead_run.steering:  # the person said something: let the lead read it
                        break
                time.sleep(1.0)
            return answer([_helper_status(h) for h in mine])

        helper = next((h for h in mine if h["id"] == str(args.get("worker") or "")), None)
        if helper is None:
            return refuse(f"no helper {args.get('worker')!r}; yours: {', '.join(h['id'] for h in mine) or 'none'}")

        if name == "read_report":
            run = _helper_run(helper)
            files = list(run.reports if run else [])
            want = str(args.get("file") or "").strip()
            path = next((p for p in files if Path(p).name == want), None) if want else (files[-1] if files else None)
            if path is None:
                return refuse(f"{helper['id']} has saved no report{' named ' + want if want else ''} yet")
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            return answer({"worker": helper["id"], "file": Path(path).name, "text": text[:30000],
                           "truncated": len(text) > 30000})

        if name == "stop_worker":
            run = _helper_run(helper)
            if run is not None and not run.finished:
                run.stop.set()
            return answer({"worker": helper["id"], "status": "stopping"})

        return refuse(f"unknown tool {name}")

    # --- files: the profile's uploads and downloads folders ------------------------

    @app.get("/app/files")
    async def app_files(request: Request):
        return await _admin(lambda: _chat_session(request).browser.files())

    @app.post("/app/files/open")
    async def app_files_open(request: Request):
        """Show a folder, or open one downloaded file, on this computer."""
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body

        def work():
            from .browser import open_in_file_manager

            browser = _chat_session(request).browser
            folder = browser.downloads_dir if body.get("which") == "downloads" else browser.uploads_dir
            if folder is None:
                raise OpError("invalid_op", NO_SESSIONS)
            name = body.get("name")
            target = folder
            if name:
                target = (folder / str(name)).resolve()
                if folder.resolve() not in target.parents or not target.is_file():
                    raise OpError("file_blocked", f"no file {name!r} in {folder}")
            return {"opened": open_in_file_manager(target), "path": str(target)}

        return await _admin(work)

    @app.post("/app/upload")
    async def app_upload(request: Request):
        """Save a file the person picked into the profile's uploads folder."""
        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body

        def work():
            import base64

            folder = _chat_session(request).browser.uploads_dir
            if folder is None:
                raise OpError("invalid_op", NO_SESSIONS)
            name = Path(str(body.get("name") or "upload")).name.strip() or "upload"
            try:
                data = base64.b64decode(body.get("data") or "", validate=True)
            except Exception:
                raise OpError("invalid_op", "data must be base64")
            if len(data) > 200 * 1024 * 1024:
                raise OpError("invalid_op", "files over 200 MB are not accepted")
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            stem, suffix, n = target.stem, target.suffix, 1
            while target.exists():
                target = folder / f"{stem} ({n}){suffix}"
                n += 1
            target.write_bytes(data)
            return {"path": str(target.resolve()), "name": target.name, "size": len(data)}

        return await _admin(work)

    @app.get("/app/tabs")
    async def app_tabs(request: Request):
        """This session's tabs, read from Chrome's own page list.

        Never takes the session's lock and never touches its driver, so the
        tab strip stays live while an agent is mid-command -- `tab_list` would
        queue behind it, and switching the driver's tab to look at one would
        move the agent's next click with it.
        """

        def work():
            sess = _chat_session(request)
            profile = sess.record.profile
            profiles = _profiles()
            tabs = profiles.tabs(profile)
            mine = set(tabs.owned_by(sess.name))
            rows = []
            for target in profiles.targets(profile):
                if target.get("id") in mine:
                    rows.append({
                        "tab_id": tabs.label(target["id"]),
                        "url": target.get("url", ""),
                        "title": target.get("title", ""),
                    })
            return sorted(rows, key=lambda r: int(r["tab_id"].split("_")[-1]))

        return await _admin(work)

    def _settings_of(name: str) -> dict:
        record = getattr(registry, "_records", {}).get(name)
        return dict(record.settings) if record is not None else {}

    @app.get("/debug/trace")
    async def debug_trace(request: Request, limit: int = 100):
        """What is running right now, step by step, and the latest finished steps.

        A hang shows as an active step that keeps ageing, with the chain of
        steps it is part of. Operator only: steps name sessions and chats.
        """
        if not registry.is_operator(_token(request)):
            return _refused(OpError("session_sealed", "the trace needs the operator token"))
        return ok({"active": trace_util.active(), "recent": trace_util.recent(max(1, min(500, limit)))})

    def _session_tokens(name: str, chat_list: list[dict]) -> int | None:
        """Tokens a session's chats have used: a running one's live total, else
        what was saved."""
        total = 0
        for chat in chat_list:
            run = runs.get((name, chat["id"]))
            usage = (run.usage if run is not None and run.usage else chat.get("usage")) or {}
            total += usage.get("prompt", 0) + usage.get("completion", 0)
        return total or None

    @app.get("/app/live")
    async def app_live(request: Request):
        """Every session with a browser up or recent work: the app's Live grid.

        Lock-free: `working` is whether a command holds the session's lock
        right now, or a chat reply is running -- read, never waited on.
        Operator only, since it spans sealed sessions.
        """

        def work():
            _operator(request)
            now = time.time()
            profiles = _profiles()
            replying = {key for key, run in runs.items() if not run.finished}
            rows = []
            for info in registry.list():
                name = info["name"]
                sess = registry._live.get(name)
                activity = dict(sess.activity) if sess is not None else {}
                running = sess is not None and sess.browser.is_running
                chat_running = [cid for (sname, cid) in replying if sname == name]
                recent = activity and now - activity.get("at", 0) < 1800
                if not (running or recent or chat_running):
                    continue
                tab = url = title = None
                target = sess.browser.active_target_hint() if running else None
                gate_tabs = profiles.tabs(info["profile"])
                owned = set(gate_tabs.owned_by(name)) if running else set()
                if running and target not in owned:
                    target = next(iter(sorted(owned)), None)
                if target is not None:
                    tab = gate_tabs.label(target)
                    for row in profiles.targets(info["profile"]):
                        if row.get("id") == target:
                            url, title = row.get("url"), row.get("title")
                            break
                chat_list = chats.list(name) if name.startswith("chat-") else []
                heading = next((c.get("title") for c in chat_list if c.get("title") and c.get("title") != "New chat"), None)
                rows.append({
                    "session": name,
                    "profile": info["profile"],
                    "sealed": info["sealed"],
                    "kind": "chat" if name.startswith("chat-") else "agent",
                    # An agent's session carries the title it named its work with.
                    "title": heading or _settings_of(name).get("title") or name,
                    # Read from the record: the public list hides sealed sessions'
                    # settings, and every helper is sealed. Operator only here.
                    "role": _settings_of(name).get("role"),
                    "lead": _settings_of(name).get("lead"),
                    "working": bool(chat_running) or (sess is not None and sess.lock.locked()),
                    "chat_running": chat_running,
                    "browser": running,
                    "tab": tab,
                    "url": url,
                    "page_title": title,
                    "op": activity.get("op"),
                    "ok": activity.get("ok"),
                    "at": activity.get("at"),
                    "since": activity.get("since"),
                    "steps": activity.get("steps", 0),
                    # The app's own model calls only: an MCP agent's model is
                    # its harness's, and ABT never sees those tokens.
                    "tokens": _session_tokens(name, chat_list),
                })
            rows.sort(key=lambda r: (not r["working"], -(r["at"] or 0)))
            return {"now": now, "sessions": rows}

        return await _admin(work)

    # --- one-tap connect: an agent harness gets its own session ------------------

    @app.get("/app/connect")
    async def app_connect_list(request: Request):
        """The agent harnesses on this machine, and which profile each uses."""
        from . import connect as connect_util

        def work():
            _operator(request)
            return connect_util.status()

        return await _admin(work)

    @app.post("/app/connect/{harness}")
    async def app_connect(harness: str, request: Request):
        """Write a harness's MCP entry, its agents' sessions on the profile asked for.

        No session is made here: each agent names its own on its first
        browser call, and shows in the Agents view under that name.
        """
        from . import connect as connect_util

        body = await _object(request)
        if isinstance(body, JSONResponse):
            return body

        def work():
            _operator(request)
            found = connect_util.find(harness)
            profile = str(body.get("profile") or DEFAULT)
            _profiles().require(profile)
            port = request.url.port or 8765
            return connect_util.connect(found.id, profile, f"http://127.0.0.1:{port}")

        return await _admin(work)

    @app.delete("/app/connect/{harness}")
    async def app_disconnect(harness: str, request: Request):
        """Remove a harness's `abt` entry. Its agents' sessions, tabs and logs stay."""
        from . import connect as connect_util

        def work():
            _operator(request)
            return connect_util.disconnect(harness)

        return await _admin(work)

    @app.post("/app/live/{name}/stop")
    async def app_live_stop(name: str, request: Request):
        """Stop the chat replies running in a session, from the Live grid."""

        def work():
            _operator(request)
            stopped = 0
            for (sname, _cid), run in list(runs.items()):
                if sname == name and not run.finished:
                    run.stop.set()
                    stopped += 1
            return {"session": name, "stopped": stopped}

        return await _admin(work)

    @app.get("/app/overview")
    async def app_overview(request: Request):
        """Every conversation, in every session: the app's chat list.

        In the app each chat is its own session, so this is the one list a
        person picks from. Operator only -- it names sealed sessions' chats.
        """

        def work():
            _operator(request)
            replying = {key for key, run in runs.items() if not run.finished}
            rows = []
            for session in registry.list():
                listed = chats.list(session["name"])
                if not session["name"].startswith("chat-") and not any(c.get("messages") for c in listed):
                    # An agent's session, driven over MCP, the CLI or HTTP: no
                    # conversation here, but it is listed so its browser can be
                    # watched -- under the name the agent gave its work.
                    live = registry._live.get(session["name"])
                    at = (live.activity or {}).get("at") if live is not None else None
                    rows.append({
                        "session": session["name"],
                        "profile": session["profile"],
                        "sealed": session["sealed"],
                        "role": None,
                        "lead": None,
                        "agent": True,
                        "chat_id": listed[0]["id"] if listed else "",
                        "title": _settings_of(session["name"]).get("title") or session["name"],
                        "updated": (datetime.fromtimestamp(at, timezone.utc).isoformat()
                                    if at else session.get("created")),
                        "messages": 0,
                        "running": bool(live is not None and live.browser.is_running and at
                                        and time.time() - at < 60),
                    })
                    continue
                for chat in listed:
                    rows.append({
                        "session": session["name"],
                        "profile": session["profile"],
                        "sealed": session["sealed"],
                        "role": _settings_of(session["name"]).get("role"),
                        "lead": _settings_of(session["name"]).get("lead"),
                        "chat_id": chat["id"],
                        "title": chat.get("title") or "New chat",
                        "updated": chat.get("updated"),
                        "messages": chat.get("messages", 0),
                        "running": (session["name"], chat["id"]) in replying,
                    })
            return sorted(rows, key=lambda r: r["updated"] or "", reverse=True)

        return await _admin(work)

    @app.get("/app/runs")
    async def app_runs(request: Request):
        """Which chats in this session are replying right now."""

        def work():
            sess = _chat_session(request)
            return [
                r.chat_id for (name, _), r in runs.items() if name == sess.name and not r.finished
            ]

        return await _admin(work)

    @app.websocket("/app/chat")
    async def app_chat(ws: WebSocket):
        if not _local_origin(ws):
            await ws.close(code=1008)
            return
        params = ws.query_params
        token = ws.headers.get("x-abt-token") or params.get("token")
        await ws.accept()
        try:
            _app_ready()
            sess = await run_in_threadpool(registry.get, params.get("session") or None, token)
        except OpError as exc:
            await ws.send_json(fail(exc))
            await ws.close(code=1008)
            return

        queue: asyncio.Queue = asyncio.Queue()
        watchers.setdefault(sess.name, set()).add(queue)
        # What this page missed: every reply still running in this session,
        # from its first event.
        for (name, _), run in list(runs.items()):
            if name == sess.name and not run.finished:
                queue.put_nowait({"type": "resume", "chat_id": run.chat_id})
                for event in run.events:
                    queue.put_nowait(event)

        async def writer() -> None:
            while True:
                event = await queue.get()
                await ws.send_json(event)

        sender = asyncio.create_task(writer())
        try:
            while True:
                message = await ws.receive_json()
                kind = message.get("type") if isinstance(message, dict) else None
                if kind == "stop":
                    run = runs.get((sess.name, str(message.get("chat_id"))))
                    if run is not None:
                        run.stop.set()
                elif kind == "send":
                    error = await start_run(sess, message)
                    if error:
                        queue.put_nowait(
                            {"type": "error", "text": error, "chat_id": message.get("chat_id")}
                        )
        except (WebSocketDisconnect, RuntimeError):
            pass  # the page left; its replies keep running
        finally:
            watchers.get(sess.name, set()).discard(queue)
            sender.cancel()

    return app


async def _json(request: Request):
    try:
        return await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=fail(OpError("invalid_op", "request body is not valid JSON")),
        )
