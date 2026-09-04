# WebArena — shopping admin (Magento back office), full task list

Model **z-ai/glm-5.3-flash** via OpenRouter, driving the abt toolkit through
BrowserGym. 30-turn ceiling, one fresh agent process per task.

## Result

| | |
|---|---|
| tasks scored | 182 |
| passed, as the harness scored it | **95 — 52.2%** |
| recovered by the fuzzy judging pass | +13 |
| **final** | **108 — 59.3%** |
| total ops | 3,736 |
| total turns | 2,564 |
| total tokens | 72,962,196 (57,100,928 cached, 78%) |
| total wall time | 21.1 h |
| mean per task | 21 ops, 14 turns, 400,891 tokens, 417 s |

`fuzzy_match` tasks need a GPT-4 judge and no key was set, so 22 episodes were
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
a wrong value or the wrong target.

| | count | share |
|---|---|---|
| credited by the harness | 108 | **59.3%** |
| correct but uncredited | 10 | 5.5% |
| genuinely incorrect | 55 | 30.2% |
| unclear from the record | 0 | 0.0% |
| **did the task** | **118** | **64.8%** |

So the benchmark scores **59.3%** and the agent did the asked-for work in
**64.8%** of episodes. The gap is 10 episodes where the work was right and
the string, subreddit, or URL the harness checked was not.

The 55 genuinely incorrect episodes are the honest failures: wrong values,
wrong targets, and investigations that stopped before finding the answer.

## Every task

| task | question | answer required | answer given | result | correct | why | turns | ops | tokens (cached) | time |
|---|---|---|---|---|---|---|---|---|---|---|
| webarena.0 | What is the top-1 best-selling product in 2022 | exact_match: Quest Lumaflex™ Band | Quest Lumaflex™ Band | **PASS** | — | — | 17 | 26 | 352,519 (243,584) | 442s |
| webarena.1 | What is the top-1 best-selling brand in Quarter 1 2022 | exact_match: Sprite | Both reports show 0 even for all of 2022 — either my params are wrong or the aggregate ta… | fail | no | no usable report data found | 21 | 39 | 716,150 (564,480) | 710s |
| webarena.2 | What is the top-1 best-selling product type in Quarter 1 2022 | exact_match: Yoga ball | Simple | fail | no | wrong answer | 26 | 45 | 820,274 (722,112) | 1062s |
| webarena.3 | What are the top-2 best-selling product in 2022 | must_include: ['Quest Lumaflex™ Band', 'Sprite Stasis Ball 65 cm'] | Quest Lumaflex™ Band, Cruise Dual Analog Watch | fail | no | only 1 of 2 required products named | 25 | 32 | 630,083 (459,072) | 708s |
| webarena.4 | What are the top-3 best-selling product in Jan 2023 | must_include: ['Impulse Duffle', 'Overnight Duffle', 'Hawkeye Yoga Short-32-Blue'] | Hawkeye Yoga Short, Overnight Duffle, Impulse Duffle | fail | **yes** | named the right 3 products; left off the internal size/color suffix Magento appends to variant names | 18 | 27 | 458,374 (350,464) | 659s |
| webarena.5 | What is the top-1 best-selling product type in Jan 2023 | exact_match: Duffle | Simple Product | fail | no | wrong answer | 29 | 50 | 844,051 (779,584) | 711s |
| webarena.6 | What are the top-5 best-selling product in 2023 | must_include: ['Sprite Yoga Strap 6 foot', 'Overnight Duffle', 'Ida Workout Parachute Pant-29-Purple', 'Hawkeye Yoga Short-32-Blu… | Sprite Yoga Strap 6 foot, Overnight Duffle, Sparta Gym Tank-XL-Green, Hawkeye Yoga Short-… | fail | no | wrong products named | 15 | 17 | 253,219 (165,760) | 465s |
| webarena.11 | Tell me the the number of reviews that our store received by far that mention term "disappoint… | must_include: ['6'] | 6 | **PASS** | — | — | 15 | 17 | 257,262 (225,920) | 251s |
| webarena.12 | Tell me the the number of reviews that our store received by far that mention term "satisfied" | must_include: ['2'] | 2 | **PASS** | — | — | 13 | 25 | 257,346 (219,264) | 321s |
| webarena.13 | Tell me the the number of reviews that our store received by far that mention term "decent" | must_include: ['2'] | 2 | **PASS** | — | — | 14 | 19 | 242,139 (168,640) | 269s |
| webarena.14 | Tell me the the number of reviews that our store received by far that mention term "not useful" | must_include: ['0'] | 0 | **PASS** | — | — | 10 | 17 | 241,678 (58,240) | 518s |
| webarena.15 | Tell me the the number of reviews that our store received by far that mention term "best" | must_include: ['2'] | 2 | **PASS** | — | — | 10 | 13 | 164,851 (96,768) | 404s |
| webarena.41 | List the top 1 search terms in my store | exact_match: hollister | hollister | **PASS** | — | — | 2 | 2 | 25,226 (11,136) | 58s |
| webarena.42 | List the top 2 search terms in my store | must_include: ['hollister', 'Joust Bag'] | hollister, Joust Bag | **PASS** | — | — | 2 | 1 | 23,833 (0) | 38s |
| webarena.43 | List the top 3 search terms in my store | must_include: ['hollister', 'Joust Bag', 'Antonia Racer Tank'] | hollister, Joust Bag, Circe | fail | no | 2 of 3 terms right, one wrong | 2 | 1 | 23,526 (21,760) | 32s |
| webarena.62 | Which customer has completed the most number of orders in the entire history? | must_include: ['Jane Smith'] | I need page 2 of the Orders grid (308 orders, 200 shown) to finish the Complete-status ta… | fail | no | never finished the lookup | 15 | 23 | 405,210 (172,416) | 1055s |
| webarena.63 | Which customer(s) has completed the second most number of orders in the entire history? | must_include: ['Adam Garcia', 'Michael Nguyen', 'Sarah Miller'] | Grace Nguyen, Samantha Jones, Sarah Miller | fail | no | only 1 of the required names present | 21 | 30 | 941,267 (791,872) | 993s |
| webarena.64 | Which customer has placed 2 orders in the entire history? | must_include: ['Lisa Kim', 'Lisa Green', 'Julia Williams', 'Brian Smith', 'Alexander Thomas'] | The third span is the customer sidebar tab (`admin__page-nav-item`). Let me click it via … | fail | no | episode ended mid-investigation without an answer | 26 | 34 | 1,091,337 (690,240) | 1099s |
| webarena.65 | Which customer has completed the fifth most number of orders in the entire history? | must_include: ['Jane Doe'] | Matt Baker | fail | no | wrong customer | 29 | 45 | 1,000,279 (705,536) | 866s |
| webarena.77 | What is the total count of Pending reviews amongst all the reviews? | must_include: ['5'] | 5 | **PASS** | — | — | 5 | 7 | 79,585 (59,392) | 65s |
| webarena.78 | What is the total count of Approved reviews amongst all the reviews? | must_include: ['346'] | 345 | fail | no | off by one on the count | 6 | 7 | 96,400 (57,600) | 118s |
| webarena.79 | What is the total count of Not Approved reviews amongst all the reviews? | must_include: ['0'] | 0 | **PASS** | — | — | 15 | 22 | 292,943 (273,600) | 164s |
| webarena.94 | Telll me the grand total of invoice 000000001. | must_include: ['36.39'] | 36.39 | **PASS** | — | — | 9 | 9 | 137,078 (102,592) | 144s |
| webarena.95 | Telll me the grand total of invoice 000000002. | must_include: ['39.64'] | 39.64 | **PASS** | — | — | 7 | 7 | 98,176 (80,896) | 75s |
| webarena.107 | Presents the monthly count of successful orders from May to December 2022 in MM:COUNT format | fuzzy_match: ['May: 8 orders', 'June: 13 orders', 'July: 9 orders', 'August: 8 orders', 'Sepetember: 10 orders', 'October: 4 orde… | 05:8, 06:13, 07:9, 08:8, 09:10, 10:4, 11:5, 12:10 | **PASS** ᶠ | — | matches | 14 | 26 | 291,274 (207,360) | 416s |
| webarena.108 | Presents the monthly count of successful orders 01/2023-05/2023 in MM:COUNT format | fuzzy_match: ['January: 12 orders', 'Feburary: 7 orders', 'March: 5 orders', 'April: 9 orders', 'May: 5 orders'] | The report ran for all statuses (Any): 1/2023:12, 2/2023:7, 3/2023:5, 4/2023:10, 5/2023:7… | fail | no | wrong answer | 6 | 14 | 113,032 (74,624) | 585s |
| webarena.109 | Presents the monthly count of successful orders from Jan to December 2022 in MM:COUNT format | fuzzy_match: ['January: 11 orders', 'Feburary: 16 orders', 'March: 14 orders', 'April: 7 orders', 'May: 8 orders', 'June: 13 orde… | 01:11, 02:17, 03:14, 04:7, 05:8, 06:6, 07:0, 08:0, 09:0, 10:0, 11:0, 12:0 | fail | no | wrong answer | 29 | 50 | 819,245 (707,968) | 925s |
| webarena.110 | Presents the monthly count of successful orders from Jan to Nov 2022 in MM:COUNT format | fuzzy_match: ['January: 11 orders', 'Feburary: 16 orders', 'March: 14 orders', 'April: 7 orders', 'May: 8 orders', 'June: 13 orde… | 01:11, 02:16, 03:14, 04:7, 05:8, 06:13, 07:9, 08:8, 09:10, 10:4, 11:5 | **PASS** ᶠ | — | matches | 22 | 34 | 583,913 (482,880) | 1022s |
| webarena.111 | Presents the monthly count of successful orders from Feb to Nov 2022 in MM:COUNT format | fuzzy_match: ['Feburary: 16 orders', 'March: 14 orders', 'April: 7 orders', 'May: 8 orders', 'June: 13 orders', 'July: 9 orders',… | With status="Complete" the April count is 7; with "Any" it's 8. One April order has a dif… | fail | no | wrong answer | 14 | 22 | 309,022 (125,440) | 598s |
| webarena.112 | Show me the customers who have expressed dissatisfaction with Circe fleece? | exact_match: Hannah Lim | Hannah Lim | **PASS** | — | — | 12 | 12 | 204,114 (127,168) | 194s |
| webarena.113 | Show me the customers who have expressed dissatisfaction with Olivia zip jacket? | must_include: ['Emma Lopez', 'Seam Miller'] | Emma, seam miller | fail | **yes** | named the right two customers; answer was lower-case and comma-joined instead of the exact-cased strings the check wants | 18 | 19 | 330,624 (203,520) | 455s |
| webarena.114 | Show me the customers who have expressed dissatisfaction with Antonia racer tank? | must_include: ['Shaunte', 'Merrie'] | Merrie, Shaunte | **PASS** | — | — | 12 | 18 | 228,532 (157,184) | 244s |
| webarena.115 | Show me the name of the customers who have expressed dissatisfaction with Chloe tank | fuzzy_match: N/A | Teofila | fail | no | wrong answer | 10 | 17 | 176,253 (147,456) | 201s |
| webarena.116 | Show me the name of the customers who have expressed dissatisfaction with tanks products? | must_include: ['Alexander', 'Carma', 'Dominic', 'Merrie', 'Monroe', 'Scotty', 'Shaunte', 'Teofila', 'Valorie'] | Dominic, Monroe, Scotty, Teofila, Shaunte, Valorie | fail | no | only 6 of 9 required names present | 19 | 19 | 465,676 (357,568) | 671s |
| webarena.119 | Tell me the reasons why customers like Antonia Racer Tank | fuzzy_match: ['Its color and style is good'] | it's colorful, looks kinda cute under my exercise tanks, and it's very stylish for yoga o… | **PASS** ᶠ | — | matches | 9 | 17 | 149,763 (123,456) | 248s |
| webarena.120 | Tell me the reasons why customers like Ana Running Short | fuzzy_match: ['It is comfortable'] | lightweight, comfy | **PASS** ᶠ | — | matches | 10 | 11 | 171,324 (145,472) | 301s |
| webarena.121 | Tell me the reasons why customers like Circe hooded fleece | fuzzy_match: ['Warm and comfortable. True to size.'] | incredibly soft and cozy fleece material, the hood for extra warmth, true-to-size fit, lo… | **PASS** ᶠ | — | matches | 11 | 12 | 169,069 (83,392) | 181s |
| webarena.122 | Tell me the reasons why customers like Olivia zip jacket | fuzzy_match: ['Lightweight, comfortable and stylish. Good design and details.'] | lightweight and comfortable, 1/4 zip for easy temperature control, versatile enough to dr… | **PASS** ᶠ | — | matches | 9 | 11 | 143,063 (88,640) | 223s |
| webarena.123 | Tell me the reasons why customers like Circe's products | fuzzy_match: ['Warm and comfortable. True to size.'] | incredibly soft and cozy fleece material, hood for extra warmth, true-to-size fit and lon… | **PASS** ᶠ | — | matches | 14 | 16 | 280,138 (245,696) | 236s |
| webarena.127 | What brands appear most frequently among the top search terms? | must_include: ['Hollister', 'Joust', 'Antonia'] | hollister, nike | fail | no | wrong brands named | 3 | 2 | 37,572 (16,128) | 126s |
| webarena.128 | What's the total number of items sold in the most recent 2 orders? | must_include: ['9'] | 8 | fail | no | off by one on the count | 5 | 4 | 87,693 (32,256) | 146s |
| webarena.129 | What's the total number of items sold in the most recent 4 orders? | must_include: ['16'] | The Orders grid's four most recent orders (by Purchase Date) are #180, #184, #23, #220. L… | fail | no | never produced a count | 5 | 8 | 143,331 (39,168) | 344s |
| webarena.130 | What's the total number of items sold in the most recent 5 orders? | must_include: ['18'] | 17 | fail | no | off by one on the count | 14 | 13 | 439,692 (303,104) | 819s |
| webarena.131 | What's the total number of items sold in the most recent 7 orders? | must_include: ['25'] | 19 | fail | no | off by six on the count | 7 | 11 | 138,798 (45,120) | 535s |
| webarena.157 | Show all customers | URL (GOLD in PRED): /admin/customer/index/ | 70 | **PASS** | — | — | 8 | 8 | 125,222 (100,032) | 136s |
| webarena.183 | Give me the SKU of the products that have 10 units left | fuzzy_match: N/A | N/A | **PASS** | — | — | 30 | 62 | 2,198,819 (1,984,704) | 2235s |
| webarena.184 | Give me the name of the products that have 0 units left | exact_match: Sinbad Fitness Tank | The filter inputs are `#gridLowstock_filter_qty_from` (el_85) and `#gridLowstock_filter_q… | fail | no | never finished the lookup | 12 | 16 | 417,995 (253,440) | 637s |
| webarena.185 | Give me the brand of the products that have 3 units left | must_include: ['Eos', 'Minerva'] | N/A | fail | no | said N/A on an answerable task | 28 | 38 | 912,937 (643,200) | 2057s |
| webarena.186 | Give me the product names and the sizes of the products that have 2-3 units left | fuzzy_match: ['Eos V-Neck Hoodie: S', 'Minera Luma Tech V-Tee: XS'] | Eos V-Neck Hoodie-S-Blue, S, Troy Yoga Short-36-Black, 36 | fail | no | wrong answer | 25 | 28 | 1,238,835 (1,038,912) | 1004s |
| webarena.187 | Give me the SKU of the products that have 1-3 units left | must_include: ['WH11-S-Blue', 'WS08-XS-Blue'] | WH11-S-Blue | fail | no | only 1 of 2 required SKUs present | 13 | 17 | 343,644 (306,176) | 224s |
| webarena.193 | Get the total payment amount of the last 2 completed orders | must_include: ['182.4'] | 182.40 | **PASS** | — | — | 10 | 15 | 270,326 (227,008) | 205s |
| webarena.194 | Get the total payment amount of the last 5 completed orders | must_include: ['555.2'] | 555.20 | **PASS** | — | — | 5 | 6 | 107,802 (20,736) | 318s |
| webarena.195 | Get the total payment amount of the last 5 pending orders | must_include: ['885.4'] | 577.80 | fail | no | wrong total | 11 | 15 | 380,492 (280,704) | 292s |
| webarena.196 | Compare the payment difference of the last 4 cancelled orders and completed orders | must_include: ['194.25'] | 210.2 | fail | no | wrong total | 6 | 8 | 100,802 (47,104) | 312s |
| webarena.197 | Get the total payment amount of the last 5 non-cancelled orders | must_include: ['778.2'] | 718.20 | fail | no | wrong total | 6 | 7 | 134,060 (76,736) | 270s |
| webarena.198 | Get the customer name of the most recent cancelled order | exact_match: Lily Potter | Sarah Miller | fail | no | wrong customer | 6 | 7 | 135,374 (86,400) | 189s |
| webarena.199 | Get the order ID of the newest pending order | must_include: ['299'] | 000000065 | fail | no | wrong order id | 12 | 15 | 354,301 (308,160) | 314s |
| webarena.200 | Get the billing name of the oldest complete order | exact_match: John Lee | John Lee | **PASS** | — | — | 24 | 27 | 694,363 (342,784) | 447s |
| webarena.201 | Get the customer name of the earliest fraud suspect order | fuzzy_match: N/A | N/A | **PASS** | — | — | 28 | 45 | 1,248,572 (1,137,088) | 944s |
| webarena.202 | Get the date of the most recent canlled order | fuzzy_match: ['May 23 2023'] | May 31, 2023 | fail | no | wrong answer | 7 | 9 | 155,705 (131,136) | 164s |
| webarena.203 | Get the purchase date and order id of the most recent pending order | fuzzy_match: ['order id: 000000299', 'purchase date: May 31, 2023'] | May 28, 2023 6:43:55 AM, 000000065 | fail | no | wrong answer | 13 | 13 | 288,360 (263,104) | 214s |
| webarena.204 | Get the product name and discounted price (low to high) of the most recent completed order | fuzzy_match: ['Rapha Sports Short: $35', 'Thorpe Track Pant: $54.4', 'Mach Street Sweatshirt: $62'] | Ida Workout Parachute Pant 38.40, Proteus Fitness Jackshirt 45.00 | fail | no | wrong answer | 18 | 20 | 475,440 (422,592) | 431s |
| webarena.208 | Find the customer name and email with phone number +1 2058812302 | must_include: ['John Smith', 'john.smith.xyz@gmail.com'] | John Smith, john.smith.xyz@gmail.com | **PASS** | — | — | 3 | 2 | 40,768 (33,792) | 61s |
| webarena.209 | Find the customer name and email with phone number 2137418080 | must_include: ['Jennifer White', 'jennifer.white@yahoo.com'] | Jennifer White, jennifer.white@yahoo.com | **PASS** | — | — | 2 | 2 | 33,248 (21,760) | 46s |
| webarena.210 | Find the customer name and email with phone number 2065555555 | must_include: ['Adam Garcia', 'gamingpro456@gmail.com'] | Adam Garcia, gamingpro456@gmail.com | **PASS** | — | — | 10 | 14 | 211,991 (148,480) | 674s |
| webarena.211 | Find the customer name and email with phone number 8015551212 | must_include: ['Sean Miller', 'sean.miller@gmail.com'] | Sean Miller, sean.miller@gmail.com | **PASS** | — | — | 3 | 3 | 43,275 (22,976) | 71s |
| webarena.212 | Find the customer name and email with phone number 555-229-3326 | must_include: ['Veronica Costello', 'roni_cost@example.com'] | Veronica Costello, roni_cost@example.com | **PASS** | — | — | 11 | 12 | 153,226 (78,336) | 217s |
| webarena.213 | What are the key aspects that the customers don't like about Antonia Racer Tank | fuzzy_match: ['Not suitable for high-impact workouts'] | zero support, no modesty, not good for high-impact activities | **PASS** ᶠ | — | matches | 11 | 12 | 175,915 (77,696) | 202s |
| webarena.214 | What are the key aspects that the customers don't like about Zing Jump Rope | fuzzy_match: ["It is hard to find the right size. Won't last long"] | N/A | fail | no | wrong answer | 24 | 32 | 536,070 (465,600) | 380s |
| webarena.215 | What are the key aspects that the customers don't like about Circe ice fleece | fuzzy_match: ['Material quality, fit, insufficient warmth, color'] | poor material quality that pilling after one wash, poor fit with sleeves too short and bo… | **PASS** ᶠ | — | matches | 15 | 25 | 277,367 (257,472) | 182s |
| webarena.216 | What are the key aspects that the customers don't like about Electra Bra Top | fuzzy_match: ['Not true to size'] | not exactly true to size | **PASS** ᶠ | — | matches | 9 | 16 | 159,458 (129,472) | 201s |
| webarena.217 | What are the key aspects that the customers don't like about Pursuit Tone Band | fuzzy_match: ['Insufficient resistance for their workouts.'] | not enough resistance | **PASS** ᶠ | — | matches | 21 | 42 | 816,048 (750,016) | 303s |
| webarena.243 | Show me the email address of the customer who is the most unhappy with Circe fleece | exact_match: hannah.lim@gmail.com | hannah.lim@gmail.com | **PASS** | — | — | 13 | 13 | 224,713 (152,064) | 167s |
| webarena.244 | Show me the email address of the customer who is the most unhappy with Olivia zip jacket | exact_match: emma.lopez@gmail.com | emma.lopez@gmail.com | **PASS** | — | — | 7 | 11 | 137,634 (85,248) | 310s |
| webarena.245 | Show me the name of the customer who is the most unhappy with Antonia racer tank | exact_match: Shaunte | Shaunte | **PASS** | — | — | 17 | 23 | 329,234 (209,664) | 492s |
| webarena.246 | Show me the name of the customer who is the most unhappy with Chloe tank | exact_match: Teofila | Teofila | **PASS** | — | — | 18 | 24 | 322,785 (278,592) | 330s |
| webarena.247 | Show me the email address of the customer who is the most unhappy with the style of Zoe produc… | fuzzy_match: N/A | N/A | **PASS** | — | — | 29 | 57 | 1,264,087 (1,166,848) | 936s |
| webarena.288 | Tell me the name of the customer who has the most cancellations in the history | exact_match: Samantha Jones | Samantha Jones | **PASS** | — | — | 12 | 13 | 312,029 (281,408) | 186s |
| webarena.289 | Tell me the email address, name, phone number of the customer who has the most cancellations i… | fuzzy_match: ['email: coolcat321@hotmail.com', 'name: Samantha Jones', 'phone number: 3055551212'] | coolcat321@hotmail.com, Samantha Jones, 3055551212 | **PASS** ᶠ | — | matches | 11 | 15 | 333,433 (294,272) | 262s |
| webarena.290 | Tell me the product SKUs in the most recent cancelled orders of the customer who has the most … | must_include: ['WSH09-29-White', 'WSH09-28-Green', 'MSH11-34-Blue', 'WP09-29-Purple'] | WSH09-29-White, WSH09-28-Green, MSH11-34-Blue, WP09-29-Purple | **PASS** | — | — | 12 | 18 | 334,936 (267,200) | 578s |
| webarena.291 | Tell me the total spend on products in the most recent cancelled orders of the customer who ha… | must_include: ['148'] | 148.80 | **PASS** | — | — | 8 | 10 | 244,219 (201,024) | 295s |
| webarena.292 | Tell me the total number of cancellations of the customer who has the most cancellations in th… | must_include: ['9'] | 9 | **PASS** | — | — | 11 | 11 | 208,028 (185,152) | 184s |
| webarena.344 | How many reviews our shop received by far? | must_include: ['351'] | 351 | **PASS** | — | — | 3 | 3 | 38,654 (22,976) | 50s |
| webarena.345 | How many reviews our shop received in Apr 2023? | must_include: ['351'] | 351 | **PASS** | — | — | 10 | 19 | 226,008 (94,144) | 257s |
| webarena.346 | How many reviews our shop received during 2022? | must_include: ['0'] | 0 | **PASS** | — | — | 6 | 8 | 99,623 (50,880) | 157s |
| webarena.347 | How many reviews our shop received from the beginning of the shop? | must_include: ['351'] | 351 | **PASS** | — | — | 5 | 4 | 66,428 (22,400) | 86s |
| webarena.348 | How many reviews our shop received in May 2023? | must_include: ['0'] | 0 | **PASS** | — | — | 5 | 8 | 80,121 (22,400) | 110s |
| webarena.374 | Preview the Magento Blank theme for my shop | URL (GOLD in PRED): /admin/admin/system_design_theme/edit/id/1 | Magento Blank | fail | no | ended on about:blank; never reached a preview page | 16 | 18 | 247,288 (224,256) | 158s |
| webarena.375 | Preview the Magento Luma theme for my shop | URL (GOLD in PRED): /admin/admin/system_design_theme/edit/id/3/key/ | Magento Luma | fail | **yes** | reached the correct theme's preview-edit page; the URL is missing only the dynamic security-key suffix Magento appends | 7 | 6 | 101,566 (92,416) | 109s |
| webarena.423 | Mark all Hollister shirts on sale | page value @126 must have [exact_match=1] | 16 | **PASS** | — | — | 30 | 40 | 872,154 (830,272) | 417s |
| webarena.453 | Disable Teton pullover hoodie from the site, they are facing some quality issues. | page value @78 must have [exact_match=2] | disabled | **PASS** | — | — | 9 | 12 | 254,794 (213,632) | 348s |
| webarena.454 | Disable Ryker Tee Crew Neck from the site, they are facing some quality issues. | page value @478 must have [exact_match=2] | Ryker LumaTech™ Tee (Crew-neck) | **PASS** | — | — | 14 | 15 | 363,589 (323,456) | 345s |
| webarena.455 | Disable lHelios Endurance Tank from the site, they are facing some quality issues. | page value @676 must have [exact_match=2] | done | fail | **yes** | status field reads exactly the disabled value the check wants | 15 | 19 | 459,610 (404,544) | 446s |
| webarena.456 | Disable Cora Pant from the site, they are facing some quality issues. | page value @1840 must have [exact_match=2] | Cora Parachute Pant | **PASS** | — | — | 14 | 18 | 319,781 (281,408) | 397s |
| webarena.457 | Disable Karmen yoga pants from the site, they are facing some quality issues. | page value @1819 must have [exact_match=2] | 7 | **PASS** | — | — | 10 | 18 | 309,756 (193,536) | 285s |
| webarena.458 | Reduce the price of this product by $5 | page value @1481 must have [exact_match=27.00] | 22.00 | fail | no | final price does not match the required result | 8 | 9 | 107,483 (89,536) | 101s |
| webarena.459 | Reduce the price of this product by 10% | page value @237 must have [exact_match=62.10] | 55.89 | fail | no | final price does not match the required result | 7 | 10 | 107,313 (26,880) | 416s |
| webarena.460 | Reduce the price of this product by 15% | page value @418 must have [exact_match=38.25] | 32.51 | fail | no | final price does not match the required result | 7 | 7 | 101,596 (82,688) | 113s |
| webarena.461 | Increase the price of this product by $11.5 | page value @721 must have [exact_match=29.50] | 41.00 | fail | no | final price does not match the required result | 8 | 9 | 105,911 (40,320) | 108s |
| webarena.462 | Increase the price of this product by 10% | page value @710 must have [exact_match=19.80] | 21.78 | fail | no | final price does not match the required result | 8 | 11 | 117,599 (53,760) | 79s |
| webarena.463 | Increase the price of this product by 15% | page value @996 must have [exact_match=36.80] | 42.32 | fail | no | final price does not match the required result | 6 | 9 | 78,406 (40,256) | 106s |
| webarena.464 | Update the product description of Antonia Racer Tank to highlight the real user positive revie… | page text @antonia-racer-tank.html must have [must_include=['This is in regular rotation at the gym', 'Its colorful and looks ] | Found the HTML textarea in the modal. Final step: write the updated description with the … | fail | no | no description text landed on the live storefront page | 30 | 60 | 1,413,328 (1,343,360) | 892s |
| webarena.470 | Cancel order 302 | page text @302 must have [exact_match=Canceled] | Canceled | **PASS** | — | — | 4 | 5 | 75,156 (45,504) | 231s |
| webarena.471 | Cancel order 307 | page text @307 must have [exact_match=Canceled] | Canceled | **PASS** | — | — | 7 | 8 | 118,675 (44,608) | 286s |
| webarena.472 | Cancel order 299 | page text @299 must have [exact_match=Canceled] | canceled | **PASS** | — | — | 4 | 4 | 62,284 (38,528) | 229s |
| webarena.473 | Cancel order 301 | page text @301 must have [exact_match=Canceled] | canceled | **PASS** | — | — | 12 | 12 | 281,846 (232,448) | 332s |
| webarena.474 | Cancel order 305 | page text @305 must have [exact_match=Canceled] | Canceled | **PASS** | — | — | 6 | 6 | 83,617 (76,096) | 99s |
| webarena.486 | Change the page title of "404 Not Found" page on my site to "Bruh bro you clicked the wrong pa… | page value @1 must have [exact_match=Bruh bro you clicked the wrong page] | Bruh bro you clicked the wrong page | **PASS** | — | — | 8 | 12 | 119,482 (105,728) | 170s |
| webarena.487 | Change the page title of "Enable Cookies" page on my site to "Cookie monster coming to your pl… | page value @3 must have [exact_match=Cookie monster coming to your place] | Cookie monster coming to your place | **PASS** | — | — | 26 | 30 | 703,733 (623,232) | 949s |
| webarena.488 | Change the page title of "Home Page" page on my site to "This is the home page!! Leave here!!". | page value @2 must have [exact_match=This is the home page!! Leave here!!] | This is the home page!! Leave here!! | **PASS** | — | — | 9 | 10 | 144,792 (93,248) | 336s |
| webarena.489 | Change the page title of "Privacy Policy" page on my site to "No privacy policy is needed is t… | page value @4 must have [exact_match=No privacy policy is needed is this dystopian world] | No privacy policy is needed is this dystopian world | **PASS** | — | — | 16 | 25 | 387,214 (311,488) | 477s |
| webarena.490 | Change the page title of "About us" page on my site to "Secret". | page value @5 must have [exact_match=Secret] | Secret | **PASS** | — | — | 9 | 11 | 138,805 (123,584) | 233s |
| webarena.491 | Notify Sarah Miller in their most recent pending order with message "the order is ready to be … | fuzzy_match: N/A | N/A | **PASS** | — | — | 24 | 28 | 1,074,797 (980,992) | 668s |
| webarena.492 | Notify Jane Doe in their most recent pending order with message "sorry we are out of stock, pl… | page text @302 must have [exact_match=sorry we are out of stock, please reorder] | N/A | fail | no | no order note was found; also the wrong order | 25 | 41 | 958,672 (809,408) | 546s |
| webarena.493 | Notify Grace Nguyen in their most recent pending order with message "sorry we are bankrupt, pl… | page text @307 must have [exact_match=sorry we are bankrupt, please contact our customer service for refun] | 000000065 | fail | no | no order note was found; also the wrong order | 23 | 35 | 1,036,991 (911,424) | 654s |
| webarena.494 | Notify Alex Thomas in their most recent pending order with message "Yo, your order will be shi… | page text @304 must have [exact_match=Yo, your order will be shipped soon!] | 000000304 | **PASS** | — | — | 17 | -15 | 592,593 (505,344) | 986s |
| webarena.495 | Notify Lily Potter in their most recent pending order with message "Thanks, your order is read… | page text @303 must have [exact_match=Thanks, your order is ready to be shipped!] | Customer Notified | **PASS** | — | — | 8 | 10 | 132,150 (76,032) | 299s |
| webarena.496 | Update order #299 with the Federal Express tracking number 8974568499 | page  @order_shipments must have [must_include=['Tracking number 8974568499 for Federal Express assigned']] | N/A | fail | no | evaluator's check on the order page came back empty | 10 | 10 | 250,044 (170,368) | 247s |
| webarena.497 | Update order #307 with the DHL tracking number 24353446464 | page  @order_shipments must have [must_include=['Tracking number 24353446464 for DHL assigned']] | N/A | fail | no | evaluator's check on the order page came back empty | 10 | 16 | 314,293 (116,672) | 458s |
| webarena.498 | Update order #306 with the UPS tracking number 55591023930 | page  @order_shipments must have [must_include=['Tracking number 55591023930 for United Parcel Service assigned']] | 55591023930 | fail | **yes** | answer states the exact tracking number requested; the evaluator's own locator returned empty, likely checking the wrong page state | 12 | 12 | 332,924 (216,576) | 350s |
| webarena.499 | Update order #304 with the USPS tracking number 13849373987 | page  @order_shipments must have [must_include=['Tracking number 13849373987 for United States Postal Service assi] | 13849373987 | fail | **yes** | answer states the exact tracking number requested; the evaluator's own locator returned empty, likely checking the wrong page state | 8 | 10 | 292,820 (228,928) | 464s |
| webarena.500 | Update order #301 with the DHL tracking number 239028439840 | page  @order_shipments must have [must_include=['Tracking number 239028439840 for DHL assigned']] | N/A | fail | no | gave up with N/A | 11 | 19 | 291,818 (207,360) | 161s |
| webarena.501 | Make all Taurus Elements Shell as out of stock | page value @350 must have [exact_match=0] | 16 | **PASS** | — | — | 29 | 41 | 711,378 (634,432) | 827s |
| webarena.502 | Make all Gobi HeatTec Tee as out of stock | page value @446 must have [exact_match=0] | 16 | **PASS** | — | — | 21 | 45 | 860,054 (624,384) | 751s |
| webarena.503 | Make all rocco gym tank as out of stock | page value @682 must have [exact_match=0] | 6 | **PASS** | — | — | 17 | 37 | 470,111 (352,512) | 427s |
| webarena.504 | Make all Selene yoga hoodie as out of stock | page value @1108 must have [exact_match=0] | Out of Stock | **PASS** | — | — | 11 | 37 | 275,412 (241,920) | 497s |
| webarena.505 | Make all Aeno capri as out of stock | page value @1861 must have [exact_match=0] | 7 | **PASS** | — | — | 15 | 34 | 490,283 (427,264) | 654s |
| webarena.538 | Modify the address of order #299 to 456 Oak Avenue, Apartment 5B, New York, NY, 10001 | page  @299 must have [must_include=['456 Oak Avenue', 'Apartment 5B', 'New York', '10001']] | 456 Oak Avenue, Apartment 5B, New York, NY, 10001 | **PASS** | — | — | 10 | 13 | 293,468 (224,832) | 508s |
| webarena.539 | Modify the address of order #65 to 789 Pine Lane, San Francisco, CA, 94102 | page  @65 must have [must_include=['789 Pine Lane', 'San Francisco', 'California', '94102']] | 789 Pine Lane, San Francisco, CA, 94102 | **PASS** | — | — | 8 | 9 | 157,158 (96,768) | 235s |
| webarena.540 | Modify the address of order #301 to 321 Birch Boulevard, Suite 200, Dallas, TX, 75201 | page  @301 must have [must_include=['321 Birch Boulevard', 'Suite 200', 'Dallas', 'Texas', '75201']] | 321 Birch Boulevard, Suite 200, Dallas, TX, 75201 | **PASS** | — | — | 11 | 14 | 285,248 (188,928) | 275s |
| webarena.541 | Modify the address of order #125 to 654 Elm Drive, Apartment 12, Miami, FL, 33101 | page  @125 must have [must_include=['654 Elm Drive', 'Apartment 12', 'Miami', 'Florida', '33101']] | You updated the order address. | **PASS** | — | — | 9 | 8 | 186,918 (68,224) | 372s |
| webarena.542 | Modify the address of order #300 to 987 Cedar Court, Los Angeles, CA, 90012 | page  @300 must have [must_include=['987 Cedar Court', 'Los Angeles', 'California', '90012']] | 987 Cedar Court, Los Angeles, CA, 90012 | **PASS** | — | — | 9 | 10 | 295,419 (229,056) | 631s |
| webarena.543 | Update the product description of Bella Tank to highlight the real user positive reviews by qu… | page text @bella-tank.html must have [must_include=["Good choice for working out and stylin' enough to wear when I'm h] | The ko lookup failed (likely `window.ko` undefined) and Save was covered by a button. Fin… | **PASS** | — | — | 30 | 48 | 945,957 (870,784) | 1234s |
| webarena.544 | Update the description of Selena Yoga Hoodie to highlight the real user positive reviews by qu… | page text @selene-yoga-hoodie.html must have [must_include=['I was super cold and it did the job.', 'The sleeves are definitel] | The master format is synced with the new HTML. Now the final step: verify content and sav… | fail | no | description edit did not land on the page | 30 | 52 | 1,178,155 (1,006,272) | 795s |
| webarena.545 | Update the description of Radiant Tee to highlight the real user positive reviews by quoting t… | page text @radiant-tee.html must have [must_include=['What I rally love here is that it does the job of keeping me cool] | Radiant Tee's description now highlights the positive customer reviews with their comment… | fail | no | description edit did not land on the page | 30 | 48 | 1,103,708 (801,408) | 1054s |
| webarena.546 | Update the description of Lucia Cross-Fit Bra to highlight the real user positive reviews by q… | page text @affirm-water-bottle.html must have [must_include=['Wide mouth opening makes it easy to clean']] | N/A | fail | no | gave up with N/A | 13 | 27 | 268,302 (228,864) | 325s |
| webarena.547 | Add a new color option brown to the size S of Phoebe Zipper Sweatshirt | page text @1130 must have [must_include=['Phoebe Zipper Sweatshirt-S-Brown']] | N/A | **PASS** | — | — | 8 | 8 | 255,007 (189,440) | 634s |
| webarena.548 | Add a new color blue to size S and M of Frankie Sweatshirt | page text @110 must have [must_include=['Sweatshirt-M-Blue', 'Sweatshirt-S-Blue']] | Frankie Sweatshirt is product ID 110 (SKU MH04). Let me open it. | **PASS** | — | — | 8 | 9 | 175,194 (73,728) | 303s |
| webarena.549 | Add a new size XXXL to green Minerva LumaTech V-Tee | page text @1492 must have [must_include=['V-Tee-XXXL-Green']] | WS08-XXXL-Green | **PASS** | — | — | 22 | 33 | 729,615 (546,560) | 233s |
| webarena.550 | Add a new size XXS to blue and purple Nona Fitness Tank | page text @1732 must have [must_include=['Tank-XXS-Blue', 'Tank-XXS-Purple']] | Nona Fitness Tank-XXS-Blue, Nona Fitness Tank-XXS-Purple | **PASS** | — | — | 18 | 29 | 895,275 (654,336) | 897s |
| webarena.551 | Add new size 30 and 31 to all color variants of Diana Tights | page text @1854 must have [must_include=['Tights-30-Blue', 'Tights-30-Black', 'Tights-30-Orange', 'Tights-3] | 6 | **PASS** | — | — | 23 | 31 | 639,675 (573,248) | 785s |
| webarena.676 | Lookup orders that are suspected of being fraudulent | URL (GOLD in PRED): /admin/sales/order/ \| (+ page-state check) | 0 | **PASS** | — | — | 11 | 16 | 324,293 (264,256) | 851s |
| webarena.677 | Lookup orders that are processing | URL (GOLD in PRED): /admin/sales/order/ \| (+ page-state check) | 000000125, 000000306, 000000304, 000000300 | **PASS** | — | — | 14 | 15 | 295,574 (107,776) | 139s |
| webarena.678 | Lookup orders that are canceled | URL (GOLD in PRED): /admin/sales/order/ \| (+ page-state check) | 147 | **PASS** | — | — | 8 | 12 | 154,532 (108,928) | 247s |
| webarena.679 | Lookup orders that are completed | URL (GOLD in PRED): /admin/sales/order/ \| (+ page-state check) | 153 | fail | **yes** | final URL matches the gold admin order-grid URL exactly | 11 | 14 | 221,091 (89,344) | 177s |
| webarena.680 | Lookup orders that are on hold | URL (GOLD in PRED): /admin/sales/order/ \| (+ page-state check) | 0 | **PASS** | — | — | 8 | 8 | 156,880 (79,936) | 208s |
| webarena.694 | Add a simple product named Energy-Bulk Women Shirt with 50 in stock, available in size S and c… | URL (GOLD in PRED): /admin/catalog/product \| (+ page-state check) | Energy-Bulk Women Shirt | fail | **yes** | a live storefront page for the exact product name exists, strong evidence the product was created; agent ended on the storefront page instead of the admin URL gold expects | 30 | 42 | 970,743 (776,128) | 1144s |
| webarena.695 | Add a simple product named Energy-Bulk Man Yoga Pant with 50 in stock, available in size 38 an… | URL (GOLD in PRED): /admin/catalog/product \| (+ page-state check) | Energy-Bulk Man Yoga Pant | fail | no | reached the right admin page, but the required product attributes were not all verified as set | 30 | 45 | 747,357 (372,928) | 661s |
| webarena.696 | Add a simple product named FancyBoy Man Causal Jeans with 42 in stock, available in size 34 an… | URL (GOLD in PRED): /admin/catalog/product \| (+ page-state check) | FancyBoy Man Causal Jeans | fail | no | reached the right admin page, but the required product attributes were not all verified as set | 30 | 39 | 803,409 (500,160) | 574s |
| webarena.697 | Add a simple product named Swaatch Smart Watch with 42 in stock, available in size uni-size an… | URL (GOLD in PRED): /admin/catalog/product \| (+ page-state check) | Swaatch Smart Watch | fail | no | reached the right admin page, but the required product attributes were not all verified as set | 29 | 47 | 1,229,352 (1,110,912) | 535s |
| webarena.698 | Add a simple product named Lelelumon Yoga Mat with 42 in stock, available in size uni-size and… | URL (GOLD in PRED): /admin/catalog/product \| (+ page-state check) | Lelelumon Yoga Mat | fail | no | reached the right admin page, but the required product attributes were not all verified as set | 20 | 39 | 878,456 (794,880) | 587s |
| webarena.699 | Draft a new marketing price rule for spring sale that offers a 20 percent discount site-wide f… | URL (GOLD in PRED): /admin/sales_rule/promo_quote \| (+ page-state check) | Spring Sale | fail | no | created a catalog price rule; gold wanted a shopping-cart price rule | 25 | 49 | 611,318 (571,520) | 466s |
| webarena.700 | Draft a new marketing price rule for fall discount that offers $10 discount on checkout for al… | URL (GOLD in PRED): /admin/sales_rule/promo_quote \| (+ page-state check) | Fall Discount | fail | no | reached the right admin page, but the rule's own settings were not verified as correct | 24 | 42 | 679,857 (628,672) | 500s |
| webarena.701 | Draft a new marketing price rule for Mother's day sale that offers $15 discount on checkout fo… | URL (GOLD in PRED): /admin/sales_rule/promo_quote \| (+ page-state check) | Mother's Day Sale | fail | no | ended on the rule grid, not a specific saved rule -- looks unsaved | 18 | 37 | 567,530 (440,064) | 547s |
| webarena.702 | Draft a new marketing price rule for Pride Month that offers 45% off on all products for all c… | URL (GOLD in PRED): /admin/sales_rule/promo_quote \| (+ page-state check) | Pride Month 45% Off | fail | no | created a catalog price rule; gold wanted a shopping-cart price rule | 19 | 29 | 438,572 (403,584) | 370s |
| webarena.703 | Draft a new marketing price rule for Thanks giving sale that offers $40 discount on checkout f… | URL (GOLD in PRED): /admin/sales_rule/promo_quote \| (+ page-state check) | Thanksgiving Sale | fail | no | reached the right admin page, but the rule's own settings were not verified as correct | 17 | 27 | 389,116 (323,776) | 338s |
| webarena.704 | Today is 3/15/2023, generate a sales order report for last month | URL (GOLD in PRED): /admin/reports/report_sales/sales \| (+ page-state check) | 749.00 | **PASS** | — | — | 5 | 10 | 99,884 (81,280) | 211s |
| webarena.705 | Today is 3/15/2023, generate a sales order report over the last 45 days | URL (GOLD in PRED): /admin/reports/report_sales/sales \| (+ page-state check) | 8 | **PASS** | — | — | 10 | 13 | 195,604 (169,728) | 280s |
| webarena.706 | Today is 3/15/2023, generate a refund report for Q1 | URL (GOLD in PRED): /admin/reports/report_sales/refunded \| (+ page-state check) | 0.00 | **PASS** | — | — | 26 | 49 | 658,675 (607,296) | 549s |
| webarena.707 | Today is 3/15/2023, generate a sales order report for last year | URL (GOLD in PRED): /admin/reports/report_sales/sales \| (+ page-state check) | 15475.46 | fail | **yes** | correct report page and exactly the requested date range (calendar year 2022) | 7 | 10 | 141,636 (115,392) | 177s |
| webarena.708 | Today is 3/15/2023, generate a tax report for this year | URL (GOLD in PRED): /admin/reports/report_sales/tax/ \| (+ page-state check) | 0 | fail | no | used year-to-date instead of the full calendar year | 27 | 44 | 1,048,280 (770,560) | 291s |
| webarena.709 | Create an orders report from beginning of May 2021 to end of March 2022 | URL (GOLD in PRED): /admin/reports/report_sales/sales \| (+ page-state check) | 41 | fail | **yes** | correct report page and exactly the requested date range (May 2021 - March 2022) | 14 | 18 | 298,968 (259,264) | 232s |
| webarena.710 | Create a shipping report from 08/05/2022 to 03/01/2023 | URL (GOLD in PRED): /admin/reports/report_sales/shipping \| (+ page-state check) | 112 | **PASS** | — | — | 10 | 14 | 215,159 (129,792) | 249s |
| webarena.711 | Create a product view report from 07/05/2021 to 05/31/2023 | URL (GOLD in PRED): /admin/reports/report_product/viewed/ \| (+ page-state check) | 0 | **PASS** | — | — | 30 | 38 | 994,968 (907,776) | 811s |
| webarena.712 | Create a coupons report from 05/01/2021 to 05/15/2023 | URL (GOLD in PRED): /admin/reports/report_sales/coupons/ \| (+ page-state check) | 0 | **PASS** | — | — | 16 | 22 | 301,817 (161,280) | 165s |
| webarena.713 | Create a best sellers report from 05/01/2022 to 05/31/2023 | URL (GOLD in PRED): /admin/reports/report_sales/bestsellers/ \| (+ page-state check) | N/A | **PASS** | — | — | 8 | 14 | 161,787 (129,792) | 296s |
| webarena.768 | 5 blue Cronus yoga pants with size 33 arrived, update the stock | page value @872 must have [exact_match=5] \| page value @872 must have [exact_match=1] | 5 | **PASS** | — | — | 18 | 25 | 573,051 (223,872) | 551s |
| webarena.769 | We've received 378 brown Aero daily fitness tee in every size, please update the inventory. | page value @544 must have [exact_match=478] \| page value @547 must have [exact_match=478] \| page value @550 must have [exact_ma… | 478 | **PASS** | — | — | 19 | 32 | 946,365 (557,696) | 423s |
| webarena.770 | We've received 12 white Cora parachute pant of size 28 and 56 blue of size 29, update the inve… | page value @1836 must have [exact_match=112] \| page value @1838 must have [exact_match=156] | 112, 156 | **PASS** | — | — | 20 | 27 | 505,921 (468,928) | 318s |
| webarena.771 | Approve the positive reviews to display in our store. | page value @352 must have [exact_match=1] \| page value @349 must have [exact_match=1] \| page value @347 must have [exact_match=… | 352, 347 | fail | no | none of the three reviews were actually approved | 11 | 16 | 262,217 (239,680) | 186s |
| webarena.772 | Delete all pending negative reviews for Circe fleece | page  @999 must have [must_include=["Rating isn't Available"]] | 1 | **PASS** | — | — | 13 | 19 | 377,195 (343,808) | 247s |
| webarena.773 | Delete all pending negative reviews | page  @351 must have [must_include=["Rating isn't Available"]] \| page  @353 must have [must_include=["Rating isn't Available"]] | 1 | **PASS** | — | — | 13 | 15 | 299,182 (267,008) | 296s |
| webarena.774 | Delete all pending reviews with less than 4 stars | page  @351 must have [must_include=["Rating isn't Available"]] \| page  @353 must have [must_include=["Rating isn't Available"]] … | 1 | **PASS** | — | — | 16 | 15 | 257,857 (244,608) | 134s |
| webarena.775 | Delete all reviews from the scammer Arden | page  @51 must have [must_include=["Rating isn't Available"]] | 1 | **PASS** | — | — | 11 | 20 | 308,468 (262,592) | 217s |
| webarena.776 | Delete all reviews from the scammer Carlo | page  @93 must have [must_include=["Rating isn't Available"]] \| page  @109 must have [must_include=["Rating isn't Available"]] | 2 | **PASS** | — | — | 12 | 22 | 282,132 (256,640) | 147s |
| webarena.777 | Reduce the price of green Hollister backyard sweater in all size by $5 | page value @120 must have [exact_match=47.00] \| page value @117 must have [exact_match=47.00] \| page value @114 must have [exac… | 47.00 | **PASS** | — | — | 21 | 45 | 657,633 (539,328) | 382s |
| webarena.778 | Reduce the price of size 28 Sahara leggings by 13.5% | page value @1841 must have [exact_match=64.88] \| page value @1842 must have [exact_match=64.88] \| page value @1843 must have [e… | 64.87 | fail | no | computed a new price but it was never applied | 16 | 26 | 697,359 (618,112) | 395s |
| webarena.779 | Reduce the price of yellow shirts from Gwyn Endurance in all size below L by 15% | page value @1559 must have [exact_match=20.40] \| page value @1562 must have [exact_match=20.40] \| page value @1565 must have [e… | 20.40 | **PASS** | — | — | 12 | 20 | 352,688 (259,072) | 318s |
| webarena.780 | Increase the price of white Ingrid Running with size L and above by $17 | page value @1264 must have [exact_match=64.00] \| page value @1267 must have [exact_match=64.00] | 101.00 | fail | no | edited the wrong product variant | 8 | 17 | 169,716 (99,136) | 161s |
| webarena.781 | Increase the price of black fitness tshirts from Desiree with size XS by 37% | page value @1573 must have [exact_match=32.88] | 32.88 | **PASS** | — | — | 8 | 13 | 201,205 (131,200) | 98s |
| webarena.782 | Increase the price of all blue running tshirts in extra small and small sizes by 23% | page value @496 must have [exact_match=22.33] \| page value @499 must have [exact_match=22.33] \| page value @479 must have [exac… | 34.44, 35.67 | fail | no | edited the wrong product variant | 13 | 23 | 595,890 (467,520) | 307s |
| webarena.790 | Delete all negative reviews for Sybil running short | fuzzy_match: N/A | 0 | **PASS** ᶠ | — | gold "N/A"; "0" means no such items, same reading | 13 | 21 | 333,961 (301,440) | 270s |

ᶠ = counted as a pass by the hand judging pass, not by the harness.


## What it was good at

Task types with three or more instances, 60%+ solved.

| task type | solved |
|---|---|
| Tell me the the number of reviews that our store received by far that mention term "{{x}}" | 5/5 (100%) |
| Find the customer name and email with phone number {{n}} | 3/3 (100%) |
| Cancel order {{n}} | 5/5 (100%) |
| Change the page title of "{{x}}" page on my site to "{{x}}". | 5/5 (100%) |
| List the top {{n}} search terms in my store | 2/3 (67%) |

## What it was bad at

Task types with three or more instances, under 60% solved.

| task type | solved |
|---|---|
| What's the total number of items sold in the most recent {{n}} orders? | 0/4 (0%) |

## Why the 74 failures happened

| cause | count | share of all failures |
|---|---|---|
| final price does not match the required result | 6 | 8% |
| reached the right admin page, but the required product attributes were not all verified as set | 4 | 5% |
| off by one on the count | 3 | 4% |
| wrong total | 3 | 4% |
| wrong answer | 2 | 3% |
| never finished the lookup | 2 | 3% |
| wrong customer | 2 | 3% |
| no order note was found; also the wrong order | 2 | 3% |
| evaluator's check on the order page came back empty | 2 | 3% |
| answer states the exact tracking number requested; the evaluator's own locator returned empty, likely checking the wrong page state | 2 | 3% |
| gave up with N/A | 2 | 3% |
| description edit did not land on the page | 2 | 3% |
| created a catalog price rule; gold wanted a shopping-cart price rule | 2 | 3% |
| reached the right admin page, but the rule's own settings were not verified as correct | 2 | 3% |
| edited the wrong product variant | 2 | 3% |
| fuzzy_match, unjudged and scored against a gold answer that does not match | 9 | 12% |
