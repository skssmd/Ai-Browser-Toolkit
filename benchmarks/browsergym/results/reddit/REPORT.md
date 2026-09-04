# WebArena — reddit (Postmill), full task list

Model **z-ai/glm-5.3-flash** via OpenRouter, driving the abt toolkit through
BrowserGym. 30-turn ceiling, one fresh agent process per task.

## Result

| | |
|---|---|
| tasks scored | 106 |
| passed, as the harness scored it | **87 — 82.1%** |
| recovered by the fuzzy judging pass | +2 |
| **final** | **89 — 84.0%** |
| total ops | 1,582 |
| total turns | 1,183 |
| total tokens | 27,444,731 (19,492,544 cached, 71%) |
| total wall time | 10.3 h |
| mean per task | 15 ops, 11 turns, 258,913 tokens, 349 s |

`fuzzy_match` tasks need a GPT-4 judge and no key was set, so 2 episodes were
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
| credited by the harness | 89 | **84.0%** |
| correct but uncredited | 6 | 5.7% |
| genuinely incorrect | 11 | 10.4% |
| unclear from the record | 0 | 0.0% |
| **did the task** | **95** | **89.6%** |

So the benchmark scores **84.0%** and the agent did the asked-for work in
**89.6%** of episodes. The gap is 6 episodes where the work was right and
the string, subreddit, or URL the harness checked was not.

The 11 genuinely incorrect episodes are the honest failures: wrong values,
wrong targets, and investigations that stopped before finding the answer.

## Every task

| task | question | answer required | answer given | result | correct | why | turns | ops | tokens (cached) | time |
|---|---|---|---|---|---|---|---|---|---|---|
| webarena.27 | Tell me the count of comments that have received more downvotes than upvotes for the user who … | must_include: ['0'] | 0 | **PASS** | — | — | 16 | 19 | 338,923 (299,712) | 340s |
| webarena.28 | Tell me the count of comments that have received more downvotes than upvotes for the user who … | must_include: ['0'] | 1 | fail | no | wrong count | 21 | 25 | 651,493 (577,920) | 878s |
| webarena.29 | Tell me the count of comments that have received more downvotes than upvotes for the user who … | must_include: ['1'] | 0 | fail | no | wrong count | 24 | 34 | 760,745 (691,520) | 978s |
| webarena.30 | Tell me the count of comments that have received more downvotes than upvotes for the user who … | must_include: ['0'] | 0 | **PASS** | — | — | 14 | 23 | 377,731 (222,080) | 395s |
| webarena.31 | Tell me the count of comments that have received more downvotes than upvotes for the user who … | must_include: ['0'] | 0 | **PASS** | — | — | 11 | 18 | 218,729 (110,592) | 506s |
| webarena.66 | Among the top 10 post in "books" forum, show me the post URLs that recommand a single book | must_include: ['http://www.reddit.com/f/books/59396/apple-books-has-a-free-audiobook-of-a-christmas-carol', 'http://www.reddit.co… | http://localhost:9999/f/books/12/to-kill-a-mockingbird-by-harper-lee, http://localhost:99… | fail | no | named the wrong posts | 16 | 40 | 458,276 (219,520) | 284s |
| webarena.67 | Among the top 10 post in "books" forum, show me the book names from posts that recommand a sin… | must_include: ['A Christmas Carol', 'The Hobbit'] | To Kill a Mockingbird, Gone with the wind | fail | no | named the wrong books | 8 | 8 | 170,215 (71,616) | 433s |
| webarena.68 | Among the top 10 post in "books" forum, show me the author name and the book name from posts t… | must_include: ['A Christmas Carol', 'Levar Burton', 'The Hobbit', 'J. R. R. Tolkien'] | Harper Lee, To Kill a Mockingbird | fail | no | named the wrong author/book | 16 | 16 | 356,990 (304,128) | 312s |
| webarena.69 | Among the top 10 post in "books" forum, is there any post talks about supporting local book st… | must_include: ['bookshop.org'] | bookshop.org | **PASS** | — | — | 8 | 10 | 188,409 (107,008) | 469s |
| webarena.399 | Change my reddit bio to "I am a robot" | page text @MarvelsGrantMan136 must have [exact_match=I am a robot] | I am a robot | **PASS** | — | — | 17 | 20 | 371,110 (274,176) | 168s |
| webarena.400 | Change my reddit bio to "Pro Python Developer with 20 years of Experience" | page text @MarvelsGrantMan136 must have [exact_match=Pro Python Developer with 20 years of Experience] | Pro Python Developer with 20 years of Experience | **PASS** | — | — | 11 | 14 | 184,527 (122,816) | 171s |
| webarena.401 | Change my reddit bio to "Seeking SDE positions" | page text @MarvelsGrantMan136 must have [exact_match=Seeking SDE positions] | Seeking SDE positions | **PASS** | — | — | 14 | 17 | 245,634 (220,416) | 140s |
| webarena.402 | Change my reddit bio to "Freelance Web Developer" | page text @MarvelsGrantMan136 must have [exact_match=Freelance Web Developer] | Freelance Web Developer | **PASS** | — | — | 17 | -35 | 312,103 (171,584) | 565s |
| webarena.403 | Change my reddit bio to "Awesome Prompt Artist" | page text @MarvelsGrantMan136 must have [exact_match=Awesome Prompt Artist] | Awesome Prompt Artist | **PASS** | — | — | 9 | 10 | 128,470 (110,400) | 82s |
| webarena.404 | Upvote the newest post in books subreddit | page document.querySelector('div.su @adults-reading-to-each-other-out-loud must have [must_include=['vote vote--user-upvoted']] | Only post 124260 ("Adults reading to each other out loud?") is already upvoted by this us… | **PASS** | — | — | 18 | 29 | 614,711 (419,328) | 429s |
| webarena.405 | Upvote the newest post in DIY subreddit | page document.querySelector('div.su @how-can-i-bring-an-hdmi-cable-from-my-pc must have [must_include=['vote vote--user-upvoted']] | Now sorted by "New" (`/f/DIY/new`). Interesting: the two 6-day-old seeded posts are absen… | **PASS** | — | — | 11 | 17 | 287,689 (206,976) | 930s |
| webarena.406 | Upvote the newest post in future technology subreddit | page document.querySelector('div.su @openai-ceo-it-s-not-funny-that-i-m-afrai must have [must_include=['vote vote--user-upvoted']] | OpenAI CEO: It’s Not Funny That I’m Afraid of the AI We’re Creating | **PASS** | — | — | 16 | 17 | 378,576 (281,088) | 389s |
| webarena.407 | Upvote the newest post in deeplearning subreddit | page document.querySelector('div.su @meta-s-llama-weights-leaked-on-torrent-a must have [must_include=['vote vote--user-upvoted']] | Confirmed: the newest post (2023-03-31T18:44:26+00:00) is "Should I continue with this?".… | fail | no | target was already upvoted before the episode; agent misidentified the newest post | 9 | 11 | 227,589 (131,328) | 633s |
| webarena.408 | Upvote the newest post in explain like im 5 subreddit | page document.querySelector('div.su @eli5-how-does-pinching-a-ribbon-and-slid must have [must_include=['vote vote--user-upvoted']] | Eli5 why does pressing my palms against my eyes create a kaleidoscope effect? | fail | no | target was already upvoted before the episode; agent misidentified the newest post | 9 | 13 | 203,461 (112,192) | 490s |
| webarena.409 | Reply to the manager of the website in this post with "thanks! I am a big fan of your website." | page  @1235250 must have [must_include=['thanks! I am a big fan of your website.']] | thanks! I am a big fan of your website. | **PASS** | — | — | 7 | 9 | 201,000 (173,376) | 220s |
| webarena.410 | Reply to the first reply in this post with "don't panic" | page  @1042264 must have [must_include=["don't panic"]] | don't panic | **PASS** | — | — | 4 | 4 | 85,688 (68,672) | 175s |
| webarena.580 | Create a new forum named sci_fi, with a description of A wild place for sci-fi enthusiasts, an… | page value @edit must have [must_include=['A wild place for sci-fi enthusiasts']] \| page value @edit must have [must_include=['N… | sci_fi | **PASS** | — | — | 16 | 22 | 363,045 (310,208) | 311s |
| webarena.581 | Create a new forum named cmu_lti, with a description of Language Technologies Institute at Car… | page value @edit must have [must_include=['Language Technologies Institute at Carnegie Mellon University']] \| page value @edit m… | cmu_lti | **PASS** | — | — | 14 | 24 | 263,068 (144,000) | 284s |
| webarena.582 | Create a new forum named Cyberpunk, with a description of Welcome to the future, and include [… | page value @edit must have [must_include=['Welcome to the future']] \| page value @edit must have [must_include=['Games', 'Books'… | Cyberpunk | **PASS** | — | — | 7 | 11 | 138,746 (48,064) | 429s |
| webarena.583 | Create a new forum named PlantsForCatParents, with a description of Cat parents & plan lovers,… | page value @edit must have [must_include=['Cat parents & plan lovers']] \| page value @edit must have [must_include=['Cat friendl… | PlantsForCatParents | **PASS** | — | — | 9 | 12 | 173,243 (94,976) | 369s |
| webarena.584 | Create a new forum named Karaoke, with a description of Place for Karaoke lovers, and include … | page value @Karaoke must have [must_include=['Place for Karaoke lovers']] \| page value @Karaoke must have [must_include=['device… | Karaoke | fail | no | evaluator found no forum description at all | 13 | 17 | 238,865 (157,312) | 444s |
| webarena.595 | Open the thread of a trending post on the forum "space" and subscribe. | URL (GOLD in PRED): /f/space \| (+ page-state check) | The Moon, Saturn and Jupiter through my 4" telescope and smartphone | **PASS** | — | — | 12 | 17 | 248,432 (133,056) | 452s |
| webarena.596 | Open the thread of a trending post on the forum "books" and subscribe. | URL (GOLD in PRED): /f/books \| (+ page-state check) | What could machine learning help with in the field of books? | **PASS** | — | — | 9 | 9 | 263,211 (66,432) | 362s |
| webarena.597 | Open the thread of a trending post on the forum "consoles" and subscribe. | URL (GOLD in PRED): /f/consoles \| (+ page-state check) | http://localhost:9999/f/consoles/7/what-is-the-recommended-console-to-buy-these-days | **PASS** | — | — | 12 | 16 | 245,688 (197,376) | 630s |
| webarena.598 | Open the thread of a trending post on the forum "pittsburgh" and subscribe. | URL (GOLD in PRED): /f/pittsburgh \| (+ page-state check) | Fun thing to do in Pittsburgh | **PASS** | — | — | 10 | 12 | 228,064 (166,848) | 579s |
| webarena.599 | Open the thread of a trending post on the forum "machine learning" and subscribe. | URL (GOLD in PRED): /f/MachineLearning \| (+ page-state check) | what is the SOTA web navigation agent repo | **PASS** | — | — | 10 | 12 | 216,688 (167,488) | 430s |
| webarena.600 | Post my question, "what is the recommended console to buy these days", in a subreddit where I'… | URL (GOLD in PRED): /f/consoles \| (+ page-state check) | consoles | **PASS** | — | — | 9 | 12 | 158,148 (67,072) | 230s |
| webarena.601 | Post my question, "is car necessary in NYC", in a subreddit where I'm likely to get an answer | URL (GOLD in PRED): /f/nyc \| (+ page-state check) | nyc | **PASS** | — | — | 12 | 15 | 216,924 (154,368) | 218s |
| webarena.602 | Post my question, "places for new drivers to learn driving in pittsburgh", in a subreddit wher… | URL (GOLD in PRED): /f/pittsburgh \| (+ page-state check) | pittsburgh | **PASS** | — | — | 6 | 8 | 103,143 (68,416) | 311s |
| webarena.603 | Post my question, "safe and budge apartment to live in nyc", in a subreddit where I'm likely t… | URL (GOLD in PRED): /f/nyc \| (+ page-state check) | nyc | **PASS** | — | — | 13 | 21 | 319,377 (256,064) | 413s |
| webarena.604 | Post my question, "what is the SOTA web navigation agent repo", in a subreddit where I'm likel… | URL (GOLD in PRED): /f/deeplearning \|OR\| /f/MachineLearning \|OR\| /f/singularity \| (+ page-state check) | MachineLearning | **PASS** | — | — | 9 | 13 | 170,927 (140,416) | 198s |
| webarena.605 | Find a subreddit focused on topics related to gaming consoles, and post my question, "what is … | URL (GOLD in PRED): /f/consoles \| (+ page-state check) | what is the recommended console to buy these days | **PASS** | — | — | 6 | 9 | 115,792 (96,768) | 179s |
| webarena.606 | Find a subreddit focused on topics related to NYC, and post my question, "is car necessary" th… | URL (GOLD in PRED): /f/nyc \| (+ page-state check) | nyc | **PASS** | — | — | 10 | 12 | 195,423 (172,992) | 175s |
| webarena.607 | Find a subreddit focused on topics related to city Pittsburgh, and post my question, "places f… | URL (GOLD in PRED): /f/pittsburgh \| (+ page-state check) | pittsburgh | **PASS** | — | — | 12 | 18 | 232,869 (196,544) | 327s |
| webarena.608 | Find a subreddit focused on topics related to city lives in DMV area, and post my question, "s… | URL (GOLD in PRED): /f/washington \|OR\| /f/washingtondc \| (+ page-state check) | washingtondc | **PASS** | — | — | 10 | 20 | 219,675 (184,896) | 194s |
| webarena.609 | Find a subreddit focused on topics related to ML, DL, NLP, and post my question, "what is the … | URL (GOLD in PRED): /f/deeplearning \|OR\| /f/MachineLearning \|OR\| /f/singularity \| (+ page-state check) | MachineLearning | **PASS** | — | — | 7 | 10 | 117,494 (78,336) | 78s |
| webarena.610 | Post a review of my recent reading "To Kill a Mockingbird by Harper Lee" in the r/books with m… | URL (GOLD in PRED): /f/books \| (+ page-state check) | good book! | **PASS** | — | — | 8 | 11 | 155,943 (130,816) | 420s |
| webarena.611 | Post a review of my recent reading "Harry Potter" in the r/books with my comment "Wonderful jo… | URL (GOLD in PRED): /f/books \| (+ page-state check) | posted | **PASS** | — | — | 9 | 13 | 161,654 (99,072) | 114s |
| webarena.612 | Post a review of my recent reading "big little lies" in the r/books with my comment "can't sto… | URL (GOLD in PRED): /f/books \| (+ page-state check) | can't stop it | **PASS** | — | — | 7 | 9 | 113,385 (62,208) | 77s |
| webarena.613 | Post a review of my recent reading "Love story" in the r/books with my comment "I cried". | URL (GOLD in PRED): /f/books \| (+ page-state check) | I cried | **PASS** | — | — | 7 | 8 | 111,742 (90,368) | 147s |
| webarena.614 | Post a review of my recent reading "Gone with the wind" in the r/books with my comment "It's a… | URL (GOLD in PRED): /f/books \| (+ page-state check) | It's a book with history | **PASS** | — | — | 10 | 10 | 153,920 (94,464) | 100s |
| webarena.615 | Re-post the image of Bald Eagle in this page to earthporn subreddit and note "from /f/pics" | URL (GOLD in PRED): /f/earthporn \| (+ page-state check) | http://localhost:9999/f/EarthPorn/63/amazing-shot-of-a-blue-jay-pestering-a-bald-eagle-fr… | fail | **yes** | both program_html checks (note text + exact image hash) pass; only the subreddit-name capitalization in the URL check fails | 11 | 14 | 204,281 (159,936) | 321s |
| webarena.616 | Re-post the image of Thanksgiving turkey in this page to funny subreddit and note "from /f/pic… | URL (GOLD in PRED): /f/funny \| (+ page-state check) | A Trejo Thanksgiving. (from /f/pics) | **PASS** | — | — | 15 | 22 | 463,333 (379,584) | 393s |
| webarena.617 | Re-post the image of Firework in this page to earthporn subreddit and note "from /f/pics" | URL (GOLD in PRED): /f/earthporn \| (+ page-state check) | done | fail | **yes** | both program_html checks pass; only the URL check fails | 24 | 33 | 907,167 (817,536) | 836s |
| webarena.618 | Re-post the image of Wife's costume in this page to funny subreddit and note "from /f/pics" | URL (GOLD in PRED): /f/funny \| (+ page-state check) | http://localhost:9999/f/funny/66/my-wife-s-toy-costume-for-2022-from-f-pics | fail | **yes** | post body contains the required note verbatim and the correct image; only the URL-match fails | 14 | 19 | 375,181 (233,280) | 942s |
| webarena.619 | Re-post the image of costume contest in this page to funny subreddit and note "from /f/pics" | URL (GOLD in PRED): /f/funny \| (+ page-state check) | http://localhost:9999/f/funny/67/we-won-first-place-in-the-costume-contest | fail | **yes** | post body contains the required note verbatim and the correct image; only the URL-match fails | 20 | 25 | 488,219 (318,080) | 157s |
| webarena.620 | Ask for advice about deal with long-distance relationships in a subreddit for relations | URL (GOLD in PRED): /f/relationship_advice \| (+ page-state check) | How do you deal with a long-distance relationship? | **PASS** | — | — | 12 | 15 | 254,697 (200,512) | 317s |
| webarena.621 | Ask for advice about cheat in a subreddit for relations | URL (GOLD in PRED): /f/relationship_advice \| (+ page-state check) | Need advice about cheating in my relationship | **PASS** | — | — | 15 | 18 | 319,915 (201,920) | 505s |
| webarena.622 | Ask for advice about sexual harassment in a subreddit for relations | URL (GOLD in PRED): /f/relationship_advice \| (+ page-state check) | How do I deal with sexual harassment? Seeking advice | **PASS** | — | — | 10 | 12 | 178,565 (134,784) | 420s |
| webarena.623 | Ask for advice about gift for birthday in a subreddit for relations | URL (GOLD in PRED): /f/relationship_advice \| (+ page-state check) | What gift should I get for my girlfriend's birthday? | **PASS** | — | — | 7 | 12 | 113,142 (91,328) | 116s |
| webarena.624 | Ask for advice about break-up remedy in a subreddit for relations | URL (GOLD in PRED): /f/relationship_advice \| (+ page-state check) | done | **PASS** | — | — | 9 | 17 | 200,036 (160,064) | 415s |
| webarena.625 | Create a discussion post about "the effectiveness of online learning" in a relevant subreddit … | URL (GOLD in PRED): /f/machinelearning \|OR\| /f/deeplearning \| (+ page-state check) | The effectiveness of online learning | fail | no | posted to r/AskReddit; gold wanted r/machinelearning or r/deeplearning | 7 | 10 | 117,392 (81,024) | 197s |
| webarena.626 | Create a discussion post about "Iphone 14" in a relevant subreddit and ask users for their opi… | URL (GOLD in PRED): /f/iphone \| (+ page-state check) | Iphone 14 | **PASS** | — | — | 7 | 12 | 138,532 (85,824) | 320s |
| webarena.627 | Create a discussion post about "Harry Potter movie series" in a relevant subreddit and ask use… | URL (GOLD in PRED): /f/movies \| (+ page-state check) | Harry Potter movie series | **PASS** | — | — | 5 | 8 | 76,155 (67,200) | 94s |
| webarena.628 | Create a discussion post about "long distance relationship" in a relevant subreddit and ask us… | URL (GOLD in PRED): /f/relationship_advice \| (+ page-state check) | long distance relationship | **PASS** | — | — | 7 | 9 | 115,485 (75,008) | 162s |
| webarena.629 | Create a discussion post about "Fun thing to do in Pittsburgh" in a relevant subreddit and ask… | URL (GOLD in PRED): /f/pittsburgh \| (+ page-state check) | http://localhost:9999/f/pittsburgh/77/fun-thing-to-do-in-pittsburgh | **PASS** | — | — | 5 | 7 | 76,252 (21,760) | 164s |
| webarena.630 | Ask for product recommendations for noise-cancelling headphones within a budget of $200 in r/h… | URL (GOLD in PRED): /f/headphones \| (+ page-state check) | Looking for product recommendations for noise-cancelling headphones within a budget of $2… | **PASS** | — | — | 6 | 8 | 120,659 (82,688) | 446s |
| webarena.631 | Ask for product recommendations for running shoes within a budget of $100 in r/sports | URL (GOLD in PRED): /f/sports \| (+ page-state check) | submitted | **PASS** | — | — | 5 | 7 | 75,200 (55,808) | 119s |
| webarena.632 | Ask for product recommendations for running shoes within a budget of $500 in r/sports | URL (GOLD in PRED): /f/sports \| (+ page-state check) | done | **PASS** | — | — | 8 | 13 | 144,363 (68,864) | 313s |
| webarena.633 | Ask for product recommendations for running pants within a budget of $500 in r/sports | URL (GOLD in PRED): /f/sports \| (+ page-state check) | http://localhost:9999/f/sports/81/looking-for-running-pants-recommendations-within-a-500 | **PASS** | — | — | 7 | 10 | 105,350 (57,024) | 212s |
| webarena.634 | Ask for product recommendations for used iphone within a budget of $1000 in r/iphone | URL (GOLD in PRED): /f/iphone \| (+ page-state check) | http://localhost:9999/f/iphone/82/looking-for-recommendations-for-a-used-iphone-within-a-… | **PASS** | — | — | 16 | 19 | 296,941 (189,312) | 417s |
| webarena.635 | Post in the most appropriate subreddit and ask for recommendations for noise-cancelling headph… | URL (GOLD in PRED): /f/headphones \| (+ page-state check) | headphones | **PASS** | — | — | 14 | 23 | 377,455 (276,224) | 546s |
| webarena.636 | Post in the most appropriate subreddit and ask for recommendations for DIY toolkit products wi… | URL (GOLD in PRED): /f/DIY \| (+ page-state check) | DIY | **PASS** | — | — | 17 | 31 | 489,754 (355,136) | 601s |
| webarena.637 | Post in the most appropriate subreddit and ask for recommendations for sony headphones product… | URL (GOLD in PRED): /f/headphones \| (+ page-state check) | headphones | **PASS** | — | — | 21 | 31 | 619,265 (431,168) | 523s |
| webarena.638 | Post in the most appropriate subreddit and ask for recommendations for must-have product in my… | URL (GOLD in PRED): /f/BuyItForLife \| (+ page-state check) | BuyItForLife | **PASS** | — | — | 12 | 17 | 287,042 (125,440) | 326s |
| webarena.639 | Post in the most appropriate subreddit and ask for recommendations for used iphone products wi… | URL (GOLD in PRED): /f/iphone \| (+ page-state check) | iphone | **PASS** | — | — | 12 | 15 | 296,646 (171,200) | 494s |
| webarena.640 | Post a notice on a virtual meetup for book reading enthusiasts on March 15th in the r/books su… | URL (GOLD in PRED): /f/books \| (+ page-state check) | http://localhost:9999/f/books/88/virtual-meetup-for-book-reading-enthusiasts-on-march-15th | **PASS** | — | — | 5 | 7 | 76,066 (56,064) | 111s |
| webarena.641 | Post a notice on a virtual meetup for Harry Potter enthusiasts on July 8th in the books subred… | URL (GOLD in PRED): /f/books \| (+ page-state check) | Virtual meetup for Harry Potter enthusiasts on July 8th | **PASS** | — | — | 8 | 11 | 124,935 (89,280) | 157s |
| webarena.642 | Post a notice on a virtual meetup for Big little lies enthusiasts on Sep 10th in the books sub… | URL (GOLD in PRED): /f/books \| (+ page-state check) | Virtual meetup for Big little lies enthusiasts on Sep 10th | **PASS** | — | — | 7 | 9 | 108,768 (57,088) | 268s |
| webarena.643 | Post a notice on a virtual meetup for racing cars enthusiasts on Oct 21st in the nyc subreddit | URL (GOLD in PRED): /f/nyc \| (+ page-state check) | Virtual meetup for racing cars enthusiasts on Oct 21st | **PASS** | — | — | 9 | 12 | 141,982 (78,656) | 181s |
| webarena.644 | Post a notice on a virtual meetup for Tears of Kingdom enthusiasts on Dec 15th in the games su… | URL (GOLD in PRED): /f/games \| (+ page-state check) | Virtual meetup for Tears of Kingdom enthusiasts on Dec 15th | fail | no | posted to r/gaming; gold wanted r/games (a different subreddit) | 13 | 24 | 264,924 (188,416) | 501s |
| webarena.645 | Post in books subreddit about what could machine learning help the correpong field. | URL (GOLD in PRED): /f/books \| (+ page-state check) | What could machine learning help with in the field of books? | **PASS** | — | — | 10 | 11 | 161,729 (72,320) | 274s |
| webarena.646 | Post in DIY subreddit about what could midjourney help the correpong field. | URL (GOLD in PRED): /f/diy \| (+ page-state check) | What could Midjourney help with in the field of DIY? | fail | **yes** | post body contains both required phrases (case differs from the check) and the subreddit is DIY in a different case than gold's f/diy | 17 | 26 | 416,694 (288,768) | 466s |
| webarena.647 | Post in technology forum about what could open-source LLMs help the correpong field. | URL (GOLD in PRED): /f/technology \| (+ page-state check) | What could open-source LLMs help with in the field of technology? | **PASS** | — | — | 8 | 14 | 131,135 (64,768) | 244s |
| webarena.648 | Post in dataisbeautiful forum about what could large language models help the correpong field. | URL (GOLD in PRED): /f/dataisbeautiful \| (+ page-state check) | What could large language models help with in the field of correpong? | **PASS** | — | — | 11 | 18 | 230,873 (127,616) | 433s |
| webarena.649 | Post in history subreddit about what could diffusion model help the correpong field. | URL (GOLD in PRED): /f/history \| (+ page-state check) | What could diffusion model help with in the field of history? | **PASS** | — | — | 11 | 16 | 202,131 (71,936) | 285s |
| webarena.650 | Reply to the post with my comment "I am a big fan of the bookorg" | URL (GOLD in PRED): /f/books/59421/friendly-reminder-bookshop-org-exists \| (+ page-state check) | I am a big fan of the bookorg | **PASS** | — | — | 6 | 9 | 190,177 (132,864) | 492s |
| webarena.651 | Reply to the post with my comment "Yeah, pittsburgh traffic, you know..." | URL (GOLD in PRED): /f/pittsburgh/45899/driving-in-pittsburgh-summed-up-by-one-traffic-sign \| (+ page-state check) | Yeah, pittsburgh traffic, you know... | fail | no | replied to the wrong comment; text has nothing to do with the requested reply | 4 | 1 | 84,556 (6,912) | 372s |
| webarena.652 | Reply to the post with my comment "???" | URL (GOLD in PRED): /f/technology/134852/ai-experts-disown-musk-backed-campaign-citing-their-research \| (+ page-state check) | ??? | **PASS** | — | — | 6 | 8 | 79,391 (36,608) | 80s |
| webarena.714 | Thumbs down the top 1 post ever in gadgets. | page document.querySelector('div.su @a-custom-gaming-pc-built-inside-a-vintag must have [must_include=['vote vote--user-downvoted… | A custom gaming PC built inside a vintage 1940s Motorola radio case | **PASS** | — | — | 10 | 19 | 192,943 (115,776) | 340s |
| webarena.715 | Thumbs down the top 2 post ever in history. | page document.querySelector('div.su @the-scientist-who-discovered-sperm-was-s must have [must_include=['vote vote--user-downvoted… | The Moon, Saturn and Jupiter through my 4" telescope and smartphone, NASA's Annual Day of… | fail | **yes** | both program_html checks read back 'vote--user-downvoted' on the two gold posts, matching the required content | 7 | 8 | 145,884 (75,136) | 146s |
| webarena.716 | Thumbs down the top 3 post ever in books. | page document.querySelector('div.su @the-letters-of-t-s-eliot-to-emily-hale-t must have [must_include=['vote vote--user-downvoted… | The letters of T. S. Eliot to Emily Hale that were kept sealed from 1956 to 2020 have bee… | **PASS** | — | — | 18 | 25 | 450,293 (260,928) | 338s |
| webarena.717 | Thumbs down the top 4 post ever in movies. | page document.querySelector('div.su @who-will-win-the-oscar-for-actress-in-a- must have [must_include=['vote vote--user-downvoted… | Who will win the Oscar for ACTRESS IN A SUPPORTING ROLE?, Who will win the Oscar for FILM… | **PASS** | — | — | 17 | 16 | 407,858 (210,560) | 464s |
| webarena.718 | Thumbs down the top 5 post ever in technology. | page document.querySelector('div.su @brain-cancer-vaccine-succeeds-at-prolong must have [must_include=['vote vote--user-downvoted… | Brain cancer vaccine succeeds at prolonging survival in Phase 3 trial, India cuts interne… | **PASS** | — | — | 11 | 13 | 271,272 (214,016) | 440s |
| webarena.719 | Like all submissions created by ThetaGang_wsb in subreddit wallstreetbets | page document.querySelector('div.su @how-will-airbnb-close-following-their-ea must have [must_include=['vote vote--user-upvoted']… | 2 | **PASS** | — | — | 8 | 10 | 140,588 (124,416) | 164s |
| webarena.720 | Like all submissions created by CameronKelsey in subreddit earthporn | page document.querySelector('div.su @my-favorite-place-on-the-planet-henry-s- must have [must_include=['vote vote--user-upvoted']… | 3 | **PASS** | — | — | 8 | 12 | 187,289 (144,000) | 175s |
| webarena.721 | Like all submissions created by UniversityofBath in subreddit IAmA | page document.querySelector('div.su @hi-i-m-vienne-a-doctoral-student-at-the- must have [must_include=['vote vote--user-upvoted']… | 8 | **PASS** | — | — | 9 | 14 | 237,534 (169,408) | 386s |
| webarena.722 | Like all submissions created by Don_Gato1 in subreddit new york | page document.querySelector('div.su @fox-news-hosts-cast-new-york-as-crime-ri must have [must_include=['vote vote--user-upvoted']] | 1 | **PASS** | — | — | 12 | 15 | 278,269 (246,272) | 298s |
| webarena.723 | Like all submissions created by FTorrez81 in subreddit iphone13 | fuzzy_match: N/A | 0 | **PASS** ᶠ | — | gold "N/A"; "0" means no such items, same reading | 12 | 15 | 324,914 (248,384) | 520s |
| webarena.724 | Like all submissions created by Hrekires in subreddit news | page document.querySelector('div.su @gov-whitmer-signs-bills-to-repeal-right- must have [must_include=['vote vote--user-upvoted']… | 10 | **PASS** | — | — | 15 | 26 | 473,674 (422,912) | 331s |
| webarena.725 | DisLike all submissions created by RickyDontLoseThat in subreddit massachusetts | page document.querySelector('div.su @the-last-of-lincoln must have [must_include=['vote vote--user-downvoted']] | 1 | **PASS** | — | — | 11 | 16 | 279,690 (239,552) | 346s |
| webarena.726 | DisLike all submissions created by jacyanthis in subreddit earthporn | fuzzy_match: N/A | 0 | **PASS** ᶠ | — | gold "N/A"; "0" means no such items, same reading | 13 | 18 | 308,466 (195,136) | 269s |
| webarena.727 | DisLike all submissions created by PatientBuilder499 in subreddit videos | page document.querySelector('div.su @hundreds-of-civilian-turkish-volunteers- must have [must_include=['vote vote--user-downvoted… | 1 | **PASS** | — | — | 13 | 23 | 360,305 (291,776) | 499s |
| webarena.728 | DisLike all submissions created by sirbarani in subreddit sports | page document.querySelector('div.su @iran-football-legend-daei-will-not-atten must have [must_include=['vote vote--user-downvoted… | 1 | **PASS** | — | — | 9 | 9 | 246,562 (200,704) | 541s |
| webarena.729 | DisLike all submissions created by AdamCannon in subreddit UpliftingNews | page document.querySelector('div.su @same-sex-marriage-is-now-legal-in-all-of must have [must_include=['vote vote--user-downvoted… | 1 | **PASS** | — | — | 10 | 12 | 292,504 (189,184) | 301s |
| webarena.730 | DisLike all submissions created by Hrekires in subreddit news | page document.querySelector('div.su @gov-whitmer-signs-bills-to-repeal-right- must have [must_include=['vote vote--user-downvoted… | 10 | **PASS** | — | — | 12 | 25 | 302,701 (261,504) | 416s |
| webarena.731 | Edit my post on Nvidia RTX 4090 by adding a line to the body that says "EDIT: This news aged w… | page text @nvidia-rtx-4090 must have [must_include=['EDIT: This news aged well', 'Crazy device for ML!']] | Nvidia RTX 4090 | **PASS** | — | — | 14 | 18 | 332,670 (294,976) | 212s |
| webarena.732 | Edit my post on The Night Agent by adding a line to the body that says "Done watching, pretty … | page text @the-night-agent-renewed-for-season-2-at- must have [exact_match=Done watching, pretty cool!] | 134868 | **PASS** | — | — | 14 | 12 | 388,978 (246,400) | 280s |
| webarena.733 | Edit my post on Star Trek Starfleet Academy series by adding a line to the body that says "Eve… | page text @star-trek-starfleet-academy-series-from- must have [exact_match=Every watch makes me feel like a kid again] | Every watch makes me feel like a kid again | **PASS** | — | — | 7 | 7 | 143,211 (120,576) | 202s |
| webarena.734 | Edit my post on Ted Lasso by adding a line to the body that says "Done watching. I love the re… | page text @ted-lasso-season-3-premiere-scores-870k- must have [exact_match=Done watching. I love the renew!] | done | **PASS** | — | — | 9 | 10 | 260,787 (224,192) | 272s |
| webarena.735 | Edit my post on Lord of the Rings by adding a line to the body that says "The cast is amazing!" | page text @lord-of-the-rings-the-rings-of-power-sea must have [exact_match=The cast is amazing!] | The cast is amazing! | **PASS** | — | — | 20 | 26 | 676,416 (609,728) | 389s |

ᶠ = counted as a pass by the hand judging pass, not by the harness.


## What it was good at

Task types with three or more instances, 60%+ solved.

| task type | solved |
|---|---|
| Change my reddit bio to "{{x}}" | 5/5 (100%) |
| Open the thread of a trending post on the forum "{{x}}" and subscribe. | 5/5 (100%) |
| Post my question, "{{x}}", in a subreddit where I'm likely to get an answer | 5/5 (100%) |
| Post a review of my recent reading "{{x}}" in the r/books with my comment "{{x}}". | 5/5 (100%) |
| Create a discussion post about "{{x}}" in a relevant subreddit and ask users for their opinions with the simp… | 4/5 (80%) |
| Reply to the post with my comment "{{x}}" | 2/3 (67%) |

## What it was bad at

Task types with three or more instances, under 60% solved.

| task type | solved |
|---|---|

## Why the 17 failures happened

| cause | count | share of all failures |
|---|---|---|
| wrong count | 2 | 12% |
| target was already upvoted before the episode; agent misidentified the newest post | 2 | 12% |
| post body contains the required note verbatim and the correct image; only the URL-match fails | 2 | 12% |
| named the wrong posts | 1 | 6% |
| named the wrong books | 1 | 6% |
| named the wrong author/book | 1 | 6% |
| evaluator found no forum description at all | 1 | 6% |
| both program_html checks (note text + exact image hash) pass; only the subreddit-name capitalization in the URL check fails | 1 | 6% |
| both program_html checks pass; only the URL check fails | 1 | 6% |
| posted to r/AskReddit; gold wanted r/machinelearning or r/deeplearning | 1 | 6% |
| posted to r/gaming; gold wanted r/games (a different subreddit) | 1 | 6% |
| post body contains both required phrases (case differs from the check) and the subreddit is DIY in a different case than gold's f/diy | 1 | 6% |
| replied to the wrong comment; text has nothing to do with the requested reply | 1 | 6% |
| both program_html checks read back 'vote--user-downvoted' on the two gold posts, matching the required content | 1 | 6% |
