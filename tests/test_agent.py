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


def test_the_request_body_is_ascii_so_no_backend_chokes_on_it(monkeypatch):
    """Seen live: a free model behind openrouter/free failed with "'ascii'
    codec can't encode character '\u2014'" on page text holding an em dash."""
    sent = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def post(url, headers=None, content=None, timeout=None, **kw):
        sent["body"] = content
        return Reply()

    monkeypatch.setattr(agent.httpx, "post", post)
    agent.complete("https://x.test/v1", "k", "m", [{"role": "user", "content": "a \u2014 b"}], [])
    sent["body"].decode("ascii")  # raises if anything non-ASCII went out
    assert json.loads(sent["body"])["messages"][0]["content"] == "a \u2014 b"
