"""HTTP surface. The server process is the command loop.

Every request runs in a session. Each session owns a lock, and commands within
a session run in order under it -- a driver is not thread-safe -- while
different sessions never wait on each other. The blocking work is pushed to a
threadpool so a long command never stalls the event loop -- `GET /status`
stays answerable meanwhile.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import messenger as messenger_api
from . import shots as shots_util
from .browser import BrowserSession
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
from .sessions import Session, SingleSessionRegistry
from .viewer import VIEWER_HTML

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
            registry.touch(sess)
            results = []
            for index, item in enumerate(items):
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
            job = jobs.create(parsed)
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
        job = jobs.create(parsed)
        background.add_task(send_job, sess, parsed, job["job_id"])
        return ok(job)

    @app.get("/messenger/jobs")
    async def messenger_jobs():
        return ok(jobs.list())

    @app.get("/messenger/jobs/{job_id}")
    async def messenger_job(job_id: str):
        job = jobs.get(job_id)
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
            if reset and thread_url:
                cursors.reset(thread_url)
            return messenger_api.read_messages(
                sess.browser, thread_url, limit, since_last, cursors
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

    def _root() -> Path | None:
        return recorder.root if recorder is not None else None

    @app.get("/logs")
    async def logs():
        """Every recorded session, newest first."""
        root = _root()
        if root is None:
            return ok({"recording": False, "sessions": []})
        return ok(
            {
                "recording": True,
                "current": recorder.session_id,
                "sessions": await run_in_threadpool(list_sessions, root),
            }
        )

    @app.get("/logs/sites")
    async def logs_sites():
        """Every site touched across every session."""
        root = _root()
        if root is None:
            return ok([])
        return ok(await run_in_threadpool(sites_index, root))

    @app.get("/logs/{session_id}")
    async def logs_session(
        session_id: str,
        site: str | None = None,
        tab: str | None = None,
        op: str | None = None,
        errors_only: bool = False,
    ):
        root = _root()
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
    async def logs_shot(session_id: str, name: str):
        """One recorded frame. Named in the event that produced it."""
        root = _root()
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

    return app


async def _json(request: Request):
    try:
        return await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=fail(OpError("invalid_op", "request body is not valid JSON")),
        )
