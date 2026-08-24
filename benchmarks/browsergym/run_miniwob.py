"""Run MiniWoB++ episodes where every page action is executed by abt.

BrowserGym owns the browser, the observations and the scoring; the toolkit
owns every interaction. See adapter.py for the sharing mechanism.

Usage (server must be running in attach mode):

    set ABT_CDP_URL=http://127.0.0.1:9222
    start-server.bat
    py benchmarks/browsergym/run_miniwob.py --task click-button --episodes 3

The browser runs headed on purpose: you can watch the episode.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse
import tempfile

sys.path.insert(0, str(Path(__file__).parent))
from adapter import AbtClient, inject_cdp_port, lower_action  # noqa: E402


def serve_html(html_dir: Path, port: int) -> str:
    """Serve the MiniWoB++ html tree on a throwaway local port."""

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(html_dir))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


def flatten_tree(obs: dict) -> str:
    from browsergym.utils.obs import flatten_axtree_to_str

    return flatten_axtree_to_str(obs["axtree_object"])


def scripted_click_button(obs: dict) -> str:
    """No-LLM policy for click-button: find the quoted target in the tree."""
    goal = obs.get("goal") or ""
    m = re.search(r'"([^"]+)"', goal)
    if not m:
        return "noop(500)"
    target = m.group(1)
    for line in flatten_tree(obs).splitlines():
        if target not in line:
            continue
        bid = re.match(r"\s*\[([^\[\]]+)\]", line)
        if bid and re.search(r"button|link|generic", line):
            return f"click(bid='{bid.group(1)}')"
    return "noop(500)"


def _first_bid(lines, *needles):
    for line in lines:
        m = re.match(r"\s*\[([^\[\]]+)\]", line)
        if m and all(n in line.lower() for n in needles):
            return m.group(1)
    return None


def scripted_enter_text(obs, state=None):
    """Two-phase policy: type the quoted string, then press Submit."""
    state = state if state is not None else {}
    lines = flatten_tree(obs).splitlines()
    m = re.search(r'"([^"]+)"', obs.get("goal", ""))
    if not state.get("typed"):
        bid = _first_bid(lines, "textbox")
        if bid and m:
            state["typed"] = True
            return f"fill(bid='{bid}', value='{m.group(1)}')"
        return "noop(300)"
    bid = _first_bid(lines, "button", "submit")
    return f"click(bid='{bid}')" if bid else "noop(300)"


def make_enter_text_policy():
    """One policy instance per episode; the phase state lives in the closure."""
    state = {}

    def policy(obs):
        return scripted_enter_text(obs, state)

    return policy


POLICIES = {
    "click-button": lambda: scripted_click_button,
    "enter-text": make_enter_text_policy,
}


# --- agent-session policy -----------------------------------------------------
#
# The toolkit is a tool for AI agents, not an agent itself: Claude Code,
# opencode or Codex drive it through CLI / HTTP / MCP however they like.
# This mode runs ONE such agent per episode. The runner only hands over the
# goal and the abt endpoint, waits for the agent to finish, then asks
# BrowserGym to score the result. The agent never sees bids or BrowserGym's
# action DSL -- it uses the toolkit exactly as it would in production.

AGENT_PROMPT = """You are completing a web task using ai-browser-toolkit (abt),
which drives a real browser already open on the task page.

GOAL: {goal}

These are SHORT tasks -- usually solvable in 2-3 calls if you lean on these
four things:

1. **Look with css.** `find {{"css":"input[type=text]"}}` is exact; searching
   by visible text matches ancestors and surprises. Css first, text last.
2. **Read the actionables you already got.** Every result carries a dom_diff;
   controls that just appeared are listed in `dom_diff.actionable` with fresh
   refs. Act on those instead of running find again -- most of your next
   target is already in your hand.
3. **Batch.** Once you know the targets (e.g. two fields + Submit), send all
   ops in ONE call: a JSON array of raw ops
   (`[{{"op":"input","css":"#u","value":"x"}},{{"op":"click","css":"#subbtn"}}]`).
   A form is one round trip, not six.
4. **get_text for content.** When the goal needs values written on the page,
   `get_text` returns the rendered text (popups/tabs included via tab_list +
   tab_switch). Don't fall back to run_js DOM scans.
5. **Screenshot on ambiguity.** When two controls share a label, or a dialog
   suddenly covers the form, take a screenshot before clicking -- layout
   tells you which button is which when text cannot.

Two traps: a stale_ref means "take a fresh ref from your last diff" --
never goto/reload the task page to fix it (that resets the goal). Forms
like these expect the final Submit/OK press -- press it. If a surprise
dialog interrupts, READ it: dialogs offering "Exit / Leave / Home" usually
mean FAILURE -- dismissing via Cancel/No is the safe move. And a successful
submit makes these pages freeze or blank -- but only trust that when your
submit actually landed where you aimed; verify the click's target, then
stop poking the page.

If you drop to the CLI instead, EVERY command needs -p {port} (the default
port belongs to an unrelated server):

  py -m abt status -p {port}
  py -m abt find "input[type=text]" -p {port}
  py -m abt click --ref el_3 -p {port}
  py -m abt input "21" --ref el_5 -p {port}
  '{{"op":"press","key":"Enter"}}' | py -m abt exec - -p {port}

Accomplish the GOAL on the page that is already open, then STOP and reply
with just: DONE
"""

MCP_HINT = """

abt is also connected to you over MCP as server "abt" (tools named
abt_browser_*): prefer those typed tools over shelling out -- same operations,
validated parameters, no quoting problems. The batch tool there accepts a
raw ops array exactly like the CLI example above.
"""


# MiniWoB pages end themselves EPISODE_MAX_TIME (often 10 s) after load, and
# some scale reward down by elapsed time. An out-of-process CLI agent boots in
# ~30-60 s and can never act inside that window, so the runner neutralizes the
# wall clock while leaving correctness fully graded by task.validate().
# Disclosed in README.md.
FREEZE_TIMERS_JS = (
    "(() => { const c = window.core; if (!c) return 'no core';"
    " const orig = c.endEpisode;"
    " c.endEpisode = function (reward, timeProportional, reason) {"
    "  if (reason === 'timed out') return undefined;"
    "  return orig.call(c, reward, false, reason); };"
    " return 'frozen'; })()"
)

MCP_HINT = """

abt is also connected to you over MCP as server "abt" -- prefer its typed
tools over shelling out; they run the same operations with validated
parameters.
"""


def _pretty_event(line: str) -> str | None:
    """Compact human-readable rendering of an opencode --format json event."""
    line = line.strip()
    if not line.startswith("{"):
        return line
    try:
        ev = json.loads(line)
    except ValueError:
        return line
    part = ev.get("part") or {}
    if ev.get("type") == "tool_use":
        st = part.get("state") or {}
        args_s = json.dumps(st.get("input") or {}, ensure_ascii=True)[:200]
        if st.get("status") == "error":
            try:
                etype = json.loads(st.get("error") or "{}").get("error", {}).get("type", "?")
            except ValueError:
                etype = "?"
            return f"[tool ] {part.get('tool')} {args_s}  !! {etype}"
        return f"[tool ] {part.get('tool')} {args_s}"
    if part.get("type") == "reasoning":
        txt = (part.get("text") or "").strip().replace("\n", " ")
        return f"[think] {txt[:400]}" if txt else None
    if part.get("type") == "text":
        txt = (part.get("text") or "").strip().replace("\n", " ")
        return f"[agent] {txt[:400]}" if txt else None
    return None


def run_agent_session(
    cmd: list[str], timeout_s: float, transcript_dir: Path, name: str,
    *, stream: bool = True,
) -> dict:
    """Run one agent CLI session, teeing its output live to the console
    and keeping the FULL transcript (not a tail) next to the results."""
    import subprocess
    import time

    transcript_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        if stream:
            pretty = _pretty_event(line)
            if pretty:
                print(pretty, flush=True)
        if proc.poll() is None and time.time() - started > timeout_s:
            proc.kill()
            lines.append(f"\n[killed after {timeout_s}s wall-clock budget]\n")
            break
    proc.wait(timeout=30)
    out = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "duration_s": round(time.time() - started, 1),
        "timed_out": "[killed after" in lines[-1] if lines else False,
        "output": "".join(lines),
    }
    (transcript_dir / f"{name}.json").write_text(json.dumps(out, indent=2))
    return out


def build_agent_command(
    which: str, goal: str, server: str, mcp: bool = False
) -> list[str]:
    port = urlparse(server).port or 8765
    prompt = AGENT_PROMPT.format(goal=goal.strip(), port=port)
    if mcp:
        prompt += MCP_HINT
    if which == "claude":
        cmd = [
            "claude", "-p", prompt,
            "--allowedTools", "Bash(py:*)",
            "--max-turns", "40",
        ]
        if mcp:
            cfg_dir = Path(tempfile.mkdtemp(prefix="abt-mcp-"))
            (cfg_dir / "mcp.json").write_text(json.dumps({"mcpServers": {
                "abt": {"type": "stdio", "command": "py",
                        "args": ["-m", "abt", "mcp", "--api", server]},
            }}))
            cmd += ["--strict-mcp-config", "--mcp-config", str(cfg_dir / "mcp.json"),
                    "--allowedTools", "mcp__abt:*"]
        return cmd
    if which == "opencode":
        # json events so the runner can pretty-print tool calls/results and
        # keep the full transcript; the default format collapses results
        cmd = ["opencode", "run", "--format", "json"]
        if mcp:
            cfg_dir = Path(tempfile.mkdtemp(prefix="abt-mcp-"))
            (cfg_dir / "opencode.json").write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "mcp": {"abt": {
                    "type": "local", "enabled": True,
                    "command": ["py", "-m", "abt", "mcp", "--api", server],
                    "environment": {},
                }},
            }))
            cmd += ["--dir", str(cfg_dir)]
        cmd.append(prompt)
        return cmd
    raise SystemExit(f"unknown agent {which!r}; expected claude|opencode")


def llm_policy(obs: dict) -> str:
    """Ask an OpenAI-compatible endpoint for one action."""
    import httpx

    prompt = (
        "You are controlling a web page. Reply with exactly ONE action call.\n"
        "Available actions: noop(wait_ms), click(bid), fill(bid, value), "
        "press(bid, key_comb), scroll(delta_x, delta_y), goto(url).\n\n"
        f"Goal: {obs.get('goal')}\n\nPage:\n{flatten_tree(obs)}\n\nAction:"
    )
    resp = httpx.post(
        f"{os.environ['OPENAI_BASE_URL'].rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={
            "model": os.environ["ABT_BENCH_MODEL"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 60,
        },
        timeout=60,
    )
    text = resp.json()["choices"][0]["message"]["content"].strip()
    return text.splitlines()[-1].strip()


def main() -> int:
    # Agent CLIs emit unicode; a captured cp1252 stdout would crash mid-stream.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="click-button")
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--wait-ms", type=int, default=300)
    ap.add_argument("--policy", choices=["scripted", "llm", "agent"], default="scripted")
    ap.add_argument("--agent", choices=["claude", "opencode"], default="opencode",
                    help="which agent CLI plays the policy when --policy agent")
    ap.add_argument("--agent-timeout", type=float, default=240.0,
                    help="wall-clock budget for one agent session, seconds")
    ap.add_argument("--quiet-agent", action="store_true",
                    help="do not stream the agent's terminal output live")
    ap.add_argument("--agent-mcp", action="store_true",
                    help="also expose abt to the agent over MCP (typed tools)")
    ap.add_argument("--no-freeze-timers", action="store_true",
                    help="keep MiniWoB wall-clock limits; default neutralizes "
                         "them so an external CLI agent can act at all")
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--html-dir", default=str(Path(os.environ["TEMP"]) / "opencode" / "miniwob" / "miniwob" / "html"))
    ap.add_argument("--html-port", type=int, default=8033)
    ap.add_argument("--out", default="results/miniwob-run.json")
    args = ap.parse_args()

    base_url = serve_html(Path(args.html_dir), args.html_port)
    # Task URLs are built as base_url + "<subdomain>.html", so the base must
    # point into the miniwob/ subtree -- that is where core/ sits relative.
    os.environ["MINIWOB_URL"] = base_url + "/miniwob/"

    inject_cdp_port(args.cdp_port)

    from browsergym.core.env import BrowserEnv
    from browsergym.miniwob import ALL_MINIWOB_TASKS

    task_cls = next(c for c in ALL_MINIWOB_TASKS if c.subdomain == args.task)
    client = AbtClient(args.server)
    if args.policy == "llm":
        make_policy = lambda: llm_policy  # noqa: E731
    elif args.policy == "agent":
        make_policy = None  # one agent session per episode; handled below
    elif args.task in POLICIES:
        make_policy = POLICIES[args.task]
    else:
        raise SystemExit(f"no scripted policy for {args.task!r}; use --policy llm")

    env = BrowserEnv(
        task_entrypoint=lambda seed, **kw: task_cls(
            seed=seed, base_url=base_url + "/miniwob/", **kw
        ),
        headless=False,  # watchable by design
    )

    results = []
    try:
        for ep in range(args.episodes):
            seed = args.seed + ep
            obs, info = env.reset(seed=seed)
            client.attach(headless=False)  # fresh browser per reset()

            if not args.no_freeze_timers:
                frozen = client.command({"op": "run_js", "script": FREEZE_TIMERS_JS})
                if ep == 0:
                    print(f"[freeze-timers] {json.dumps(frozen.get('result'))[:100]}")

            steps = []
            reward, terminated, truncated = 0.0, False, False
            if args.policy == "agent":
                cmd = build_agent_command(args.agent, obs.get("goal") or "",
                                          args.server, mcp=args.agent_mcp)
                print(f"[ep {ep}] agent session: {args.agent} ...")
                session = run_agent_session(
                    cmd, args.agent_timeout,
                    Path(args.out).parent / "agent-transcripts", f"ep{seed}",
                    stream=not args.quiet_agent,
                )
                obs, reward, terminated, truncated, info = env.step("noop(500)")
                steps.append({
                    "step": 0, "action": f"agent:{args.agent}",
                    "ops": None, "error": None if session["returncode"] == 0
                    else f"rc={session['returncode']}", "reward": float(reward),
                })
                print(f"[ep {ep}] agent rc={session['returncode']} "
                      f"in {session['duration_s']}s -> reward={reward}")
                print(f"[ep {ep}] full transcript: "
                      f"{Path(args.out).parent / 'agent-transcripts' / f'ep{seed}.json'}")
                print(f"[ep {ep}] every op + screenshot the agent caused: "
                      f"`py -m abt logs -p {urlparse(args.server).port}`")
            else:
                policy = make_policy()
                for step in range(args.max_steps):
                    action = policy(obs)
                    ops = lower_action(action)
                    payload = client.commands(ops) if ops else {"ok": True}
                    err = None if payload.get("ok") else str(payload.get("error"))
                    obs, reward, terminated, truncated, info = env.step(
                        f"noop({args.wait_ms})"
                    )
                    steps.append(
                        {"step": step, "action": action, "ops": len(ops),
                         "error": err, "reward": float(reward)}
                    )
                    print(f"[ep {ep} step {step}] {action} -> reward={reward}")
                    if err or terminated or truncated or reward != 0.0:
                        break
            success = float(reward) == 1.0
            results.append(
                {"task_id": task_cls.get_task_id(), "seed": seed,
                 "success": success, "reward": float(reward),
                 "steps": len(steps), "log": steps}
            )
            print(f"[ep {ep}] success={success}")
    finally:
        env.close()

    score = sum(r["success"] for r in results) / max(len(results), 1)
    out = {
        "benchmark": "miniwob",
        "task": args.task,
        "episodes": results,
        "n_episodes": len(results),
        "score": score,
        "executor": "ai-browser-toolkit (HTTP ops)",
        "scorer": "browsergym task.validate",
        "policy": args.policy,
        "agent": args.agent if args.policy == "agent" else None,
        "agent_mcp": args.agent_mcp if args.policy == "agent" else None,
        "freeze_timers": not args.no_freeze_timers,
    }
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print(f"score {score:.2f} over {len(results)} episodes -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
