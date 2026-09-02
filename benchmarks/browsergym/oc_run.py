"""Run one opencode session and report back what it cost.

opencode's `run --format json` emits one JSON object per line. Everything the
old in-process loop recorded is in that stream, so nothing is lost by handing
the driving to opencode:

    step-start   a model call is beginning
    text         assistant prose (the final answer arrives here)
    tool         one tool invocation, with its state
    step-finish  that call's tokens {input,output,reasoning,cache{read,write}}
                 and cost

One `step-finish` is one model round trip, which is what `turns` has always
meant here, so the numbers stay comparable to the sweeps that came before.

The raw stream is written to a trace file as it arrives, line-buffered, so a
session that hangs or is killed still leaves everything it had said.

Parsing is deliberately forgiving. An unrecognised event is counted and
ignored rather than raising: opencode is a moving target, and an episode that
dies because a new event type appeared would cost far more than a missing
field.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

# The scored line. Anchored to line start so prose that merely mentions the
# word cannot match, and the LAST one wins -- a model that restates its answer
# should be taken at its final word.
_ANSWER = re.compile(r"^\s*ANSWER:\s*(.*?)\s*$", re.MULTILINE)


def answer_of(text: str) -> str | None:
    found = _ANSWER.findall(text or "")
    return found[-1].strip() if found else None


# Variables that reach opencode from whatever launched it and break it in
# ways it reports only as "Unexpected server error". It runs inside
# BrowserGym here, which is a Playwright process with its own ideas about
# proxies and Node, and an inherited proxy or CA override sends opencode's
# HTTPS calls somewhere that cannot answer them.
#
# Stripped rather than overridden: if the host genuinely needs a proxy, this
# is the wrong file to encode that in, and a benchmark talking to localhost
# needs none.
_STRIP = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "NODE_OPTIONS", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    return env


def _run_once(
    goal: str,
    model: str,
    agent: str = "webarena",
    cwd: str = ".",
    timeout: float = 1800.0,
    trace: str | None = None,
    binary: str = "opencode",
) -> dict:
    """Drive one task through opencode and return what it did and cost."""
    cmd = [
        binary, "run",
        "--agent", agent,
        "--model", model,
        "--auto",
        "--format", "json",
        goal,
    ]

    started = time.time()
    if trace:
        # The sweep may not have made the directory yet, and an episode that
        # dies for want of a folder wastes a model run for nothing.
        os.makedirs(os.path.dirname(trace) or ".", exist_ok=True)
    handle = open(trace, "w", encoding="utf-8", buffering=1) if trace else None
    texts: list[str] = []
    turns = ops = tool_failures = unknown = 0
    tin = tout = treason = tcache = 0
    cost = 0.0
    status = "ok"

    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return {"status": "launch_failed", "error": str(exc), "wall_s": 0.0}

    try:
        for line in proc.stdout:
            if handle:
                handle.write(line)
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            part = event.get("part") or {}
            kind = part.get("type") or event.get("type")

            if kind == "text":
                texts.append(part.get("text") or "")
            elif kind == "step-finish":
                turns += 1
                tokens = part.get("tokens") or {}
                tin += tokens.get("input") or 0
                tout += tokens.get("output") or 0
                treason += tokens.get("reasoning") or 0
                cache = tokens.get("cache") or {}
                tcache += cache.get("read") or 0
                cost += part.get("cost") or 0.0
            elif kind == "tool":
                ops += 1
                # The state key moves around between versions; look for a
                # failure marker anywhere rather than pinning one path.
                blob = json.dumps(part)
                if '"error"' in blob or '"status":"error"' in blob:
                    tool_failures += 1
            elif kind not in ("step-start", "reasoning", "snapshot"):
                unknown += 1

        proc.wait(timeout=max(timeout - (time.time() - started), 1))
    except subprocess.TimeoutExpired:
        proc.kill()
        status = "timeout"
    finally:
        if handle:
            handle.close()

    reply = "".join(texts)
    return {
        "status": status if proc.returncode in (0, None) or status != "ok" else "nonzero_exit",
        "returncode": proc.returncode,
        "reply": reply,
        "answer": answer_of(reply),
        "turns": turns,
        "ops": ops,
        "op_failures": tool_failures,
        "unknown_events": unknown,
        "input_tokens": tin,
        "output_tokens": tout,
        "reasoning_tokens": treason,
        "cache_read_tokens": tcache,
        "total_tokens": tin + tout,
        "cost": round(cost, 6),
        "wall_s": round(time.time() - started, 1),
    }


def run_opencode(
    goal: str,
    model: str,
    agent: str = "webarena",
    cwd: str = ".",
    timeout: float = 1800.0,
    trace: str | None = None,
    binary: str = "opencode",
    attempts: int = 5,
) -> dict:
    """Drive one task, retrying the transient failures of a free backend.

    opencode's hosted free models answer a lone request happily and then
    return `UnknownError: Unexpected server error` under a burst -- twelve
    episodes fired back to back all failed in about thirty seconds each,
    while the same call by hand a minute later succeeded. That is a rate
    limit wearing a stack trace.

    An attempt that produced no turns at all is the one worth repeating:
    nothing was spent and nothing was learned. An attempt that ran and then
    died has already cost tokens and may have changed the page, so it is
    returned as-is rather than run again on a dirty browser.

    The delay doubles from ten seconds, which is slower than the model and
    far cheaper than an episode scored zero for a reason that had nothing to
    do with the agent.
    """
    delay = 10.0
    last: dict = {}
    for attempt in range(1, max(attempts, 1) + 1):
        last = _run_once(goal, model, agent, cwd, timeout, trace, binary)
        if (last.get("turns") or 0) > 0:
            if attempt > 1:
                last["oc_attempts"] = attempt
            return last
        if attempt == attempts:
            break
        time.sleep(delay)
        delay = min(delay * 2, 120.0)

    last["oc_attempts"] = attempts
    last.setdefault("status", "no_turns")
    if last.get("status") == "nonzero_exit":
        last["status"] = "backend_error"
    return last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("goal")
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--agent", default="webarena")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--trace")
    ap.add_argument("--binary", default="opencode")
    args = ap.parse_args()

    result = run_opencode(
        args.goal, args.model, args.agent, args.dir,
        args.timeout, args.trace, args.binary,
    )
    json.dump(result, sys.stdout, indent=1)
    print()
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
