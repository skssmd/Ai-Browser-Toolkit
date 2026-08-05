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
frameless answer ends the matter without a single extra request. A page with
frames pays one switch and one snapshot each, bounded on both depth and count,
and skips anything too small to see or click.
"""

from __future__ import annotations

from selenium.common.exceptions import WebDriverException

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
  for (let k = 0; k < window.length; k++) {
    if (window[k] === f.contentWindow) { out.push(k); break; }
  }
}
return out;
"""


def child_slots(driver, min_px: int = MIN_FRAME_PX) -> list[int]:
    """Frames worth walking inside whichever document the driver is in now."""
    try:
        found = driver.execute_script(_SCAN_JS, min_px)
    except WebDriverException:
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
    except WebDriverException:
        pass


def enter(driver, path: tuple[int, ...]) -> bool:
    """Switch into the frame at `path`, from the top down. False if it is gone.

    A path is positions among the child browsing contexts, not handles, because
    a WebElement for a frame is only valid in its parent and there is nothing
    else durable to hold. Positions are what the driver switches by natively,
    so each step is a single request rather than a lookup and a switch.

    The cost of positions is that a page which adds or removes a frame between
    snapshot and use shifts the ones after it -- the same exposure `find` has
    always had, and the reason a ref still verifies the element it lands on.
    """
    leave(driver)
    for slot in path:
        try:
            driver.switch_to.frame(slot)
        except WebDriverException:
            leave(driver)
            return False
    return True
