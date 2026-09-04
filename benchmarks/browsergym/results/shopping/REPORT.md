# WebArena — shopping (One Stop Market), full task list

Model **z-ai/glm-5.3-flash** via OpenRouter, driving the abt toolkit through
BrowserGym. 30-turn ceiling, one fresh agent process per task.

## Result

| | |
|---|---|
| tasks scored | 187 |
| passed, as the harness scored it | **98 — 52.4%** |
| recovered by the fuzzy judging pass | +11 |
| **final** | **109 — 58.3%** |
| total ops | 2,088 |
| total turns | 1,601 |
| total tokens | 34,636,273 (26,290,560 cached, 76%) |
| total wall time | 11.1 h |
| mean per task | 11 ops, 9 turns, 185,222 tokens, 214 s |

`fuzzy_match` tasks need a GPT-4 judge and no key was set, so 24 episodes were
recorded as failures without being scored. They were judged by hand against
WebArena's own criterion — does the answer mean the same as the reference — and
every verdict is in the table, because the judging was done by the same party
that ran the agent.


## Did it actually do the task?

A second measure, kept apart from the score and never a substitute for
it. WebArena grades a string; this asks whether the work was right. An
episode counts correct when everything the evaluator required appears in
what the agent produced -- its reply, or the page it left behind -- as an
in-order run of words. That forgives an inserted word, punctuation, and an
answer written in prose instead of on the ANSWER: line. It does not forgive
a wrong value: 260.69 is not 265.69 under any reading.

| | count | share |
|---|---|---|
| credited by the harness | 109 | **58.3%** |
| correct but uncredited | 15 | 8.0% |
| genuinely incorrect | 51 | 27.3% |
| unclear from the record | 12 | 6.4% |
| **did the task** | **124** | **66.3%** |

So the benchmark scores **58.3%** and the agent did the asked-for work in
**66.3%** of episodes. The gap is 15 episodes where the work was right and
the string was not: contact-form drafts whose required phrase the task
statement itself contradicts, wishlist additions the evaluator checked on a
page the agent had already moved past, and answers stated in prose rather
than on the marker line.

The 51 genuinely incorrect episodes are the honest failures: wrong totals,
missed rows, and investigations that stopped before finding the answer.

## Every task

| task | question | answer required | answer given | result | correct | why | turns | ops | tokens (cached) | time |
|---|---|---|---|---|---|---|---|---|---|---|
| webarena.117 | What is the date when I made my first purchase on this site? | fuzzy_match: 3/2/22 | 3/2/22 | **PASS** ᶠ | — | exact: "3/2/22" | 8 | 8 | 124,152 (103,616) | 117s |
| webarena.118 | I have jaw bruxism problem, show me something that could alleviate the problem. | page must_include: jaw bruxism, mouth guard | Mouth Guard, Professional Anti Grinding Night Guard for Teeth Grinding… | fail | no | prose on the ANSWER line, not an answer | 5 | 7 | 75,512 (27,136) | 101s |
| webarena.124 | What is the price range of wireless earphone in the One Stop Market? | must_include: 0.14, 745.00 | 0.01, 17,774.32 | fail | no | wrong answer | 6 | 9 | 99,685 (83,392) | 146s |
| webarena.125 | What is the price range of teeth grinding mouth guard in the One Stop Market? | must_include: 1.46, 85 | 0.01, 7149.00 | fail | no | wrong answer | 13 | 14 | 291,547 (219,968) | 569s |
| webarena.126 | What is the price range of Canon photo printer in the One Stop Market? | must_include: 2.56, 649.99 | 2.56, 649.99 | **PASS** | — | — | 8 | 14 | 192,367 (46,656) | 401s |
| webarena.141 | How much I spent on food-related shopping during March 2023 | must_include: 47.41 | 32.41 | fail | no | off by 15.00 (wanted 47.41, gave 32.41) | 16 | 32 | 485,730 (395,072) | 548s |
| webarena.142 | How much I spent on hair care and hair style shopping during Jan 2023 | must_include: 95.23 | 80.50 | fail | no | off by 14.73 (wanted 95.23, gave 80.50) | 13 | 15 | 271,028 (169,600) | 297s |
| webarena.143 | How much I spent on home decoration shopping during 1/29/2023 | must_include: 265.69 | 260.69 | fail | no | off by 5.00 (wanted 265.69, gave 260.69) | 5 | 6 | 71,648 (63,168) | 85s |
| webarena.144 | How much I spent on food shopping during from mid Jan to the end Jan 2023 | must_include: 0 | 572.88 | fail | no | wrong answer | 4 | 5 | 57,553 (51,712) | 78s |
| webarena.145 | How much I spent on cooking and food shopping during March 2022 | must_include: 52.35 | Order #160 (3/2/22, Canceled) is mixed: electronics + 2 food items. Le… | fail | no | prose on the ANSWER line, not an answer | 11 | 13 | 196,785 (173,504) | 308s |
| webarena.146 | What is the size configuration of the picture frame I bought Sep 2022 | must_include: 16x24 | 16*24 | fail | no | wrong answer | 9 | 12 | 155,870 (137,408) | 183s |
| webarena.147 | What is the size configuration of the picture frame I bought 2022 | must_include: 16x24 | 18 x 24 | fail | no | wrong answer | 18 | 19 | 414,424 (356,736) | 355s |
| webarena.148 | What is the color configuration of the picture frame I bought Sep 2022 | must_include: Mist | Mist 16*24 | **PASS** | — | — | 11 | 10 | 168,234 (156,672) | 146s |
| webarena.149 | What is the color configuration of the artifical plants I bought Feb 2023 | must_include: Green-vines | Green-vines | **PASS** | — | — | 6 | 9 | 127,115 (98,304) | 77s |
| webarena.150 | What is the price configuration of the fake tree I bought Jan 2023 | must_include: 260.69 | 260.69 | **PASS** | — | — | 9 | 12 | 157,961 (141,504) | 135s |
| webarena.158 | I have a lot of Nintendo Switch game cards now, help me find the best storage option to fit all 11 cards | URL (GOLD in PRED): __SHOPPING__/heiying-game-card-case-for-nintendo-switch-switch-oled-game-card-or-micro-sd-memory-cards-portable-switch-game-memory… | HEIYING Game Card Case for Nintendo Switch& Switch OLED Game Card or M… | **PASS** | — | — | 14 | 15 | 324,537 (295,232) | 230s |
| webarena.159 | I have a lot of Nintendo Switch game cards now, help me find the best storage option to fit all 31 cards | URL (GOLD in PRED): __SHOPPING__/game-card-holder-storage-case-for-nintendo-switch-games-or-ps-vita-game-case-or-sd-memory-cards-black.html | Game Card Holder Storage Case for Nintendo Switch Games or PS Vita Gam… | **PASS** | — | — | 10 | 15 | 199,054 (176,000) | 151s |
| webarena.160 | I have a lot of Nintendo Switch game cards now, help me find the best storage option to fit all 6 cards | URL (GOLD in PRED): __SHOPPING__/heiying-game-card-case-for-nintendo-switch-switch-oled-game-card-or-micro-sd-memory-cards-portable-switch-game-memory… | Mijibisu Car Headrest Mount Holder for Nintendo Switch, Carrying Case … | fail | ? | prose on the ANSWER line, not an answer | 16 | 18 | 374,511 (338,752) | 286s |
| webarena.161 | I have a lot of Nintendo Switch game cards now, help me find the best storage option to fit all 23 cards | URL (GOLD in PRED): __SHOPPING__/heiying-game-card-case-for-nintendo-switch-switch-oled-game-card-or-micro-sd-memory-cards-portable-switch-game-memory… | HEIYING Game Card Case for Nintendo Switch& Switch OLED Game Card or M… | **PASS** | — | — | 10 | 13 | 219,702 (173,888) | 270s |
| webarena.162 | I have a lot of Nintendo Switch game cards now, help me find the best storage option to fit all 40 cards | URL (GOLD in PRED): __SHOPPING__/game-card-holder-storage-case-for-nintendo-switch-games-or-ps-vita-game-case-or-sd-memory-cards-black.html | Game Card Holder Storage Case for Nintendo Switch Games or PS Vita Gam… | **PASS** | — | — | 5 | 6 | 72,543 (52,608) | 75s |
| webarena.163 | What are the main criticisms of this product? Please extract the relevant sentences. | must_include: I ordered the 16gb but I only got 14 gigs even though I formatted the card, The memory card is kind of slow on games and downloads, No o… | I ordered the 16gb but I only got 14 gigs even though I formatted the … | fail | no | prose on the ANSWER line, not an answer | 4 | 6 | 58,525 (50,240) | 78s |
| webarena.164 | What are the main criticisms of this product? Please extract the relevant sentences. | must_include: Dry, Uneven color | Those labial never came to me and I would like them again because I pa… | **PASS** | — | — | 6 | 5 | 77,153 (70,528) | 76s |
| webarena.165 | What are the main criticisms of this product? Please extract the relevant sentences. | must_include: The 39 was too small. I am afraid the 40 will be too big, I was very sad when the shoe rubbed up against my baby toe, I had to return th… | The 39 was too small. I was very sad when the shoe rubbed up against m… | fail | no | prose on the ANSWER line, not an answer | 5 | 4 | 72,500 (40,512) | 91s |
| webarena.166 | What are the main criticisms of this product? Please extract the relevant sentences. | fuzzy_match: N/A | It remains to be seen whether it's accomplishing the other promises of… | fail | no | gave a criticism sentence; reference was N/A | 5 | 7 | 66,440 (37,056) | 91s |
| webarena.167 | What are the main criticisms of this product? Please extract the relevant sentences. | must_include: The wireless connection works on a whim (about 40% of the time I've owned it), It seems to constantly run out of ink, Cartridge prices a… | The wireless connection works on a whim (about 40% of the time I've ow… | **PASS** | — | — | 6 | 5 | 80,718 (71,872) | 168s |
| webarena.188 | Tell me the total cost of my latest cancelled order? | must_include: 365.42 | 365.42 | **PASS** | — | — | 4 | 4 | 54,813 (20,864) | 83s |
| webarena.189 | Tell me the total cost of my latest pending order? | must_include: 754.99 | 113.35 | fail | no | off by 641.64 (wanted 754.99, gave 113.35) | 4 | 3 | 51,647 (23,552) | 66s |
| webarena.190 | Tell me the total cost of my latest complete order? | must_include: 65.32 | 65.32 | **PASS** | — | — | 5 | 4 | 67,344 (60,800) | 68s |
| webarena.191 | Tell me the total cost of my latest processing order? | fuzzy_match: N/A | N/A | **PASS** | — | — | 6 | 7 | 108,422 (74,816) | 252s |
| webarena.192 | Tell me the total cost of my latest non-cancelled order? | must_include: 754.99 | 113.35 | fail | no | off by 641.64 (wanted 754.99, gave 113.35) | 4 | 4 | 53,663 (47,360) | 62s |
| webarena.21 | List out reviewers, if exist, who mention about ear cups being small | must_include: Joseph Brzezinski, Catso, Dibbins, Anglebert Dinkherhump, Michelle Davis | Dibbins, Anglebert Dinkherhump | fail | no | wrong answer | 6 | 8 | 95,870 (50,688) | 173s |
| webarena.22 | List out reviewers, if exist, who mention about under water photo | fuzzy_match: N/A | N/A | **PASS** | — | — | 12 | 15 | 241,465 (208,960) | 225s |
| webarena.225 | What do customers say about brush from sephora | fuzzy_match: N/A | N/A | **PASS** | — | — | 10 | 13 | 196,173 (142,016) | 158s |
| webarena.226 | What is the price range for products from Amazon basic? | must_include: 5.49, 375.19 | 5.49, 508.37 | fail | no | wrong answer | 14 | 26 | 430,434 (337,472) | 433s |
| webarena.227 | What is the price range for products from EYZUTAK? | must_include: 9.99 | 9.99 | **PASS** | — | — | 5 | 7 | 70,996 (62,080) | 74s |
| webarena.228 | What is the price range for products from sephora? | must_include: 18.18, 94.99 | 18.18, 94.99 | **PASS** | — | — | 9 | 14 | 200,738 (172,416) | 228s |
| webarena.229 | What is the price range for products from ugreen? | must_include: 6.99, 38.99 | 6.99, 38.99 | **PASS** | — | — | 4 | 7 | 56,385 (47,872) | 60s |
| webarena.23 | List out reviewers, if exist, who mention about good fingerprint resistant | must_include: Rachel, T. Gannon | Rachel, T. Gannon | **PASS** | — | — | 7 | 8 | 101,228 (91,008) | 74s |
| webarena.230 | What is the price range for products from Perricone MD? | must_include: 35, 149 | 35.00, 149.00 | **PASS** | — | — | 7 | 9 | 126,531 (109,568) | 119s |
| webarena.231 | Get the order number of my most recent cancelled order | must_include: 170 | 000000170 | **PASS** | — | — | 3 | 3 | 51,468 (40,192) | 75s |
| webarena.232 | Get the order number of my most recent pending order | must_include: 189 | 000000193 | fail | no | off by 4.00 (wanted 189, gave 000000193) | 4 | 4 | 54,723 (37,696) | 66s |
| webarena.233 | Get the order number of my most recent complete order | must_include: 180 | 000000180 | **PASS** | — | — | 4 | 4 | 53,533 (36,544) | 56s |
| webarena.234 | Get the order number of my most recent on hold order | fuzzy_match: N/A | 50 per page covers all 41 orders in one view. Let me load that. | fail | no | prose on the ANSWER line, not an answer | 6 | 6 | 121,801 (90,112) | 240s |
| webarena.235 | Get the order number of my most recent under delivery order | fuzzy_match: N/A | 000000193 | fail | no | gave an order number; reference was N/A | 8 | 12 | 180,779 (139,392) | 429s |
| webarena.238 | I am doing a market survey for one stop market, show me the most expensive product from PS4 accessories catego… | URL (GOLD in PRED): __SHOPPING__/astro-gaming-a50-wireless-headset-base-station-gen-4-compatible-with-ps5-ps4-pc-mac-black-silver.html | ASTRO Gaming A50 Wireless Headset + Base Station Gen 4 - Compatible Wi… | **PASS** | — | — | 11 | 13 | 183,803 (155,456) | 148s |
| webarena.239 | I am doing a market survey for one stop market, show me the most expensive product from nutrition bars and dri… | URL (GOLD in PRED): __SHOPPING__/kellogg-s-special-k-protein-meal-bars-chocolate-caramel-12-7oz-6-count.html | Kellogg's Special K Protein Meal Bars, Chocolate Caramel, 12.7oz (6 Co… | fail | ? | prose on the ANSWER line, not an answer | 5 | 5 | 68,575 (61,184) | 67s |
| webarena.24 | List out reviewers, if exist, who mention about price being unfair | fuzzy_match: N/A | 0 | **PASS** ᶠ | — | "0" means no such reviewers, same as "N/A" (borderline) | 8 | 8 | 105,361 (86,400) | 98s |
| webarena.240 | I am doing a market survey for one stop market, show me the most expensive product from competitive swimwear c… | URL (GOLD in PRED): __SHOPPING__/women-cross-flower-beachwear-tankini-bandeau-bandage-bikini-set-push-up-swimwear-bathing-suit-two-pieces-swimsuits.ht… | Women Cross Flower Beachwear Tankini Bandeau Bandage Bikini Set Push-U… | **PASS** | — | — | 8 | 7 | 110,714 (101,888) | 93s |
| webarena.241 | I am doing a market survey for one stop market, show me the most expensive product from skin care tool categor… | URL (GOLD in PRED): __SHOPPING__/professional-medi-spa-scar-stretch-mark-reduction-system.html | Atdoriat Hydrogen Oxygen Facial Skin Beauty Machine Upgraded 8 in 1 Mu… | fail | ? | prose on the ANSWER line, not an answer | 14 | 14 | 253,513 (185,728) | 237s |
| webarena.242 | I am doing a market survey for one stop market, show me the most expensive product from Household Supplies cat… | URL (GOLD in PRED): __SHOPPING__/lynx-battery-12v-200ah-lithium-iron-phosphate-lifepo4-prismatic-deep-cell-battery-set-of-4-3-2v-cells-with-3-bus-bars… | Lynx Battery 12V 200Ah Lithium Iron Phosphate LiFePO4 Prismatic Deep C… | **PASS** | — | — | 8 | 8 | 126,255 (90,112) | 122s |
| webarena.25 | List out reviewers, if exist, who mention about average print quality | must_include: Goldfish, Roxanne Brandon Coffey | Roxanne Brandon Coffey | fail | **yes** | wrong answer | 7 | 7 | 115,975 (103,552) | 83s |
| webarena.26 | List out reviewers, if exist, who mention about complain of the customer service | must_include: Bob in Vegas, RemyR | Bob in Vegas, RemyRRemyR | **PASS** | — | — | 9 | 12 | 183,450 (163,200) | 118s |
| webarena.260 | I want to browse the products in the Video Game category | URL (GOLD in PRED): __SHOPPING__/video-games.html | http://localhost:7770/video-games.html | **PASS** | — | — | 3 | 2 | 37,068 (33,408) | 364s |
| webarena.261 | I want to browse the products in the Headphones category | URL (GOLD in PRED): __SHOPPING__/electronics/headphones.html | 631 | **PASS** | — | — | 4 | 4 | 70,815 (59,456) | 58s |
| webarena.262 | I want to browse the products in the Men shoes category | URL (GOLD in PRED): __SHOPPING__/clothing-shoes-jewelry/men/shoes.html | 2523 | **PASS** | — | — | 6 | 6 | 95,086 (83,776) | 62s |
| webarena.263 | I want to browse the products in the Woman clothing category | URL (GOLD in PRED): __SHOPPING__/clothing-shoes-jewelry/women/clothing.html | Women | fail | ? | wrong answer | 6 | 5 | 82,033 (75,264) | 68s |
| webarena.264 | I want to browse the products in the Cabinets, Racks & Shelves category | URL (GOLD in PRED): __SHOPPING__/office-products/office-furniture-lighting/cabinets-racks-shelves.html | 288 | **PASS** | — | — | 7 | 6 | 100,816 (93,056) | 97s |
| webarena.269 | Show me products under $25 in "women shoes" category | URL (GOLD in PRED): __SHOPPING__/clothing-shoes-jewelry/women/shoes.html?price=0-25 | 1312 | fail | ? | wrong answer | 10 | 11 | 166,688 (152,320) | 122s |
| webarena.270 | Show me products under $30 in "men shoes" category | URL (GOLD in PRED): __SHOPPING__/clothing-shoes-jewelry/men/shoes.html?price=0-30 | 523 | **PASS** | — | — | 8 | 7 | 118,939 (96,256) | 127s |
| webarena.271 | Show me products under $46.99 in "makeup remover" category | URL (GOLD in PRED): __SHOPPING__/beauty-personal-care/makeup/makeup-remover.html?price=0-46.99 | 96 | **PASS** | — | — | 10 | 10 | 304,570 (177,408) | 1198s |
| webarena.272 | Show me products under $78 in "children dental care" category | URL (GOLD in PRED): __SHOPPING__/beauty-personal-care/oral-care/children-s-dental-care.html?price=0-78 | 179 | **PASS** | — | — | 9 | 10 | 138,268 (114,560) | 125s |
| webarena.273 | Show me products under $199 in "furtiture with accent" category | URL (GOLD in PRED): __SHOPPING__/home-kitchen/furniture/accent-furniture.html?price=0-199 | 571 | **PASS** | — | — | 7 | 8 | 209,827 (166,848) | 147s |
| webarena.274 | Search for "usb wifi" | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/?q=usb+wifi | 7123 | **PASS** | — | — | 3 | 4 | 45,579 (25,664) | 69s |
| webarena.275 | Search for "xbox" | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/?q=xbox | 839 | **PASS** | — | — | 3 | 4 | 38,447 (33,472) | 45s |
| webarena.276 | Search for "switch accessories" | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/?q=switch+accessories | 13792 | **PASS** | — | — | 5 | 7 | 69,451 (64,448) | 381s |
| webarena.277 | Search for "batteries for iphone 13" | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/?q=iphone+13 | Found the search box on this Magento store. Now I'll search for "batte… | fail | ? | prose on the ANSWER line, not an answer | 3 | 4 | 45,539 (33,472) | 176s |
| webarena.278 | Search for "green tea bag for weight loss" | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/?q=green+tea+bag+for+weight+loss | green tea bag for weight loss | **PASS** | — | — | 3 | 4 | 38,335 (10,432) | 72s |
| webarena.279 | Provide me with the complete names of Bluetooth headphones from Sony, and also share the price range for the a… | must_include: SONY WH1000XM3 Bluetooth Wireless Noise Canceling Headphones Silver WH-1000XM3/S (Renewed), Sony WH-CH710N/H Wireless Bluetooth Noise Ca… | SONY WH1000XM3 Bluetooth Wireless Noise Canceling Headphones Silver WH… | fail | no | prose on the ANSWER line, not an answer | 18 | 19 | 608,149 (455,296) | 658s |
| webarena.280 | Provide me with the full names of chargers from Anker, and also share the price range for the available models | must_include: Anker USB C Charger 30W, 711 Charger, Compact Fast Charger (Not Foldable) for MacBook Air/iPhone 13/13 Mini/13 Pro/13 Pro Max/12, Galaxy… | The search returned 36 results across 3 pages. Let me check pages 2 an… | fail | no | prose on the ANSWER line, not an answer | 4 | 6 | 79,895 (57,024) | 175s |
| webarena.281 | Please provide me with the complete product names of Oral B brush heads designed for children, along with thei… | must_include: Oral-B Kids Extra Soft Replacement Brush Heads featuring STAR WARS, 2 count, Kids By Oral-b Stages Power Star Wars Replacement Heads 4 P… | Oral-B Kids Extra Soft Replacement Brush Heads featuring STAR WARS, 2 … | fail | no | prose on the ANSWER line, not an answer | 16 | 32 | 427,732 (308,992) | 529s |
| webarena.282 | List the full product names of slide slippers from Nike and tell me the price range of the available products | must_include: Nike Men's Air Max Camden Slide Sandal, Nike Men's Benassi JDI Fanny Pack Slides, Nike Victori One Mens Comfort Slide Cn9675-003 (Midnig… | Nike Victori One Mens Comfort Slide Cn9675-003 (Midnight Navy/Midnight… | fail | no | prose on the ANSWER line, not an answer | 13 | 22 | 372,811 (311,744) | 359s |
| webarena.283 | Look up the most recent models of XBox controllers released between 2020-2021? | URL (GOLD in PRED): __SHOPPING__/microsoft-xbox-controller-carbon-black-for-series-x-series-s-xbox-one-windows-10-android-ios-bundled-with-dual-port-c… | Microsoft Xbox Controller (Carbon Black) for Series X, Series S, Xbox … | **PASS** | — | — | 16 | 23 | 452,527 (304,256) | 532s |
| webarena.284 | Show the least expensive shoe storage with a minimum storage capacity of 12 pairs. | URL (GOLD in PRED): __SHOPPING__/onlyeasy-over-the-door-shoe-storage-organizer-hanging-shoe-rack-holder-with-24-large-fabric-pockets-22-1-x-61-4-herri… | Onlyeasy Over The Door Shoe Storage Organizer Hanging Shoe Rack Holder… | **PASS** | — | — | 20 | 37 | 633,054 (557,760) | 384s |
| webarena.285 | Show the least expensive switch card holder with a minimum storage capacity of 15 cards. | URL (GOLD in PRED): __SHOPPING__/game-card-holder-storage-case-for-nintendo-switch-games-or-ps-vita-game-case-or-sd-memory-cards-black.html | Game Card Holder Storage Case for Nintendo Switch Games or PS Vita Gam… | **PASS** | — | — | 15 | 22 | 379,167 (326,080) | 303s |
| webarena.286 | Show the least expensive ssd hard drive with a minimum storage capacity of 1TB. | URL (GOLD in PRED): __SHOPPING__/external-hard-drive-2tb-ultra-thin-external-hard-drive-2000gb-ultra-high-speed-portable-3-1-type-c-storage-drive-comp… | Portable SSD 2TB External Hard Drive Mobile Solid State Drive Portable… | fail | ? | prose on the ANSWER line, not an answer | 17 | 19 | 549,578 (489,536) | 272s |
| webarena.298 | Show the most recent completed order | URL (GOLD in PRED): __SHOPPING__/sales/order/view/order_id/180/ | 000000180 | **PASS** | — | — | 4 | 4 | 72,117 (60,032) | 74s |
| webarena.299 | Show the most recent cancelled order | URL (GOLD in PRED): __SHOPPING__/sales/order/view/order_id/170/ | 000000170 | **PASS** | — | — | 4 | 5 | 73,904 (60,672) | 64s |
| webarena.300 | Show the most recent pending order | URL (GOLD in PRED): __SHOPPING__/sales/order/view/order_id/189/ | 000000193 | fail | ? | wrong answer | 5 | 5 | 73,104 (64,320) | 69s |
| webarena.301 | Show the most recent processing order | fuzzy_match: N/A | N/A | **PASS** | — | — | 5 | 5 | 80,498 (63,936) | 184s |
| webarena.302 | Show the most recent out of delivery order | fuzzy_match: N/A | My guessed ID redirected back to history. Let me use the actual "View … | fail | no | prose on the ANSWER line, not an answer | 9 | 9 | 160,280 (131,456) | 400s |
| webarena.313 | Which number to call for the customer service? | fuzzy_match: N/A | 6505551212 | fail | no | gave a phone number; reference was N/A | 27 | 47 | 834,953 (538,944) | 775s |
| webarena.319 | How much refund I should expect from my order canlled in April 2022, including shipping fee | must_include: 0 | Order 000000173 was placed March 10, 2022 — cancelled status, grand to… | fail | no | prose on the ANSWER line, not an answer | 10 | 14 | 179,793 (129,472) | 418s |
| webarena.320 | How much refund I should expect from my order canlled in Feb 2023, including shipping fee | must_include: 406.53 | No refund tabs — plain canceled orders. Let me check the account dashb… | fail | no | prose on the ANSWER line, not an answer | 9 | 14 | 230,685 (183,616) | 345s |
| webarena.321 | How much refund I should expect from my order canlled in 2022, including shipping fee | must_include: 3053.97 | 3053.97 | **PASS** | — | — | 12 | 19 | 326,696 (184,320) | 368s |
| webarena.322 | How much refund I should expect from my order canlled in May 2023 if I cannot get the shipping fee refunded? | must_include: 350.42 | 350.42 | **PASS** | — | — | 4 | 6 | 57,477 (10,496) | 66s |
| webarena.323 | How much refund I should expect from my order canlled in 2022/03? I only kept the AC-DC Adapter and the shop t… | must_include: 264.49 | 77.90 | fail | no | off by 186.59 (wanted 264.49, gave 77.90) | 8 | 8 | 120,938 (82,432) | 119s |
| webarena.324 | Show me the "chairs" listings by ascending price. | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/index/?product_list_order=price&q=chairs&product_list_dir=asc | HOMCOM 43 Inch Wall-Mounted Stainless Steel Ventless Ethanol Fireplace… | fail | ? | prose on the ANSWER line, not an answer | 3 | 3 | 42,563 (0) | 84s |
| webarena.325 | Show me the "mouth night guard" listings by descending price. | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/index/?q=mouth%20night%20guard%20&product_list_order=price | http://localhost:7770/catalogsearch/result/index/?q=mouth%20night%20gu… | fail | ? | prose on the ANSWER line, not an answer | 7 | 8 | 102,984 (54,784) | 111s |
| webarena.326 | Show me the "Canon photo printer" listings by search relevance, from most to least. | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/?q=Canon+photo+printer | http://localhost:7770/catalogsearch/result/?q=Canon+photo+printer | **PASS** | — | — | 4 | 6 | 66,926 (54,336) | 125s |
| webarena.327 | Show me the "iphone 12 phone case" listings by name alphabetically. | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/index/?q=%20iphone%2012%20phone%20case&product_list_order=name | 43033 | fail | ? | wrong answer | 7 | 9 | 142,613 (112,320) | 278s |
| webarena.328 | Show me the "iphone 12 phone case" listings by price. | URL (GOLD in PRED): __SHOPPING__/catalogsearch/result/index/?product_list_order=price&q=%20iphone%2012%20phone%20case | http://localhost:7770/catalogsearch/result/index/?q=iphone%2012%20phon… | fail | ? | prose on the ANSWER line, not an answer | 5 | 6 | 75,970 (62,208) | 128s |
| webarena.329 | How much I spend on 4/19/2023 on shopping at One Stop Market? | must_include: 0 | The playbook gives me a fast path. Let me pull the full order history. | fail | no | prose on the ANSWER line, not an answer | 4 | 4 | 62,341 (48,064) | 191s |
| webarena.330 | How much I spend in March 2023 on shopping at One Stop Market? | must_include: 81.31 | 83.31 | fail | no | off by 2.00 (wanted 81.31, gave 83.31) | 5 | 5 | 74,532 (64,768) | 77s |
| webarena.331 | How much I spend in July 2022 on shopping at One Stop Market? | must_include: 40.16 | 40.16 | **PASS** | — | — | 9 | 13 | 215,155 (135,936) | 130s |
| webarena.332 | How much I spend each month from Jan to the end of March 2023 on shopping at One Stop Market? | fuzzy_match: Jan: 572.8, Feb: 762.18, Mar: 83.31 | All 41 orders are now on one page, sorted newest first. Filtering to J… | fail | no | prose on the ANSWER line; needed three monthly totals | 5 | 5 | 79,822 (55,040) | 302s |
| webarena.333 | How much did I spend on shopping at One Stop Market on November 2022? They gave me a 20% discount on the total… | must_include: 359.546 | 322.54 | fail | no | off by 37.01 (wanted 359.546, gave 322.54) | 7 | 6 | 98,395 (75,328) | 115s |
| webarena.334 | Tell me when I last ordered my muffin cornbread mix? | fuzzy_match: March 11th 2023 | March 11, 2023 | **PASS** ᶠ | — | "March 11, 2023" == "March 11th 2023" | 8 | 12 | 190,581 (167,232) | 180s |
| webarena.335 | Tell me when I last ordered my body butter? | fuzzy_match: January 16th 2023 | January 16, 2023 | **PASS** ᶠ | — | "January 16, 2023" == "January 16th 2023" | 8 | 7 | 118,884 (108,416) | 138s |
| webarena.336 | Tell me when I last ordered my conditioner? | fuzzy_match: January 16th 2023 | January 16, 2023 | **PASS** ᶠ | — | "January 16, 2023" == "January 16th 2023" | 8 | 13 | 201,609 (172,928) | 183s |
| webarena.337 | Tell me when I last ordered my bread olive? | fuzzy_match: December 12th 2022 | 12/12/22 | **PASS** ᶠ | — | "12/12/22" == "December 12th 2022" | 9 | 9 | 159,307 (140,352) | 204s |
| webarena.338 | Tell me when I last ordered my toothpaste? | fuzzy_match: December 4th 2022 | December 4, 2022 | **PASS** ᶠ | — | "December 4, 2022" == "December 4th 2022" | 8 | 8 | 168,185 (132,544) | 223s |
| webarena.351 | List products from PS4 accessories category by ascending price | URL (GOLD in PRED): __SHOPPING__/video-games/playstation-4/accessories.html?product_list_order=price | Dechoga PS4 Charging Board, Replacement USB Charging Port Socket Board… | **PASS** | — | — | 4 | 5 | 77,870 (62,080) | 80s |
| webarena.352 | List products from nutrition bars and drinks category by ascending price | URL (GOLD in PRED): __SHOPPING__/health-household/diet-sports-nutrition/nutrition-bars-drinks.html?product_list_order=price | Pages 2–4 captured. Now fetching pages 5, 6, 7, and returning to sorte… | **PASS** | — | — | 10 | 14 | 208,554 (161,792) | 387s |
| webarena.353 | List products from competitive swimwear category by ascending price | URL (GOLD in PRED): __SHOPPING__/clothing-shoes-jewelry/sport-specific-clothing/competitive-swimwear.html?product_list_order=price | Beachwear Padded Swimwear Solid, MOKINGTOP Women Bikini Swimsuit, Tank… | **PASS** | — | — | 8 | 10 | 138,085 (102,080) | 185s |
| webarena.354 | List products from living room furtniture category by descending price | URL (GOLD in PRED): __SHOPPING__/home-kitchen/furniture/living-room-furniture.html?product_list_order=price&product_list_dir=desc | SND-A New Convertible Sleeper Sofa Bed,Living Room with Night Light an… | **PASS** | — | — | 12 | 12 | 192,779 (176,704) | 155s |
| webarena.355 | List products from kids' bedding category by descending price | URL (GOLD in PRED): __SHOPPING__/home-kitchen/bedding/kids-bedding.html?product_list_dir=desc | No top-level await. Let me use synchronous XHR instead. | **PASS** | — | — | 12 | 12 | 223,826 (186,304) | 343s |
| webarena.358 | Show me the shipping method for order number 187. | must_include: Flat Rate - Fixed | Flat Rate - Fixed | **PASS** | — | — | 4 | 4 | 53,611 (37,056) | 49s |
| webarena.359 | Show me the order date for order number 148. | fuzzy_match: 1/29/2023 | January 29, 2023 | **PASS** ᶠ | — | "January 29, 2023" == "1/29/2023" | 4 | 5 | 71,411 (10,432) | 74s |
| webarena.360 | Show me the product names for order number 148. | must_include: Bornbridge Artificial Spiral Topiary Tree - Indoor / Outdoor Topiary Trees - Artificial Outdoor Plants (2 Pack, 4' Cypress), Russound 5B… | Bornbridge Artificial Spiral Topiary Tree - Indoor / Outdoor Topiary T… | **PASS** | — | — | 5 | 7 | 98,384 (49,984) | 79s |
| webarena.361 | Show me the order statuses for order number 170 and 189. | fuzzy_match: 170: cancelled, 189: pending | 170: Canceled, 189: Pending | **PASS** ᶠ | — | "Canceled" == "cancelled", both statuses right | 4 | 4 | 54,853 (37,184) | 78s |
| webarena.362 | Show me the billing address for order number 00178. | must_include: 101 S San Mateo Dr, San Mateo, California, 94010, United States | Emma Lopez, 101 S San Mateo Dr, San Mateo, California, 94010, United S… | **PASS** | — | — | 5 | 5 | 71,996 (63,936) | 66s |
| webarena.368 | find discounted items. | fuzzy_match: N/A | N/A | **PASS** | — | — | 20 | 65 | 1,208,633 (729,600) | 1188s |
| webarena.376 | Summarize customer reviews for Amazon Echo Dot 3rd generation. | fuzzy_match: N/A | N/A | **PASS** | — | — | 9 | 17 | 153,016 (124,032) | 145s |
| webarena.384 | List the customer names who complain about the quality of EYZUTAK phone cases | must_include: Lisa Lee, Evelyn Kurver, Amanda, N Randall | Lisa Lee, Evelyn Kurver, Amanda, N Randall | **PASS** | — | — | 7 | 10 | 112,660 (88,192) | 114s |
| webarena.385 | List the customer names who thinks EYZUTAK phone cases are of good looking | must_include: Lisa Lee, MH, Misba009, Amanda, N Randall, Amazon Customer, Cally, Bethany Robertson | Lisa Lee, MH, Misba009, Amanda, Amazon Customer, Cally, Bethany Robert… | fail | **yes** | prose on the ANSWER line, not an answer | 8 | 12 | 156,815 (126,720) | 270s |
| webarena.386 | What is the rating of Ugreen lightning to 3.5mm cable. Please round to the nearest whole number | must_include: 65 \|OR\| 3 | 3 | fail | no | wrong answer | 11 | 15 | 244,870 (208,448) | 133s |
| webarena.387 | Who gave 4 or 5 stars for phone cases from EYZUTAK | must_include: MH, Misba009, Amanda, Amazon Customer, Cally, Bethany Robertson | MH, Misba009, Amanda, Amazon Customer, Cally, Bethany Robertson | **PASS** | — | — | 11 | 12 | 166,978 (153,856) | 117s |
| webarena.388 | Who gave 1 or 2 stars for phone cases from EYZUTAK | must_include: Evelyn Kurver, N Randall | Evelyn Kurver, N Randall | **PASS** | — | — | 9 | 10 | 134,496 (120,960) | 127s |
| webarena.431 | Add the product with the lowest per unit price from my open tabs to the shopping cart | page must_include: SPAAS White Taper Candles - 4 Pack \|OR\| 10 Inch Tall Candles, Scent-Free Premium Wax Candle Sticks \|OR\| 8 Hour Long Burning Whi… | SPAAS White Taper Candles - 4 Pack \| 10 Inch Tall Candles, Scent-Free… | **PASS** | — | — | 6 | 11 | 88,603 (67,456) | 127s |
| webarena.432 | Add the product with the lowest per unit price from my open tabs to the shopping cart | page must_include: V8 +Energy, Healthy Energy Drink, Steady Energy from Black and Green Tea, Pomegranate Blueberry, 8 Ounce Can ,Pack of 24 | V8 +Energy, Healthy Energy Drink, Steady Energy from Black and Green T… | **PASS** | — | — | 5 | 6 | 68,079 (60,416) | 86s |
| webarena.433 | Add the product with the lowest per unit price from my open tabs to the shopping cart | page must_include: Tazrigo 5pcs White Dental Resin Brush Pens Dental Shaping Silicone Tooth Tool | Stylus pens for Touch Screens(2 Pcs),Universal Stylus,[2-in-1] 2022 Up… | fail | no | prose on the ANSWER line, not an answer | 8 | 9 | 119,607 (96,960) | 118s |
| webarena.434 | Add the product with the lowest per unit price from my open tabs to the shopping cart | page must_include: VIVIKI Women Glitter Socks Ultrathin Transparent Tulle Lace Socks - No Show Ankle Crew Socks 3 Pack | VIVIKI Women Glitter Socks Ultrathin Transparent Tulle Lace Socks - No… | **PASS** | — | — | 8 | 14 | 163,492 (80,960) | 183s |
| webarena.435 | Add the product with the lowest per unit price from my open tabs to the shopping cart | page must_include: DP to HDMI Cable 6FT (2 Pack), Fosmon Gold Plated Displayport to HDMI Cable 1080p Full HD for PCs to HDTV, Monitor, Projector with … | DP to HDMI Cable 6FT (2 Pack), Fosmon Gold Plated Displayport to HDMI … | **PASS** | — | — | 6 | 7 | 81,447 (74,752) | 81s |
| webarena.436 | I previously ordered some a mattress foundation around Feb or March 2023 and later cancelled. Can you reorder … | field must_include: B07DFJ5XKH | Greaton Fully Assembled Split Wood Traditional Box Spring/Foundation F… | fail | no | prose on the ANSWER line, not an answer | 7 | 7 | 124,877 (107,392) | 433s |
| webarena.437 | I previously ordered some a table lamp in May 2023 and later cancelled. Can you reorder it for me? | field must_include: B072XS3F6W | Uttermost Volterra Crackled Taupe-Gray Ceramic Table Lamp | fail | no | evaluator checked the page, not the answer | 10 | 9 | 174,648 (158,144) | 140s |
| webarena.438 | I previously ordered some a TV stand sometime around sep 2022 and later cancelled. Can you reorder it for me? | field must_include: B08PVHRRB7 | Manhattan Comforts Nacka TV Stand 2.0, Oak and White | fail | no | evaluator checked the page, not the answer | 10 | 10 | 193,455 (172,160) | 202s |
| webarena.439 | I previously ordered some a cat t-shirt during 2022 and later cancelled. Can you reorder it for me? | field must_include: B0844BWS76 | 000000194 | **PASS** | — | — | 20 | 34 | 739,149 (682,944) | 323s |
| webarena.440 | I previously ordered some a make up removal kit during summer 2022 and later cancelled. Can you reorder it for… | field must_include: B0738JQG6Q | The Body Shop Camomile Makeup Removing Kit | fail | no | evaluator checked the page, not the answer | 8 | 9 | 137,009 (100,224) | 118s |
| webarena.465 | Add Tide PODS Spring Meadow Scent HE Turbo Laundry Detergent Pacs, 81 Count to my wish list | field must_include: Tide PODS Spring Meadow Scent HE Turbo Laundry Detergent Pacs, 81 Count | Tide PODS Spring Meadow Scent HE Turbo Laundry Detergent Pacs, 81 Coun… | **PASS** | — | — | 5 | 6 | 84,019 (72,640) | 79s |
| webarena.466 | Add 2 Hawaiian Bamboo Orchid Roots #zc50 - by Discount Hawaiian Gifts to my wish list | field must_include: 2 Hawaiian Bamboo Orchid Roots #zc50 - by Discount Hawaiian Gifts | 2 Hawaiian Bamboo Orchid Roots #zc50 - by Discount Hawaiian Gifts | **PASS** | — | — | 7 | 8 | 130,634 (103,232) | 228s |
| webarena.467 | Add HONGJ Hawaiian Beach Outfits Set for Mens, Summer Tropical Tree Printed Relaxed-fit Hawaii Shirts Shorts 2… | field must_include: HONGJ Hawaiian Beach Outfits Set for Mens, Summer Tropical Tree Printed Relaxed-fit Hawaii Shirts Shorts 2 Piece Suits | HONGJ Hawaiian Beach Outfits Set for Mens, Summer Tropical Tree Printe… | **PASS** | — | — | 5 | 5 | 68,566 (60,480) | 92s |
| webarena.468 | Add DkRgVNY Lace Spcling Lingerie Womens Sexy Hollow Out Underwear Bodysuit One Piece Snap Crotch Clubwear Ted… | field must_include: DkRgVNY Lace Spcling Lingerie Womens Sexy Hollow Out Underwear Bodysuit One Piece Snap Crotch Clubwear Teddy Bodysuit | DkRgVNY Lace Spcling Lingerie Womens Sexy Hollow Out Underwear Bodysui… | **PASS** | — | — | 6 | 7 | 106,742 (87,744) | 153s |
| webarena.469 | Add Light Blue Simple Summer New Low Heels Slippers for Women Fashion Chunky Heels Pointed Toe Wine Glasses Sa… | field must_include: Light Blue Simple Summer New Low Heels Slippers for Women Fashion Chunky Heels Pointed Toe Wine Glasses Sandals Comfortable Walkin… | Light Blue Simple Summer New Low Heels Slippers for Women Fashion Chun… | **PASS** | — | — | 5 | 6 | 77,048 (65,344) | 123s |
| webarena.47 | Today is 6/12/2023. Tell me how many fulfilled orders I have over the past month, and the total amount of mone… | fuzzy_match: 0 order, $0 total spend | 0, 0 | **PASS** ᶠ | — | "0, 0" == "0 order, $0 total spend" | 6 | 5 | 117,884 (91,456) | 231s |
| webarena.48 | Today is 6/12/2023. Tell me how many fulfilled orders I have over the past three days, and the total amount of… | fuzzy_match: 0 order, $0 total spend | I have all 42 orders now. The list is sorted date-descending: the newe… | fail | no | prose on the ANSWER line, not an answer | 7 | 7 | 130,174 (61,568) | 322s |
| webarena.49 | Today is 6/12/2023. Tell me how many fulfilled orders I have over the past four month, and the total amount of… | fuzzy_match: 3 orders, $845.49 total spend | 3, 845.49 | **PASS** ᶠ | — | "3, 845.49" == "3 orders, $845.49 total spend" | 8 | 7 | 125,552 (69,632) | 150s |
| webarena.50 | Today is 6/12/2023. Tell me how many fulfilled orders I have over the past year, and the total amount of money… | fuzzy_match: 24 orders, $6560.69 total spend | 21, 6560.69 | fail | no | order count wrong: said 21, answer was 24 | 5 | 5 | 79,769 (64,640) | 103s |
| webarena.506 | Buy the highest rated product from the meat substitute category within a budget between 100 and 200. | field must_include: B01CTR3DLE | Beyond Meat Beef Beefy Crumble, 5 Pound -- 2 per case. | **PASS** | — | — | 21 | 26 | 559,050 (277,056) | 344s |
| webarena.507 | Buy the highest rated product from the Ceiling light category within a budget above 1000. | field must_include: B07BVL3P1V | 40''X138" Hight Ceiling Chandelier Crystal Raindrop Chandeliers Stairc… | **PASS** | — | — | 24 | 24 | 506,270 (369,920) | 363s |
| webarena.508 | Buy the highest rated product from the NS switch pouch category within a budget under 60. | field must_include: B07116LGP6 | Multi Pouch The Legend of Zelda Breath of the Wild for Nintendo Switch | fail | **yes** | prose on the ANSWER line, not an answer | 22 | 44 | 705,731 (411,712) | 759s |
| webarena.509 | Buy the best rating product from "Men's shoe" category with at least 5 reviews and the product is least expens… | field must_include: B01J4MM3KO | Clarks Men's Tunsil Lane Oxford | fail | no | ran out of turns | 30 | 34 | 1,290,765 (1,203,648) | 570s |
| webarena.51 | Today is 6/12/2023. Tell me how many fulfilled orders I have over the past six month, and the total amount of … | fuzzy_match: 12 orders, $1603.69 total spend | 9, 1774.62 | fail | no | both wrong: 9 vs 12 orders, 1774.62 vs 1603.69 | 4 | 8 | 66,323 (52,032) | 120s |
| webarena.510 | Buy the best rating product from "Home Audio Speaker" category with at least 5 reviews and the product is leas… | field must_include: B002R5ABIW | Hiquphon Tweeters - Matched Pair (OW1-92mm Linn) | fail | no | ran out of turns | 30 | 35 | 870,055 (821,056) | 461s |
| webarena.511 | Add a laundry detergent to my wish list. | field must_include: laundry, detergent | Tide PODS Spring Meadow Scent HE Turbo Laundry Detergent Pacs, 81 Coun… | **PASS** | — | — | 7 | 8 | 104,243 (95,552) | 76s |
| webarena.512 | Add a toothpaste to my wish list. | field must_include: toothpaste | Baking Soda Whitening Toothpaste,Intensive Stain Removal Whitening Too… | **PASS** | — | — | 6 | 7 | 80,597 (73,088) | 88s |
| webarena.513 | Add a chair to my wish list. | field must_include: chair | XCJ Comfortable Task ChairHome Office Chair, Modern Faux Fur Home Offi… | **PASS** | — | — | 4 | 5 | 56,477 (49,216) | 72s |
| webarena.514 | Add a white desk to my wish list. | field must_include: white, desk | Techni Mobili Rolling Writing Height Adjustable Desktop and Moveable S… | **PASS** | — | — | 5 | 5 | 73,847 (59,904) | 241s |
| webarena.515 | Add a white computer desk to my wish list. | field must_include: white, computer, desk | EMMA + OLIVER White Computer Desk with Keyboard Tray and Drawers | **PASS** | — | — | 5 | 5 | 65,582 (48,832) | 62s |
| webarena.516 | Add this product to my wishlist | field must_include: Elmwood Inn Fine Teas, Orange Vanilla Caffeine-free Fruit Infusion, 16-Ounce Pouch | Elmwood Inn Fine Teas, Orange Vanilla Caffeine-free Fruit Infusion, 16… | fail | **yes** | prose on the ANSWER line, not an answer | 5 | 6 | 78,091 (67,392) | 81s |
| webarena.517 | Add this product to my wishlist | field must_include: Skinit Decal Gaming Skin Compatible with Xbox One S Console and Controller Bundle - Officially Licensed NFL Baltimore Ravens Desig… | Skinit Decal Gaming Skin Compatible with Xbox One S Console and Contro… | fail | **yes** | prose on the ANSWER line, not an answer | 3 | 4 | 39,394 (33,536) | 89s |
| webarena.518 | Add this product to my wishlist | field must_include: Sceptre E195BD-SRR 19-Inch 720P LED TV, True Black (2017) | Sceptre E195BD-SRR 19-Inch 720P LED TV, True Black (2017) has been add… | fail | **yes** | prose on the ANSWER line, not an answer | 3 | 3 | 36,884 (21,504) | 52s |
| webarena.519 | Add this product to my wishlist | field must_include: iPhone 13 Pro Max Case, Neon Turtle iPhone 13 Pro Max Cases, Tempered Glass Back+Soft Silicone TPU Shock Protective Case for Apple… | iPhone 13 Pro Max Case, Neon Turtle iPhone 13 Pro Max Cases, Tempered … | fail | **yes** | prose on the ANSWER line, not an answer | 3 | 2 | 38,011 (33,856) | 55s |
| webarena.520 | Add this product to my wishlist | field must_include: Magnetic Metal Stainless Steel D-pads Kits Directional Pad Replacement Parts for Xbox One Elite Controller, Elite Series 2, Xbox O… | Magnetic Metal Stainless Steel D-pads Kits Directional Pad Replacement… | fail | **yes** | prose on the ANSWER line, not an answer | 3 | 2 | 36,044 (33,024) | 47s |
| webarena.521 | Subscribe to the newsletter of OneStopMarket | field exact_match: true | subscribed | **PASS** | — | — | 11 | 16 | 202,242 (170,432) | 376s |
| webarena.528 | Draft a refund message via their "contact us" form for the phone screen protector I bought March 2023. It brok… | field must_include: refund, it broke after three days of use, 000000180, 12.99 | 000000180, 12.99 | fail | **yes** | evaluator checked the page, not the answer | 8 | 13 | 148,312 (47,936) | 149s |
| webarena.529 | Draft a refund message via their "contact us" form for the bluetooth speaker I bought Feb 2023. It broke after… | field must_include: refund, it broke after three days of use, 000000148, 169.95 | 000000161, 56.35 | fail | no | evaluator checked the page, not the answer | 9 | 9 | 195,680 (176,256) | 120s |
| webarena.530 | Draft a refund message via their "contact us" form for the kitchen organizer I bought around Feb 2023. It brok… | field must_include: refund, it broke after three days of use, 000000161, 68.88 | 68.88 | fail | **yes** | evaluator checked the page, not the answer | 12 | 18 | 322,607 (280,256) | 209s |
| webarena.531 | Draft a refund message via their "contact us" form for the phone case I bought March 2023. It broke after thre… | field must_include: refund, it broke after three days of use, 000000180, $12.99 | Order ID: 000000180, reason: the phone case broke after three days of … | fail | **yes** | prose on the ANSWER line, not an answer | 11 | 15 | 203,432 (141,376) | 163s |
| webarena.532 | Draft a refund message via their "contact us" form for the PS3 remote controller I bought early 2023. It broke… | field must_include: refund, it broke after three days of use, 000000180, 1.63 | 1.63 | fail | no | evaluator checked the page, not the answer | 12 | 13 | 290,235 (262,720) | 256s |
| webarena.571 | I recently moved, my address is 231 Willow Way, Suite 100, Chicago, IL, 60601, update my information on OneSto… | field must_include: 231 Willow Way, Suite 100, Chicago, Illinois, 60601 \| field must_include: 231 Willow Way, Suite 100, Chicago, Illinois, 60601 | 231 Willow Way, Suite 100, Chicago, Illinois, 60601, United States | **PASS** | — | — | 8 | 17 | 132,169 (109,312) | 119s |
| webarena.572 | I recently moved, my address is 654 Aspen Road, House #3, Boston, MA, 02110, update my information on OneStopS… | field must_include: 654 Aspen Road, House #3, Boston, Massachusetts, 02110 \| field must_include: 654 Aspen Road, House #3, Boston, Massachusetts, 021… | Address updated to 654 Aspen Road, House #3, Boston, Massachusetts, 02… | **PASS** | — | — | 9 | 14 | 140,036 (117,696) | 102s |
| webarena.573 | I recently moved, my address is 987 Sycamore Circle, Philadelphia, PA, 19102, update my information on OneStop… | field must_include: 987 Sycamore Circle, Philadelphia, Pennsylvania, 19102 \| field must_include: 987 Sycamore Circle, Philadelphia, Pennsylvania, 191… | 987 Sycamore Circle Philadelphia, Pennsylvania, 19102 United States | **PASS** | — | — | 9 | 14 | 172,122 (101,056) | 153s |
| webarena.574 | I recently moved, my address is 111 Magnolia Path, Atlanta, GA, 30303, update my information on OneStopShoppin… | field must_include: 111 Magnolia Path, Atlanta, Georgia, 30303 \| field must_include: 111 Magnolia Path, Atlanta, Georgia, 30303 | 111 Magnolia Path, Atlanta, GA, 30303 | **PASS** | — | — | 11 | 17 | 209,038 (143,808) | 164s |
| webarena.575 | I recently moved, my address is 222 Redwood Rise, Suite 300, Seattle, WA, 98101, update my information on OneS… | field must_include: 222 Redwood Rise, Suite 300, Seattle, Washington, 98101 \| field must_include: 222 Redwood Rise, Suite 300, Seattle, Washington, 9… | 222 Redwood Rise Suite 300 Seattle, Washington, 98101 United States | **PASS** | — | — | 8 | 13 | 125,771 (52,864) | 151s |
| webarena.585 | Rate my recent purchase of floor lamp with 5 stars, using my nickname Emma Lopez? | field must_include: 100 \| field must_include: Emma Lopez | You submitted your review for moderation. | **PASS** | — | — | 21 | 29 | 495,601 (312,896) | 341s |
| webarena.586 | Rate my recent purchase of Jiffy Corn Muffin Cornbread Mix with 4 stars, using my nickname ShoppingEmma? | field must_include: 80 \| field must_include: ShoppingEmma | You submitted your review for moderation. | **PASS** | — | — | 12 | 20 | 229,175 (196,800) | 210s |
| webarena.587 | Rate my recent purchase of PS3 Remote Controllers with 3 stars, using my nickname GamingEmma? | field must_include: 60 \| field must_include: GamingEmma | You submitted your review for moderation. | **PASS** | — | — | 26 | 42 | 711,659 (514,048) | 526s |
| webarena.588 | Rate my recent purchase of Foundation For Mattress With Frame Set with 1 stars, using my nickname ShoppingEmma… | field must_include: 20 \| field must_include: ShoppingEmma | You submitted your review for moderation. | **PASS** | — | — | 11 | 22 | 323,079 (203,200) | 288s |
| webarena.589 | Rate my recent purchase of Mini Wireless Bluetooth Speaker with 2 stars, using my nickname SimpleEmma? | field must_include: 40 \| field must_include: SimpleEmma | You submitted your review for moderation. | **PASS** | — | — | 7 | 13 | 133,261 (89,280) | 254s |
| webarena.653 | Fill the "contact us" form in the site for a refund on the phone screen protector I bought, stating that it br… | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: refund, it broke after three days of use, 000000180, B087QJN9W1 | B087QJN9W1 | fail | **yes** | wrong answer | 8 | 9 | 116,011 (36,928) | 140s |
| webarena.654 | Fill the "contact us" form in the site for a refund on the bluetooth speaker I bought, stating that it broke a… | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: refund, it broke after three days of use, 161, B09P7BFL4H | Contact form filled (not submitted) requesting a refund for the wangli… | fail | **yes** | prose on the ANSWER line, not an answer | 7 | 10 | 144,469 (94,528) | 127s |
| webarena.655 | Fill the "contact us" form in the site for a refund on the iphone case I bought, stating that it broke after j… | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: refund, it broke after three days of use, 180, B087QJN9W1 | B087QJN9W1 | fail | no | wrong answer | 8 | 8 | 129,146 (59,520) | 415s |
| webarena.656 | Fill the "contact us" form in the site for a refund on the remote controller I bought, stating that it broke a… | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: refund, it broke after three days of use, 180, B0041MSF2S | Contact form filled (unsubmitted) with a refund request stating the re… | fail | **yes** | page lacked 'it broke after three days of use' | 8 | 9 | 113,879 (63,872) | 148s |
| webarena.657 | Fill the "contact us" form in the site for a refund on the speaker I bought, stating that it broke after just … | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: refund, broke after three days of use, 148, B003FVW3VA | B003FVW3VA | fail | **yes** | page lacked 'broke after three days of use' | 9 | 9 | 136,109 (114,816) | 120s |
| webarena.792 | Buy the highest rated product from the Beauty & Personal Care category within a budget under 20. | fuzzy_match: N/A | 13 products tie at 100% rating with 10 reviews — review count doesn't … | fail | no | prose on the ANSWER line; never completed the purchase | 16 | 16 | 504,847 (182,912) | 2029s |
| webarena.793 | Buy the highest rated product from the Men clothing category within a budget above 50 but under 129.99. | fuzzy_match: N/A | Price filter works — 502 items in $50.00–$129.98 (note: site shows the… | fail | no | prose on the ANSWER line; never completed the purchase | 11 | 11 | 291,444 (240,960) | 564s |
| webarena.794 | Change the delivery address for my most recent order to 4000 Forbes Ave, Pittsburgh, PA. | fuzzy_match: N/A | N/A | **PASS** | — | — | 8 | 8 | 175,741 (104,896) | 206s |
| webarena.795 | Change the delivery address for my most recent order to 6726 McPherson Blvd, Pittsburgh, PA. | fuzzy_match: N/A | N/A | **PASS** | — | — | 6 | 9 | 118,690 (75,072) | 123s |
| webarena.796 | Change the delivery address for my most recent order to 155 5th Street, San Francisco, CA. | fuzzy_match: N/A | N/A | **PASS** | — | — | 7 | 10 | 134,811 (91,008) | 111s |
| webarena.797 | Change the delivery address for my most recent order to 3 Oxford St, Cambridge, MA. | fuzzy_match: N/A | Order addresses are stored per-order (old orders show San Mateo; the a… | fail | no | prose on the ANSWER line; address never changed | 9 | 11 | 213,322 (145,408) | 585s |
| webarena.798 | Change the delivery address for my most recent order to 77 Massachusetts Ave, Cambridge, MA. | fuzzy_match: N/A | N/A | **PASS** | — | — | 12 | 16 | 276,447 (196,608) | 227s |
| webarena.96 | Tell me the status of my latest order and when will it arrive | fuzzy_match: The last order was canceled. It will never arrive. | Pending, N/A | fail | no | said "Pending"; the order was cancelled | 4 | 3 | 51,130 (32,768) | 58s |
| webarena.689 | Draft an email to the shop owner via their contact us function for a coupon as I am a loyal customer | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: coupon, I am a loyal customer | drafted | **PASS** | — | — | 4 | 5 | 74,623 (61,376) | 93s |
| webarena.690 | Draft an email to the shop owner via their contact us function for a coupon as they promised me a coupon last … | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: coupon, promised | drafted | **PASS** | — | — | 6 | 7 | 85,280 (75,968) | 123s |
| webarena.691 | Draft an email to the shop owner via their contact us function for a coupon as I plan to make a bulk purchase | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: coupon, bulk purchase | Hello, I am planning to make a bulk purchase from your store and would… | **PASS** | — | — | 4 | 5 | 74,738 (61,120) | 98s |
| webarena.692 | Draft an email to the shop owner via their contact us function for a coupon as I am a student | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: coupon, student | Drafted (unsubmitted) email in the contact form to the shop owner aski… | **PASS** | — | — | 7 | 6 | 92,993 (87,040) | 93s |
| webarena.693 | Draft an email to the shop owner via their contact us function for a coupon as my refund is suppoed to be repl… | URL (GOLD in PRED): __SHOPPING__/contact \| field must_include: coupon, refund | Drafted an email via the Contact Us form to the shop owner requesting … | **PASS** | — | — | 7 | 9 | 105,580 (80,448) | 133s |

ᶠ = counted as a pass by the hand judging pass, not by the harness.


## What it was good at

Task types with three or more instances, 60%+ solved.

| task type | solved |
|---|---|
| Tell me when I last ordered my {{description}}? | 5/5 (100%) |
| List products from {{product_category}} category by {{order}} price | 5/5 (100%) |
| Show me the {{info}} for order number {{order_number}}. | 5/5 (100%) |
| Add {{product}} to my wish list | 5/5 (100%) |
| Add a {{product}} to my wish list. | 5/5 (100%) |
| I recently moved, my address is {{address}}, update my information on OneStopShopping accordingly | 5/5 (100%) |
| Rate my recent purchase of {{product}} with {{num_star}} stars, using my nickname {{nickname}}? | 5/5 (100%) |
| Draft an email to the shop owner via their contact us function for a coupon as {{reason}} | 5/5 (100%) |
| I have a lot of Nintendo Switch game cards now, help me find the best storage option to fit all {{num}} cards | 4/5 (80%) |
| What is the price range for products from {{brand}}? | 4/5 (80%) |
| I want to browse the products in the {{category}} category | 4/5 (80%) |
| Show me products under ${{price}} in "{{product_category}}" category | 4/5 (80%) |
| Search for "{{keyword}}" | 4/5 (80%) |
| Add the product with the lowest per unit price from my open tabs to the shopping cart | 4/5 (80%) |
| Change the delivery address for my most recent order to {{address}}. | 4/5 (80%) |
| List out reviewers, if exist, who mention about {{description}} | 4/6 (67%) |
| Show the least expensive {{product}} with a minimum storage capacity of {{min_storage}}. | 2/3 (67%) |
| What is the {{option}} configuration of the {{product}} I bought {{time}} | 3/5 (60%) |
| Tell me the total cost of my latest {{status}} order? | 3/5 (60%) |
| I am doing a market survey for one stop market, show me the most expensive product from {{product_category}} category | 3/5 (60%) |
| Show the most recent {{status}} order | 3/5 (60%) |

## What it was bad at

Task types with three or more instances, under 60% solved.

| task type | solved |
|---|---|
| How much I spent on {{category}} shopping during {{time}} | 0/5 (0%) |
| Add this product to my wishlist | 0/5 (0%) |
| Draft a refund message via their "contact us" form for the {{product}} I bought {{time}}. It broke after three days of u… | 0/5 (0%) |
| Fill the "contact us" form in the site for a refund on the {{product}} I bought, stating that it broke after just three … | 0/5 (0%) |
| How much I spend {{time}} on shopping at One Stop Market? | 1/4 (25%) |
| Show me the "{{product}}" listings by {{sorting_order}}. | 1/5 (20%) |
| I previously ordered some {{product}} {{time}} and later cancelled. Can you reorder it for me? | 1/5 (20%) |
| What is the price range of {{product}} in the One Stop Market? | 1/3 (33%) |
| How much refund I should expect from my order canlled in {{time}}, including shipping fee | 1/3 (33%) |
| What are the main criticisms of this product? Please extract the relevant sentences. | 2/5 (40%) |
| Get the order number of my most recent {{status}} order | 2/5 (40%) |
| Today is 6/12/2023. Tell me how many fulfilled orders I have {{period}}, and the total amount of money I spent. | 2/5 (40%) |
| Buy the highest rated product from the {{product_category}} category within a budget {{dollar_value}}. | 2/5 (40%) |

## Why the 78 failures happened

| cause | count | share of all failures |
|---|---|---|
| stopped mid-investigation and put reasoning on the ANSWER line | 37 | 47% |
| wrong answer | 18 | 23% |
| arithmetic: aggregated a total and got a near-miss | 9 | 12% |
| scored on page state, not on the answer | 7 | 9% |
| answered when the reference was N/A | 3 | 4% |
| hit the 30-turn ceiling | 2 | 3% |
| page content missing a required phrase | 2 | 3% |

## Reading this

The agent is reliable at **single-fact lookup** — read one page, report one
value. It is unreliable at three things, and they account for most of the
losses.

**Aggregation.** Anything of the form "how much did I spend across period X"
requires paging through order history and summing. It finds the right orders
and then drops or double-counts a row: 265.69 against 260.69, 47.41 against
32.41. No prompt fixes arithmetic over paginated data.

**Stopping cleanly.** A large share of failures are episodes that never
produced an answer at all -- the model emitted its own reasoning on the
ANSWER line while still mid-investigation. The answer was often findable; the
episode simply ended in the wrong shape.

**Exact strings.** Several tasks were solved and then lost on punctuation:
`16*24` against `16x24`, `January 29, 2023` against `1/29/2023`. The judging
pass recovers these for fuzzy_match tasks; for string_match and program_html
there is no recovery, and the task statement sometimes contradicts the
requirement outright -- 656 and 657 were told to write "broke after *just*
three days" while the evaluator demanded the phrase without "just".
