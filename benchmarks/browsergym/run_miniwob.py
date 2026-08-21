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
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="click-button")
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--wait-ms", type=int, default=300)
    ap.add_argument("--policy", choices=["scripted", "llm"], default="scripted")
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
            policy = make_policy()

            steps = []
            reward, terminated, truncated = 0.0, False, False
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
    }
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print(f"score {score:.2f} over {len(results)} episodes -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
