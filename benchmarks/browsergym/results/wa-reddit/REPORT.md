# WebArena — unbiased/pareto via abt

- sites running: reddit
- graded 106 | skipped (site not up) 0 | harness faults 0

## Task success — scored by WebArena, not by us

**92/106 (86.8%)**

## Toolkit metrics — ours, and not part of the score

| metric | value | reads as |
|---|---|---|
| ops per task | 23.1 | how much work the toolkit did |
| ops per turn | 1.93 | 1.00 means it never batched |
| **op success rate** | **94.1%** | **whether the agent learned the tool** |
| turns per task | 7.9 | round trips to the model |
| tokens per task | 189,247 | the cost |
| cached share | 60% | prefix caching working |
| model time | 132s | waiting on the model |
| browser time | -s | inside the browser |
| total tokens burned | 20,060,210 | |

## Per task

| task | pass | ops | fails | turns | tokens | wall |
|---|---|---|---|---|---|---|
| webarena.27 | yes | 38 | 1 | 9 | 188018 | 413.1s |
| webarena.28 | ok | 23 | 1 | 12 | 386256 | 206.2s |
| webarena.29 | yes | 27 | 0 | 8 | 200620 | 294.5s |
| webarena.30 | yes | 19 | 1 | 8 | 155402 | 238.5s |
| webarena.31 | yes | 40 | 0 | 11 | 241655 | 384.9s |
| webarena.399 | yes | 6 | 0 | 4 | 57035 | 46.2s |
| webarena.400 | yes | 21 | 1 | 6 | 84190 | 168.4s |
| webarena.401 | yes | 9 | 0 | 6 | 80635 | 205.8s |
| webarena.402 | yes | 21 | 0 | 6 | 77807 | 228.4s |
| webarena.403 | yes | 16 | 1 | 9 | 146967 | 415.0s |
| webarena.404 | yes | 45 | 2 | 9 | 212775 | 321.7s |
| webarena.405 | yes | 9 | 0 | 10 | 170991 | 96.4s |
| webarena.406 | yes | 21 | 3 | 9 | 207964 | 531.4s |
| webarena.407 | ok | 34 | 0 | 8 | 158615 | 506.1s |
| webarena.408 | ok | 16 | 2 | 8 | 180267 | 253.6s |
| webarena.409 | yes | 15 | 0 | 4 | 97773 | 149.2s |
| webarena.410 | yes | 10 | 0 | 4 | 105284 | 85.1s |
| webarena.580 | yes | 21 | 0 | 4 | 52264 | 81.3s |
| webarena.581 | yes | 22 | 0 | 5 | 70634 | 172.3s |
| webarena.582 | yes | 48 | 1 | 10 | 160541 | 417.2s |
| webarena.583 | yes | 22 | 1 | 10 | 179192 | 113.6s |
| webarena.584 | ok | 28 | 1 | 7 | 107859 | 161.2s |
| webarena.595 | yes | 12 | 0 | 6 | 139657 | 84.4s |
| webarena.596 | yes | 22 | 3 | 10 | 175019 | 148.1s |
| webarena.597 | yes | 12 | 0 | 6 | 142662 | 86.7s |
| webarena.598 | yes | 24 | 4 | 6 | 171237 | 112.5s |
| webarena.599 | yes | 23 | 2 | 7 | 182907 | 149.1s |
| webarena.600 | yes | 39 | 4 | 8 | 174924 | 184.7s |
| webarena.601 | yes | 29 | 0 | 6 | 135437 | 131.0s |
| webarena.602 | yes | 27 | 2 | 6 | 127624 | 256.6s |
| webarena.603 | yes | 10 | 0 | 6 | 155887 | 135.4s |
| webarena.604 | yes | 9 | 2 | 8 | 156849 | 121.7s |
| webarena.605 | yes | 7 | 1 | 6 | 96326 | 113.0s |
| webarena.606 | yes | 12 | 0 | 7 | 182038 | 184.3s |
| webarena.607 | yes | 7 | 0 | 4 | 64431 | 129.4s |
| webarena.608 | yes | 20 | 1 | 10 | 186750 | 130.7s |
| webarena.609 | yes | 11 | 0 | 4 | 75330 | 68.1s |
| webarena.610 | yes | 8 | 1 | 6 | 116002 | 110.2s |
| webarena.611 | yes | 15 | 1 | 10 | 358531 | 196.5s |
| webarena.612 | yes | 8 | 0 | 6 | 215354 | 126.6s |
| webarena.613 | yes | 15 | 2 | 11 | 238397 | 211.4s |
| webarena.614 | yes | 29 | 6 | 9 | 377632 | 159.1s |
| webarena.615 | ok | 36 | 2 | 11 | 408932 | 282.4s |
| webarena.616 | yes | 30 | 1 | 14 | 573956 | 205.7s |
| webarena.617 | ok | 22 | 2 | 11 | 437305 | 163.1s |
| webarena.618 | yes | 30 | 1 | 12 | 236773 | 154.1s |
| webarena.619 | yes | 30 | 2 | 11 | 254130 | 195.6s |
| webarena.620 | yes | 39 | 3 | 12 | 439169 | 354.6s |
| webarena.621 | yes | 19 | 0 | 6 | 146641 | 72.8s |
| webarena.622 | yes | 22 | 2 | 9 | 171211 | 101.2s |
| webarena.623 | yes | 27 | 2 | 10 | 224592 | 97.8s |
| webarena.624 | yes | 12 | 0 | 5 | 92866 | 66.6s |
| webarena.625 | ok | 11 | 1 | 6 | 115968 | 77.8s |
| webarena.626 | yes | 12 | 0 | 6 | 153509 | 60.1s |
| webarena.627 | yes | 14 | 0 | 5 | 109843 | 62.8s |
| webarena.628 | yes | 12 | 1 | 6 | 112463 | 62.4s |
| webarena.629 | yes | 17 | 1 | 6 | 126503 | 82.9s |
| webarena.630 | yes | 26 | 2 | 10 | 197943 | 160.9s |
| webarena.631 | yes | 22 | 2 | 8 | 157944 | 76.3s |
| webarena.632 | yes | 15 | 0 | 5 | 111857 | 69.3s |
| webarena.633 | yes | 12 | 0 | 4 | 76154 | 58.0s |
| webarena.634 | yes | 13 | 0 | 4 | 75707 | 57.6s |
| webarena.635 | yes | 42 | 3 | 7 | 135043 | 230.3s |
| webarena.636 | yes | 20 | 0 | 6 | 127570 | 110.8s |
| webarena.637 | yes | 23 | 1 | 6 | 141396 | 83.3s |
| webarena.638 | yes | 23 | 0 | 7 | 181997 | 71.1s |
| webarena.639 | yes | 24 | 4 | 10 | 215468 | 122.7s |
| webarena.640 | yes | 23 | 2 | 10 | 209255 | 152.4s |
| webarena.641 | yes | 15 | 0 | 7 | 141176 | 114.8s |
| webarena.642 | yes | 33 | 2 | 13 | 290748 | 146.8s |
| webarena.643 | yes | 22 | 1 | 8 | 167381 | 146.1s |
| webarena.644 | ok | 35 | 1 | 8 | 186936 | 250.8s |
| webarena.645 | yes | 15 | 1 | 6 | 126483 | 83.0s |
| webarena.646 | ok | 48 | 4 | 14 | 427105 | 387.0s |
| webarena.647 | yes | 42 | 6 | 8 | 178240 | 292.2s |
| webarena.648 | yes | 41 | 4 | 12 | 345709 | 219.4s |
| webarena.649 | yes | 28 | 3 | 10 | 253440 | 144.7s |
| webarena.650 | yes | 17 | 2 | 9 | 257804 | 117.9s |
| webarena.651 | yes | 19 | 3 | 5 | 154876 | 123.3s |
| webarena.652 | yes | 5 | 0 | 3 | 39889 | 40.6s |
| webarena.66 | ok | 32 | 1 | 6 | 129833 | 155.2s |
| webarena.67 | ok | 30 | 1 | 9 | 220554 | 184.4s |
| webarena.68 | ok | 50 | 3 | 7 | 182012 | 143.1s |
| webarena.69 | yes | 15 | 2 | 5 | 105473 | 133.0s |
| webarena.714 | yes | 31 | 3 | 12 | 320738 | 208.2s |
| webarena.715 | yes | 19 | 1 | 10 | 382775 | 200.0s |
| webarena.716 | yes | 8 | 0 | 5 | 105003 | 91.7s |
| webarena.717 | yes | 27 | 0 | 11 | 331883 | 137.7s |
| webarena.718 | yes | 42 | 1 | 5 | 107399 | 140.6s |
| webarena.719 | yes | 28 | 0 | 10 | 297251 | 127.4s |
| webarena.720 | yes | 36 | 1 | 12 | 347480 | 158.6s |
| webarena.721 | yes | 37 | 2 | 9 | 312356 | 179.7s |
| webarena.722 | yes | 13 | 0 | 7 | 157447 | 63.6s |
| webarena.723 | ok | 51 | 4 | 5 | 118155 | 329.0s |
| webarena.724 | yes | 29 | 1 | 10 | 226529 | 174.2s |
| webarena.725 | yes | 19 | 3 | 9 | 230038 | 89.8s |
| webarena.726 | ok | 26 | 2 | 5 | 111803 | 112.6s |
| webarena.727 | yes | 33 | 4 | 12 | 287441 | 217.9s |
| webarena.728 | yes | 41 | 2 | 8 | 300561 | 230.5s |
| webarena.729 | yes | 22 | 3 | 9 | 194265 | 168.4s |
| webarena.730 | yes | 39 | 3 | 10 | 176313 | 196.7s |
| webarena.731 | yes | 8 | 1 | 4 | 74693 | 62.4s |
| webarena.732 | yes | 16 | 1 | 11 | 265896 | 102.3s |
| webarena.733 | yes | 23 | 1 | 8 | 166506 | 91.9s |
| webarena.734 | yes | 15 | 2 | 9 | 159920 | 84.4s |
| webarena.735 | yes | 17 | 0 | 8 | 148166 | 63.4s |
