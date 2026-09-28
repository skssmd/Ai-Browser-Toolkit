"""The chat loop with a scripted model: no network, no browser."""

from __future__ import annotations

import json

from abt import agent, mcp


def call(name, args, id="c1"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def script(*replies):
    """A fake model that answers with each reply in turn, and records requests."""
    seen = []

    def complete(model, messages):
        seen.append((model, messages))
        reply = replies[len(seen) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return complete, seen


def test_the_tools_are_the_mcp_tools():
    names = [t["function"]["name"] for t in agent.tools()]
    assert names == [t["name"] for t in mcp.TOOLS]
    assert all(t["type"] == "function" for t in agent.tools())


def test_a_tool_call_runs_and_the_answer_comes_back():
    complete, seen = script(
        {"content": "", "tool_calls": [call("command_list", {"commands": [{"op": "status"}]})]},
        {"content": "The browser is idle."},
    )
    ran, events, messages = [], [], [{"role": "user", "content": "status?"}]
    used = agent.run_turn(
        messages,
        models=["m1"],
        complete_fn=complete,
        call_tool=lambda name, args: ran.append((name, args)) or ('{"ok":true}', False),
        emit=events.append,
        system="sys",
    )
    assert used == "m1"
    assert ran == [("command_list", {"commands": [{"op": "status"}]})]
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "assistant"]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert seen[0][1][0] == {"role": "system", "content": "sys"}
    assert messages[2]["tool_call_id"] == "c1"


def test_a_failing_model_falls_back_down_the_list():
    complete, seen = script(agent.ModelError("no tool support"), {"content": "done"})
    events = []
    used = agent.run_turn(
        [{"role": "user", "content": "x"}],
        models=["free-a", "free-b"],
        complete_fn=complete,
        call_tool=lambda n, a: ("", False),
        emit=events.append,
    )
    assert used == "free-b"
    assert [m for m, _ in seen] == ["free-a", "free-b"]
    assert events[0]["type"] == "notice"


def test_a_bad_key_does_not_walk_the_whole_list():
    complete, seen = script(agent.ModelError("401", retry_elsewhere=False))
    events = []
    assert agent.run_turn(
        [{"role": "user", "content": "x"}], models=["a", "b"], complete_fn=complete,
        call_tool=lambda n, a: ("", False), emit=events.append,
    ) is None
    assert len(seen) == 1 and events[-1]["type"] == "error"


def test_no_model_says_so():
    events = []
    assert agent.run_turn([], models=[], complete_fn=None, call_tool=None, emit=events.append) is None
    assert "Settings" in events[0]["text"]


def test_stop_ends_the_turn():
    complete, _ = script({"content": "", "tool_calls": [call("command_list", {"commands": []})]})
    events = []
    agent.run_turn(
        [{"role": "user", "content": "x"}], models=["m"], complete_fn=complete,
        call_tool=lambda n, a: ("never", False), emit=events.append, should_stop=lambda: True,
    )
    assert events[-1] == {"type": "notice", "text": "Stopped."}


def test_bad_arguments_are_reported_to_the_model_not_run():
    bad = {"id": "c9", "type": "function", "function": {"name": "command_list", "arguments": "{nope"}}
    complete, _ = script({"content": "", "tool_calls": [bad]}, {"content": "ok"})
    messages, ran = [{"role": "user", "content": "x"}], []
    agent.run_turn(
        messages, models=["m"], complete_fn=complete,
        call_tool=lambda n, a: ran.append(n) or ("", False), emit=lambda e: None,
    )
    assert ran == []
    assert "not valid JSON" in messages[2]["content"]


def test_old_tool_results_are_trimmed_new_ones_kept():
    messages = [{"role": "tool", "tool_call_id": str(i), "content": "x" * 5000} for i in range(6)]
    out = agent.trimmed(messages)
    assert len(out[0]["content"]) < 2000
    assert len(out[-1]["content"]) == 5000
    assert len(messages[0]["content"]) == 5000  # the saved conversation is untouched


def test_the_system_prompt_names_the_rules():
    text = agent.system_prompt(["a.com", "!a.com/api"], run_js=False)
    assert "a.com, !a.com/api" in text and "run_js is switched off" in text


class FakeStream:
    """What httpx.stream hands back: headers, a status, lines or a body."""

    def __init__(self, lines=None, body=None, status=200):
        self.status_code = status
        self.headers = {"content-type": "text/event-stream" if lines is not None else "application/json"}
        self._lines = lines or []
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        return iter(self._lines)

    def read(self):
        return b""

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


def serve(monkeypatch, reply, sent=None):
    def stream(method, url, headers=None, content=None, timeout=None, **kw):
        if sent is not None:
            sent["body"] = content
        return reply

    monkeypatch.setattr(agent.httpx, "stream", stream)


def sse(*chunks):
    return [": OPENROUTER PROCESSING", ""] + [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]


def test_the_request_body_is_ascii_so_no_backend_chokes_on_it(monkeypatch):
    """Seen live: a free model behind openrouter/free failed with "'ascii'
    codec can't encode character '—'" on page text holding an em dash."""
    sent = {}
    serve(monkeypatch, FakeStream(body={"choices": [{"message": {"content": "ok"}}]}), sent)
    agent.complete("https://x.test/v1", "k", "m", [{"role": "user", "content": "a — b"}], [])
    sent["body"].decode("ascii")  # raises if anything non-ASCII went out
    body = json.loads(sent["body"])
    assert body["messages"][0]["content"] == "a — b"
    assert body["stream"] is True


def test_text_streams_piece_by_piece(monkeypatch):
    serve(monkeypatch, FakeStream(sse(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo."}}]},
    )))
    pieces = []
    message = agent.complete("https://x.test/v1", "k", "m", [], [], on_text=pieces.append)
    assert pieces == ["Hel", "lo."]
    assert message["content"] == "Hello." and "tool_calls" not in message


def test_a_tool_call_split_across_chunks_is_joined(monkeypatch):
    serve(monkeypatch, FakeStream(sse(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "command_", "arguments": '{"comm'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "list", "arguments": 'ands":[]}'}}]}}]},
    )))
    message = agent.complete("https://x.test/v1", "k", "m", [], [])
    [call] = message["tool_calls"]
    assert call["id"] == "c1"
    assert call["function"] == {"name": "command_list", "arguments": '{"commands":[]}'}


def test_a_provider_that_does_not_stream_still_works(monkeypatch):
    serve(monkeypatch, FakeStream(body={"choices": [{"message": {"content": "whole"}}]}))
    assert agent.complete("https://x.test/v1", "k", "m", [], [])["content"] == "whole"


def test_an_error_mid_stream_is_a_model_error(monkeypatch):
    import pytest

    serve(monkeypatch, FakeStream(sse({"error": {"message": "upstream overloaded"}})))
    with pytest.raises(agent.ModelError) as exc:
        agent.complete("https://x.test/v1", "k", "m", [], [])
    assert "overloaded" in str(exc.value)


def test_a_bad_key_is_not_retried_elsewhere(monkeypatch):
    serve(monkeypatch, FakeStream(body={"error": {"message": "no auth"}}, status=401))
    import pytest

    with pytest.raises(agent.ModelError) as exc:
        agent.complete("https://x.test/v1", "k", "m", [], [])
    assert exc.value.retry_elsewhere is False
