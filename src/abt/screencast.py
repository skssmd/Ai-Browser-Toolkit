"""A live view of one tab, and a way to reach into it.

The server opens Chrome's own DevTools WebSocket for the tab and relays
between it and the GUI. That is a separate DevTools client from every
session's Playwright connection, so watching never contends with an agent
working the same tab.

Input is translated from a small, closed vocabulary rather than forwarded as
raw CDP: a raw pipe would hand whoever holds the socket every DevTools method,
`Runtime.evaluate` included -- which is `run_js` without the switch that can
turn it off.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

MOUSE = {"mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"}
KEYS = {"keyDown", "keyUp", "rawKeyDown", "char"}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_cdp(event: Any) -> tuple[str, dict] | None:
    """One GUI input event as one CDP call, or None to drop it."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "mouse" and event.get("event") in MOUSE:
        x, y = _number(event.get("x")), _number(event.get("y"))
        if x is None or y is None:
            return None
        params: dict[str, Any] = {
            "type": event["event"],
            "x": x,
            "y": y,
            "modifiers": int(event.get("modifiers") or 0),
        }
        if event["event"] == "mouseWheel":
            params["deltaX"] = _number(event.get("deltaX")) or 0.0
            params["deltaY"] = _number(event.get("deltaY")) or 0.0
        else:
            params["button"] = str(event.get("button") or "left")
            params["clickCount"] = int(event.get("clickCount") or 1)
        return "Input.dispatchMouseEvent", params
    if kind == "key" and event.get("event") in KEYS:
        params = {"type": event["event"], "modifiers": int(event.get("modifiers") or 0)}
        for name in ("key", "code", "text"):
            if isinstance(event.get(name), str):
                params[name] = event[name]
        if event.get("windowsVirtualKeyCode") is not None:
            params["windowsVirtualKeyCode"] = int(event["windowsVirtualKeyCode"])
        return "Input.dispatchKeyEvent", params
    if kind == "text" and isinstance(event.get("text"), str):
        return "Input.insertText", {"text": event["text"]}
    return None


async def relay(client, devtools_url: str, quality: int = 60, max_width: int = 1600) -> None:
    """Pump frames to `client` and its input to Chrome until either side goes."""
    from websockets.asyncio.client import connect

    ids = itertools.count(1)
    async with connect(devtools_url, max_size=None) as chrome:

        async def send(method: str, params: dict | None = None) -> None:
            await chrome.send(json.dumps({"id": next(ids), "method": method, "params": params or {}}))

        await send("Page.startScreencast", {
            "format": "jpeg",
            "quality": quality,
            "maxWidth": max_width,
            "maxHeight": max_width,
        })

        async def from_chrome() -> None:
            async for raw in chrome:
                message = json.loads(raw)
                method = message.get("method")
                if method == "Page.screencastFrame":
                    params = message["params"]
                    # Unacknowledged, Chrome stops sending after a frame or two.
                    await send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
                    await client.send_json({
                        "type": "frame",
                        "data": params["data"],
                        "metadata": params.get("metadata", {}),
                    })
                elif method == "Inspector.detached":
                    return

        async def from_client() -> None:
            while True:
                call = to_cdp(await client.receive_json())
                if call is not None:
                    await send(*call)

        tasks = {asyncio.create_task(from_chrome()), asyncio.create_task(from_client())}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and type(exc).__name__ not in ("WebSocketDisconnect", "ConnectionClosedOK"):
                raise exc
