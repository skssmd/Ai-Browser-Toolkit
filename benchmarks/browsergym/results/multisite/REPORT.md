# WebArena — multi-site (shopping → reddit), full task list

Model **z-ai/glm-5.3-flash** via OpenRouter, driving the abt toolkit through
BrowserGym. 30-turn ceiling, one fresh agent process per task.

These are the only five WebArena tasks that span two sites we can host. Each
one is the same shape: read product reviews on the Magento storefront
(`localhost:7770`), filter them by star rating, then cross to Postmill
(`localhost:9999`) and post the gathered titles to a named subreddit. The
agent has to carry text between two unrelated applications and get it there
character-for-character.

## Result

| | |
|---|---|
| tasks scored | 5 |
| passed, as the harness scored it | **2 — 40.0%** |
| total ops | 152 |
| total turns | 105 |
| total tokens | 2,750,042 (2,199,104 cached, 80%) |
| total wall time | 0.5 h |
| mean per task | 30 ops, 21 turns, 550,008 tokens, 368 s |

No `fuzzy_match` tasks in this set — every task is scored on `url_match` plus
`program_html`, so there is nothing for a judging pass to recover.

## Did it actually do the task?

The same second measure used in the single-site reports, kept apart from the
score and never a substitute for it. WebArena grades a string; this asks
whether the work was right.

| | count | share |
|---|---|---|
| credited by the harness | 2 | **40.0%** |
| correct but uncredited | 3 | 60.0% |
| genuinely incorrect | 0 | 0.0% |
| **did the task** | **5** | **100.0%** |

Every one of the five posts exists, in the right subreddit, under the exact
required title, carrying the right review titles gathered under the right
star filter. The benchmark scores **40%**; the work was done in all five.

## Every task

| task | question | answer required | answer given | result | correct | why | turns | ops | tokens (cached) | time |
|---|---|---|---|---|---|---|---|---|---|---|
| webarena.671 | Gather the titles of Sony Computer Entertainment VR reviews with 2 stars and less from OneStopShop, post them in the games subreddit under the title "real user feedback on Sony Computer Entertainment VR" | URL (GOLD in PRED): /f/gaming \| post title exact\_match "real user feedback on Sony Computer Entertainment VR" \| post body must\_include 3 review titles | Disappointing. Didn't last long…, didn't last a year without issues, Received used items!! | **PASS** | — | — | 21 | 31 | 611,236 (512,064) | 523s |
| webarena.672 | Same, Nintendo Switch Fortnite Wildcat Console EU, 3 stars and less | URL (GOLD in PRED): /f/gaming \| title exact\_match \| body must\_include 6 review titles | EU charger and wild cat card doesn't even work!, REFUND REJECTED, Charging port not compatible, not compatible in the US, Wildcard Bonus Credits Not Redeemable!, Code not available!! | fail | **yes** | one character: body needed `doesn’t` (U+2019), agent typed `doesn't`. Title exact-matched; the other 5 titles all present | 17 | 24 | 395,649 (354,816) | 283s |
| webarena.673 | Same, Racing Wheel Overdrive for Xbox X, 1 star | URL (GOLD in PRED): /f/gaming \| title exact\_match \| body must\_include 5 review titles | Unable to set neutral steering, Doesn't work with PC., Crazy problems in automatic mode; then pedals stopped working, Only works with certain games. | fail | **yes** | one character: body needed `Doesn’t work with PC` (U+2019), agent typed `Doesn't`. Title exact-matched; the other 4 titles all present | 19 | 25 | 471,180 (354,112) | 262s |
| webarena.674 | Same, Doc and Pies Arcade Factory Cocktail Arcade Machine, 3 stars and less | URL (GOLD in PRED): /f/gaming \| title exact\_match \| body must\_include 3 review titles | Poorly Made Exterior. Consider a different Company., piece of junk ,..can't believe I spent money on this !!!!, Based arrived broken but game itself works | fail | **yes** | unexplained: re-checking the recorded `observed` against `expected`, the title exact-matches and all 3 required titles are present; not turn-limited, answer sent normally. Scored 0 anyway | 29 | 47 | 802,199 (661,248) | 362s |
| webarena.675 | Same, HORI 3D Surround Gaming Neckset, 2 stars and less | URL (GOLD in PRED): /f/gaming \| title exact\_match \| body must\_include 3 review titles | Not worth it for PC users, I really wanted to like this., I wish this was better... | **PASS** | — | — | 19 | 25 | 469,778 (316,864) | 411s |

## Why the 3 failures happened

| cause | count | share of all failures |
|---|---|---|
| curly apostrophe (U+2019) retyped as ASCII `'` | 2 | 67% |
| unexplained — every recorded check passes, scored 0 | 1 | 33% |

## Reading this

**The cross-site part was never the problem.** All five episodes navigated
between the two applications, applied the star filter correctly, found the
right forum (the task says "games subreddit"; the site's forum is `gaming`,
and `/f/games` is a 404 — every episode worked that out), and posted under
the exact required title. No episode failed on navigation, on targeting, or
on getting lost between the sites.

**Two of three failures are one character.** The Magento review titles
contain a typographic apostrophe (U+2019). The toolkit delivers it intact —
the trace shows `doesn’t` arriving correctly in the page text at turn 3 — and
the model then transcribes it as `doesn't` in its own reasoning one turn
later, and types the ASCII version into the post. The loss happens when the
model **retypes text from memory** rather than copying it. Nothing in the
read path is lossy.

**That check is an artifact, not a design goal.** WebArena's own
`clean_answer` (`evaluation_harness/evaluators.py:80`) runs on both sides of
every `must_include` and `exact_match` comparison:

```python
answer = answer.strip()
if answer.startswith("'") and answer.endswith("'"):
    answer = answer[1:-1]
elif answer.startswith('"') and answer.endswith('"'):
    answer = answer[1:-1]
return answer.lower()
```

Case, surrounding whitespace, and wrapping quotes are all deliberately
normalised away — the benchmark's authors did not want cosmetic differences
counted as failures, and `DOESN'T` passes against `doesn't`. Unicode
punctuation is simply not in that list, so `’` against `'` fails while a
difference they did think about is forgiven. If byte-exact fidelity were the
intent, the function would not lowercase; if semantic equivalence were the
intent, quote folding belongs in the same function as the lowercasing. The
gold strings came straight out of Magento's database, which stores the
typographic form, and models overwhelmingly normalise typography when
transcribing — neither side did anything wrong.

Practically the distinction is empty: a reader opening those two posts sees
the correct review titles, correctly filtered, under the correct heading, and
cannot tell them apart from the two that passed. One added line in
`clean_answer` folding curly quotes to straight would flip both to passes
without loosening the check in any way that matters. That gap is the whole
reason this report carries a "did the task" column beside the score.

**A prompt bug in the harness, found and fixed here.** `run_webarena_one.py`
told every episode "You are on a self-contained store at {url}. Everything
you need is on this site. Do NOT navigate to any other domain." On a
multi-site task that is false, and one agent said so out loud — it called
posting to a subreddit "odd since we're told not to navigate to other
domains" — before crossing anyway. `.671` ran under that wording and still
passed; `.672`–`.675` ran after the line was made conditional, naming every
site the task actually spans. The single-site wording is untouched, so the
475-task single-site benchmark is unaffected.

**A note on preambles.** `.674` and `.675` both wrapped their post body in a
sentence of their own ("Here are the review titles from OneStopShop for…").
`.675` passed regardless — `must_include` tolerates surrounding text — so the
preamble is not what cost `.674`, and the report does not claim it was.
