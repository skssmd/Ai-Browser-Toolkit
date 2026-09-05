"""Control ops: arbitrary JS, native dialogs, session status, shutdown."""

from __future__ import annotations

from .. import doctor, proc
from ..browser import BrowserSession, _profile_locked
from ..diff import diff_html, diff_text, page_key, page_text
from ..engine import EngineError, NoAlert, ScriptError
from ..errors import OpError
from ..paths import default_log_dir


def run_js(session: BrowserSession, cmd) -> dict:
    """Run a script body and hand back what it returned.

    The script is a function *body*, not an expression, so a value only comes
    back if the script says `return`. That trips people, and silently: a
    watched agent sent `1+1`, got null, concluded "run_js return values aren't
    surfaced", and spent three turns building a workaround that wrote results
    into the DOM and read them back out. Nothing was broken. Nothing in the
    documentation said otherwise either -- the workflow mentions run_js nine
    times and every one of them is telling you not to use it.

    So when a script returns nothing and contains no `return` at all, the
    reply says why. The check is deliberately conservative: a script that does
    contain `return` may still legitimately produce null, and guessing at that
    would be worse than staying quiet.
    """
    if not session.run_js_enabled:
        raise OpError(
            "invalid_op",
            "run_js is disabled on this server",
            hint=(
                "Read the page with get_text and act on the address each line "
                "carries: a line whose address holds # is a control, and "
                '{"op": "click", "level": "AEDBa"} operates it. `find` returns '
                "a level per match for anything you need to search for."
            ),
        )

    try:
        value = session.driver.execute_script(cmd.script, *cmd.args)
    except ScriptError as exc:
        raise OpError("js_error", f"script threw: {exc.msg or exc}") from exc
    except EngineError as exc:
        raise OpError("js_error", f"script failed: {exc.msg or exc}") from exc

    result = {"value": value}
    if value is None and not "return" in (cmd.script or ""):
        result["hint"] = (
            "value is null because this script has no `return`. The script is "
            "a function body, not an expression: `1+1` evaluates and discards, "
            "`return 1+1;` hands back 2. Add `return` to whatever you want to "
            "read. Do not write results into the DOM to read them back -- that "
            "is two round trips for something already returned."
        )
    return result


def alert(session: BrowserSession, cmd) -> dict:
    """Inspect or answer a native browser dialog (alert/confirm/prompt)."""
    try:
        dialog = session.driver.switch_to.alert
    except NoAlert:
        return {"present": False}

    message = None
    try:
        message = dialog.text
    except EngineError:
        pass

    if cmd.action == "text":
        return {"present": True, "text": message}
    if cmd.action == "accept":
        dialog.accept()
    elif cmd.action == "dismiss":
        dialog.dismiss()
    else:  # send_text
        dialog.send_keys(cmd.text or "")
        dialog.accept()
    return {"present": True, "text": message, "action": cmd.action}


def diff(session: BrowserSession, cmd) -> dict:
    """Diff the current page against the last known state, or re-baseline."""
    tab_id = session.active_tab
    entry = session.baseline()

    if cmd.reset or entry is None:
        session.set_baseline()
        return {
            "baseline": "set",
            "tab_id": tab_id,
            "url": session.driver.current_url,
            "note": "baseline is now the current page",
        }

    after = session.snapshot()
    session.set_baseline(after)
    url_after = session.driver.current_url
    navigated = page_key(entry["url"]) != page_key(url_after)
    payload = {
        "baseline": "present",
        "tab_id": tab_id,
        "url_before": entry["url"],
        "url_after": url_after,
    }
    if navigated:
        from . import landing_text

        payload["navigation"] = True
        payload["text"], note = landing_text(
            session, entry["text"], after["text"], entry["url"], url_after, cmd
        )
        payload["note"] = (
            "the page changed since the baseline; "
            + note
            + ". The element track is skipped"
        )
    else:
        payload["text"] = diff_text(
            entry["text"], after["text"], include_removed=cmd.include_removed
        )
        if cmd.element_diff:
            payload["elements"] = diff_html(entry["dom"], after["dom"], cmd.max_tokens)

    # After the diff, never before it -- see `remember_seen`.
    session.remember_seen(after)
    return payload


# --- browser lifecycle ------------------------------------------------------


def browser_state(session: BrowserSession) -> dict:
    """Lifecycle state, answerable with no browser present.

    Two configs, because one key cannot answer both questions. `config` is what
    is running now (or ran most recently), which is what a bare browser_restart
    will use. `defaults` is what `abt serve` was given, which is what a bare
    browser_start will use.
    """
    return {
        "running": session.is_running,
        "config": session.config.to_dict(),
        "defaults": session.defaults.to_dict(),
    }


def browser_start(session: BrowserSession, cmd) -> dict:
    return session.start(
        browser=cmd.browser, profile=cmd.profile, headless=cmd.headless
    )


def browser_stop(session: BrowserSession, cmd) -> dict:
    return session.stop()


def browser_restart(session: BrowserSession, cmd) -> dict:
    return session.restart(
        browser=cmd.browser, profile=cmd.profile, headless=cmd.headless
    )


def browser_status(session: BrowserSession, cmd) -> dict:
    return browser_state(session)


def browser_open_manual(session: BrowserSession, cmd) -> dict:
    """Launch the real installed browser directly, bypassing Selenium/Playwright.

    For sites -- Google among them -- that block a CDP-controlled browser at
    sign-in no matter what anti-detection flags `_make_options` sets. Fire and
    forget: the caller logs in by hand and closes the window; `browser_start`
    then picks up the saved session on the same profile.

    Refuses rather than stopping abt's own browser for the caller, on purpose:
    a profile is never safely shared between two running browsers, and both
    directions of that swap (which one to keep, whether to wait) are the
    caller's call, not this op's to make silently.
    """
    config = session.defaults.merge(browser=cmd.browser, profile=cmd.profile)
    if session.is_running:
        raise OpError(
            "invalid_op",
            "abt's browser is already running on this profile; run "
            "browser_stop first, then open a manual window on the same profile.",
        )
    if _profile_locked(config):
        raise OpError(
            "invalid_op",
            f"a browser already has the profile at {config.profile} open; "
            "close it, then try again.",
        )
    browsers = {b.name: b.path for b in doctor.find_browsers()}
    binary = browsers.get(config.browser)
    if binary is None:
        raise OpError(
            "browser_not_found",
            f"no installed {config.browser} found; run "
            "`abt doctor --install-browser` to install one.",
        )
    config.profile.mkdir(parents=True, exist_ok=True)
    log_dir = default_log_dir()
    proc.spawn_detached(
        [str(binary), f"--user-data-dir={config.profile}"],
        cwd=config.profile,
        stdout=log_dir / "manual-browser.log",
        stderr=log_dir / "manual-browser.err",
    )
    return {
        "launched": True,
        "browser": config.browser,
        "profile": str(config.profile),
    }


def status(session: BrowserSession, cmd) -> dict:
    return session_status(session)


def session_status(session: BrowserSession) -> dict:
    """Where the session is, or that there is no session.

    `running` is always present. Everything else is only meaningful with a
    browser up, and a caller that reads `url` without checking `running` should
    find it missing rather than find a lie.
    """
    if not session.is_running:
        return browser_state(session)
    tabs = session.tabs()
    active = session.active_tab
    return {
        "running": True,
        "url": session.driver.current_url,
        "title": session.driver.title,
        "active_tab": active,
        "tabs": tabs,
        "headless": session.headless,
        "profile": str(session.profile),
    }


def shutdown(session: BrowserSession, cmd) -> dict:
    # The server tears the browser down after the response is sent, so the
    # caller gets confirmation instead of a dropped connection.
    return {"stopping": True}


# --- playbooks ----------------------------------------------------------------
#
# Reachable from an agent for the first time here. They were CLI-only and
# read-only over HTTP, so the one feature meant to compound across runs never
# accumulated anything: every agent rediscovered every site.


def guidelines_search(session: BrowserSession, cmd) -> dict:
    from .. import guidelines

    found = guidelines.search(cmd.query, limit=cmd.limit)
    if found.get("matches"):
        # A match reports `domain` and `files` separately, so the name to read
        # has to be assembled -- and guidelines_read's own hint promises this
        # call "returns the exact names". Spell them out rather than leaving
        # the caller to guess the join.
        names = [
            f"{match['domain']}/{filename}"
            for match in found["matches"]
            for filename in (match.get("files") or [])
        ]
        found["note"] = (
            f"Read it before your first op. Exact names to pass to "
            f"guidelines_read: {names}. This is a note from an agent who "
            f"already worked this site out -- following it costs one call and "
            f"saves the turns they spent finding out."
        )
    if not found.get("matches"):
        # An empty lookup is the moment an agent closes the subject and starts
        # driving, so it is the last chance to say that the general workflow
        # exists and that writing one back is the other half of the job. An
        # agent that read this, found nothing and moved on is exactly how a
        # site gets rediscovered from scratch for the tenth time.
        found["note"] = (
            "No playbook for this site. That is normal and is an answer -- most "
            "sites have none, so carry on rather than searching again another "
            'way. If you have not read it yet, {"op": "guidelines_read", '
            '"name": "toolkit-workflow"} is the general workflow for driving '
            "this toolkit and is worth the one call. When you work something "
            "out here, leave a guidelines_note behind so the next run starts "
            "ahead of where you did."
        )
    return found


def guidelines_read(session: BrowserSession, cmd) -> dict:
    from .. import guidelines

    try:
        return {"name": cmd.name, "text": guidelines.read(cmd.name)}
    except KeyError as exc:
        raise OpError(
            "element_not_found",
            f"no playbook named {cmd.name!r}",
            hint="Run guidelines_search first; it returns the exact names.",
        ) from exc


_NOTE = """
## {title}
- **URL:** {url}
- **What happened:** {problem}
- **Tried and learned:** {tried}
- **Solution:** {solution}
- *recorded {when} by an agent*
"""


def _entry_titles(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def _drop_entry(text: str, title: str) -> tuple[str, bool]:
    """Cut one entry out by its heading, leaving every other entry untouched.

    Surgical on purpose. An agent that could rewrite the file would eventually
    erase what earlier runs learned; an agent that can only cut the one entry
    it is superseding can correct the record without being able to lose it.
    """
    want = title.strip().lower()
    kept: list[str] = []
    skipping = False
    dropped = False
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            skipping = False
            if line[3:].strip().lower() == want:
                skipping = dropped = True
                continue
        if not skipping:
            kept.append(line)
    return "".join(kept), dropped


def guidelines_note(session: BrowserSession, cmd) -> dict:
    """Add an entry to this domain's playbook, creating the file if needed.

    Appends by default: a playbook is a list that grows, and an agent that
    could overwrite it would erase the work of every run before it.

    `replaces` is the one exception, and it is deliberately narrow. Appending
    is safe until an earlier entry turns out to be wrong -- then the file holds
    two entries that contradict each other and the next reader cannot tell
    which won. Naming the superseded entry cuts exactly that one and nothing
    else, so the record can be corrected without being able to be lost.

    A `replaces` that matches nothing still saves the note, and says so. The
    alternative is discarding what the agent just learned over a mistyped
    title, which costs more than the duplicate does.
    """
    from datetime import date

    from .. import guidelines

    name = f"{cmd.domain}/learned.md"
    try:
        existing = guidelines.read(name)
    except KeyError:
        existing = f"# {cmd.domain}\n\nWhat agents have had to work out here.\n"

    wanted = (getattr(cmd, "replaces", None) or "").strip()
    replaced: str | None = None
    if wanted:
        existing, dropped = _drop_entry(existing, wanted)
        replaced = wanted if dropped else None

    entry = _NOTE.format(
        title=cmd.title.strip(),
        url=cmd.url.strip(),
        problem=cmd.problem.strip(),
        tried=cmd.tried.strip(),
        solution=cmd.solution.strip(),
        when=date.today().isoformat(),
    )
    try:
        path = guidelines.save(cmd.domain, "learned.md", existing.rstrip() + "\n" + entry)
    except (KeyError, OSError) as exc:
        raise OpError("invalid_op", f"could not save a note for {cmd.domain!r}: {exc}") from exc

    result = {
        "saved": str(path),
        "domain": cmd.domain,
        "entries": existing.count("\n## ") + 1,
        "note": (
            "Stored locally. A pull will not overwrite it and it is not shared "
            "-- `abt guidelines submit` is the separate step for that."
        ),
    }
    if wanted:
        result["replaced"] = replaced
        if replaced is None:
            titles = _entry_titles(existing)
            result["hint"] = (
                f"saved, but nothing was replaced: no entry is titled "
                f"{wanted!r}. The playbook now holds both. Titles present: "
                f"{titles}. Send another note with `replaces` set to one of "
                f"those, copied exactly, to retire the wrong one."
            )
    return result
