"""Finding and entering the documents a page embeds inside itself.

A frame is a separate document with a separate DOM. The parent's TreeWalker
treats `<iframe>` as a leaf, `innerText` stops at the boundary, and WebDriver
only ever searches the frame it is currently switched into. So all three
snapshot tracks are blind in the same place at the same time, and the blindness
is silent: the page reports fine, just without whatever is inside.

That is not an edge case. The controls most worth clicking are the ones a page
did not write itself -- the sign-in widget, the card field, the CAPTCHA, the
embedded editor -- and those arrive as somebody else's frame.

**Why this goes through WebDriver rather than JavaScript.** Recursing into
`iframe.contentDocument` from the snapshot script is shorter and works
perfectly on same-origin frames, which is to say it works on the frames nobody
needed help with. The browser refuses that access across origins, and the
frames that matter are cross-origin almost by definition. `switch_to.frame`
has no such limit, so it is the only approach that answers the case this was
written for.

**What it costs.** This is on the diff's hot path, which is the thing the
toolkit is for, so the budget is round trips rather than work. A page with no
frames pays *nothing*: the snapshot script already walks the document, so it
reports the frames it found in the same call that was happening anyway, and a
frameless answer ends the matter without one extra request. A page with frames
pays a lookup, a switch and a snapshot for each, bounded on both depth and
count, and skips anything too small to see or click.

There was a cheaper version that dropped the lookup. See `enter` for what it
cost instead.
"""

from __future__ import annotations

from .engine import By, EngineError

# Frames, in the one ordering everything here uses: where the elements sit in
# the document. `find_elements` and `querySelectorAll` agree on it, which is
# what makes a position mean the same thing to the scan and to the switch.
_FRAME_SELECTOR = "iframe, frame"

# Frames walked per snapshot. An ad-heavy page can carry dozens, all of them
# somebody else's inventory; the cap keeps a pathological page from turning one
# snapshot into fifty round trips.
MAX_FRAMES = 8

# How deep to descend. Nesting past this is rare and the cost compounds, so the
# default reaches a widget inside a widget and stops.
MAX_FRAME_DEPTH = 2

# Below this, on either axis, there is nothing a person could read or hit. The
# 0x0 preload frame Google Identity Services mounts beside its real button is
# the canonical one -- loaded, functional, and invisible.
MIN_FRAME_PX = 4


# The same question the snapshot script answers inline, for the callers that
# only want to know where the frames are -- `find`, `get_text`, resolving a
# selector -- and have no reason to pay for a snapshot to learn it.
_SCAN_JS = """
const out = [];
// Not `|| 4`: a threshold of 0 is a legitimate "walk everything", and the
// falsy fallback would quietly turn it back into 4.
const min = arguments[0] == null ? 4 : arguments[0];
const nodes = document.querySelectorAll('iframe, frame');
for (let i = 0; i < nodes.length; i++) {
  const f = nodes[i];
  if (f.getClientRects().length === 0) continue;
  if (f.offsetWidth < min || f.offsetHeight < min) continue;
  out.push(i);
}
return out;
"""


def child_slots(driver, min_px: int = MIN_FRAME_PX) -> list[int]:
    """Frames worth walking inside whichever document the driver is in now."""
    try:
        found = driver.execute_script(_SCAN_JS, min_px)
    except EngineError:
        return []
    return [int(slot) for slot in found or []]


def leave(driver) -> None:
    """Put the driver back on the top document. Never raises.

    Frame context is sticky: it survives the command that set it and silently
    retargets every later one, so anything that enters a frame has to be able
    to get back unconditionally.
    """
    try:
        driver.switch_to.default_content()
    except EngineError:
        pass


def enter(driver, path: tuple[int, ...]) -> bool:
    """Switch into the frame at `path`, from the top down. False if it is gone.

    A path is document positions -- where each `<iframe>` sits among its
    siblings -- not handles, because a WebElement for a frame is only valid in
    its parent and there is nothing else durable to hold. The cost is that a
    page which adds or removes a frame between snapshot and use shifts the ones
    after it: the same exposure `find` has always had, and the reason a ref
    still verifies the element it lands on.

    **Each step fetches the element rather than passing the number.** Handing
    the driver an integer is one request instead of two and was worth 32ms a
    frame, but it means something else. A page has two orderings of its frames
    -- document order, and the `window.frames` order that the WebDriver spec
    says an integer indexes -- and they are not always the same list. On
    linkedin.com/login they are exactly reversed: Google's 0x0 boot frame is
    first in the DOM and second in `window.frames`, because Chrome orders that
    list by when each context attached.

    So the fast version skipped the boot frame, entered it anyway, and reported
    its contents as the page while the real sign-in button stayed invisible --
    the same silent wrong answer this whole module exists to remove, now one
    level further in and harder to see. An element reference means the same
    frame under either ordering, which is worth more than the 32ms.
    """
    leave(driver)
    for index in path:
        try:
            siblings = driver.find_elements(By.CSS, _FRAME_SELECTOR)
            if index >= len(siblings):
                leave(driver)
                return False
            driver.switch_to.frame(siblings[index])
        except EngineError:
            leave(driver)
            return False
    return True
