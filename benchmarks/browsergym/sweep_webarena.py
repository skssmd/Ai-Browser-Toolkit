"""Run WebArena tasks through abt, recording what BrowserGym does not.

BrowserGym answers one question: did the agent complete the task. That is the
question it should answer, and this file never touches it -- `validate()` reads
the site's own state and the score comes back untouched.

Everything else here exists because no web-agent benchmark reports it. A score
tells you a model finished a task; it says nothing about whether the *toolkit*
helped or fought it. So each episode also records:

  turns            round trips to the model
  ops              operations the toolkit ran -- counted by the SERVER's log,
                   never self-reported, so an agent that claims three and runs
                   nine is counted at nine
  op_failures      how often the toolkit refused
  op_success_rate  the learning signal: an agent that has worked out the tool
                   stops being refused
  ops_per_turn     did it batch, or pay a round trip per step
  tokens           input / output / cached -- the cost the toolkit exists to cut
  model_s          time waiting on the model
  browser_s        time inside the browser
  op_mix           which ops it chose, for judging whether it reached for the
                   right one

The split matters: `ops` and `tokens` move in opposite directions on different
tasks, and only one of them is the toolkit's doing. A page-heavy task is
expensive in tokens because the page is big; a fiddly one is expensive in ops
because the widget is awkward.

    py sweep_webarena.py plan  --out results/wa-shopping --sites shopping
    py sweep_webarena.py run   --out results/wa-shopping
    py sweep_webarena.py report --out results/wa-shopping
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
RUNNER = HERE / "run_webarena_one.py"

DEFAULT_MODEL = "stealth/ox-alpha"
DEFAULT_PROVIDER = "openrouter"


def _task_sites() -> dict[str, list[str]]:
    """Which sites each task needs, read from WebArena's own task file.

    Read rather than hardcoded: the mapping is data that ships with the
    benchmark, and a copy here would drift the moment the task set changed.
    Returns {} if the file cannot be found, and the caller then plans
    everything -- degraded, not broken.
    """
    import json as _json
    import os
    import site

    for base in site.getsitepackages():
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if not name.endswith(".json") or "test" not in name:
                    continue
                path = Path(dirpath) / name
                try:
                    data = _json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, list) and data and "sites" in (data[0] or {}):
                    return {
                        f"webarena.{t['task_id']}": t.get("sites") or []
                        for t in data
                    }
    return {}


def plan_path(out: Path) -> Path:
    return out / "plan.json"


# Outcomes a retry cannot improve. Everything else goes back in the queue.
#
#   ok            ran and was scored -- the answer will not change
#   skipped_site  the site is not running; retrying reaches the same absence
#
# harness_error and harness_timeout are deliberately absent. They describe the
# environment at a moment -- a 402, a container that had not finished booting,
# a key that expired -- not the task. Counting them as done struck 39 tasks off
# one plan without a single turn being spent on them.
SETTLED = frozenset({"ok", "skipped_site"})


def read_rows(out: Path) -> list[dict]:
    """Every recorded episode, in the order they were written."""
    rows: list[dict] = []
    for path in sorted(Path(out).glob("episodes*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """One row per task: the settled one, else the last attempt.

    A retried task has more than one row. Counting all of them would report a
    task that failed once and passed later as both, and would make the totals
    disagree with the plan.
    """
    best: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("task_id"))
        current = best.get(key)
        if current is None or (
            row.get("status") in SETTLED and current.get("status") not in SETTLED
        ):
            best[key] = row
        elif current.get("status") not in SETTLED:
            best[key] = row  # keep the most recent attempt
    return list(best.values())


def _truncated(row: dict, max_turns: int | None) -> bool:
    """Did this episode stop because it ran out of turns, under a lower ceiling?

    Only true while the ceiling has since been raised. A task run at 40 and
    stopped at 40 is finished; retrying it would loop.
    """
    # Retrying these is switched off. Raising the ceiling 25 -> 30 -> 32 and
    # re-running 32 capped episodes reproduced the same ceiling failure every
    # time, at about three cents each. webarena.284 showed why: a good share
    # of them are long-but-answerable tasks -- scan a product pool, find the
    # cheapest match -- not tasks the site cannot do. No ceiling short of
    # absurd finishes those, and no prompt shortens genuine work.
    #
    # The mechanism stays, because raising the ceiling for a NEW reason is
    # still the right trigger. Flip this to re-enable it.
    return False
    if not row.get("hit_turn_limit") or (row.get("reward") or 0) > 0:
        return False
    if not max_turns:
        return False
    return (row.get("turns") or 0) < max_turns


def load_done(out: Path, max_turns: int | None = None) -> set[str]:
    """Task ids that need no further attempt.

    A task cut off by a ceiling that has since been raised is not one of them.
    The seven "buy the highest rated X" flows that stopped mid-checkout at 25
    turns were failures of the budget, not of the agent.
    """
    done = set()
    for row in read_rows(out):
        if "task_id" not in row or row.get("status") not in SETTLED:
            continue
        if _truncated(row, max_turns):
            continue
        done.add(str(row["task_id"]))
    return done


def cmd_plan(args) -> int:
    """Fix the task list before running, and record why each was included."""
    from browsergym.webarena import ALL_WEBARENA_TASK_IDS

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = plan_path(out)
    if dest.exists() and not args.force:
        raise SystemExit(
            f"{dest} exists. A plan is a commitment; rewriting it after a run "
            f"invalidates the results. --force starts a genuinely new sweep."
        )

    task_ids = sorted(ALL_WEBARENA_TASK_IDS)
    if args.sites:
        # Only plan tasks whose sites are actually running. A task needing an
        # absent site is skipped at run time anyway, but planning it wastes a
        # browser launch each -- and a plan padded with tasks that cannot be
        # scored makes the completion figure meaningless.
        wanted = set(args.sites.split(","))
        by_id = _task_sites()
        if by_id:
            task_ids = [
                t for t in task_ids
                if by_id.get(t) is not None and set(by_id[t]) <= wanted
            ]
    if args.limit:
        task_ids = task_ids[: args.limit]

    plan = {
        "benchmark": "webarena",
        "created": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "server": args.server,
        "sites_running": args.sites.split(","),
        "trace_port": args.trace_port,
        # Each concurrent sweep needs its own, or two workers fight over one
        # browser: BrowserGym launches chromium on this port and abt attaches
        # to it, so a shared port silently crosses the wires.
        "cdp_port": args.cdp_port,
        # Recorded so a resume can tell a task that failed from one that was
        # cut off. Raise it and the truncated ones become runnable again.
        "max_turns": args.max_turns,
        # Stated in the plan because it bounds every number that comes out:
        # a task needing a site that is not up is skipped, never failed.
        "note": (
            "Only the listed sites are running. Tasks needing others are "
            "recorded as skipped, not as failures."
        ),
        "task_ids": task_ids,
        "episodes": len(task_ids),
    }
    dest.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"planned {len(task_ids)} tasks -> {dest}")
    return 0


def run_one(plan: dict, out: Path, task_id: str, budget: float) -> dict:
    """One task in its own process, so a wedged browser costs one episode."""
    scratch = out / "raw" / f"{task_id}.json"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(RUNNER),
        "--task-id", str(task_id),
        "--server", plan["server"],
        "--provider", plan["provider"],
        "--model", plan["model"],
        "--out", str(scratch),
    ]
    if plan.get("trace_port"):
        cmd += ["--trace-port", str(plan["trace_port"])]
    if plan.get("cdp_port"):
        cmd += ["--cdp-port", str(plan["cdp_port"])]
    if plan.get("max_turns"):
        cmd += ["--max-turns", str(plan["max_turns"])]
    started = time.time()
    row = {"task_id": task_id, "started": datetime.now(timezone.utc).isoformat()}
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=budget, cwd=str(HERE.parent.parent),
        )
    except subprocess.TimeoutExpired:
        row.update({"status": "harness_timeout", "success": False,
                    "wall_s": round(time.time() - started, 1)})
        return row

    row["wall_s"] = round(time.time() - started, 1)
    if not scratch.exists():
        tail = (proc.stderr or proc.stdout or "")[-500:]
        # A task whose site is not running is not a failure of anything.
        status = "skipped_site" if "site not running" in tail else "harness_error"
        row.update({"status": status, "success": False, "stderr_tail": tail})
        return row

    row.update(json.loads(scratch.read_text(encoding="utf-8")))
    return row


ERROR_RUN_LIMIT = 6


def cmd_run(args) -> int:
    consecutive_errors = 0
    out = Path(args.out)
    plan = json.loads(plan_path(out).read_text(encoding="utf-8"))
    done = load_done(out, plan.get("max_turns"))
    todo = [t for t in plan["task_ids"] if str(t) not in done]
    if args.max_episodes:
        todo = todo[: args.max_episodes]
    print(f"{len(done)} recorded, {len(todo)} to run")

    sink = out / "episodes.jsonl"
    for index, task_id in enumerate(todo, 1):
        print(f"[{index}/{len(todo)}] task {task_id} ...", flush=True)
        row = run_one(plan, out, task_id, args.timeout)

        # An unbroken run of harness errors means the environment changed
        # under the sweep, not that these tasks are hard. Carrying on spends
        # the plan on failures nobody can score.
        if row.get("status") == "harness_error":
            consecutive_errors += 1
        else:
            consecutive_errors = 0
        if consecutive_errors >= ERROR_RUN_LIMIT:
            print(
                f"\n  STOPPING: {consecutive_errors} harness errors in a row.\n"
                f"  Something the sweep depends on has changed -- the model, a "
                f"site container, or the API key.\n"
                f"  Last error tail:\n    "
                + (row.get("stderr_tail") or "(none recorded)")[-400:].replace(
                    "\n", "\n    "
                ),
                flush=True,
            )
            break
        with sink.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        mark = "PASS" if row.get("success") else row.get("status", "fail")
        print(f"    {mark}  ops={row.get('ops')} turns={row.get('turns')} "
              f"tok={row.get('total_tokens')} {row.get('wall_s')}s", flush=True)
    return 0


def _mean(rows, key):
    values = [r.get(key) for r in rows if r.get(key) is not None]
    return sum(values) / len(values) if values else None


def _fmt(value, spec=".1f"):
    return "-" if value is None else format(value, spec)


def cmd_report(args) -> int:
    out = Path(args.out)
    plan = json.loads(plan_path(out).read_text(encoding="utf-8"))
    # One row per task. A retried task has several, and counting them all
    # would report the same task as both a failure and a pass.
    rows = dedupe_rows(read_rows(out))

    graded = [r for r in rows if r.get("status") == "ok"]
    passed = [r for r in graded if r.get("success")]
    skipped = [r for r in rows if r.get("status") == "skipped_site"]
    faults = [r for r in rows if r.get("status") in ("harness_error", "harness_timeout")]

    total_ops = sum(r.get("ops") or 0 for r in graded)
    total_fail = sum(r.get("op_failures") or 0 for r in graded)
    tokens = sum(r.get("total_tokens") or 0 for r in rows)

    lines = [
        f"# WebArena — {plan['model']} via abt",
        "",
        f"- sites running: {', '.join(plan['sites_running'])}",
        f"- graded {len(graded)} | skipped (site not up) {len(skipped)} | "
        f"harness faults {len(faults)}",
        "",
        "## Task success — scored by WebArena, not by us",
        "",
        f"**{len(passed)}/{len(graded)} "
        f"({100 * len(passed) / max(len(graded), 1):.1f}%)**",
        "",
        "## Toolkit metrics — ours, and not part of the score",
        "",
        "| metric | value | reads as |",
        "|---|---|---|",
        f"| ops per task | {_fmt(_mean(graded, 'ops'))} | how much work the toolkit did |",
        f"| ops per turn | {_fmt(_mean(graded, 'ops_per_turn'), '.2f')} | 1.00 means it never batched |",
        f"| **op success rate** | **{100 * (total_ops - total_fail) / max(total_ops, 1):.1f}%** "
        f"| **whether the agent learned the tool** |",
        f"| turns per task | {_fmt(_mean(graded, 'turns'))} | round trips to the model |",
        f"| tokens per task | {_fmt(_mean(graded, 'total_tokens'), ',.0f')} | the cost |",
        f"| cached share | {_fmt(_mean(graded, 'cache_share'), '.0%')} | prefix caching working |",
        f"| model time | {_fmt(_mean(graded, 'model_s'), '.0f')}s | waiting on the model |",
        f"| browser time | {_fmt(_mean(graded, 'browser_s'), '.1f')}s | inside the browser |",
        f"| total tokens burned | {tokens:,} | |",
        "",
        "## Per task",
        "",
        "| task | pass | ops | fails | turns | tokens | wall |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('task_id')} "
            f"| {'yes' if row.get('success') else (row.get('status') or 'no')} "
            f"| {row.get('ops', '-')} | {row.get('op_failures', '-')} "
            f"| {row.get('turns', '-')} | {row.get('total_tokens', '-')} "
            f"| {row.get('wall_s', '-')}s |"
        )

    text = "\n".join(lines) + "\n"
    (out / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--sites", default="shopping")
    p.add_argument("--max-turns", type=int, default=30,
                   help="Turn ceiling for every episode in this plan. 25 cut "
                        "off 7%% of shopping tasks mid-checkout. Cost grows "
                        "with the square of turns.")
    p.add_argument("--cdp-port", type=int, default=None,
                   help="Debugging port for this sweep's browser. Give each "
                        "concurrent sweep its own; 9222 is the default when "
                        "unset and is what a lone sweep already uses.")
    p.add_argument("--provider", default=DEFAULT_PROVIDER)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--server", default="http://127.0.0.1:8766")
    p.add_argument("--trace-port", type=int, default=9100,
                   help="Each episode serves its live loop view here.")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run")
    p.add_argument("--out", required=True)
    p.add_argument("--max-episodes", type=int)
    p.add_argument("--timeout", type=float, default=900.0)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
