"""Reference only: the Messenger part of `create_app` in src/abt/server.py.

Nothing imports this. Both pieces sat inside `create_app`: the registries
right after `app.state.recorder = recorder`, the routes after
`app.post("/command-list")(_command_list)`. See README.md.
"""

# --- state, inside create_app ---
    jobs = messenger_api.JobRegistry()
    cursors = messenger_api.MessageCursors()
    app.state.messenger_jobs = jobs
    app.state.messenger_cursors = cursors
    # One cursor set per session: `since_last` in one session must not use up
    # what another has not read yet.
    cursor_sets: dict[str, messenger_api.MessageCursors] = {DEFAULT: cursors}

    def _cursors(sess: Session) -> messenger_api.MessageCursors:
        return cursor_sets.setdefault(sess.name, messenger_api.MessageCursors())


# --- routes, inside create_app ---
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

