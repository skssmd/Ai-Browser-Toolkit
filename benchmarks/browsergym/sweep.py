"""Run a whole MiniWoB++ suite and write one result row per episode.

Why a separate script that shells out to run_miniwob.py, rather than a loop
inside it: a full sweep is 125 tasks x N seeds, several hours, and it WILL hit
a hung chromium, a leaked CDP port, or an agent CLI that never exits. One
process per episode makes every one of those recoverable for free -- the
episode dies, the sweep records it and moves on. A single long-lived process
would carry that damage into every later episode and quietly poison the
numbers.

The other half is pre-registration. `plan` writes the exact task list and
seeds BEFORE anything runs; `run` refuses to execute anything not in that
plan. A benchmark whose task list is decided after seeing the results is a
demo, and the difference is not visible in the output -- so it has to be
enforced by the tool.

    py benchmarks/browsergym/sweep.py plan --out results/sweep-haiku
    py benchmarks/browsergym/sweep.py run  --out results/sweep-haiku
    py benchmarks/browsergym/sweep.py report --out results/sweep-haiku

`run` is resumable: re-running it skips episodes already in episodes.jsonl,
so a crashed or interrupted sweep continues where it stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
RUNNER = HERE / "run_miniwob.py"

# Haiku only, by decision: one model across the whole suite. Mixing models
# inside a sweep produces an average that describes no configuration that
# actually exists.
# The inline loop against OpenRouter's free stealth model: no agent CLI to
# keep logged in, no per-episode process startup, and it batches -- 2.0 ops a
# turn against the CLI agent's 1.0 on the same task.
DEFAULT_MODEL = "stealth/ox-alpha"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_SEEDS = [9001, 9002, 9003]


def all_task_names() -> list[str]:
    from browsergym.miniwob import ALL_MINIWOB_TASKS

    return sorted(t.subdomain for t in ALL_MINIWOB_TASKS)


def plan_path(out: Path) -> Path:
    return out / "plan.json"


def episodes_path(out: Path) -> Path:
    return out / "episodes.jsonl"


def cmd_plan(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = plan_path(out)
    if dest.exists() and not args.force:
        raise SystemExit(
            f"{dest} already exists. A plan is a commitment -- rewriting it "
            f"after a run invalidates the results. Pass --force only when "
            f"starting a genuinely new sweep."
        )

    tasks = all_task_names()
    if args.tasks:
        wanted = [t.strip() for t in args.tasks.split(",") if t.strip()]
        unknown = [t for t in wanted if t not in tasks]
        if unknown:
            raise SystemExit(f"no such miniwob task(s): {', '.join(unknown)}")
        tasks = wanted
    if args.limit:
        tasks = tasks[: args.limit]

    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else DEFAULT_SEEDS
    plan = {
        "benchmark": "miniwob",
        "created": datetime.now(timezone.utc).isoformat(),
        "policy": args.policy,
        "provider": args.provider,
        "agent": args.agent,
        "model": args.model,
        "mcp": not args.no_mcp,
        "freeze_timers": True,
        "agent_timeout": args.agent_timeout,
        "server": args.server,
        "tasks": tasks,
        "seeds": seeds,
        "episodes": len(tasks) * len(seeds),
    }
    dest.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"planned {len(tasks)} tasks x {len(seeds)} seeds "
          f"= {plan['episodes']} episodes -> {dest}")
    return 0


def load_done(out: Path) -> set[tuple[str, int]]:
    """Which (task, seed) pairs already have a row."""
    done: set[tuple[str, int]] = set()
    lines: list[str] = []
    for path in sorted(Path(out).glob("episodes*.jsonl")):
        lines += path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn last line from a kill; it will be re-run
        done.add((row["task"], int(row["seed"])))
    return done


def run_one(plan: dict, out: Path, task: str, seed: int, budget: float) -> dict:
    """One episode in its own process. Never raises."""
    scratch = out / "raw" / f"{task}-{seed}.json"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    policy = plan.get("policy", "agent")
    cmd = [
        sys.executable, str(RUNNER),
        "--task", task, "--seed", str(seed), "--episodes", "1",
        "--policy", policy,
        "--agent-model", plan["model"],
        "--server", plan["server"],
        "--out", str(scratch),
    ]
    if policy == "loop":
        cmd += ["--provider", plan.get("provider", DEFAULT_PROVIDER)]
    else:
        cmd += ["--agent", plan["agent"],
                "--agent-timeout", str(plan["agent_timeout"]),
                "--quiet-agent"]
        if plan["mcp"]:
            cmd.append("--agent-mcp")

    started = time.time()
    row = {
        "task": task, "seed": seed,
        "started": datetime.now(timezone.utc).isoformat(),
    }
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=budget, cwd=str(HERE.parent.parent),
        )
    except subprocess.TimeoutExpired:
        # The runner outlived even the agent's own budget: a wedged browser or
        # a CLI that never exited. Recorded as a harness fault, NOT a task
        # failure -- conflating the two flatters or damns the toolkit unfairly.
        row.update({"status": "harness_timeout", "success": False, "reward": None,
                    "wall_s": round(time.time() - started, 1)})
        return row

    row["wall_s"] = round(time.time() - started, 1)
    if not scratch.exists():
        row.update({"status": "harness_error", "success": False, "reward": None,
                    "returncode": proc.returncode,
                    "stderr_tail": (proc.stderr or proc.stdout or "")[-600:]})
        return row

    try:
        payload = json.loads(scratch.read_text(encoding="utf-8"))
        episode = payload["episodes"][0]
    except (ValueError, KeyError, IndexError) as exc:
        row.update({"status": "harness_error", "success": False, "reward": None,
                    "stderr_tail": f"unreadable result: {exc}"})
        return row

    row.update({
        "status": "ok",
        "success": bool(episode.get("success")),
        "reward": episode.get("reward"),
        "ops": episode.get("ops"),
        "op_errors": episode.get("op_errors"),
        "duration_s": episode.get("duration_s"),
        "agent_timed_out": episode.get("agent_timed_out"),
        "input_tokens": episode.get("input_tokens"),
        "output_tokens": episode.get("output_tokens"),
        "cache_read_tokens": episode.get("cache_read_tokens"),
        "turns": episode.get("turns"),
        "ops_per_turn": episode.get("ops_per_turn"),
        "cost_usd": episode.get("cost_usd"),
    })
    return row


def shard_of(episodes: list, spec: str | None) -> list:
    """The slice of the plan this worker owns.

    Round-robin rather than contiguous blocks: the tasks are alphabetical and
    difficulty clusters by name (four `choose-date*`, three `book-flight*`), so
    contiguous blocks hand one worker every hard variant and leave another
    idle. Interleaving spreads them.

    Every worker reads the same plan and computes its own slice, so no worker
    needs to know about the others and a dead worker's slice is simply not run
    rather than silently reassigned.
    """
    if not spec:
        return episodes
    try:
        index, total = (int(part) for part in spec.split("/", 1))
    except ValueError:
        raise SystemExit(f"--shard wants i/n, e.g. 1/4; got {spec!r}")
    if not 1 <= index <= total:
        raise SystemExit(f"--shard {spec}: i must be between 1 and n")
    return [ep for n, ep in enumerate(episodes) if n % total == index - 1]


def cmd_run(args) -> int:
    out = Path(args.out)
    plan = json.loads(plan_path(out).read_text(encoding="utf-8"))
    done = load_done(out)

    todo = [(t, s) for t in plan["tasks"] for s in plan["seeds"]
            if (t, s) not in done]
    if args.shard:
        before = len(todo)
        todo = shard_of(todo, args.shard)
        print(f"shard {args.shard}: {len(todo)} of {before} remaining episodes")
    print(f"{len(done)} episodes already recorded, {len(todo)} to run")
    if args.max_episodes:
        todo = todo[: args.max_episodes]
        print(f"limited to {len(todo)} this pass")

    # Generous: the runner's own agent budget should fire first. This exists
    # only to catch a process that has stopped making progress entirely.
    budget = plan["agent_timeout"] + 240

    # One file per worker. Concurrent appends to a single file can interleave
    # a partial line under load, and a torn line is a lost episode; `report`
    # reads every episodes*.jsonl, so they recombine on the way out.
    sink = (
        out / f"episodes-{args.shard.replace('/', 'of')}.jsonl"
        if args.shard
        else episodes_path(out)
    )
    for index, (task, seed) in enumerate(todo, 1):
        print(f"[{index}/{len(todo)}] {task} seed={seed} ...", flush=True)
        row = run_one(plan, out, task, seed, budget)
        with sink.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        mark = "PASS" if row.get("success") else row.get("status", "fail")
        print(f"    {mark}  ops={row.get('ops')}  {row.get('wall_s')}s",
              flush=True)
    print(f"\nwrote {sink}")
    return 0


def _fmt(value, spec="", dash="-"):
    return dash if value is None else format(value, spec)


def cmd_report(args) -> int:
    out = Path(args.out)
    plan = json.loads(plan_path(out).read_text(encoding="utf-8"))
    rows = []
    for path in sorted(out.glob("episodes*.jsonl")):
        rows += [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    by_task: dict[str, list[dict]] = {}
    for row in rows:
        by_task.setdefault(row["task"], []).append(row)

    graded = [r for r in rows if r.get("status") == "ok"]
    harness = [r for r in rows if r.get("status") != "ok"]
    passed = [r for r in graded if r.get("success")]

    def mean(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    lines = [
        f"# MiniWoB++ sweep -- {plan['model']}",
        "",
        f"- agent: `{plan['agent']}`, MCP: {plan['mcp']}, "
        f"timers frozen: {plan['freeze_timers']}",
        f"- planned: {len(plan['tasks'])} tasks x {len(plan['seeds'])} seeds "
        f"= {plan['episodes']} episodes",
        f"- graded: {len(graded)}  |  harness faults (excluded): {len(harness)}",
        "",
        f"**Pass rate: {len(passed)}/{len(graded)} "
        f"({100 * len(passed) / max(len(graded), 1):.1f}%)**",
        "",
        f"- mean ops per graded episode: {_fmt(mean(r.get('ops') for r in graded), '.1f')}",
        f"- mean ops per PASS: {_fmt(mean(r.get('ops') for r in passed), '.1f')}",
        f"- mean ops per turn: {_fmt(mean(r.get('ops_per_turn') for r in graded), '.2f')}"
        "  (1.00 means the model never batched)",
        f"- mean duration per PASS: {_fmt(mean(r.get('duration_s') for r in passed), '.0f')}s",
        f"- total cost: ${_fmt(sum(r.get('cost_usd') or 0 for r in rows), '.2f')}",
        "",
        "| task | pass | ops (mean) | tokens in/out | notes |",
        "|---|---|---|---|---|",
    ]
    for task in sorted(by_task):
        group = by_task[task]
        ok = [r for r in group if r.get("status") == "ok"]
        wins = sum(1 for r in ok if r.get("success"))
        faults = len(group) - len(ok)
        lines.append(
            f"| {task} | {wins}/{len(ok)} | "
            f"{_fmt(mean(r.get('ops') for r in ok), '.1f')} | "
            f"{_fmt(mean(r.get('input_tokens') for r in ok), '.0f')}/"
            f"{_fmt(mean(r.get('output_tokens') for r in ok), '.0f')} | "
            f"{('%d harness fault(s)' % faults) if faults else ''} |"
        )

    text = "\n".join(lines) + "\n"
    dest = out / "report.md"
    dest.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {dest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="fix the task list and seeds up front")
    p.add_argument("--out", required=True)
    p.add_argument("--tasks", help="comma-separated subdomains; default all 125")
    p.add_argument("--limit", type=int, help="first N tasks (smoke runs)")
    p.add_argument("--seeds", help=f"comma-separated; default {DEFAULT_SEEDS}")
    p.add_argument("--policy", default="loop", choices=["loop", "agent"],
                   help="loop is the inline model->ops loop; agent spawns a CLI.")
    p.add_argument("--provider", default=DEFAULT_PROVIDER,
                   choices=["openrouter", "anthropic"])
    p.add_argument("--agent", default="claude", choices=["claude", "opencode"])
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--no-mcp", action="store_true")
    p.add_argument("--agent-timeout", type=float, default=300.0)
    p.add_argument("--server", default="http://127.0.0.1:8766")
    p.add_argument("--force", action="store_true", help="overwrite an existing plan")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="execute the plan; resumable")
    p.add_argument("--out", required=True)
    p.add_argument("--max-episodes", type=int, help="stop after N this pass")
    p.add_argument("--shard", help="this worker's slice, as i/n (e.g. 1/4). Run "
                                   "one process per shard, each with its own "
                                   "--server port and browser profile.")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="render results as markdown")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
