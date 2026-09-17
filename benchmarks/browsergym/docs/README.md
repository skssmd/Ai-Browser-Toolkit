# Understanding the benchmark

Four documents. Read them in order the first time; after that they are
reference.

| | |
|---|---|
| [00 — setting it up from scratch](00-setting-up-from-scratch.md) | a blank VPS to two workers, with the exact commands that were run |
| [01 — servers and tunnels](01-servers-and-tunnels.md) | what listens on the host, how to start each one, how to see them from your machine |
| [02 — running a sweep](02-running-a-sweep.md) | sites, plan, run, resume — and the traps that cost hours |
| [03 — what gets logged](03-what-gets-logged.md) | the four record layers, what each can answer, and where each lies to you |

Related, outside this folder:

- [`../WEBARENA-SETUP.md`](../WEBARENA-SETUP.md) — the earlier shopping-era
  install, with the measured image sizes and how each harness bug was proven
- [`../WEBARENA.md`](../WEBARENA.md) — the original harness notes
- [`../dashboard.py`](../dashboard.py) — the analytics dashboard itself, the
  same file that runs live on `:9102`
- [`../../../guidelines/toolkit-workflow.md`](../../../guidelines/toolkit-workflow.md)
  — how to drive the toolkit itself

## The short version

Two workers, one per site, on a VPS. Right now they are **gitlab**
(`localhost:8023`) and **reddit** (`localhost:9999`), model
`stealth/union-alpha`. Each has its own toolkit server, browser profile, CDP
port, trace port and results directory — sharing any of them breaks in a way
that does not announce itself.

| | gitlab | reddit |
|---|---|---|
| site port | `8023` (+ `8024` ctrl) | `9999` (+ `9998` ctrl) |
| toolkit server | `8766` | `8767` |
| profile | `bench/profile` | `bench/profile-reddit` |
| CDP | `9222` | `9223` |
| trace | `9100` | `9101` |
| results | `results/wa-gitlab/` | `results/wa-reddit/` |

A plan is written once and fixes the model, the ports, the turn ceiling and
the task list. The sweep runs each task in its own process, appends a row per
episode, and can be stopped and resumed at any point.

A third, 18-task **multisite** pass (the tasks needing both gitlab and reddit)
is queued behind the reddit worker and starts when its sweep ends — see
[02, §4](02-running-a-sweep.md). It has its own `wa-multisite` results
directory and its own **Multisite** tab on the dashboard.

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
