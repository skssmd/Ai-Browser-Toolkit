"""Rebuild a finished episode turn by turn, from what was actually kept.

The console trace is a summary by design: it flattens what the model said to
400 characters and what the page gained to 200, so that a long sweep stays
watchable. That is the wrong artifact for asking "what exactly did this episode
see", and the question comes up whenever a run has to be explained rather than
scored.

The answer is that nothing was lost, only split. The toolkit's own session log
carries every command it was handed and every response it sent back, complete,
with timings and errors -- but not a word of the model's reasoning, since the
toolkit never sees it. The trace carries the reasoning and nothing complete.
Neither alone is a retrace; together they are.

So this joins them. Episodes are delimited in the session log by the
`browser_start` / `browser_restart` that opens each one, which makes the log a
sequence of episode-sized segments; the trace says which ops belong to which
turn. Matching the two on the sequence of op names -- rather than on
timestamps, which need a timezone to be right and are only ever approximately
right -- pins the segment to the trace with no ambiguity, and refuses rather
than guesses when nothing matches.

Runs from 0.5.1 on need none of this: the loop writes the untouched response
beside the trace as it goes. This is for everything before that.

    python retrace.py --events <events.jsonl> --trace <trace.log> --out <md>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TURN = re.compile(r"^--- turn (\d+) -+\s*$")
SAYS = re.compile(r"^  \[(says|think)\s*\] (.*)$")
SENDING = re.compile(r"^  \[ops  \] sending (\d+):")
OP_LINE = re.compile(r"^          (\w+)\s")
BACK = re.compile(r"^  \[back \] (\d+) ops, (ok|(\d+) FAILED)")

# Housekeeping the loop issues around an episode rather than during it. They
# appear in the log between episodes and would otherwise shift every match by
# one.
BOUNDARY = {"browser_start", "browser_restart"}

# The harness talks to the toolkit too, and the model never sees those calls, so
# the trace has no line for them. Two kinds: `current_url`, which the runner asks
# before and after every episode to decide where the browser ended up, and the
# `goto` to the site's front page that opens an episode. Both must be stepped
# over, and the opening goto especially -- it is the same op name as the model's
# own first move, so a matcher looking only at op names pairs turn 1 with the
# harness's navigation and every turn after it lands one event early.
HARNESS = {"current_url"}


def harness_opening(event: dict) -> bool:
    """The runner's own `goto` to the front page, which opens each episode."""
    from urllib.parse import urlparse

    if event.get("op") != "goto":
        return False
    url = (event.get("request") or {}).get("url") or ""
    return urlparse(url).path in ("", "/")


def parse_trace(path: Path) -> tuple[str, list[dict]]:
    """The turns a trace describes: what was said, and which ops were sent."""
    header: list[str] = []
    turns: list[dict] = []
    current: dict | None = None
    in_ops = False

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TURN.match(line)
        if match:
            if current:
                turns.append(current)
            current = {"turn": int(match.group(1)), "says": "", "think": "",
                       "ops": [], "sent": 0, "failures": 0}
            in_ops = False
            continue

        if current is None:
            header.append(line)
            continue

        said = SAYS.match(line)
        if said:
            current[said.group(1)] = said.group(2)
            in_ops = False
            continue

        sending = SENDING.match(line)
        if sending:
            current["sent"] = int(sending.group(1))
            in_ops = True
            continue

        back = BACK.match(line)
        if back:
            current["failures"] = int(back.group(3) or 0)
            in_ops = False
            continue

        if in_ops:
            op = OP_LINE.match(line)
            if op:
                current["ops"].append(op.group(1))

    if current:
        turns.append(current)
    return "\n".join(header).strip(), turns


def segments(events: list[dict]) -> list[list[dict]]:
    """The log cut into episodes, each opening with a browser start."""
    out: list[list[dict]] = []
    for event in events:
        if event.get("op") in BOUNDARY or not out:
            out.append([])
        out[-1].append(event)
    return out


def signature(turns: list[dict]) -> list[str]:
    return [name for turn in turns for name in turn["ops"]]


def model_events(segment: list[dict]) -> list[dict]:
    """The segment with the harness's own calls taken out.

    Only the opening `goto` is dropped, not every front-page navigation: a task
    can legitimately send the model back to the front page mid-episode, and that
    move is the model's.
    """
    out: list[dict] = []
    opened = False
    for event in segment:
        if event.get("op") in BOUNDARY:
            continue
        if event.get("op") in HARNESS:
            continue
        if not opened and harness_opening(event):
            opened = True
            continue
        opened = True
        out.append(event)
    return out


def align(events: list[dict], turns: list[dict]) -> list[list[dict]] | None:
    """Hand each turn the events it produced, or say the two do not line up.

    A batch runs until its first failure and then stops, so a turn that reports
    failures owns fewer events than it sent ops -- the tail never ran, and
    reading on would steal the next turn's first event.
    """
    batches: list[list[dict]] = []
    cursor = 0
    for turn in turns:
        batch: list[dict] = []
        for name in turn["ops"]:
            if cursor >= len(events) or events[cursor].get("op") != name:
                break
            event = events[cursor]
            batch.append(event)
            cursor += 1
            if not event.get("ok"):
                break  # the rest of this batch never ran
        batches.append(batch)
    # Every event must have found a turn, or this is the wrong episode.
    if cursor != len(events):
        return None
    return batches


def pick(all_segments: list[list[dict]],
         turns: list[dict]) -> tuple[list[dict], list[list[dict]]] | None:
    """The one episode these turns describe. Ambiguity is refused, not guessed."""
    hits = []
    for segment in all_segments:
        events = model_events(segment)
        if not events:
            continue
        batches = align(events, turns)
        if batches is not None:
            hits.append((segment, batches, len(events)))
    if not hits:
        return None
    # Two episodes can run the same short op sequence; the one that accounts for
    # the most events is the one the trace describes.
    segment, batches, _ = max(hits, key=lambda hit: hit[2])
    return segment, batches


def fence(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return "```text\n" + value + "\n```\n"
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```\n"


def render(title: str, header: str, turns: list[dict],
           batches: list[list[dict]], limit: int | None) -> str:
    body = [f"# {title}\n"]
    if header:
        body.append("\n<details><summary>Task as the model was given it"
                    "</summary>\n\n```text\n" + header + "\n```\n</details>\n")

    shown = list(zip(turns, batches))
    if limit is not None:
        shown = shown[:limit]

    for turn, batch in shown:
        body.append(f"\n## Turn {turn['turn']}\n")
        if turn["think"]:
            body.append("**What it was thinking** *(trace only keeps the first "
                        "400 characters)*\n\n> " + turn["think"] + "\n")
        body.append("\n**What it said** *(trace only keeps the first 400 "
                    "characters)*\n\n> " + (turn["says"] or "*nothing — it went "
                    "straight to ops*") + "\n")

        if turn["failures"] and len(batch) < len(turn["ops"]):
            body.append(f"\n*It sent {len(turn['ops'])} ops; the batch stopped "
                        f"at the failure below, so the last "
                        f"{len(turn['ops']) - len(batch)} never ran.*\n")

        if not batch:
            body.append("\n*No toolkit events for this turn — the model sent no "
                        "ops, or the episode ended here.*\n")
            continue

        body.append(f"\n**The {len(batch)} command(s) it sent, and what came "
                    "back — verbatim**\n")
        for event in batch:
            status = "ok" if event.get("ok") else f"FAILED ({event.get('error_type')})"
            body.append(f"\n<b>{event.get('op')}</b> — {status}, "
                        f"{event.get('duration_ms')} ms, at "
                        f"`{event.get('url')}`\n")
            body.append("\nRequest:\n" + fence(event.get("request")))
            body.append("\nResponse:\n" + fence(event.get("response")))

    if limit is not None and len(turns) > limit:
        body.append(f"\n---\n\n*{len(turns) - limit} further turns not shown.*\n")
    return "".join(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, help="abt session events.jsonl")
    parser.add_argument("--trace", required=True, help="the episode's trace .log")
    parser.add_argument("--out", required=True, help="markdown to write")
    parser.add_argument("--turns", type=int, default=None,
                        help="stop after this many turns (default: all)")
    parser.add_argument("--title", default=None)
    args = parser.parse_args()

    events = [json.loads(line) for line in
              Path(args.events).read_text(encoding="utf-8").splitlines() if line.strip()]
    header, turns = parse_trace(Path(args.trace))
    if not turns:
        print("no turns found in the trace", file=sys.stderr)
        return 2

    found = pick(segments(events), turns)
    if found is None:
        print(f"no episode in {args.events} runs the {len(signature(turns))} ops "
              f"this trace describes -- wrong session log for this episode?",
              file=sys.stderr)
        return 3
    segment, batches = found

    title = args.title or Path(args.trace).stem
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(title, header, turns, batches, args.turns),
                   encoding="utf-8")
    matched = sum(len(b) for b in batches)
    print(f"{out} <- {len(turns)} turns, {matched} events "
          f"(seq {segment[0]['seq']}..{segment[-1]['seq']}, "
          f"{segment[0]['at']} .. {segment[-1]['at']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
