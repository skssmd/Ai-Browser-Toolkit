# Understanding the benchmark

Five documents. Read them in order the first time; after that they are
reference.

| | |
|---|---|
| [00 — setting it up from scratch](00-setting-up-from-scratch.md) | a blank VPS to the workers, with the exact commands that were run |
| [01 — servers and tunnels](01-servers-and-tunnels.md) | what listens on the host, how to start each one, how to see them from your machine |
| [02 — running a sweep](02-running-a-sweep.md) | sites, plan, run, resume — and the traps that cost hours |
| [03 — what gets logged](03-what-gets-logged.md) | the four record layers, what each can answer, and where each lies to you |
| [04 — cross-site tasks](04-multisite-tasks.md) | the multisite pairings (currently reddit+shopping, 5 tasks) and the one prompt line that permits them |

Related, outside this folder:

- [`../WEBARENA-SETUP.md`](../WEBARENA-SETUP.md) — the earlier shopping-era
  install, with the measured image sizes and how each harness bug was proven
- [`../WEBARENA.md`](../WEBARENA.md) — the original harness notes
- [`../dashboard.py`](../dashboard.py) — the analytics dashboard itself, the
  same file that runs live on `:9102`
- [`../../../guidelines/toolkit-workflow.md`](../../../guidelines/toolkit-workflow.md)
  — how to drive the toolkit itself

## The short version

Three workers on a VPS, model `stealth/union-alpha`. Right now they are
**shopping** (`localhost:7770`, 187 tasks), **shopping_admin**
(`localhost:7780/admin`, 182) and a **shopping+reddit multisite** pass
(5 cross-site tasks). Each has its own toolkit server, browser profile, CDP
port, trace port and results directory — sharing any of them breaks in a way
that does not announce itself.

| | shopping | shopping_admin | multisite |
|---|---|---|---|
| site port | `7770` (+ `7771` ctrl) | `7780` (+ `7781` ctrl, `/admin`) | `7770` + `9999` |
| toolkit server | `8766` | `8767` | `8768` |
| profile | `bench/profile` | `bench/profile-reddit` | `bench/profile-multi` |
| CDP | `9222` | `9223` | `9224` |
| trace | `9100` | `9101` | `9103` |
| results | `results/wa-shopping/` | `results/wa-admin/` | `results/wa-multisite/` |

A plan is written once and fixes the model, the ports, the turn ceiling and
the task list. The turn ceiling is **100** everywhere (`--max-turns` in
`sweep_webarena.py`, `run_webarena_one.py`, `loop_policy.py`). The sweep runs
each task in its own process, appends a row per episode, and can be stopped and
resumed at any point.

GitLab was retired on 2026-09-17 (its ~60 GB image and the swapfile it needed
were not worth the disk); its tab and old `results/wa-gitlab` records remain,
read-only. The multisite pass — the tasks needing more than one site — is now
shopping+reddit, 5 tasks, and gets worker 3 rather than queueing behind
another sweep. See [02, §4](02-running-a-sweep.md) and
[04](04-multisite-tasks.md).

Watch it at `localhost:9102`. Check a claim in
`results/<sweep>/episodes.jsonl`. Find out why something failed in
`results/<sweep>/traces/<task>.log`.

## What the numbers mean, and what they do not

The pass rate is computed over episodes that **ran**. Attempts that died
before reaching the model — credit limits, a wedged driver, a container mid
boot — are recorded, excluded, and returned to the queue. They are failures of
the environment, not of the agent, and counting them either way is a choice
that should be made out loud rather than by accident.

WebArena scores the whole system: model, scaffold and browser tooling
together. It cannot tell you which of the three earned the score. Treat a
result as a claim about the bundle, not about the toolkit — the toolkit-level
numbers are `op_success_rate`, `ops_per_turn` and tokens per task.
