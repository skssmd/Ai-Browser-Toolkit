# WebArena — unbiased/pareto via abt

- sites running: shopping, reddit
- graded 5 | skipped (site not up) 0 | harness faults 0

## Task success — scored by WebArena, not by us

**1/5 (20.0%)**

## Toolkit metrics — ours, and not part of the score

| metric | value | reads as |
|---|---|---|
| ops per task | 19.8 | how much work the toolkit did |
| ops per turn | 1.58 | 1.00 means it never batched |
| **op success rate** | **92.9%** | **whether the agent learned the tool** |
| turns per task | 13.8 | round trips to the model |
| tokens per task | 406,288 | the cost |
| cached share | 66% | prefix caching working |
| model time | 207s | waiting on the model |
| browser time | -s | inside the browser |
| total tokens burned | 2,031,441 | |

## Per task

| task | pass | ops | fails | turns | tokens | wall |
|---|---|---|---|---|---|---|
| webarena.671 | ok | 18 | 2 | 13 | 313157 | 229.3s |
| webarena.672 | yes | 23 | 1 | 15 | 510740 | 264.4s |
| webarena.673 | ok | 19 | 2 | 15 | 419974 | 504.8s |
| webarena.674 | ok | 18 | 0 | 12 | 379487 | 175.9s |
| webarena.675 | ok | 21 | 2 | 14 | 408083 | 162.5s |
