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



SEED_TARGET = 5
"""How many entries a site's playbook needs before we stop asking for more.

A playbook nobody writes never helps anybody, and a feature that only pays off
once someone has already used it cannot be measured at all. So the first few
episodes on an untouched site are asked to leave a note; once the site has
enough of them the ask disappears, and from then on whether an agent reads or
writes one is decided by the toolkit's own documentation and nothing else.

The ask is deliberately site-agnostic: it says "write down what you worked
out", never what to look for here. Seeding memory is legitimate, seeding
answers is not, and that sentence is the line between them.

Every episode records `seeded`, so the two phases are a fact in the data
rather than something anyone has to remember.
"""


def _observed(client, expected: dict) -> dict:
    """What the page actually held where the evaluator was going to look.

    A program_html task is scored on page content, so a failure says only
    "wrong" unless you also keep what was there. webarena.532 filled a contact
    form with four required phrases, missed one by a word, and left no way to
    tell which -- the trace elides long op values and the session log had
    rotated. Recording the locator's own value turns that from a guess into a
    diff.

    Runs before env.close(), because the browser goes with it. Never raises: a
    diagnostic that can cost an episode its record is worse than none.
    """
    seen = {}
    for i, rule in enumerate(expected.get("program_html") or []):
        locator = (rule.get("locator") or "").strip()
        if not locator:
            continue
        try:
            answer = client.command(
                {"op": "run_js", "script": "return " + locator.rstrip(";")}
            )
            value = (answer.get("result") or {}).get("value")
            if isinstance(value, str):
                value = value[:2000]
            seen[str(i)] = value
        except Exception:
            seen[str(i)] = None
    return seen


def _playbook_entries(site: str) -> int:
    """How many entries this site's playbook already holds."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from abt import guidelines

        return guidelines.read(site + "/learned.md").count(chr(10) + "## ")
    except Exception:
        return 0


def trace_path_for(out: str) -> str:
    """results/<sweep>/raw/<task>.json -> results/<sweep>/traces/<task>.log

    Derived rather than passed as a flag: the sweep parent that launches this
    process is already running and cannot learn a new argument.
    """
    raw = Path(out)
    return str(raw.parent.parent / "traces" / (raw.stem + ".log"))



def answer_of(reply: str) -> str:
    """The `ANSWER:` line, or the whole reply if there is not one.

    A reasoning model narrates its conclusion; exact_match compares the whole
    string. The marker separates the two so the agent can do both. Taking the
    LAST marker matters -- a model that reconsiders writes more than one, and
    the final one is the one it settled on.

    Falling back to the whole reply keeps an episode that forgot the marker
    scoring exactly as it did before the marker existed.
    """
    found = None
    for line in reply.splitlines():
        stripped = line.strip().lstrip("*# ").strip()
        if stripped.upper().startswith("ANSWER:"):
            found = stripped[len("ANSWER:"):].strip().strip("*`").strip()
    return found if found else reply


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--server", default="http://127.0.0.1:8766")
    ap.add_argument("--provider", default="openrouter")
    ap.add_argument("--oc-binary", default="/root/.opencode/bin/opencode")
    ap.add_argument("--oc-dir", default="/opt/webarena/bench/oc")
    ap.add_argument("--oc-agent", default="webarena")
    ap.add_argument("--model", default="stealth/ox-alpha")
    ap.add_argument("--max-turns", type=int, default=30,
                    help="Turn ceiling. 25 truncated 7%% of shopping tasks -- "
                         "all of them multi-step 'buy the X' flows that ran out "
                         "mid-checkout. Cost grows with the square of turns, so "
                         "raise this deliberately, not by default.")
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--trace-port", type=int, default=None,
                    help="Serve the live loop view on this port while running.")
    ap.add_argument("--headed", dest="headless", action="store_false",
                    default=True,
                    help="Show the browser. Needs a display; on a server the "
                         "run dies at startup without one.")
    ap.add_argument("--shopping-url", default="http://localhost:7770",
                    help="Where the shopping site answers. Must be the host "
                         "the site REDIRECTS TO, not merely one that reaches "
                         "it: WebArena's validate() rejects any open tab whose "
                         "netloc is not in this list, scoring 0 before the "
                         "evaluator runs. Magento redirects to localhost, so "
                         "127.0.0.1 here silently zeroes every episode.")
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
    # A high, unused port -- NOT a low one. Chrome refuses ports on its
    # reserved list outright with ERR_UNSAFE_PORT, which is not a connection
    # failure and so never reaches the "site not running" branch: the episode
    # dies as a harness error instead of being recorded as skipped.
    absent = "http://127.0.0.1:19999"
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
        if any(marker in text for marker in
               ("connection", "refused", "err_connection", "not running")):
            print("site not running", file=sys.stderr)
            return 3
        raise

    client.attach(headless=args.headless)

    # attach() restarts the browser, which reconnects to BrowserGym's Chromium
    # but loses the page BrowserGym had already navigated to -- so the agent
    # woke up on about:blank, was asked a shopping question, and went to the
    # real amazon.com to answer it. Every op after that was against the open
    # internet rather than the benchmark, which is worse than a failure: it
    # looks like a result.
    start_url = obs.get("url") or ""
    if start_url and not start_url.startswith("about:"):
        client.command({"op": "goto", "url": start_url})
    landed = (client.command({"op": "current_url"}).get("result") or {}).get("url")
    if not landed or landed.startswith("about:"):
        print(f"could not land on the task page (got {landed!r})", file=sys.stderr)
        return 4

    ops_before, errs_before = client.op_tally()
    started = time.time()

    # The site is named in the goal on purpose. Without it the model has only
    # the page in front of it, and a shopping question with no stated site is
    # an invitation to go and find one.
    # Captured here, not read back off the post-step obs. The judge-unavailable
    # path replaces obs with an empty dict, so exactly the episodes that need
    # judging by hand were losing the one field a human needs to judge them.
    task_goal = obs.get("goal") or ""
    # The netloc, which is what the toolkit itself keys playbooks by. An
    # earlier version invented "webarena-reddit" on the theory that every site
    # shares one localhost key -- but the netloc carries the port, so the six
    # sites are already distinct, and the invented key only hid the notes
    # agents had already filed under the real one.
    from urllib.parse import urlsplit

    site_key = urlsplit(start_url).netloc or "localhost"

    goal = (
        f"{obs.get('goal') or ''}\n\n"
        f"You are on a self-contained store at {start_url}. Everything you need "
        f"is on this site. Do NOT navigate to any other domain -- there is no "
        f"internet here, and the task is only about this site.\n\n"
        f"If the task asks you to show, find or open something, LEAVE THE "
        f"BROWSER ON that page when you finish -- do not navigate away to "
        f"summarise. Where you end up is part of the answer.\n\n"
        f"END YOUR FINAL MESSAGE WITH A LINE OF EXACTLY THIS FORM:\n\n"
        f"    ANSWER: <the answer>\n\n"
        f"That line is compared to the expected answer as a string, character "
        f"for character, after lowercasing -- so it must hold the answer and "
        f"nothing else: no markdown, no bold, no units that were not asked "
        f"for, no restating the question, nothing after it. Say whatever you "
        f"like above that line; only the line is scored.\n"
        f"  - A number or amount: digits only -- 47.41, not $47.41 or "
        f"**$47.41** or 'about $47.41'. Include a decimal only if the value "
        f"has one.\n"
        f"  - A count of zero is still an answer: write 0, do not write that "
        f"there were none.\n"
        f"  - A name or title: copy it exactly as the site spells it, "
        f"including any (R) or (tm), and nothing around it.\n"
        f"  - Dimensions or sizes: copy the site's own spelling.\n"
        f"  - Several values: separate them with ', ' and nothing else.\n"
        f"  - Genuinely impossible or not present on the site: N/A\n\n"
        f"KNOWING WHEN TO STOP IS PART OF THE TASK. If you have looked in the "
        f"places a feature would be and it is in none of them, that is a "
        f"finding, not a reason to keep looking. Answer N/A and stop. Some of "
        f"these tasks ask for something the site genuinely cannot do, and N/A "
        f"is the right answer to those -- it is not giving up.\n"
        f"Concretely: once you have checked the obvious UI, searched the page "
        f"for the control, and tried the plausible URLs, you have your answer. "
        f"Probing for undocumented routes, introspecting GraphQL, and reading "
        f"the site's JavaScript config have never once found a feature that "
        f"was not in the UI, and each attempt costs a turn you cannot get "
        f"back.\n"
        f"Never substitute a DIFFERENT action that looks close. Editing an "
        f"account default when you were asked to change one order is a wrong "
        f"answer, not a partial one."
    )
    seeded = _playbook_entries(site_key) < SEED_TARGET
    if seeded:
        goal += (
            "\n\nIf you work something out here that the next run would rather "
            "be told than rediscover, write it down before you finish. Say what "
            "did not work as well as what did. Skip it if this task taught you "
            "nothing."
        )
    if args.provider == "opencode":
        # opencode owns the loop, so the prompt shrinks to what only this
        # harness knows: the task and which site it lives on. How to drive
        # the toolkit comes from abt's own MCP instructions, and the answer
        # format from the agent definition -- restating either here would
        # measure our prompt rather than the product.
        import oc_run

        oc_goal = (
            f"{task_goal}\n\n"
            f"You are on a self-contained site at {start_url}. Everything you "
            f"need is on this site. Do NOT navigate to any other domain -- "
            f"there is no internet here, and the task is only about this site."
        )
        raw = oc_run.run_opencode(
            goal=oc_goal,
            model=args.model,
            agent=args.oc_agent,
            cwd=args.oc_dir,
            timeout=float(args.timeout) if getattr(args, "timeout", None) else 1800.0,
            trace=trace_path_for(args.out),
            binary=args.oc_binary,
        )
        turns = raw.get("turns") or 0
        session = {
            "provider": "opencode",
            "model": args.model,
            "turns": turns,
            # opencode enforces no ceiling of its own, so this can only be
            # reported, never imposed. Left honest rather than faked.
            "hit_turn_limit": bool(args.max_turns) and turns >= args.max_turns,
            "ops_sent": raw.get("ops") or 0,
            "op_failures": raw.get("op_failures") or 0,
            "ops_per_turn": round((raw.get("ops") or 0) / max(turns - 1, 1), 2),
            "usage": {
                "input": raw.get("input_tokens") or 0,
                "output": raw.get("output_tokens") or 0,
                "cache_read": raw.get("cache_read_tokens") or 0,
                "cache_write": 0,
                "billable_input": raw.get("input_tokens") or 0,
            },
            "reply": (raw.get("reply") or "")[-2000:],
            "oc_status": raw.get("status"),
            "oc_cost": raw.get("cost"),
        }
    else:
        session = loop_policy.run_episode(
            goal=goal,
            server=args.server,
            model=args.model,
            max_turns=args.max_turns,
            provider=args.provider,
            quiet=False,
            trace_port=args.trace_port,
            trace_path=trace_path_for(args.out),
        )

    wall = time.time() - started
    ops_after, errs_after = client.op_tally()

    # Read BEFORE closing. The config is a temp file BrowserGym deletes on
    # close, and the browser goes with it -- gathering afterwards silently
    # produced None for both, which is the kind of empty field nobody notices
    # until the judging pass has nothing to judge.
    eval_types, reference, expected = [], None, {}
    try:
        config = json.loads(Path(env.unwrapped.task.config_file).read_text())
        spec = config.get("eval") or {}
        eval_types = spec.get("eval_types") or []
        reference = spec.get("reference_answers") or spec.get("reference_url")
        # A program_html task has no reference *string* -- what it expects is
        # a program that inspects the page. Recording only reference_answers
        # left every such episode with an empty "answer required" field and no
        # way to tell a near miss from a wrong page: 47 of shopping's 187 are
        # scored this way, and each one failed silently to the reader.
        expected = {
            key: spec[key]
            for key in ("program_html", "url_note", "reference_url")
            if spec.get(key)
        }
    except Exception:
        pass
    observed = _observed(client, expected)
    try:
        final_url = (
            client.command({"op": "current_url"}).get("result") or {}
        ).get("url")
    except Exception:
        final_url = None

    # The answer must reach the evaluator as an action, not just our record:
    # WebArena's string_match reads the last send_msg_to_user of the episode,
    # so ending on noop scored an empty string every time, however right the
    # agent was. repr() gives a correctly escaped Python string literal, which
    # is exactly what BrowserGym's action parser expects.
    reply_text = (session.get("reply") or "").strip()
    answer = answer_of(reply_text)
    final_action = f"send_msg_to_user({answer!r})" if answer else "noop(500)"
    judge = "ok"
    try:
        obs, reward, terminated, truncated, info = env.step(final_action)
    except Exception as exc:  # noqa: BLE001 - classified below
        detail = f"{type(exc).__name__}: {exc}"
        if "OPENAI_API_KEY" in detail or "openai" in detail.lower():
            # WebArena's fuzzy_match asks GPT-4 whether the answer means the
            # same as the reference. Without a key the evaluator raises, and
            # that exception used to escape and turn a completed episode into
            # a harness_error -- losing the turns, the tokens and the reply
            # for work the agent had already done correctly.
            #
            # The agent is not what failed here. Keep everything, score 0 for
            # now, and mark it so a later pass can judge it from the goal,
            # the reference and the reply that are already recorded.
            judge, reward, terminated, truncated = "unavailable", 0.0, True, False
            obs, info = {}, {}
        else:
            # A malformed answer must not cost the episode its score either --
            # fall back to the old ending, which still validates site state.
            judge = "fallback"
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
        # What the evaluator actually saw. Without this, a 0 is ambiguous
        # between "answered wrongly" and "answer never reached the scorer".
        "scored_action": final_action[:200],
        # "unavailable" means nobody could score this, not that it was wrong.
        # Exclude those from any pass rate, and judge them separately.
        "judge": judge,
        "answer_sent": answer[:300],
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
        "goal": task_goal[:600],
        # Judging happens AFTER the sweep, not inside it: scoring is a pass
        # over the record, so a judging mistake costs a re-read rather than
        # eight hours of re-browsing. That only works if the record carries
        # what a judge needs -- the reference answer and what kind of check
        # WebArena wanted -- so it is captured here rather than looked up
        # later against a task file that may have moved on.
        "eval_types": eval_types,
        "expected": expected,
        "observed": observed,
        "seeded": seeded,
        "reference_answer": reference,
        "final_url": final_url,
        "reply": session.get("reply") or "",
    })

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"reward={record['reward']} ops={ops} turns={record['turns']} "
          f"tokens={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
