"""Nothing waits forever, and Stop stops now.

Seen live: Playwright's Node.js driver died under two parallel chats, every
call to it waited forever, and Stop only took effect "after this step" -- a
step that never ended. No browser or network here: the hangs are simulated.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from abt import agent
from abt.engine import DeadSession
from abt.pwdriver import PlaywrightDriver


def bare_driver(deadline: float) -> PlaywrightDriver:
    driver = object.__new__(PlaywrightDriver)
    driver._owner = None
    driver._pool = ThreadPoolExecutor(max_workers=1)
    driver._hung = False
    driver.CALL_DEADLINE = deadline
    return driver


def test_a_call_that_never_answers_fails_as_a_dead_session():
    driver = bare_driver(0.3)
    forever = threading.Event()
    started = time.monotonic()
    with pytest.raises(DeadSession):
        driver._call(lambda: forever.wait(30))
    assert time.monotonic() - started < 2
    # Every later call fails at once instead of queuing behind the stuck one.
    started = time.monotonic()
    with pytest.raises(DeadSession):
        driver._call(lambda: "never runs")
    assert time.monotonic() - started < 0.2
    forever.set()


def test_a_stuck_driver_is_ended_not_left_connected(monkeypatch):
    """Left connected, a stuck driver kept a tab paused and hung every session."""
    from types import SimpleNamespace

    from abt import pwdriver

    driver = bare_driver(0.3)
    driver._pw = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(
        _transport=SimpleNamespace(_proc=SimpleNamespace(returncode=None, pid=4242)))))
    ended = []
    monkeypatch.setattr(pwdriver.os, "kill", lambda pid, sig: ended.append(pid))
    forever = threading.Event()
    with pytest.raises(DeadSession):
        driver._call(lambda: forever.wait(30))
    assert ended == [4242]
    forever.set()


def test_a_normal_call_still_returns():
    assert bare_driver(5)._call(lambda: 42) == 42


def test_stop_ends_a_turn_waiting_on_the_model():
    stop = threading.Event()

    def complete(model, messages):
        # A provider that never answers -- until Stop closes the stream.
        while not stop.is_set():
            time.sleep(0.05)
        raise agent.Stopped()

    events = []
    threading.Timer(0.3, stop.set).start()
    started = time.monotonic()
    agent.run_turn([{"role": "user", "content": "go"}], models=["m"], complete_fn=complete,
                   call_tool=None, emit=events.append, should_stop=stop.is_set)
    assert time.monotonic() - started < 2
    assert {"type": "notice", "text": "Stopped."} in events


def test_stop_does_not_wait_for_a_hung_browser_command():
    stop = threading.Event()
    replies = iter([{"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "command_list", "arguments": '{"commands": [{"op": "goto", "url": "https://x.test"}]}'}}]}])
    hang = threading.Event()

    def call_tool(name, args):
        hang.wait(30)  # a goto whose browser connection is gone
        return "{}", False

    events, messages = [], [{"role": "user", "content": "go"}]
    threading.Timer(0.3, stop.set).start()
    started = time.monotonic()
    agent.run_turn(messages, models=["m"], complete_fn=lambda m, msgs: next(replies),
                   call_tool=call_tool, emit=events.append, should_stop=stop.is_set)
    assert time.monotonic() - started < 2
    assert any(e.get("type") == "tool_result" and "stopped by the person" in e.get("text", "") for e in events)
    assert {"type": "notice", "text": "Stopped."} in events
    hang.set()


def test_a_dead_driver_process_is_noticed_at_once_and_logged(capsys):
    from types import SimpleNamespace

    driver = bare_driver(60)
    proc = SimpleNamespace(returncode=None)
    driver._pw = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(
        _transport=SimpleNamespace(_proc=proc))))
    forever = threading.Event()
    threading.Timer(0.3, lambda: setattr(proc, "returncode", 3221225477)).start()  # it dies
    started = time.monotonic()
    with pytest.raises(DeadSession, match="exited"):
        driver._call(lambda: forever.wait(30))
    assert time.monotonic() - started < 3  # noticed at once, not at the 60s deadline
    assert "exited (code 3221225477)" in capsys.readouterr().err
    forever.set()


# -- nothing ever tells a caller to restart the browser -----------------------------


def test_no_error_text_tells_anyone_to_restart_the_browser():
    """A dropped connection re-attaches on the next command, so there is nothing
    for a caller to do about it -- and advice to restart closed healthy tabs."""
    from abt.browser import NO_BROWSER_MESSAGE
    from abt.errors import HINTS

    # (Restarting the *server* is the operator's call and may be named.)
    advice = ("restart the browser", "browser restart", "browser_restart", "restart it", "restarting it")
    for kind, hint in HINTS.items():
        assert not any(phrase in hint.lower() for phrase in advice), kind
    assert not any(phrase in NO_BROWSER_MESSAGE.lower() for phrase in advice)
    driver = bare_driver(0.2)
    with pytest.raises(DeadSession) as dead:
        driver._call(lambda: threading.Event().wait(30))
    assert "restart" not in str(dead.value).lower()


def test_a_connection_that_dies_mid_command_is_reattached_and_the_agent_is_told_so():
    from abt.errors import OpError
    from abt.server import _after_dropped_connection, fail

    class Browser:
        def __init__(self, ok=True):
            self.ok, self.reconnected = ok, 0

        def reconnect(self):
            self.reconnected += 1
            if not self.ok:
                raise OpError("browser_dead", "could not reconnect")

    original = fail(OpError("browser_dead", "the browser connection stopped answering"), 2)
    healed = Browser()
    out = _after_dropped_connection(healed, original, 2)
    assert healed.reconnected == 1
    error = out["error"]
    assert error["type"] == "timeout" and error["op_index"] == 2
    assert "re-established" in error["message"] and "restart" not in str(error).lower()
    # Could not be re-attached: the original error stands.
    assert _after_dropped_connection(Browser(ok=False), original, 2) == original


def test_a_standalone_browsers_dead_connection_relaunches_it(tmp_path, monkeypatch):
    """No other connection to take over: its driver owned the Chrome."""
    from abt.browser import BrowserSession

    browser = BrowserSession(profile=tmp_path, headless=True)
    browser._driver = object()
    calls = []
    monkeypatch.setattr(browser, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(browser, "start", lambda **kw: calls.append(("start", kw)))
    browser.reconnect()
    assert calls[0] == "stop" and calls[1][0] == "start"
    assert calls[1][1]["headless"] is True and browser._driver is None
