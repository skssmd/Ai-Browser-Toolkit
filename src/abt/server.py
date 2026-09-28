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
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import messenger as messenger_api
from . import screencast as screencast_util
from . import shots as shots_util
from .browser import NO_BROWSER_MESSAGE, BrowserSession
from .engine import EngineError
from .errors import OpError
from .ops import dispatch
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


def _unmapped(exc: Exception) -> OpError:
    """Give an exception nobody translated the least wrong type available.

    Everything used to land on `browser_dead`, which is the most expensive
    wrong answer the toolkit can give: its hint tells the caller to restart
    the browser, so an agent stops working on the page and starts working on
    the toolkit. A timeout in particular says nothing about the browser being
    dead -- it is the ordinary way a wait ends.

    Ops should translate their own failures; this is the net under them, and
    a `browser_dead` reaching here should be read as a missing translation.
    """
    name = type(exc).__name__
    detail = f"{name}: {exc}"
    if "Timeout" in name:
        return OpError("timeout", detail)
    if "NoSuchWindow" in name:
        # A shared session whose last tab was released or taken over has no
        # page at all. The browser is fine; the session needs a tab.
        return OpError(
            "tab_not_found",
            f"this session has no tab to act on ({detail})",
            hint="Open one with tab_new, or tab_claim an unowned tab from tab_list.",
        )
    return OpError("browser_dead", detail)


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
    app = FastAPI(title="aibrowsertoolkit", version="0.1.0")
    app.state.registry = registry
    # The default session's browser, for callers that predate sessions.
    app.state.session = registry.get(None).browser
    app.state.recorder = recorder
    jobs = messenger_api.JobRegistry()
    cursors = messenger_api.MessageCursors()
    app.state.messenger_jobs = jobs
    app.state.messenger_cursors = cursors
    # One cursor set per session: `since_last` in one session must not use up
    # what another has not read yet.
    cursor_sets: dict[str, messenger_api.MessageCursors] = {DEFAULT: cursors}

    def _cursors(sess: Session) -> messenger_api.MessageCursors:
        return cursor_sets.setdefault(sess.name, messenger_api.MessageCursors())

    def _session_for(request: Request) -> Session:
        name = request.headers.get("x-abt-session") or request.query_params.get("session")
        token = request.headers.get("x-abt-token") or request.query_params.get("token")
        return registry.get(name or None, token or None)

    def run_one(sess: Session, data: Any, op_index: int) -> dict:
        """Validate then execute one command. Never raises."""
        browser = sess.browser
        started = now_ms()
        browser.last_target = None
        try:
            cmd = parse_command(data)
            response = ok(dispatch(browser, cmd))
        except OpError as exc:
            response = fail(exc, op_index)
        except Exception as exc:  # an unmapped Selenium surprise
            response = fail(_unmapped(exc), op_index)
        if sess.recorder is not None:
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

    def execute(sess: Session, items: list[Any], continue_on_error: bool) -> list[dict]:
        with sess.lock:
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
                results.append(response)
                if response["ok"] and _is_shutdown(item):
                    break
                if not response["ok"] and not continue_on_error:
                    break
            return results

    def teardown() -> None:
        # Let the response flush before the process goes away.
        time.sleep(0.25)
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

    # --- messenger ------------------------------------------------------------

    def run_locked(sess: Session, work: Callable[[], Any], request: dict) -> dict:
        """Run one browser job under the session's lock, logged like a command."""
        started = now_ms()
        try:
            with sess.lock:
                if sess.closed:
                    raise OpError("unknown_session", f"session {sess.name!r} was removed")
                registry.touch(sess)
                sess.browser.last_target = None
                sess.browser.health_check()
                response = ok(work())
        except OpError as exc:
            response = fail(exc)
        except Exception as exc:
            response = fail(OpError("browser_dead", f"{type(exc).__name__}: {exc}"))
        if sess.recorder is not None:
            _record(sess, request, response, now_ms() - started)
        return response

    def send_job(sess: Session, request: messenger_api.SendMessage, job_id: str) -> None:
        jobs.start(job_id)
        body = {"op": "messenger_send", "job_id": job_id, **request.model_dump()}
        response = run_locked(
            sess, lambda: messenger_api.send_in_new_tab(sess.browser, request), body
        )
        if response["ok"]:
            jobs.finish(job_id, response["result"])
        else:
            jobs.fail(job_id, response["error"])

    @app.post("/messenger/sendmessage")
    async def messenger_send(request: Request, background: BackgroundTasks):
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body
        try:
            sess = _session_for(request)
            parsed = messenger_api.parse_send(body)
        except OpError as exc:
            return JSONResponse(status_code=400, content=fail(exc))

        if parsed.background:
            job = jobs.create(parsed, session=sess.name)
            background.add_task(send_job, sess, parsed, job["job_id"])
            return ok(job)
        return await run_in_threadpool(
            run_locked,
            sess,
            lambda: messenger_api.send(sess.browser, parsed),
            {"op": "messenger_send", **body},
        )

    @app.post("/messenger/sendmessage/async")
    async def messenger_send_async(request: Request, background: BackgroundTasks):
        """Queue a send and answer immediately. Same body, background forced on."""
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body
        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400,
                content=fail(OpError("invalid_op", "body must be an object")),
            )
        try:
            sess = _session_for(request)
            parsed = messenger_api.parse_send({**body, "background": True})
        except OpError as exc:
            return JSONResponse(status_code=400, content=fail(exc))
        job = jobs.create(parsed, session=sess.name)
        background.add_task(send_job, sess, parsed, job["job_id"])
        return ok(job)

    @app.get("/messenger/jobs")
    async def messenger_jobs(request: Request):
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        return ok(jobs.list(session=sess.name))

    @app.get("/messenger/jobs/{job_id}")
    async def messenger_job(job_id: str, request: Request):
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)
        job = jobs.get(job_id)
        if job is not None and job.get("session") != sess.name:
            # Someone else's job is indistinguishable from no job.
            job = None
        if job is None:
            return JSONResponse(
                status_code=404,
                content=fail(OpError("invalid_op", f"no job {job_id!r}")),
            )
        return ok(job)

    @app.get("/messenger/threads")
    async def messenger_threads(request: Request, limit: int = 50, url: str | None = None):
        """The sidebar: every visible thread, its preview, and its link."""
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)

        def work():
            if url:
                sess.browser.goto(url)
            return messenger_api.list_threads(sess.browser, limit)

        return await run_locked_async(
            sess, work, {"op": "messenger_threads", "limit": limit}
        )

    @app.get("/messenger/messages")
    async def messenger_messages(
        request: Request,
        thread_url: str | None = None,
        limit: int = 50,
        since_last: bool = False,
        reset: bool = False,
    ):
        """Messages in a thread. `since_last` returns only what is new."""
        try:
            sess = _session_for(request)
        except OpError as exc:
            return _refused(exc)

        def work():
            session_cursors = _cursors(sess)
            if reset and thread_url:
                session_cursors.reset(thread_url)
            return messenger_api.read_messages(
                sess.browser, thread_url, limit, since_last, session_cursors
            )

        return await run_locked_async(
            sess,
            work,
            {"op": "messenger_messages", "thread_url": thread_url, "since_last": since_last},
        )

    async def run_locked_async(sess: Session, work, request: dict) -> dict:
        return await run_in_threadpool(run_locked, sess, work, request)

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
                    "all; browser_restart is the way out if it never frees up"
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
            # commands. `abt browser restart` is the way out.
            return fail(
                OpError(
                    "browser_dead",
                    f"browser is not reachable ({type(exc).__name__}: {exc}). "
                    f"Try `abt browser restart`.",
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
        registry.profiles.watch(profile, +1)
        try:
            await screencast_util.relay(
                ws, f"ws://127.0.0.1:{port}/devtools/page/{target}", upload_root=uploads
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
        return _session_for(request)

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
                # session's uploads folder, whatever the session's setting.
                from .ops.interact import STRICT_UPLOADS

                STRICT_UPLOADS.set(True)
                # The person never presses "start": a chat that needs the page
                # gets a browser, and one that died under it gets a new one
                # and the same commands again, once.
                needs_page = any(
                    isinstance(item, dict)
                    and not str(item.get("op", "")).startswith(("browser_", "guidelines_"))
                    and item.get("op") != "status"
                    for item in items
                )
                if needs_page and not sess.browser.is_running:
                    execute(sess, [{"op": "browser_start"}], False)
                results = execute(sess, items, keep_going)
                # A dead Chrome does not always say so: a goto into it fails
                # as navigation_failed. So on any failure, ask the browser
                # itself whether it is still there.
                if needs_page and any(not r["ok"] for r in results) and browser_gone(sess):
                    if execute(sess, [{"op": "browser_restart"}], False)[0]["ok"]:
                        results = execute(sess, items, keep_going)
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

    runs: dict[tuple[str, str], ChatRun] = {}
    watchers: dict[str, set] = {}  # session -> the queues of pages watching it

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
        if current is not None and not current.finished:
            return "this chat is still working on the last message"
        text = str(message.get("text") or "").strip()
        try:
            chat = await run_in_threadpool(chats.get, sess.name, chat_id)
        except OpError as exc:
            return exc.message
        settings = app_settings.load()
        models = [m for m in [message.get("model"), chat.get("model"), *settings["models"]] if m]
        chat["messages"].append({"role": "user", "content": text})
        if chat.get("title") in (None, "", "New chat"):
            chat["title"] = text[:60] or "New chat"
        run = ChatRun(sess.name, chat_id)
        runs[key] = run
        loop = asyncio.get_running_loop()
        publish(run, {"type": "user", "text": text})

        def emit(event: dict) -> None:
            loop.call_soon_threadsafe(publish, run, event)

        def work() -> None:
            tool_list = agent_util.tools()
            system = agent_util.system_prompt(
                sess.record.settings.get("rules"), sess.browser.run_js_enabled
            )
            try:
                used = agent_util.run_turn(
                    chat["messages"],
                    models=models,
                    complete_fn=lambda model, msgs: agent_util.complete(
                        settings["endpoint"], settings["api_key"], model, msgs, tool_list,
                        on_text=lambda piece: emit({"type": "delta", "text": piece}),
                    ),
                    call_tool=lambda name, args: call_tool(sess, name, args),
                    emit=emit,
                    should_stop=run.stop.is_set,
                    system=system,
                )
                if used:
                    chat["model"] = used
            except Exception as exc:  # the chat must say so, not go quiet
                emit({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
            finally:
                chats.save(sess.name, chat)

                def finish() -> None:
                    run.finished = True
                    publish(run, {"type": "done", "title": chat["title"]})

                loop.call_soon_threadsafe(finish)

        loop.run_in_executor(None, work)
        return None

    # --- files: the session's uploads and downloads folders ------------------------

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
        """Save a file the person picked into the session's uploads folder."""
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
