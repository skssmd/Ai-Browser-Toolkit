# WebArena — unbiased/pareto via abt

- sites running: gitlab
- graded 180 | skipped (site not up) 0 | harness faults 0

## Task success — scored by WebArena, not by us

**127/180 (70.6%)**

## Toolkit metrics — ours, and not part of the score

| metric | value | reads as |
|---|---|---|
| ops per task | 20.0 | how much work the toolkit did |
| ops per turn | 1.55 | 1.00 means it never batched |
| **op success rate** | **92.4%** | **whether the agent learned the tool** |
| turns per task | 9.4 | round trips to the model |
| tokens per task | 222,573 | the cost |
| cached share | 60% | prefix caching working |
| model time | 129s | waiting on the model |
| browser time | -s | inside the browser |
| total tokens burned | 40,063,133 | |

## Per task

| task | pass | ops | fails | turns | tokens | wall |
|---|---|---|---|---|---|---|
| webarena.102 | ok | 21 | 1 | 8 | 198738 | 341.3s |
| webarena.103 | yes | 54 | 1 | 11 | 240149 | 348.1s |
| webarena.104 | ok | 11 | 0 | 6 | 97514 | 219.8s |
| webarena.105 | yes | 30 | 1 | 10 | 241050 | 281.1s |
| webarena.106 | ok | 11 | 0 | 5 | 86253 | 201.0s |
| webarena.132 | yes | 9 | 0 | 5 | 118359 | 102.3s |
| webarena.133 | yes | 24 | 1 | 6 | 110736 | 127.0s |
| webarena.134 | yes | 35 | 3 | 10 | 212927 | 408.9s |
| webarena.135 | yes | 3 | 0 | 3 | 62568 | 107.5s |
| webarena.136 | ok | 21 | 2 | 6 | 113643 | 437.4s |
| webarena.156 | yes | 16 | 1 | 4 | 61709 | 99.0s |
| webarena.168 | yes | 5 | 1 | 6 | 108768 | 77.7s |
| webarena.169 | yes | 11 | 0 | 7 | 170749 | 127.4s |
| webarena.170 | ok | 41 | 5 | 9 | 178763 | 656.4s |
| webarena.171 | ok | 15 | 0 | 8 | 160714 | 82.3s |
| webarena.172 | ok | 13 | 0 | 8 | 209259 | 300.4s |
| webarena.173 | ok | 27 | 4 | 5 | 93187 | 392.9s |
| webarena.174 | ok | 6 | 0 | 4 | 71307 | 75.4s |
| webarena.175 | ok | 14 | 0 | 5 | 130574 | 118.6s |
| webarena.176 | ok | 6 | 0 | 4 | 73714 | 47.8s |
| webarena.177 | ok | 24 | 2 | 8 | 194005 | 112.1s |
| webarena.178 | ok | 19 | 2 | 6 | 142703 | 149.8s |
| webarena.179 | ok | 16 | 1 | 7 | 185280 | 163.8s |
| webarena.180 | ok | 10 | 0 | 9 | 213181 | 113.8s |
| webarena.181 | ok | 10 | 2 | 7 | 141082 | 116.8s |
| webarena.182 | yes | 29 | 3 | 8 | 200063 | 118.9s |
| webarena.205 | yes | 7 | 0 | 3 | 58386 | 62.5s |
| webarena.206 | yes | 4 | 0 | 3 | 71611 | 49.9s |
| webarena.207 | yes | 34 | 2 | 7 | 186487 | 216.5s |
| webarena.258 | yes | 20 | 2 | 9 | 183685 | 122.9s |
| webarena.259 | yes | 10 | 0 | 7 | 124452 | 62.7s |
| webarena.293 | ok | 17 | 5 | 8 | 171449 | 85.5s |
| webarena.294 | ok | 22 | 3 | 9 | 186885 | 133.5s |
| webarena.295 | ok | 17 | 2 | 8 | 167838 | 94.9s |
| webarena.296 | ok | 14 | 1 | 5 | 126105 | 70.3s |
| webarena.297 | ok | 8 | 0 | 5 | 78449 | 58.8s |
| webarena.303 | yes | 27 | 1 | 10 | 241046 | 102.2s |
| webarena.304 | yes | 13 | 1 | 8 | 212877 | 105.7s |
| webarena.305 | yes | 25 | 4 | 7 | 156417 | 168.4s |
| webarena.306 | yes | 36 | 3 | 11 | 388705 | 165.2s |
| webarena.307 | ok | 29 | 6 | 13 | 522111 | 189.7s |
| webarena.308 | yes | 10 | 1 | 6 | 121312 | 96.0s |
| webarena.309 | yes | 25 | 3 | 8 | 147181 | 217.1s |
| webarena.310 | yes | 15 | 3 | 6 | 104458 | 116.5s |
| webarena.311 | yes | 18 | 2 | 9 | 174987 | 105.5s |
| webarena.312 | yes | 15 | 0 | 6 | 172357 | 81.7s |
| webarena.314 | yes | 16 | 3 | 8 | 165946 | 258.3s |
| webarena.315 | yes | 19 | 2 | 7 | 157506 | 68.9s |
| webarena.316 | yes | 15 | 3 | 5 | 117048 | 82.5s |
| webarena.317 | ok | 13 | 1 | 6 | 155506 | 58.7s |
| webarena.318 | yes | 23 | 2 | 8 | 153228 | 75.7s |
| webarena.339 | yes | 9 | 0 | 4 | 82766 | 53.8s |
| webarena.340 | ok | 19 | 2 | 6 | 127953 | 82.5s |
| webarena.341 | yes | 33 | 2 | 10 | 265434 | 115.1s |
| webarena.342 | yes | 30 | 3 | 10 | 259691 | 134.0s |
| webarena.343 | yes | 24 | 2 | 7 | 159716 | 94.4s |
| webarena.349 | ok | 6 | 0 | 5 | 75836 | 97.4s |
| webarena.350 | yes | 26 | 2 | 9 | 147102 | 81.0s |
| webarena.357 | yes | 11 | 0 | 3 | 56956 | 47.0s |
| webarena.389 | yes | 11 | 1 | 5 | 107978 | 56.7s |
| webarena.390 | yes | 13 | 1 | 5 | 107753 | 55.4s |
| webarena.391 | yes | 18 | 1 | 5 | 110621 | 75.6s |
| webarena.392 | yes | 8 | 0 | 5 | 105727 | 58.9s |
| webarena.393 | yes | 12 | 0 | 6 | 111127 | 100.0s |
| webarena.394 | yes | 22 | 1 | 10 | 192817 | 108.4s |
| webarena.395 | yes | 30 | 2 | 10 | 349994 | 105.6s |
| webarena.396 | yes | 31 | 1 | 11 | 257062 | 90.2s |
| webarena.397 | yes | 43 | 7 | 12 | 231923 | 226.3s |
| webarena.398 | yes | 85 | 6 | 23 | 700872 | 403.3s |
| webarena.411 | ok | 34 | 2 | 14 | 331678 | 225.1s |
| webarena.412 | yes | 42 | 3 | 12 | 374421 | 223.4s |
| webarena.413 | yes | 19 | 3 | 10 | 297233 | 214.1s |
| webarena.414 | ok | 9 | 0 | 7 | 181349 | 95.0s |
| webarena.415 | yes | 20 | 2 | 5 | 107434 | 141.6s |
| webarena.416 | yes | 11 | 2 | 9 | 249542 | 123.9s |
| webarena.417 | yes | 29 | 1 | 12 | 350090 | 123.7s |
| webarena.418 | ok | 19 | 3 | 11 | 208183 | 143.8s |
| webarena.419 | yes | 19 | 2 | 6 | 122336 | 114.3s |
| webarena.420 | yes | 18 | 1 | 8 | 172381 | 126.7s |
| webarena.421 | yes | 14 | 1 | 6 | 101029 | 98.0s |
| webarena.422 | yes | 19 | 2 | 7 | 98048 | 87.9s |
| webarena.44 | yes | 13 | 1 | 7 | 130239 | 66.0s |
| webarena.441 | ok | 23 | 0 | 4 | 68021 | 151.5s |
| webarena.442 | yes | 61 | 3 | 16 | 412646 | 218.8s |
| webarena.443 | yes | 49 | 5 | 16 | 425625 | 342.3s |
| webarena.444 | yes | 57 | 8 | 10 | 193567 | 355.1s |
| webarena.445 | yes | 116 | 11 | 13 | 320185 | 257.4s |
| webarena.446 | yes | 28 | 2 | 12 | 288715 | 121.4s |
| webarena.447 | yes | 15 | 1 | 9 | 223822 | 85.2s |
| webarena.448 | yes | 9 | 0 | 3 | 41235 | 50.8s |
| webarena.449 | yes | 21 | 0 | 10 | 159460 | 93.0s |
| webarena.45 | ok | 25 | 8 | 5 | 139693 | 80.5s |
| webarena.450 | yes | 33 | 1 | 5 | 80840 | 160.5s |
| webarena.451 | yes | 7 | 0 | 5 | 75136 | 80.0s |
| webarena.452 | yes | 4 | 0 | 3 | 40092 | 48.9s |
| webarena.46 | yes | 5 | 0 | 5 | 103458 | 69.3s |
| webarena.475 | yes | 16 | 1 | 8 | 166995 | 87.2s |
| webarena.476 | yes | 40 | 12 | 10 | 219206 | 141.3s |
| webarena.477 | yes | 24 | 4 | 9 | 188359 | 96.5s |
| webarena.478 | yes | 25 | 2 | 10 | 214759 | 124.2s |
| webarena.479 | yes | 41 | 5 | 18 | 400143 | 234.5s |
| webarena.480 | yes | 18 | 1 | 12 | 244911 | 108.1s |
| webarena.481 | ok | 24 | 2 | 12 | 253979 | 129.8s |
| webarena.482 | ok | 17 | 2 | 12 | 229362 | 152.3s |
| webarena.483 | ok | 30 | 2 | 12 | 252684 | 115.4s |
| webarena.484 | ok | 18 | 1 | 12 | 256304 | 104.0s |
| webarena.485 | ok | 27 | 2 | 12 | 242116 | 141.1s |
| webarena.522 | ok | 30 | 2 | 14 | 303420 | 107.8s |
| webarena.523 | yes | 36 | 2 | 12 | 376742 | 142.6s |
| webarena.524 | yes | 22 | 0 | 10 | 329765 | 191.7s |
| webarena.525 | yes | 21 | 1 | 6 | 155783 | 275.7s |
| webarena.526 | yes | 12 | 1 | 10 | 374597 | 113.6s |
| webarena.527 | yes | 11 | 0 | 7 | 201210 | 180.8s |
| webarena.533 | yes | 8 | 0 | 5 | 99664 | 107.1s |
| webarena.534 | yes | 17 | 1 | 13 | 250475 | 142.0s |
| webarena.535 | yes | 18 | 2 | 15 | 337554 | 196.6s |
| webarena.536 | yes | 27 | 2 | 17 | 461994 | 254.2s |
| webarena.537 | yes | 7 | 0 | 8 | 150424 | 102.5s |
| webarena.567 | yes | 21 | 3 | 18 | 434713 | 249.1s |
| webarena.568 | yes | 13 | 1 | 12 | 236252 | 94.0s |
| webarena.569 | yes | 17 | 1 | 13 | 285033 | 158.5s |
| webarena.570 | yes | 25 | 1 | 19 | 418137 | 158.7s |
| webarena.576 | yes | 17 | 1 | 12 | 259489 | 103.1s |
| webarena.577 | yes | 20 | 1 | 15 | 354731 | 174.6s |
| webarena.578 | yes | 23 | 1 | 20 | 411979 | 197.7s |
| webarena.579 | yes | 20 | 3 | 17 | 490083 | 128.2s |
| webarena.590 | ok | 9 | 0 | 7 | 130388 | 67.3s |
| webarena.591 | ok | 7 | 0 | 5 | 74729 | 65.6s |
| webarena.592 | ok | 7 | 1 | 5 | 72034 | 97.4s |
| webarena.593 | yes | 9 | 1 | 7 | 183867 | 200.2s |
| webarena.594 | yes | 8 | 0 | 5 | 124832 | 171.5s |
| webarena.658 | ok | 9 | 0 | 6 | 123100 | 169.2s |
| webarena.659 | ok | 19 | 0 | 15 | 321075 | 133.3s |
| webarena.660 | ok | 21 | 1 | 13 | 319899 | 162.6s |
| webarena.661 | ok | 6 | 0 | 4 | 74332 | 125.0s |
| webarena.662 | yes | 10 | 1 | 7 | 138477 | 94.2s |
| webarena.663 | ok | 7 | 0 | 4 | 75697 | 80.5s |
| webarena.664 | yes | 10 | 2 | 8 | 176259 | 162.1s |
| webarena.665 | yes | 7 | 0 | 4 | 76413 | 95.0s |
| webarena.666 | ok | 10 | 0 | 10 | 211052 | 166.5s |
| webarena.667 | yes | 5 | 0 | 6 | 101331 | 82.0s |
| webarena.668 | ok | 11 | 0 | 11 | 223875 | 130.6s |
| webarena.669 | yes | 8 | 0 | 5 | 84850 | 201.3s |
| webarena.670 | yes | 8 | 0 | 5 | 70191 | 86.5s |
| webarena.736 | ok | 9 | 0 | 8 | 204571 | 113.6s |
| webarena.742 | yes | 29 | 3 | 19 | 520665 | 177.9s |
| webarena.743 | yes | 21 | 1 | 18 | 466339 | 161.1s |
| webarena.744 | yes | 21 | 1 | 14 | 361500 | 247.7s |
| webarena.745 | yes | 27 | 1 | 19 | 584251 | 175.8s |
| webarena.746 | yes | 27 | 3 | 21 | 558405 | 215.7s |
| webarena.747 | yes | 26 | 2 | 19 | 488380 | 237.0s |
| webarena.748 | yes | 33 | 5 | 25 | 694555 | 221.2s |
| webarena.749 | yes | 27 | 2 | 20 | 505759 | 224.5s |
| webarena.750 | yes | 25 | 1 | 16 | 444169 | 258.2s |
| webarena.751 | yes | 21 | 1 | 17 | 418899 | 167.4s |
| webarena.752 | yes | 16 | 0 | 11 | 247665 | 569.2s |
| webarena.753 | yes | 12 | 1 | 9 | 202365 | 146.2s |
| webarena.754 | yes | 14 | 1 | 11 | 240691 | 168.5s |
| webarena.755 | yes | 15 | 1 | 9 | 228699 | 618.1s |
| webarena.756 | yes | 16 | 1 | 8 | 196884 | 388.9s |
| webarena.783 | yes | 9 | 0 | 6 | 158411 | 119.5s |
| webarena.784 | ok | 5 | 0 | 6 | 129268 | 113.1s |
| webarena.785 | yes | 4 | 0 | 4 | 92219 | 87.3s |
| webarena.786 | ok | 2 | 0 | 3 | 85764 | 116.6s |
| webarena.787 | yes | 4 | 0 | 5 | 75178 | 97.3s |
| webarena.788 | yes | 6 | 0 | 7 | 157334 | 130.7s |
| webarena.789 | yes | 11 | 0 | 8 | 210856 | 65.4s |
| webarena.799 | yes | 38 | 2 | 27 | 622897 | 219.4s |
| webarena.800 | yes | 34 | 1 | 23 | 670386 | 243.0s |
| webarena.801 | yes | 32 | 1 | 17 | 369946 | 196.7s |
| webarena.802 | yes | 37 | 1 | 19 | 440286 | 248.4s |
| webarena.803 | yes | 47 | 1 | 20 | 492272 | 175.2s |
| webarena.804 | ok | 55 | 5 | 17 | 527110 | 623.2s |
| webarena.805 | ok | 12 | 0 | 8 | 176364 | 125.1s |
| webarena.806 | yes | 14 | 0 | 9 | 248280 | 154.0s |
| webarena.807 | yes | 10 | 0 | 11 | 320338 | 154.4s |
| webarena.808 | yes | 14 | 0 | 10 | 225836 | 197.9s |
| webarena.809 | yes | 13 | 1 | 8 | 169267 | 146.3s |
| webarena.810 | ok | 10 | 1 | 9 | 215263 | 130.9s |
| webarena.811 | ok | 8 | 0 | 9 | 217984 | 182.7s |
