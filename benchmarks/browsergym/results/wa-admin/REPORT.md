# WebArena — unbiased/pareto via abt

- sites running: shopping_admin
- graded 93 | skipped (site not up) 0 | harness faults 5

## Task success — scored by WebArena, not by us

**63/93 (67.7%)**

## Toolkit metrics — ours, and not part of the score

| metric | value | reads as |
|---|---|---|
| ops per task | 19.6 | how much work the toolkit did |
| ops per turn | 1.70 | 1.00 means it never batched |
| **op success rate** | **94.1%** | **whether the agent learned the tool** |
| turns per task | 7.8 | round trips to the model |
| tokens per task | 179,051 | the cost |
| cached share | 54% | prefix caching working |
| model time | 133s | waiting on the model |
| browser time | -s | inside the browser |
| total tokens burned | 16,651,753 | |

## Per task

| task | pass | ops | fails | turns | tokens | wall |
|---|---|---|---|---|---|---|
| webarena.0 | yes | 26 | 1 | 10 | 188819 | 181.8s |
| webarena.11 | yes | 17 | 3 | 8 | 147334 | 185.4s |
| webarena.112 | yes | 36 | 1 | 9 | 199164 | 173.3s |
| webarena.114 | yes | 32 | 2 | 6 | 135266 | 194.6s |
| webarena.116 | yes | 44 | 2 | 12 | 243966 | 203.4s |
| webarena.12 | yes | 17 | 1 | 5 | 86028 | 101.5s |
| webarena.128 | yes | 14 | 0 | 5 | 173019 | 93.5s |
| webarena.13 | yes | 25 | 2 | 8 | 126824 | 149.0s |
| webarena.130 | yes | 15 | 3 | 7 | 113913 | 99.1s |
| webarena.131 | yes | 35 | 1 | 7 | 265972 | 186.8s |
| webarena.14 | yes | 23 | 1 | 6 | 129157 | 124.0s |
| webarena.15 | yes | 14 | 0 | 6 | 92839 | 103.1s |
| webarena.157 | yes | 5 | 0 | 4 | 75265 | 88.7s |
| webarena.183 | yes | 17 | 1 | 7 | 172513 | 117.9s |
| webarena.187 | yes | 45 | 0 | 12 | 375154 | 219.0s |
| webarena.193 | yes | 4 | 0 | 3 | 61717 | 73.4s |
| webarena.194 | yes | 13 | 1 | 5 | 130252 | 239.8s |
| webarena.195 | yes | 33 | 0 | 8 | 211428 | 181.8s |
| webarena.196 | yes | 16 | 0 | 6 | 122647 | 149.7s |
| webarena.197 | yes | 15 | 1 | 6 | 123210 | 180.7s |
| webarena.198 | yes | 10 | 0 | 3 | 68663 | 105.5s |
| webarena.199 | yes | 16 | 0 | 5 | 84548 | 110.9s |
| webarena.200 | yes | 19 | 1 | 8 | 175886 | 127.5s |
| webarena.201 | yes | 36 | 1 | 9 | 370434 | 285.3s |
| webarena.208 | yes | 9 | 0 | 4 | 77032 | 129.2s |
| webarena.209 | yes | 3 | 0 | 4 | 65376 | 57.7s |
| webarena.210 | yes | 7 | 0 | 2 | 42320 | 62.9s |
| webarena.211 | yes | 22 | 3 | 7 | 110147 | 161.1s |
| webarena.212 | yes | 6 | 1 | 5 | 79157 | 134.4s |
| webarena.243 | yes | 15 | 0 | 11 | 245190 | 131.8s |
| webarena.244 | yes | 8 | 0 | 5 | 104301 | 146.1s |
| webarena.245 | yes | 18 | 0 | 13 | 326152 | 190.0s |
| webarena.246 | yes | 17 | 1 | 8 | 214876 | 224.3s |
| webarena.247 | yes | 13 | 2 | 12 | 249964 | 227.8s |
| webarena.288 | yes | 8 | 1 | 6 | 318650 | 668.9s |
| webarena.290 | yes | 12 | 1 | 10 | 253332 | 143.2s |
| webarena.291 | yes | 12 | 2 | 9 | 265154 | 256.7s |
| webarena.292 | yes | 8 | 1 | 7 | 195691 | 180.6s |
| webarena.3 | yes | 9 | 1 | 5 | 97921 | 152.9s |
| webarena.344 | yes | 4 | 1 | 5 | 73703 | 100.9s |
| webarena.345 | yes | 13 | 0 | 6 | 136079 | 154.8s |
| webarena.346 | yes | 16 | 1 | 9 | 167004 | 185.6s |
| webarena.347 | yes | 3 | 0 | 4 | 58341 | 123.9s |
| webarena.348 | yes | 12 | 1 | 8 | 142491 | 197.7s |
| webarena.41 | yes | 2 | 0 | 2 | 30623 | 53.6s |
| webarena.42 | yes | 2 | 0 | 2 | 25925 | 51.6s |
| webarena.43 | yes | 1 | 0 | 2 | 25637 | 46.0s |
| webarena.453 | yes | 12 | 0 | 8 | 211680 | 271.0s |
| webarena.454 | yes | 15 | 1 | 13 | 343852 | 231.9s |
| webarena.455 | yes | 17 | 1 | 11 | 269741 | 157.6s |
| webarena.456 | yes | 18 | 1 | 12 | 288693 | 541.0s |
| webarena.457 | yes | 16 | 0 | 8 | 194211 | 263.1s |
| webarena.458 | yes | 6 | 1 | 5 | 74128 | 226.0s |
| webarena.459 | yes | 3 | 0 | 3 | 42024 | 70.5s |
| webarena.460 | yes | 4 | 0 | 4 | 57151 | 115.9s |
| webarena.461 | yes | 5 | 1 | 4 | 48868 | 64.4s |
| webarena.462 | yes | 3 | 0 | 3 | 41454 | 94.7s |
| webarena.1 | ok | 10 | 3 | 8 | 140172 | 93.2s |
| webarena.107 | ok | 13 | 1 | 9 | 141590 | 102.9s |
| webarena.108 | ok | 29 | 2 | 12 | 199590 | 122.3s |
| webarena.109 | ok | 40 | 2 | 11 | 215423 | 139.8s |
| webarena.110 | ok | 10 | 0 | 4 | 67941 | 91.0s |
| webarena.111 | ok | 40 | 4 | 9 | 198735 | 164.3s |
| webarena.113 | ok | 28 | 2 | 9 | 178875 | 147.6s |
| webarena.115 | ok | 9 | 1 | 3 | 52033 | 72.4s |
| webarena.119 | ok | 35 | 2 | 10 | 173143 | 169.7s |
| webarena.120 | ok | 33 | 0 | 9 | 198670 | 129.4s |
| webarena.121 | ok | 14 | 2 | 8 | 131206 | 103.3s |
| webarena.122 | ok | 16 | 2 | 7 | 133413 | 115.9s |
| webarena.123 | ok | 28 | 0 | 8 | 142814 | 142.8s |
| webarena.127 | ok | 23 | 3 | 7 | 112983 | 151.7s |
| webarena.129 | yes | 17 | 1 | 6 | 244397 | 106.1s |
| webarena.184 | ok | 55 | 4 | 15 | 443306 | 198.5s |
| webarena.185 | ok | 35 | 2 | 14 | 256686 | 184.4s |
| webarena.186 | ok | 21 | 1 | 8 | 127090 | 94.2s |
| webarena.2 | ok | 38 | 0 | 7 | 153762 | 362.6s |
| webarena.202 | ok | 32 | 5 | 11 | 239237 | 122.4s |
| webarena.203 | ok | 42 | 1 | 5 | 127598 | 238.9s |
| webarena.204 | ok | 27 | 2 | 10 | 207348 | 132.2s |
| webarena.213 | ok | 28 | 3 | 10 | 180815 | 132.1s |
| webarena.214 | ok | 29 | 3 | 10 | 164825 | 164.9s |
| webarena.215 | ok | 25 | 1 | 11 | 205081 | 99.1s |
| webarena.216 | ok | 21 | 2 | 8 | 164881 | 187.3s |
| webarena.217 | ok | 17 | 3 | 10 | 184401 | 104.7s |
| webarena.289 | ok | 24 | 1 | 10 | 293477 | 121.1s |
| webarena.374 | ok | 27 | 1 | 13 | 278902 | 110.9s |
| webarena.375 | ok | 39 | 2 | 13 | 269458 | 303.1s |
| webarena.4 | yes | 29 | 1 | 9 | 172865 | 107.8s |
| webarena.423 | yes | 45 | 3 | 16 | 417280 | 246.0s |
| webarena.463 | yes | 4 | 0 | 3 | 41413 | 59.7s |
| webarena.464 | ok | 77 | 4 | 28 | 1136422 | 453.3s |
| webarena.470 | yes | 7 | 0 | 6 | 187642 | 84.5s |
| webarena.471 | yes | 11 | 1 | 7 | 317393 | 98.7s |
| webarena.472 | harness_error | - | - | - | - | 26.3s |
| webarena.473 | harness_error | - | - | - | - | 24.7s |
| webarena.474 | harness_error | - | - | - | - | 24.2s |
| webarena.486 | harness_error | - | - | - | - | 23.3s |
| webarena.487 | harness_error | - | - | - | - | 28.7s |
