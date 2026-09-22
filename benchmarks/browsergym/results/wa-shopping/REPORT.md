# WebArena — unbiased/pareto via abt

- sites running: shopping
- graded 158 | skipped (site not up) 0 | harness faults 5

## Task success — scored by WebArena, not by us

**92/158 (58.2%)**

## Toolkit metrics — ours, and not part of the score

| metric | value | reads as |
|---|---|---|
| ops per task | 16.4 | how much work the toolkit did |
| ops per turn | 1.57 | 1.00 means it never batched |
| **op success rate** | **95.0%** | **whether the agent learned the tool** |
| turns per task | 7.7 | round trips to the model |
| tokens per task | 212,163 | the cost |
| cached share | 58% | prefix caching working |
| model time | 120s | waiting on the model |
| browser time | -s | inside the browser |
| total tokens burned | 33,521,749 | |

## Per task

| task | pass | ops | fails | turns | tokens | wall |
|---|---|---|---|---|---|---|
| webarena.126 | yes | 28 | 1 | 4 | 85761 | 277.6s |
| webarena.148 | yes | 14 | 0 | 6 | 176364 | 73.9s |
| webarena.149 | yes | 22 | 1 | 8 | 218170 | 120.9s |
| webarena.150 | yes | 13 | 2 | 7 | 140958 | 108.5s |
| webarena.158 | yes | 28 | 0 | 6 | 128666 | 161.2s |
| webarena.159 | yes | 20 | 0 | 8 | 230717 | 177.7s |
| webarena.160 | yes | 19 | 1 | 8 | 203910 | 110.4s |
| webarena.161 | yes | 35 | 5 | 12 | 364558 | 292.0s |
| webarena.162 | yes | 21 | 0 | 8 | 204409 | 462.8s |
| webarena.164 | yes | 8 | 0 | 3 | 38062 | 87.8s |
| webarena.188 | yes | 11 | 0 | 3 | 52767 | 63.2s |
| webarena.189 | yes | 16 | 0 | 3 | 53836 | 142.8s |
| webarena.190 | yes | 9 | 1 | 5 | 94109 | 75.4s |
| webarena.191 | yes | 41 | 4 | 8 | 165309 | 227.9s |
| webarena.192 | yes | 8 | 1 | 4 | 78204 | 76.5s |
| webarena.22 | yes | 22 | 1 | 7 | 100526 | 130.9s |
| webarena.225 | yes | 34 | 1 | 8 | 218961 | 267.4s |
| webarena.226 | yes | 22 | 1 | 11 | 306102 | 289.0s |
| webarena.227 | yes | 4 | 0 | 4 | 68130 | 118.4s |
| webarena.228 | yes | 44 | 5 | 6 | 131475 | 426.3s |
| webarena.229 | yes | 13 | 1 | 4 | 81624 | 140.6s |
| webarena.23 | yes | 11 | 2 | 8 | 121063 | 92.8s |
| webarena.230 | yes | 13 | 0 | 6 | 146414 | 117.3s |
| webarena.231 | yes | 8 | 0 | 3 | 53130 | 58.1s |
| webarena.232 | yes | 13 | 0 | 3 | 53284 | 79.2s |
| webarena.233 | yes | 31 | 0 | 3 | 51270 | 182.9s |
| webarena.234 | yes | 16 | 1 | 6 | 138331 | 251.8s |
| webarena.235 | yes | 20 | 0 | 6 | 128896 | 123.5s |
| webarena.238 | yes | 19 | 0 | 6 | 169112 | 156.3s |
| webarena.239 | yes | 17 | 1 | 7 | 188917 | 156.2s |
| webarena.240 | yes | 18 | 0 | 5 | 108788 | 118.7s |
| webarena.242 | yes | 19 | 1 | 8 | 194708 | 143.3s |
| webarena.26 | yes | 24 | 0 | 8 | 178381 | 191.4s |
| webarena.260 | yes | 4 | 0 | 3 | 50866 | 46.2s |
| webarena.261 | yes | 4 | 0 | 3 | 51084 | 60.1s |
| webarena.264 | yes | 44 | 4 | 13 | 241051 | 380.1s |
| webarena.269 | yes | 19 | 2 | 6 | 158059 | 154.3s |
| webarena.270 | yes | 24 | 1 | 8 | 176433 | 244.3s |
| webarena.271 | yes | 37 | 1 | 13 | 344582 | 321.0s |
| webarena.272 | yes | 5 | 0 | 3 | 66182 | 104.7s |
| webarena.273 | yes | 16 | 2 | 11 | 280713 | 443.4s |
| webarena.274 | yes | 17 | 0 | 3 | 52229 | 130.2s |
| webarena.275 | yes | 6 | 1 | 3 | 58426 | 49.4s |
| webarena.276 | yes | 9 | 0 | 3 | 51945 | 50.4s |
| webarena.278 | yes | 8 | 0 | 3 | 50810 | 56.9s |
| webarena.279 | yes | 20 | 0 | 12 | 573233 | 224.6s |
| webarena.282 | yes | 24 | 0 | 14 | 536386 | 287.1s |
| webarena.301 | yes | 12 | 0 | 9 | 174574 | 127.2s |
| webarena.302 | yes | 12 | 1 | 9 | 177566 | 94.3s |
| webarena.313 | yes | 7 | 1 | 5 | 85830 | 20.3s |
| webarena.368 | yes | 13 | 1 | 9 | 289655 | 111.7s |
| webarena.376 | yes | 10 | 0 | 7 | 230870 | 92.6s |
| webarena.384 | yes | 8 | 0 | 7 | 161585 | 122.8s |
| webarena.385 | yes | 9 | 1 | 8 | 162931 | 96.1s |
| webarena.387 | yes | 15 | 2 | 13 | 346357 | 127.4s |
| webarena.388 | yes | 7 | 0 | 7 | 153829 | 126.7s |
| webarena.514 | yes | 4 | 0 | 4 | 75221 | 51.1s |
| webarena.515 | yes | 7 | 1 | 6 | 121887 | 99.1s |
| webarena.516 | yes | 2 | 0 | 3 | 40561 | 51.2s |
| webarena.517 | yes | 3 | 0 | 3 | 40072 | 58.4s |
| webarena.518 | yes | 5 | 0 | 4 | 54398 | 58.6s |
| webarena.117 | ok | 6 | 1 | 5 | 79109 | 182.0s |
| webarena.118 | ok | 11 | 1 | 4 | 83555 | 64.7s |
| webarena.124 | ok | 20 | 1 | 5 | 128266 | 116.7s |
| webarena.125 | ok | 62 | 1 | 17 | 777123 | 257.4s |
| webarena.141 | ok | 20 | 3 | 8 | 175116 | 107.9s |
| webarena.142 | ok | 19 | 2 | 8 | 182701 | 116.6s |
| webarena.143 | ok | 18 | 1 | 7 | 149562 | 126.6s |
| webarena.144 | yes | 14 | 1 | 6 | 144412 | 72.8s |
| webarena.145 | ok | 19 | 0 | 7 | 176296 | 101.8s |
| webarena.146 | ok | 33 | 2 | 10 | 303484 | 158.8s |
| webarena.147 | ok | 66 | 2 | 19 | 756045 | 327.3s |
| webarena.163 | ok | 12 | 2 | 8 | 119910 | 84.2s |
| webarena.165 | ok | 5 | 0 | 3 | 51435 | 50.3s |
| webarena.166 | ok | 5 | 0 | 4 | 56506 | 53.5s |
| webarena.167 | yes | 8 | 0 | 5 | 70889 | 65.1s |
| webarena.21 | ok | 18 | 3 | 9 | 155075 | 86.2s |
| webarena.24 | ok | 8 | 0 | 4 | 51870 | 47.3s |
| webarena.241 | ok | 15 | 1 | 7 | 197241 | 88.1s |
| webarena.25 | ok | 8 | 1 | 6 | 124185 | 71.9s |
| webarena.262 | ok | 13 | 0 | 6 | 136036 | 96.7s |
| webarena.263 | yes | 10 | 0 | 6 | 113402 | 65.8s |
| webarena.277 | ok | 8 | 0 | 3 | 53117 | 78.7s |
| webarena.280 | ok | 22 | 0 | 9 | 401276 | 268.4s |
| webarena.281 | ok | 39 | 5 | 15 | 452108 | 159.4s |
| webarena.283 | ok | 68 | 3 | 20 | 1348792 | 352.5s |
| webarena.284 | yes | 58 | 5 | 23 | 963089 | 296.5s |
| webarena.285 | yes | 42 | 3 | 9 | 325612 | 262.5s |
| webarena.286 | ok | 35 | 4 | 8 | 201848 | 193.3s |
| webarena.298 | yes | 11 | 0 | 5 | 95306 | 76.8s |
| webarena.299 | yes | 12 | 0 | 5 | 75204 | 63.0s |
| webarena.300 | yes | 11 | 0 | 5 | 98039 | 66.8s |
| webarena.319 | ok | 31 | 1 | 9 | 234067 | 278.7s |
| webarena.320 | yes | 27 | 0 | 5 | 109114 | 113.7s |
| webarena.321 | yes | 32 | 2 | 8 | 208766 | 176.2s |
| webarena.322 | yes | 7 | 0 | 4 | 80063 | 57.1s |
| webarena.323 | ok | 17 | 1 | 7 | 177667 | 75.3s |
| webarena.324 | ok | 20 | 2 | 5 | 96647 | 174.8s |
| webarena.325 | ok | 6 | 1 | 4 | 75024 | 80.2s |
| webarena.326 | ok | 49 | 5 | 6 | 114872 | 412.0s |
| webarena.327 | ok | 7 | 0 | 6 | 156856 | 87.6s |
| webarena.328 | ok | 10 | 2 | 8 | 225752 | 128.3s |
| webarena.329 | yes | 10 | 0 | 5 | 120769 | 87.8s |
| webarena.330 | ok | 5 | 0 | 4 | 78637 | 63.9s |
| webarena.331 | ok | 6 | 0 | 6 | 100671 | 100.4s |
| webarena.332 | ok | 7 | 0 | 6 | 120158 | 164.1s |
| webarena.333 | ok | 14 | 2 | 10 | 292794 | 129.0s |
| webarena.334 | ok | 14 | 1 | 9 | 160521 | 164.1s |
| webarena.335 | ok | 26 | 1 | 11 | 233472 | 225.2s |
| webarena.336 | ok | 22 | 1 | 15 | 497109 | 164.5s |
| webarena.337 | ok | 25 | 1 | 12 | 311712 | 325.3s |
| webarena.338 | ok | 20 | 0 | 20 | 458605 | 233.9s |
| webarena.351 | ok | 8 | 1 | 8 | 213846 | 110.1s |
| webarena.352 | yes | 11 | 0 | 11 | 274344 | 128.7s |
| webarena.353 | ok | 13 | 0 | 9 | 312230 | 104.2s |
| webarena.354 | ok | 7 | 0 | 7 | 182733 | 83.1s |
| webarena.355 | ok | 7 | 0 | 6 | 178857 | 87.8s |
| webarena.358 | yes | 4 | 0 | 5 | 71518 | 53.3s |
| webarena.359 | ok | 8 | 0 | 7 | 172802 | 96.1s |
| webarena.360 | yes | 5 | 0 | 5 | 95443 | 72.5s |
| webarena.361 | ok | 4 | 0 | 4 | 71272 | 51.4s |
| webarena.362 | yes | 5 | 0 | 5 | 95656 | 71.3s |
| webarena.386 | ok | 12 | 1 | 9 | 302472 | 203.8s |
| webarena.431 | yes | 8 | 0 | 7 | 104484 | 76.9s |
| webarena.432 | yes | 7 | 0 | 5 | 67855 | 57.3s |
| webarena.433 | yes | 5 | 0 | 5 | 64504 | 63.5s |
| webarena.434 | yes | 15 | 1 | 11 | 162856 | 98.9s |
| webarena.435 | yes | 6 | 0 | 6 | 83846 | 104.6s |
| webarena.436 | ok | 11 | 0 | 7 | 144695 | 166.3s |
| webarena.437 | ok | 14 | 0 | 11 | 295196 | 172.2s |
| webarena.438 | ok | 36 | 1 | 17 | 683981 | 301.2s |
| webarena.439 | yes | 31 | 1 | 21 | 735315 | 205.2s |
| webarena.440 | ok | 15 | 1 | 11 | 317895 | 197.6s |
| webarena.465 | yes | 5 | 0 | 4 | 88947 | 60.9s |
| webarena.466 | yes | 7 | 1 | 6 | 142514 | 70.5s |
| webarena.467 | yes | 6 | 0 | 5 | 89894 | 65.2s |
| webarena.468 | yes | 5 | 0 | 4 | 80337 | 75.4s |
| webarena.469 | ok | 5 | 0 | 4 | 80833 | 132.9s |
| webarena.47 | ok | 5 | 0 | 5 | 136724 | 517.8s |
| webarena.48 | ok | 11 | 1 | 6 | 126569 | 120.7s |
| webarena.49 | ok | 6 | 0 | 6 | 163463 | 114.7s |
| webarena.50 | ok | 3 | 0 | 4 | 77560 | 83.3s |
| webarena.506 | yes | 19 | 2 | 13 | 383610 | 151.5s |
| webarena.507 | yes | 23 | 2 | 20 | 527210 | 160.2s |
| webarena.508 | yes | 27 | 1 | 20 | 743895 | 225.6s |
| webarena.509 | ok | 54 | 4 | 34 | 2149066 | 681.8s |
| webarena.51 | ok | 10 | 1 | 6 | 118455 | 103.3s |
| webarena.510 | ok | 34 | 1 | 24 | 1216193 | 260.9s |
| webarena.511 | yes | 5 | 0 | 4 | 85061 | 70.5s |
| webarena.512 | ok | 5 | 0 | 4 | 87530 | 419.9s |
| webarena.513 | ok | 6 | 1 | 5 | 77439 | 76.0s |
| webarena.519 | yes | 4 | 0 | 3 | 47462 | 61.8s |
| webarena.520 | ok | 2 | 0 | 3 | 43306 | 135.0s |
| webarena.521 | ok | 4 | 0 | 3 | 45928 | 133.6s |
| webarena.528 | ok | 10 | 0 | 9 | 155873 | 133.5s |
| webarena.529 | ok | 35 | 0 | 16 | 539393 | 134.8s |
| webarena.530 | ok | 10 | 0 | 7 | 150668 | 133.8s |
| webarena.531 | ok | 11 | 0 | 7 | 149887 | 133.8s |
| webarena.532 | harness_error | - | - | - | - | 31.8s |
| webarena.571 | harness_error | - | - | - | - | 32.5s |
| webarena.572 | harness_error | - | - | - | - | 31.4s |
| webarena.573 | harness_error | - | - | - | - | 34.5s |
| webarena.574 | harness_error | - | - | - | - | 31.8s |
