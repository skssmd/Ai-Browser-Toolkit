"""One WebArena task: set it up, let the loop drive it, score it, measure it.

Scoring is BrowserGym's `validate()`, reading the site's own state. This file
never computes a reward -- it only records one.

Everything else it records is the point: a success rate alone cannot tell a
toolkit that helped from one that got in the way. See WEBARENA.md for which
number comes from where.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adapter import AbtClient, inject_cdp_port  # noqa: E402
import loop_policy  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--server", default="http://127.0.0.1:8766")
    ap.add_argument("--provider", default="openrouter")
    ap.add_argument("--model", default="stealth/ox-alpha")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--headed", dest="headless", action="store_false",
                    default=True,
                    help="Show the browser. Needs a display; on a server the "
                         "run dies at startup without one.")
    ap.add_argument("--shopping-url", default="http://127.0.0.1:7770",
                    help="Where the shopping site answers (through the tunnel).")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    # WebArena reads every site URL from the environment AT IMPORT TIME, so
    # this has to happen before browsergym.webarena is imported -- setting it
    # afterwards silently leaves the library pointed at its own defaults, and
    # the task then fails against a host that was never running.
    #
    # Only shopping is up. The rest are pointed at a port nothing listens on,
    # so a task needing them fails immediately and is recorded as skipped
    # rather than spending a full episode discovering it.
    import os

    # BrowserGym wants them WA_-prefixed and asserts on every one, even the
    # sites a given task will never touch -- so all seven must be set or the
    # import fails before any task runs.
    absent = "http://127.0.0.1:9"
    os.environ["WA_SHOPPING"] = args.shopping_url
    for name in ("SHOPPING_ADMIN", "REDDIT", "GITLAB", "WIKIPEDIA", "MAP",
                 "HOMEPAGE"):
        os.environ.setdefault(f"WA_{name}", absent)

    inject_cdp_port(args.cdp_port)
    import gymnasium as gym
    from browsergym.webarena import ALL_WEBARENA_TASK_IDS  # registers the envs

    task_id = args.task_id
    if task_id not in ALL_WEBARENA_TASK_IDS:
        print(f"unknown task {task_id}", file=sys.stderr)
        return 2

    client = AbtClient(args.server)
    # gym.make, not BrowserEnv directly: importing browsergym.webarena
    # registers one env per task id, and that registration is what carries the
    # task's config, its start url and -- the part that matters -- its
    # evaluator. Constructing BrowserEnv by hand skips all three.
    # Headless by default. The MiniWoB runner is headed on purpose so a person
    # can watch, and this file inherited that -- which on a server with no
    # display is fatal rather than merely invisible: Chrome exits with "Missing
    # X server or $DISPLAY" before the task starts. Watching happens through
    # /viewer and the trace server now, neither of which needs a display.
    env = gym.make(f"browsergym/{task_id}", headless=args.headless)

    record: dict = {"task_id": task_id, "model": args.model}
    try:
        obs, info = env.reset()
    except Exception as exc:
        # A task whose site is not running is not a failure of the toolkit or
        # the model, and must never be averaged in as one.
        text = str(exc).lower()
        if "connection" in text or "refused" in text or "not running" in text:
            print("site not running", file=sys.stderr)
            return 3
        raise

    client.attach(headless=args.headless)
    ops_before, errs_before = client.op_tally()
    started = time.time()

    session = loop_policy.run_episode(
        goal=obs.get("goal") or "",
        server=args.server,
        model=args.model,
        max_turns=args.max_turns,
        provider=args.provider,
        quiet=False,
    )

    wall = time.time() - started
    ops_after, errs_after = client.op_tally()
    obs, reward, terminated, truncated, info = env.step("noop(500)")
    env.close()

    ops = (ops_after - ops_before) if ops_before >= 0 else None
    failures = (errs_after - errs_before) if errs_before >= 0 else None
    usage = session.get("usage") or {}
    total = (usage.get("input") or 0) + (usage.get("output") or 0)

    record.update({
        "status": "ok",
        # --- WebArena's answer, untouched ---
        "success": float(reward) > 0,
        "reward": float(reward),
        # --- ours ---
        "turns": session.get("turns"),
        "ops": ops,
        "op_failures": failures,
        "op_success_rate": (
            round((ops - failures) / ops, 3) if ops else None
        ),
        "ops_per_turn": session.get("ops_per_turn"),
        "input_tokens": usage.get("input"),
        "output_tokens": usage.get("output"),
        "cache_read_tokens": usage.get("cache_read"),
        "total_tokens": total,
        "cache_share": (
            round((usage.get("cache_read") or 0) / usage["input"], 3)
            if usage.get("input") else None
        ),
        "model_s": round(wall, 1),
        "hit_turn_limit": session.get("hit_turn_limit"),
        "goal": (obs.get("goal") or "")[:300],
        "reply": (session.get("reply") or "")[:600],
    })

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"reward={record['reward']} ops={ops} turns={record['turns']} "
          f"tokens={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
