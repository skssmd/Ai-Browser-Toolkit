# WebArena — unbiased/pareto via abt

- sites running: gitlab, reddit
- graded 18 | skipped (site not up) 0 | harness faults 0

## Task success — scored by WebArena, not by us

**8/18 (44.4%)**

## Toolkit metrics — ours, and not part of the score

| metric | value | reads as |
|---|---|---|
| ops per task | 53.5 | how much work the toolkit did |
| ops per turn | 2.11 | 1.00 means it never batched |
| **op success rate** | **94.0%** | **whether the agent learned the tool** |
| turns per task | 16.5 | round trips to the model |
| tokens per task | 589,275 | the cost |
| cached share | 67% | prefix caching working |
| model time | 260s | waiting on the model |
| browser time | -s | inside the browser |
| total tokens burned | 10,606,942 | |

## Per task

| task | pass | ops | fails | turns | tokens | wall |
|---|---|---|---|---|---|---|
| webarena.552 | yes | 79 | 3 | 20 | 769649 | 262.9s |
| webarena.553 | ok | 58 | 5 | 18 | 867345 | 634.0s |
| webarena.554 | ok | 76 | 5 | 19 | 658895 | 312.9s |
| webarena.555 | yes | 95 | 7 | 25 | 832375 | 348.3s |
| webarena.562 | ok | 84 | 5 | 31 | 1369078 | 342.8s |
| webarena.563 | ok | 26 | 1 | 9 | 192271 | 312.3s |
| webarena.564 | ok | 55 | 5 | 30 | 1241881 | 317.3s |
| webarena.565 | ok | 45 | 3 | 24 | 960046 | 391.4s |
| webarena.566 | ok | 64 | 5 | 31 | 1541227 | 386.1s |
| webarena.681 | ok | 66 | 2 | 7 | 137650 | 215.9s |
| webarena.682 | ok | 39 | 1 | 12 | 299553 | 237.3s |
| webarena.683 | ok | 26 | 3 | 10 | 224890 | 477.0s |
| webarena.684 | yes | 31 | 1 | 10 | 228908 | 147.4s |
| webarena.685 | yes | 39 | 1 | 10 | 303636 | 162.0s |
| webarena.686 | yes | 21 | 1 | 5 | 129630 | 162.5s |
| webarena.687 | yes | 77 | 5 | 16 | 413919 | 244.2s |
| webarena.688 | yes | 65 | 4 | 12 | 242928 | 257.5s |
| webarena.791 | yes | 17 | 1 | 8 | 193061 | 153.4s |
