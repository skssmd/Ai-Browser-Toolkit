"""Op registry: maps an op name to the handler that runs it."""

from __future__ import annotations

from typing import Any, Callable

from .. import diff
from ..browser import BrowserSession
from ..diff import diff_actionable, diff_html, diff_text, page_key, page_text
from ..errors import OpError
from . import control, inspect, interact, navigate, read, tabs

Handler = Callable[[BrowserSession, Any], Any]

REGISTRY: dict[str, Handler] = {
    "goto": navigate.goto,
    "back": navigate.back,
    "forward": navigate.forward,
    "reload": navigate.reload,
    "current_url": navigate.current_url,
    "get_html": read.get_html,
    "get_text": read.get_text,
    "find": read.find,
    "find_full": read.find_full,
    "screenshot": read.screenshot,
    "click": interact.click,
    "input": interact.input,
    "select": interact.select,
    "hover": interact.hover,
    "scroll": interact.scroll,
    "wait_for": interact.wait_for,
    "press": interact.press,
    "tab_new": tabs.tab_new,
    "tab_list": tabs.tab_list,
    "tab_switch": tabs.tab_switch,
    "tab_close": tabs.tab_close,
    "read_console": inspect.read_console,
    "guidelines_search": control.guidelines_search,
    "guidelines_read": control.guidelines_read,
    "guidelines_note": control.guidelines_note,
    "read_network": inspect.read_network,
    "run_js": control.run_js,
    "alert": control.alert,
    "diff": control.diff,
    "status": control.status,
    "shutdown": control.shutdown,
    "browser_start": control.browser_start,
    "browser_stop": control.browser_stop,
    "browser_restart": control.browser_restart,
    "browser_status": control.browser_status,
    "browser_open_manual": control.browser_open_manual,
}

# Ops that change the page in place and therefore get a before/after diff
# attached to their response when diffing is on.
DIFFABLE_OPS = frozenset(
    {"click", "input", "select", "hover", "scroll", "press", "wait_for", "run_js"}
)

# Ops whose whole purpose is to land somewhere else. Diffing two unrelated
# documents is noise, so these report the page they arrived at instead.
NAVIGATION_OPS = frozenset({"goto", "back", "forward", "reload"})

# Ops that can change the DOM. Their post-command state becomes the baseline for
# the next manual `diff`.
DOM_TOUCHING_OPS = DIFFABLE_OPS | NAVIGATION_OPS | {"tab_new", "tab_close"}

# The health check exists to fail fast instead of hanging on a dead driver. But
# these are exactly what you reach for *when* it has died -- gating them behind
# it means a server whose browser crashed can never recover or be shut down.
#
# The guidelines ops are here for a different reason: they read and write files
# and never touch the page at all. Gating them on a live browser would mean an
# agent could not look up a site's playbook before starting a browser -- which
# is precisely when it is most worth reading.
NO_HEALTH_CHECK = frozenset(
    {
        "shutdown",
        "status",
        "browser_start",
        "browser_stop",
        "browser_restart",
        "browser_status",
        "browser_open_manual",
        "guidelines_search",
        "guidelines_read",
        "guidelines_note",
    }
)


# Said with the payload rather than in the op reference, because the
# reference is bare types -- {"type": "str"} -- and carries no prose at all.
# An agent that is handed "AEDBAAAA" with no legend reads it as an opaque
# ref, which is what one benchmark run did: it quoted the path back in its
# own reasoning to identify a button, then re-read the whole page anyway,
# because nothing connected the prefix to the level argument.
_TREE_LEGEND = (
    "each line begins with where it sits on the page: a letter per level, so a longer prefix is deeper and two lines sharing one sit in the same container (AEDBa and AEDBb are siblings; AEDB is what holds them). That prefix is an address -- read one part of the page again with {\"op\": \"get_text\", \"level\": \"AEDB\"} instead of re-reading all of it."
)


def dispatch(session: BrowserSession, cmd) -> Any:
    handler = REGISTRY.get(cmd.op)
    if handler is None:
        raise OpError("invalid_op", f"no handler registered for op {cmd.op!r}")
    if cmd.op not in NO_HEALTH_CHECK:
        session.health_check()
        # Every command starts on the top document. Frame context is sticky and
        # survives the command that set it, so a click on something inside a
        # sign-in widget would leave the next `run_js` or `get_html` evaluating
        # in the widget. The handlers that need to be somewhere else go there
        # themselves; nobody has to remember to come back.
        session.leave_frames()

    want_diff = session.diff_enabled if getattr(cmd, "diff", None) is None else cmd.diff
    if cmd.op in DIFFABLE_OPS and want_diff:
        return _run_with_diff(session, cmd, handler)
    if cmd.op in NAVIGATION_OPS and want_diff:
        return _run_with_page_text(session, cmd, handler)

    result = handler(session, cmd)
    if cmd.op in DOM_TOUCHING_OPS:
        session.set_baseline()
    return result


def actionable_report(
    session: BrowserSession,
    before: list[dict],
    after: dict,
) -> dict | None:
    """Refs and roles for the controls that just appeared, or None if none did.

    This decorates the text track, it does not compete with it: every entry
    carries the same string the text diff already reported, plus the role that
    says what it is and the ref that acts on it. Controls with no name never
    reach here -- the snapshot drops them -- so nothing is handed back that the
    agent cannot tie to something it has read.

    Deliberately not run after a navigation. On a new document every control is
    "new", so the diff degenerates into a full inventory of the page -- which
    the text track already handed over in full, and which would spend a ref on
    every control to say it. The value here is precision: you clicked, three
    things appeared, here they are.
    """
    entries, indices, truncated = diff_actionable(before, after["actionable"])
    if not entries:
        return None

    # Only now, knowing the handful that matter, are live handles fetched.
    elements = session.actionable_elements(after["actionable"], indices)
    if not elements:
        return None

    # Ref allocation is a convenience, never the point of the command: a driver
    # that will not hand back handles must not turn a successful click into a
    # failure.
    #
    # Allocated one frame at a time, because a ref carries the document its
    # element lives in and a single diff can pick up controls from several --
    # the page's own and two widgets', all in the same click.
    try:
        refs: list[str] = []
        for entry, element in zip(entries, elements):
            refs.extend(
                session.refs.allocate(
                    session.active_tab, [element], tuple(entry.get("frame") or ())
                )
            )
    except Exception:
        return None

    # A `name` identifies a control only while it is unique. Twelve buttons all
    # called "Edit" hand back twelve refs and nothing to choose between them,
    # which is the one place this track stops being an answer -- and the
    # DOM-walking that replaces it is what once opened the wrong row's dialog
    # while reporting success.
    #
    # So only the collisions are qualified, and only they cost anything: no
    # repeated name means no extra round trip, which is every ordinary page.
    seen: dict[str, int] = {}
    for entry in entries:
        seen[entry["name"]] = seen.get(entry["name"], 0) + 1
    ambiguous = [
        position
        for position, entry in enumerate(entries)
        if seen[entry["name"]] > 1
    ]

    context: dict[int, str] = {}
    if ambiguous:
        values = session.actionable_context(
            after["actionable"], [indices[position] for position in ambiguous]
        )
        for position, value in zip(ambiguous, values):
            if value:
                context[position] = value

    added = []
    for position, (entry, ref) in enumerate(zip(entries, refs)):
        item = {"ref": ref, "role": entry["role"], "name": entry["name"]}
        if entry.get("disabled"):
            item["disabled"] = True
        if entry.get("multiple"):
            item["multiple"] = True
        # Never the name it qualifies: a `near` that repeats the label
        # distinguishes nothing and is pure payload.
        near = context.get(position)
        if near and near != entry["name"]:
            item["near"] = near
        added.append(item)
    if not added:
        return None
    return {"added": added, "truncated": truncated}


def note_no_change(info: dict, changed_elements: bool) -> None:
    """Say that nothing changed, rather than leaving a hole where a fact goes.

    An empty diff after a successful command is a real outcome -- the click
    landed and the page did not react -- but reported as an absence it reads
    like a gap in the response, and an agent that mistakes one for the other
    goes back to re-read the page it was just handed. This is the argument the
    shadow-host count already settles: a silence has to say which silence it is.

    Watched happen: a click on a Magento "Content" accordion returned ok with an
    empty diff. The click had landed; that control simply was not the trigger.
    The agent read the empty diff as no information and spent turns hunting for
    a textarea that a different control would have revealed.
    """
    text = info.get("text") or {}
    if info.get("navigation") or text.get("added") or changed_elements:
        return
    if text.get("unchanged_count"):
        return
    info["no_change"] = True
    info["note"] = (
        "the command succeeded and nothing on the page changed -- it landed, "
        "and the page did not react. If you expected a change, this control is "
        "probably not the one that makes it; element_diff:true reports "
        "attribute-only changes a text diff cannot see."
    )


def note_status(info: dict) -> None:
    """Flag a status word in the text this response just returned.

    Traced to a real failure: an agent wrote "$354.66 (Canceled)" and then
    summed that total into "how much I spent" in the same reply -- it read the
    status correctly and the lapse was never re-checking it before the
    arithmetic. This cannot fix a slip that happens after every tool call has
    returned, but it puts the reminder in the same response that showed the
    status, right where the model is about to reason about it.

    Matches "Canceled" and its kin -- the status form -- never "Cancel", the
    imperative a button says before you press it. That grammatical split is
    what keeps this from firing on every Cancel/Delete button on the page.
    """
    added = (info.get("text") or {}).get("added") or []
    hint = diff.status_hint(added)
    if hint:
        info["status_hint"] = hint


def note_shadow(info: dict, after: dict) -> None:
    """Say how many trees this report did not look into, when that matters.

    Shadow roots are counted by the snapshot and never walked, so a change
    inside one shows up as no change at all. That silence is indistinguishable
    from "the page did not react" -- which is exactly the reading that sends an
    agent off hunting with `run_js`.

    Added only where the silence is ambiguous: an empty text diff, or a
    navigation whose "full page" is quietly missing part of itself. An ordinary
    diff that already reports something needs no footnote, and putting one on
    every response is the cost this design exists to avoid.
    """
    hosts = after.get("shadow_hosts", 0)
    if not hosts:
        return
    if info.get("text", {}).get("added") and not info.get("navigation"):
        return
    info["shadow"] = {
        "hosts": hosts,
        "note": (
            "not walked; content inside a shadow root is not in this report. "
            'search it with {"shadow": true}'
        ),
    }


def _run_with_diff(session: BrowserSession, cmd, handler) -> Any:
    """Run an interactive op, then report what it changed on the page.

    Text always; elements only when asked. The text diff is what an agent reads
    to decide its next move, and it carries no markup, so it stays cheap enough
    to be unconditional.
    """
    before = session.snapshot()
    url_before = session.driver.current_url
    navigated_away = False
    try:
        result = handler(session, cmd)
    except OpError:
        after = session.snapshot()
        session.set_baseline(after)
        raise
    except Exception as exc:
        # The op worked and the page navigated *because* it worked -- a
        # <select> that reloads on change, a click that submits. The engine
        # loses its execution context mid-op and raises, and that used to
        # reach the server's catch-all and be reported as `browser_dead`.
        #
        # Which is the most misleading answer available: the browser is fine,
        # the action succeeded, and an agent told its browser died goes off to
        # restart a healthy one. Watched exactly that -- a Magento sort
        # dropdown cost two turns and a failed browser_start before the agent
        # decided the toolkit was wrong and carried on.
        if "execution context was destroyed" not in str(exc).lower():
            raise
        navigated_away = True
        result = {"navigated": True}

    # A click that redirected has landed on a document that may still be
    # rendering, exactly like a goto. Settle before looking, or the diff reports
    # the destination's spinner as though it were the destination.
    navigated = navigated_away or page_key(url_before) != page_key(
        session.driver.current_url
    )
    if navigated:
        session.settle()
    else:
        # The same problem one scale down, and it used to go unhandled: an
        # interaction that stays on the page can still start something that
        # renders later, and snapshotting the instant the handler returns
        # reports the page as it was before its own effect.
        #
        # The case that showed it: typing an airport code into an autocomplete.
        # `input` returned ok with an empty diff, while the suggestion menu --
        # which the form requires you to pick from, and which silently rejects
        # anything you merely typed -- opened 300ms later. A `diff` asked for
        # afterwards showed it perfectly. So the content was never the problem;
        # the moment of the snapshot was.
        #
        # Bounded much tighter than a navigation's budget because every
        # interactive op pays this one. Settling stops as soon as the DOM is
        # still, so a page that does nothing costs the quiet window and not the
        # cap.
        session.settle(timeout=session.interaction_settle)

    after = session.snapshot()
    session.set_baseline(after)
    if not isinstance(result, dict):
        return result

    url_after = session.driver.current_url
    info = {"url_before": url_before, "url_after": url_after}
    if navigated:
        # The click redirected. The old document is gone, so there is nothing to
        # diff -- but the question the caller was asking ("what am I looking at
        # now?") still has an answer, and it is the new page's text.
        info["navigation"] = True
        if navigated_away:
            # Worth stating outright: the op is being reported as a success
            # *because* it navigated, and the caller's refs are now stale.
            info["navigated_during_op"] = True
        # Same reasoning as the plain navigation ops: suppress against a
        # genuinely different page, never against this one. `navigated_away`
        # only means the execution context was destroyed, which a same-page
        # form resubmission can also trigger -- so check the URL, not the flag.
        same_page = page_key(url_before) == page_key(url_after)
        info["note"] = (
            "the page navigated; text is the new page as its tree -- "
            + _TREE_LEGEND
            + (
                ""
                if same_page
                else " Minus what the previous page already showed. "
            )
            + "The element track is skipped because the two documents are "
            "unrelated"
        )
        info["text"] = page_text(
            after["text"], None if same_page else before["text"], cmd.include_removed
        )
    else:
        info["text"] = diff_text(
            before["text"], after["text"], include_removed=cmd.include_removed
        )
        if cmd.element_diff:
            budget = cmd.diff_max_tokens or session.diff_max_tokens
            info["elements"] = diff_html(before["dom"], after["dom"], budget)

        if getattr(cmd, "actionable", True):
            controls = actionable_report(session, before["actionable"], after)
            if controls is not None:
                info["actionable"] = controls

    elements = info.get("elements") or {}
    note_no_change(info, bool(elements.get("added") or elements.get("removed")))
    note_status(info)
    note_shadow(info, after)
    result["dom_diff"] = info
    return result


def _run_with_page_text(session: BrowserSession, cmd, handler) -> Any:
    """Run a navigation op, then hand back the text of the page it landed on.

    No diff: goto/back/forward/reload exist to replace the document, so the
    before and after have nothing in common worth aligning. What the caller
    wants is the destination's content, which they would otherwise have to ask
    for in a second round trip.
    """
    url_before = session.driver.current_url
    before = session.snapshot()
    try:
        result = handler(session, cmd)
    except OpError:
        session.set_baseline()
        raise

    after = session.snapshot()
    session.set_baseline(after)
    if not isinstance(result, dict):
        return result

    url_after = session.driver.current_url
    # Chrome-suppression compares against a genuinely different page -- the
    # thing two pages of the same site share is their nav and footer, not their
    # content. A reload lands on this same page, and back/forward occasionally
    # do too (a same-page anchor, a history entry that never left). There "the
    # previous page" and "the one you are looking at" are the same document, so
    # suppressing against it would hide the very thing the caller reloaded for
    # -- reported once as a live regression: late-arriving content and a
    # cross-origin frame both vanished from a reload's answer because they had
    # already been seen the first time the page loaded.
    same_page = page_key(url_before) == page_key(url_after)
    info = {
        "url_after": url_after,
        "navigation": True,
        "note": "text is the page you landed on, laid out as its tree -- "
        + _TREE_LEGEND
        + (
            ""
            if same_page
            else " Strings the previous page already showed are summarised at "
            "the end rather than repeated."
        ),
        "text": page_text(
            after["text"], None if same_page else before["text"], cmd.include_removed
        ),
    }
    elements = info.get("elements") or {}
    note_no_change(info, bool(elements.get("added") or elements.get("removed")))
    note_status(info)
    note_shadow(info, after)
    result["dom_diff"] = info
    return result
