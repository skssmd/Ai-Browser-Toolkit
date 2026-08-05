"""Screenshots for the audit trail: what the page looked like at each action.

The session log answers *what the agent did*. On its own that is not enough to
review an hour of unattended work -- "clicked Save, ok" is only trustworthy if
you can see the page it clicked Save on. A frame captured next to each event is
what turns the log into something a human can audit by scrolling.

Two decisions keep it cheap enough to leave on:

* **Only state-changing ops, plus every failure.** A `find` or `get_text`
  changes nothing, so its frame would duplicate the one before it. A failure is
  captured whatever the op was -- errors are the whole reason someone opens the
  log.
* **Downscaled JPEG through CDP, not Selenium.** `get_screenshot_as_png` is
  PNG-only and costs 300KB-1MB a frame; a 1280px-wide JPEG at quality 60 is
  60-120KB. Over a long session that is the difference between a few megabytes
  and a few hundred.

Everything here is best effort. A browser that refuses to be photographed still
runs commands -- a missing frame degrades the audit trail, it never fails work.
"""

from __future__ import annotations

from typing import Any

# Ops worth a frame: they change what is on screen. Reads are skipped -- their
# frame would be identical to the previous one.
SHOT_OPS = frozenset(
    {
        "goto",
        "back",
        "forward",
        "reload",
        "click",
        "click_at",
        "input",
        "press",
        "select",
        "hover",
        "scroll",
        "tab_new",
        "tab_switch",
        "tab_close",
        "wait_for",
        "messenger_send",
    }
)

DEFAULT_QUALITY = 60
DEFAULT_WIDTH = 1280

# Viewport size and the element's box in one round trip, so a captured frame
# costs at most two calls into the page.
_BOX_JS = """
const r = arguments[0].getBoundingClientRect();
return [r.x, r.y, r.width, r.height, window.innerWidth, window.innerHeight];
"""

_VIEWPORT_JS = "return [window.innerWidth, window.innerHeight];"


def wanted(op: str | None, ok: bool) -> bool:
    """Should this command get a frame?"""
    if not ok:
        return True
    return op in SHOT_OPS


def capture(session, quality: int = DEFAULT_QUALITY, width: int = DEFAULT_WIDTH) -> bytes | None:
    """A JPEG of the current viewport, downscaled to `width`. None if it fails."""
    driver = getattr(session, "driver", None)
    if driver is None:
        return None
    try:
        return _capture_cdp(driver, quality, width)
    except Exception:
        pass
    try:
        # Any Chromium without the CDP call still answers this one, in PNG.
        return driver.get_screenshot_as_png()
    except Exception:
        return None


def _capture_cdp(driver, quality: int, width: int) -> bytes:
    import base64

    view_w, view_h = driver.execute_script(_VIEWPORT_JS)
    scale = 1.0 if not view_w else min(1.0, width / float(view_w))
    result = driver.execute_cdp_cmd(
        "Page.captureScreenshot",
        {
            "format": "jpeg",
            "quality": int(quality),
            "captureBeyondViewport": False,
            "clip": {
                "x": 0,
                "y": 0,
                "width": float(view_w),
                "height": float(view_h),
                "scale": scale,
            },
        },
    )
    return base64.b64decode(result["data"])


def target_box(session) -> dict[str, float] | None:
    """Where the element this command acted on sits, as fractions of the frame.

    Fractions rather than pixels so the viewer can overlay the box with plain
    percentages and never has to know what the frame was scaled to.

    Read *after* the action, not at resolve time: clicking scrolls the element
    into view, so its position when it was found is not where it ended up. A
    click that navigated leaves the element stale, and a stale element means the
    page is gone and a box would be a lie -- so None is the honest answer.
    """
    element = getattr(session, "last_target", None)
    if element is None:
        return None
    try:
        x, y, w, h, view_w, view_h = session.driver.execute_script(_BOX_JS, element)
    except Exception:
        return None
    if not view_w or not view_h or w <= 0 or h <= 0:
        return None
    box = {
        "x": max(0.0, min(1.0, x / view_w)),
        "y": max(0.0, min(1.0, y / view_h)),
        "w": max(0.0, min(1.0, w / view_w)),
        "h": max(0.0, min(1.0, h / view_h)),
    }
    # Entirely off-screen: the frame does not show it, so do not draw on it.
    if box["x"] >= 1.0 or box["y"] >= 1.0 or box["w"] == 0.0 or box["h"] == 0.0:
        return None
    return {k: round(v, 5) for k, v in box.items()}


def take(session, op: str | None, ok: bool, quality: int, width: int) -> dict[str, Any] | None:
    """The whole capture step for one command: frame plus where it acted."""
    if not wanted(op, ok):
        return None
    data = capture(session, quality, width)
    if not data:
        return None
    return {"data": data, "box": target_box(session)}
