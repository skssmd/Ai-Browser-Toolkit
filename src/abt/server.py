"""HTTP surface. The server process is the command loop.

Selenium's WebDriver is not thread-safe, so every command runs inside one
threading.Lock. The blocking work is pushed to a threadpool so a long command
never stalls the event loop -- `GET /status` stays answerable meanwhile.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .browser import BrowserSession
from .errors import OpError
from .ops import dispatch
from .ops.control import session_status
from .recorder import (
    SessionRecorder,
    list_sessions,
    now_ms,
    read_events,
    sites_index,
)
from .schema import OP_NAMES, parse_command
from .viewer import VIEWER_HTML


def ok(result: Any) -> dict:
    return {"ok": True, "result": result}


def fail(error: OpError, op_index: int = 0) -> dict:
    return {"ok": False, "error": error.to_dict(op_index)}


def _is_shutdown(item: Any) -> bool:
    return isinstance(item, dict) and item.get("op") == "shutdown"


def create_app(
    session: BrowserSession,
    request_stop: Callable[[], None] | None = None,
    recorder: SessionRecorder | None = None,
) -> FastAPI:
    app = FastAPI(title="aibrowsertoolkit", version="0.1.0")
    app.state.session = session
    app.state.recorder = recorder
    lock = threading.Lock()

    def run_one(data: Any, op_index: int) -> dict:
        """Validate then execute one command. Never raises."""
        started = now_ms()
        try:
            cmd = parse_command(data)
            response = ok(dispatch(session, cmd))
        except OpError as exc:
            response = fail(exc, op_index)
        except Exception as exc:  # an unmapped Selenium surprise
            response = fail(
                OpError("browser_dead", f"{type(exc).__name__}: {exc}"), op_index
            )
        if recorder is not None:
            _record(data, response, now_ms() - started)
        return response

    def _record(data: Any, response: dict, elapsed: float) -> None:
        """Logging must never be able to fail a command."""
        tab_id = url = None
        try:
            tab_id = session.active_tab
            url = session.driver.current_url
        except Exception:
            pass
        try:
            recorder.record(data, response, tab_id, url, elapsed)
        except Exception:
            pass

    def execute(items: list[Any], continue_on_error: bool) -> list[dict]:
        with lock:
            results = []
            for index, item in enumerate(items):
                response = run_one(item, index)
                results.append(response)
                if response["ok"] and _is_shutdown(item):
                    break
                if not response["ok"] and not continue_on_error:
                    break
            return results

    def teardown() -> None:
        # Let the response flush before the process goes away.
        time.sleep(0.25)
        session.quit()
        if recorder is not None:
            recorder.close()
        if request_stop is not None:
            request_stop()

    @app.post("/command")
    async def command(request: Request, background: BackgroundTasks):
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body

        results = await run_in_threadpool(execute, [body], False)
        response = results[0]
        if response["ok"] and _is_shutdown(body):
            background.add_task(teardown)
        return response

    @app.post("/commands")
    async def commands(request: Request, background: BackgroundTasks):
        body = await _json(request)
        if isinstance(body, JSONResponse):
            return body

        if isinstance(body, dict):
            items = body.get("commands")
            continue_on_error = bool(body.get("continue_on_error", False))
        else:
            items, continue_on_error = body, False

        if not isinstance(items, list):
            return JSONResponse(
                status_code=400,
                content=fail(
                    OpError(
                        "invalid_op",
                        "body must be an array of commands, or an object with a "
                        "'commands' array and an optional 'continue_on_error' flag",
                    )
                ),
            )

        results = await run_in_threadpool(execute, items, continue_on_error)

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

    @app.get("/status")
    async def status():
        # Lock-free on purpose: usable while a long command is still running.
        try:
            return ok(await run_in_threadpool(session_status, session))
        except OpError as exc:
            return fail(exc)

    @app.get("/ops")
    async def ops():
        return ok(OP_NAMES)

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
