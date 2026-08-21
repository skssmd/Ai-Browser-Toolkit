"""Run WebArena episodes through abt -- same loop as run_miniwob.py.

Prerequisites (heavier than MiniWoB; do MiniWoB first):

1. The WebArena docker stack running locally (shopping, reddit, gitlab, map,
   wikipedia) -- see https://github.com/web-arena-x/webarena
2. A config json with the instance URLs and account credentials, in the
   format browsergym-webarena expects (the same one webarena's scripts use).
3. pip install browsergym-webarena into this benchmark venv.

Then:

    py benchmarks/browsergym/run_webarena.py --task-id 0 --config wa.cfg.json \
        --server http://127.0.0.1:8766

Scoring stays browsergym's: each episode ends with WebArenaTask.validate()
reading the shared browser / backend state. Nothing here grades anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent))
from adapter import AbtClient, inject_cdp_port, lower_action  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", type=int, required=True,
                    help="WebArena task id, see browsergym.webarena")
    ap.add_argument("--config", required=True,
                    help="webarena config json with URLs and credentials")
    ap.add_argument("--episodes", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--wait-ms", type=int, default=500)
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--out", default="results/webarena-run.json")
    args = ap.parse_args()

    inject_cdp_port(args.cdp_port)

    from browsergym.core.env import BrowserEnv
    from browsergym.webarena.task import WebArenaTask  # noqa: F401

    # NOTE: WebArenaTask construction requires the config env vars documented
    # in browsergym-webarena (SHOPPING_URL, REDDIT_URL, ... or a config path).
    # Wire the policy to an LLM before real runs: there is no scripted policy
    # for WebArena tasks.
    raise SystemExit(
        "Skeleton only: finish task construction + LLM policy per "
        "browsergym-webarena docs, mirroring run_miniwob.py's loop."
    )


if __name__ == "__main__":
    raise SystemExit(main())
