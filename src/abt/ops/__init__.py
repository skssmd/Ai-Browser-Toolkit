"""Op registry: maps an op name to the handler that runs it."""

from __future__ import annotations

from typing import Any, Callable

from .. import diff
from ..browser import BrowserSession
from ..diff import diff_html, diff_text, page_key, page_text
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
    "each line begins with where it sits on the page: a letter per level, so a longer prefix is deeper and two lines sharing one sit in the same container (AEDBa and AEDBb are siblings; AEDB is what holds them). That prefix is an address -- read one part of the page again with {\"op\": \"get_text\", \"level\": \"AEDB\"} instead of re-reading all of it. "
    "A line whose address carries # is interactable and is an edge -- everything inside it is on that one line -- and the same address acts on it: #btn #lnk #inp #sel #chk #rad #file. Click it with {\"op\": \"click\", \"level\": \"AEDBa\"}, type with {\"op\": \"input\", \"level\": \"AEDBc\", \"value\": \"...\"}. "
    "A link shows its target after an arrow; an input shows its name in the mark (#inp-q) and its current value as the text; a #sel shows the option it currently holds, and you set it by sending that option's text as the value; a #chk or #rad holds whether it is set, and you set that the same way, with a value of \"true\" or \"false\"."
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


def note_status(session: BrowserSession, info: dict) -> None:
    """Flag a status word in the text this response just returned.

    Traced to a real failure: an agent wrote "$354.66 (Canceled)" and then
    summed that total into "how much I spent" in the same reply -- it read the
    status correctly and never re-checked it before the arithmetic. Verified
    fixed: rerun with this hint attached, the same page produced "which is
    Canceled (no money spent)" and excluded it, where before it had summed the
    row anyway. The hint reaches the model because it rides on the very
    response that named the status -- there is no later point it needs to
    reach, the reasoning that goes wrong happens over data already in hand.

    Matches "Canceled" and its kin -- the status form -- never "Cancel", the
    imperative a button says before you press it. That grammatical split is
    what keeps this from firing on every Cancel/Delete button on the page.

    Once per session, regardless of how many rows or pages repeat the same
    status: an agent told once to check statuses before summing does not need
    the identical sentence on every page of a five-page order history, and a
    line repeated that often is a line stopped being read.
    """
    if session.status_warned:
        return
    added = (info.get("text") or {}).get("added") or []
    hint = diff.status_hint(added)
    if hint:
        info["status_hint"] = hint
        session.status_warned = True


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
            # *because* it navigated, and the addresses the caller was holding
            # describe a page that is no longer on screen.
            info["navigated_during_op"] = True
        # A click that redirected lands exactly where a goto lands, so it is
        # told apart the same way -- by host, in `landing_text`. `navigated_away`
        # only means the execution context was destroyed, which a same-page
        # form resubmission can also trigger, so the URL decides and not the
        # flag.
        info["text"], note = landing_text(
            session, before["text"], after["text"], url_before, url_after, cmd
        )
        info["note"] = (
            "the page navigated; "
            + note
            + ". The element track is skipped because the document was replaced"
        )
    else:
        info["text"] = diff_text(
            before["text"], after["text"], include_removed=cmd.include_removed
        )
        if cmd.element_diff:
            budget = cmd.diff_max_tokens or session.diff_max_tokens
            info["elements"] = diff_html(before["dom"], after["dom"], budget)

        # The actionable track used to ride here as its own block: a ref, a role
        # and a name for each control that appeared, beside the text line that
        # had already reported the same words. It is now on that line -- the
        # address carries #role and acts directly -- so sending it twice is
        # what this removal stops. Controls with no name are no longer dropped
        # either: an unlabelled icon had nothing to decorate before and has its
        # own line now.

    # After the diff, never before it -- see `remember_seen`. In-page changes
    # count too: text a click revealed has been read, so a later navigation to
    # a page carrying the same text should not send it again.
    session.remember_seen(after)

    elements = info.get("elements") or {}
    note_no_change(info, bool(elements.get("added") or elements.get("removed")))
    note_status(session, info)
    note_shadow(info, after)
    result["dom_diff"] = info
    return result


def landing_text(
    session, before: list, after: list, url_before: str, url_after: str, cmd
) -> tuple[dict, str]:
    """What to say about a page you arrived on, and how to describe it.

    Three cases, and the host is what separates them.

    You did not really leave (a reload, a same-page history move): there is no
    other document, so the whole tree comes back unsuppressed. Hiding anything
    here would hide the very thing a reload was asked for -- that was a live
    regression once, late-arriving content and a cross-origin frame both gone
    from a reload's answer because the first load had already shown them.

    You arrived somewhere: what comes back is the page minus everything this
    session has already been given. Not minus the page you just left -- that was
    the old rule and it was one page deep, so it held while you moved forward
    and broke the moment you doubled back. A to B withheld the shared furniture
    correctly; B back to A returned the whole of A as though it were new,
    because relative to B it was. Over 61 gitlab episodes 21.6% of every
    character delivered was a line already delivered in that same episode, and
    doubling back is what these tasks do: open a list, open an item, return to
    the list, open the next.

    The reference is each page's full snapshot, kept here, never the diff that
    was printed from it -- a line withheld from B's report is still on B, so it
    still counts as seen when C is reported. What was withheld is summarised
    with a level to ask for, so nothing is unreachable, only unrepeated.
    """
    same_page = page_key(url_before) == page_key(url_after)
    seen = None if same_page else getattr(session, "seen_text", None)
    return (
        page_text(
            after,
            None if same_page else before,
            cmd.include_removed,
            seen=seen,
            seen_from=None if same_page else getattr(session, "seen_from", None),
        ),
        "text is the page you landed on, laid out as its tree -- "
        + _TREE_LEGEND
        + (
            ""
            if same_page
            else " Anything you have already been shown is summarised at the "
            "end rather than repeated."
        ),
    )


def _run_with_page_text(session: BrowserSession, cmd, handler) -> Any:
    """Run a navigation op, then hand back what the page it landed on says.

    Within one site that is a diff; leaving it is not. See `landing_text`.
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
    text, note = landing_text(
        session, before["text"], after["text"], url_before, url_after, cmd
    )
    session.remember_seen(after)
    info = {
        "url_after": url_after,
        "navigation": True,
        "note": note,
        "text": text,
    }
    elements = info.get("elements") or {}
    note_no_change(info, bool(elements.get("added") or elements.get("removed")))
    note_status(session, info)
    note_shadow(info, after)
    result["dom_diff"] = info
    return result
