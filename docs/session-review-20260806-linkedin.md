# Session review — LinkedIn profile build (`logs/20260806-040306`)

An external agent (opencode) drove the toolkit for ~54 minutes to fill in a
LinkedIn profile. This is a review of what it actually did, read from the
session log rather than from its own summary — 228 commands, 14 failures, 81
recorded screenshots.

The agent's own writeup is accurate on outcomes. This review is about the parts
it could not see: where the time went, which affordances it never touched, and
which of its struggles are toolkit defects rather than LinkedIn's fault.

---

## 1. What happened

| Phase | Commands | Wall time | Share |
|---|---|---|---|
| Login | 4 | 1m12s | 2% |
| **Wrong-profile detour** | 31 | 6m11s | 12% |
| Headline + city + industry #1 | 20 | 4m31s | 8% |
| About | 11 | 2m39s | 5% |
| Industry #2 | 7 | 1m24s | 3% |
| Experience 1 | 18 | 3m24s | 6% |
| Experience 2 | 22 | 4m48s | 9% |
| Education | 14 | 2m58s | 6% |
| **Skills ×7** | 45 | 10m25s | 19% |
| **Industry #3–#7** | 56 | 12m33s | 23% |
| **Total** | **228** | **53m49s** | |

Only ~26 minutes went into work that landed. **Industry alone burned 14m20s
across seven attempts and never persisted.** The wrong-profile detour cost
another 6 minutes. Skills cost 10 minutes for 7 rows — 6.4 commands per skill,
where the flow is really type → pick → save → add-more.

Actual command time was 367s. The other ~2,860s was the agent thinking between
commands. That ratio matters: **the cost of this session was round trips, not
browser latency.** Anything that collapses N commands into 1 is worth far more
than anything that makes a command faster.

### Failures

14 of 228 (6%). Notably, **7 of the 14 were schema rejections, not page
problems** — the agent guessing at the API surface:

| Type | n | What |
|---|---|---|
| `invalid_op` | 7 | `timeout: 15000`, `get_text max_length`, `find diff:false`, `hover at:`, `press ArrowDown`, list-instead-of-object ×2 |
| `element_not_found` | 4 | 4 of these were `wait_for` on typeahead options that never matched |
| `not_interactable` | 3 | all three were LinkedIn dropdown options |

---

## 2. The headline finding: 46% of all commands were `run_js`

**106 of 228 commands were `run_js`.** Breakdown of what they did:

| Purpose | n |
|---|---|
| Read/scrape the DOM | 40 |
| Click something | 35 |
| Click the Save button | 17 |
| Synthetic typing / event dispatch | 12 |
| Focus a field | 2 |

Every one of those has a first-class op. The agent had `find`, `click`, `input`
and `press` available and chose raw JavaScript instead — for the *Save button*,
seventeen times.

This is a scorecard for the toolkit. An agent does not write 106 lines of
`document.querySelectorAll` because it prefers to. It does it when the ops are
not answering the question. Section 4 is that list.

> **Correction.** An earlier draft claimed this habit was *why* industry failed
> — that synthetic `HTMLElement.click()` cannot commit a React typeahead. That
> was wrong; section 3 below replaces it with what a live reproduction actually
> showed. Untrusted clicks were never the problem. The `run_js` habit made the
> session slow and hard to debug, not broken.

---

## 3. Root cause of the industry failure

Established by reproducing it live against the same page, not by reading the
log. **Two causes, compounding.** Neither is the one the agent reported, and
neither is an events-are-not-trusted problem.

### 3a. The industry name does not exist (the primary cause)

LinkedIn's current taxonomy has no "Information Technology & Services". A search
for `Information` returns exactly three:

- Technology, Information and Internet
- Information Services
- Technology, Information and Media

Type a name that is not in the taxonomy and the typeahead renders **a row
echoing your own query, with no entity behind it**. Clicking it looks like a
successful selection: the list closes and the field shows the text. The captured
SDUI payload shows why it is not — the form keeps two separate state keys:

```
industryTextIntroForm   ← the typed text
industryIdIntroForm     ← the entity id the save actually reads
```

The echo row fills the first and leaves the second empty, so
`saveProfileIntroForm` never fires and the form renders **"Industry is a
required field"**.

That error was on screen the whole time. It is plain text with **no
`role="alert"`, no `aria-invalid`, and no `aria-describedby` link** — so the
agent's error probes, which looked for exactly those, came back empty and it
concluded the form had submitted silently. It had not submitted at all.

### 3b. `input`'s clear was silently appending (the toolkit's own bug)

Reproduced minimally on the live field:

```
field before:  "Technology, Information and Internet"
input {clear: true, value: "Finance"}
field after:   "Technology, Information and InternetFinance"
```

Traced with an event log on the real input:

```
change   trusted=false  val=''                                     ← clear(): change only, no input event
keydown  trusted=true   val='Technology, Information and Internet' ← already restored
```

`clear()` empties the value, fires `change` alone, and blurs the field. A
component that tracks its own text learns nothing from `change`, so it reverts
to its last committed value the moment `send_keys` takes focus — and the typing
appends to text that was supposed to be gone. `input` then reported the
concatenation as the value it wrote, with `ok: true`.

This did not break the session's *first* attempt (the field started empty) but
it poisoned **every retry**: each one appended to the last, so the typeahead was
searching progressively garbled strings. That fully explains the "inconsistent
dropdown behaviour" the agent reported and could not pin down.

Fixed — see `known-issues.md` #14.

### What was disproven

- **"A real user's mouse/keyboard events aren't fully reproducible via scripted
  dispatch here."** False. `click` with `at:` is a trusted pointer sequence and
  commits the option correctly (`hit: p._9c87fdd9._984bed78`, value updates).
  The agent's own plain `click` at seq 201 worked too.
- **"The form submits an empty industry value."** It does not submit. No
  mutation request is issued at all — confirmed against both the Resource
  Timing log and a `fetch`/XHR interceptor.
- The `tabindex="-1"` inner div refusing Selenium's click (seq 220, 223) is
  real but incidental: clicking the option's label works.

---

## 4. Tools it had and never used

This is the list you asked for. Every item below is already implemented and
shipping.

### 4.1 `click` with `at: [x, y]` — coordinate click

`src/abt/ops/interact.py:235` — `_click_at`, a real pointer sequence with
`isTrusted` true. **Never called once**, and it is what I used to drive the
typeahead during the reproduction.

The log shows how it got missed: at seq 24 the agent tried
`{"op":"hover","css":"…","at":[700,20]}` and got `at: Extra inputs are not
permitted`. `hover` has no `at`; `click` does. From that one rejection the agent
appears to have concluded coordinates were unavailable toolkit-wide and never
revisited it — a schema inconsistency that closed off a whole technique.

Two caveats against overstating this. It is **documented**, in
`toolkit-workflow.md:272` ("Clicking what the DOM cannot address"), which the
agent either did not read or did not connect. And it would **not** by itself
have fixed industry — a plain `click` on the option commits it just as well.
The blockers were 3a and 3b.

### 4.2 `click` with `force: true`

**Zero uses in 228 commands**, despite three `not_interactable` failures that
are exactly what it is for — `src/abt/ops/interact.py:224` falls back to a JS
click, and for the `tabindex="-1"` inner div that may well have been enough to
try.

The error messages are why. The "covered by another element" branch
(`interact.py:185`) *does* say `Pass force:true`. The other two branches — the
"zero size" branch at `interact.py:180` (hit at seq 97) and the Selenium
`ElementNotInteractableException` branch at `interact.py:220` (hit at seq 220
and 223) — **do not mention `force` at all.** The agent only ever saw the two
messages that don't advertise the remedy.

### 4.3 `read_network` and `read_console`

Never used. The single question the whole industry saga turned on — *is the
field in the Save payload?* — is one `read_network` call on the save POST. The
agent instead answered it seven times by reload-and-scrape, at ~2 minutes a
round. `read_console` would likely have shown the client-side validation
rejecting the uncommitted entity, too.

### 4.4 `press` on the option element rather than the input

`press` targets any element. The typeahead pattern for a `tabindex="-1"` option
is focus-then-`return` on the *option*. The agent only ever pressed keys on the
input.

### 4.5 `find_full` / `find` with `mode: "full"`

Used exactly once (seq 22), then abandoned — which explains a large share of
those 40 scraping `run_js` calls. Default `find` is *shell* mode:
`cloneNode(false)`, children stripped (`src/abt/ops/read.py:19`). So
`find div[role="option"]` returned:

```html
<div class="bf29f068 db1a78ba" role="option" id="«rt»" aria-selected="false"></div>
```

The option's label — the only thing the agent needed — is invisible in the
default output. Every dropdown read after that went through `run_js`. See 5.2.

### 4.6 `screenshot`

Never requested, in a session where 81 screenshots were being recorded to disk
automatically. The agent drove LinkedIn's profile UI for an hour without once
looking at it, and answered "does the profile card show the industry?" by
scraping `innerText`.

### 4.7 `/commands` batching

Two batch attempts, both malformed (seq 12, 144), both abandoned after the
error — the agent posted a bare list to `/command` (singular) rather than
`/commands`. With ~12s of model time per round trip, the skills phase alone
(45 commands, 4 of which repeat verbatim per skill) was a natural batch and
would have saved several minutes.

### 4.8 `find` with `shadow: true`

Never used, though **every diff response in this session carried the shadow-root
footnote** (`hosts: 1`, "content inside a shadow root is not in this report").
The note fired ~100 times and was acted on zero times.

### Also unused

`get_html`, `scroll`, `diff`, `back`/`forward`/`reload`, `tab_*`, `alert`.

---

## 5. Limitations of the exposed surface — toolkit defects

These are the ones I'd fix. Ordered by what they cost this session.

### 5.1 `at` is on `click` but not on `hover` — and nothing says so

Cost: the session's one unfinished deliverable (4.1). The rejection message
`at: Extra inputs are not permitted` is a pydantic default; it does not say
"`click` supports this." Fix: either add `at` to `hover` (it is the same
ActionChains move), or make the rejection name the op that has it.

### 5.2 `find`'s default hides the text you searched for

Cost: ~40 `run_js` calls. Searching for an element by role and getting back a
tag with no content is a dead end for anything text-bearing — options, menu
items, list rows. `mode: "full"` exists but is not the default and not
suggested. Fix options: include a `text` field (the element's `textContent`,
truncated) in shell mode; or when shell output is empty and the element has
text children, say so in the response.

### 5.3 `find` reports `visible: true` for elements Selenium then refuses

seq 219 → 220 and seq 222 → 223. `find` computes visibility as
`getClientRects().length > 0` (`read.py:20`); Selenium's interactability check
is stricter. So `find` hands out a ref labelled visible and `click` rejects it
one command later. That contradiction is what pushed the agent to `run_js`.
Fix: either align the two, or have `click`'s error say "`find` called this
visible; it has rects but is not interactable — try `force:true` or `at:`."

### 5.4 `not_interactable` errors don't advertise `force`

Cost: `force` went unused across three failures that were its use case (4.2).
Two of three error paths omit it. Cheap fix, high value.

### 5.5 `timeout` has no unit, and the ceiling reads as arbitrary

`{"timeout": 15000}` → `Input should be less than or equal to 300`. The agent
was thinking milliseconds; the field is seconds. A caller who reads only the
error learns the wrong thing (that 300 is a max) instead of the right thing
(that the unit is seconds). Fix: name the unit in the field description and in
the validation message — `timeout is in seconds (max 300); 15000 looks like
milliseconds`.

### 5.6 `diff` is accepted on some ops and rejected on others

`diff:false` was passed 31 times and worked on `click`/`input`/`hover`/`press`;
on `find` it errors, because `find` isn't in `DIFFABLE_OPS`
(`ops/__init__.py:47`). A caller reasonably adds `diff:false` everywhere to
save tokens, and gets punished on the read ops where it is merely redundant.
Fix: accept and ignore `diff` on non-diffable ops.

### 5.7 `press` rejects DOM key names with no suggestion

`ArrowDown` → error listing the *modifiers*, not the key names. The DOM
spelling is what an agent knows. Fix: accept DOM `KeyboardEvent.key` spellings
as aliases (`ArrowDown` → `arrow_down`), or at minimum fuzzy-match and say
"did you mean `arrow_down`?" (`interact.py:57`).

### 5.8 A bare list is only rejected by the *singular* endpoint

~~`/commands` rejects a bare list.~~ **Wrong — it accepts one**
(`server.py:148`). Both failures were the agent posting a batch to `/command`.
The error it got, `command must be an object, got list`, is accurate but says
nothing about the endpoint that would have taken it. Fix: name `/commands` in
that message.

### 5.9 The shadow-root footnote is unactionable at ~100 repetitions

Fired on essentially every response. A note that always fires carries no
signal and trains the reader to skip it — including on the one page where it
mattered. Consider suppressing it when the host count is unchanged from the
previous response.

### 5.0 `input`'s clear silently appended — FIXED

The one defect here that actually broke the work rather than slowing it down.
Root cause and trace in 3b; fix and regression tests in `known-issues.md` #14.
Listed out of order because it is the only entry in this section that was a
correctness bug rather than an ergonomic one.

### 5.10 No composite "pick from a typeahead" op

The gap under all of this. Type → wait for options → read labels → click the
right one → verify the field committed is a 5-command dance the agent performed
(badly) ~12 times: for company, school, degree, 7 skills, industry, and city.
A `pick` op — `{"op":"pick","css":"input[…]","value":"…","match":"startswith"}`
— that types with real keys, waits for `[role=option]`, matches on the option's
*rendered text* (including nested), clicks with a real pointer event, and
returns the committed value would have collapsed roughly 60 commands in this
session and is the single highest-value addition on this list.

### 5.11 No LinkedIn playbook

`guidelines/` has entries for Messenger, Google Docs/Sheets and two media
sites. Nothing for LinkedIn, and **nothing anywhere in the repo mentions
"typeahead", "combobox" or "autocomplete"** — the pattern that ate 45% of this
session. `toolkit-workflow.md` is the right home for the generic version.

---

## 6. What the agent did well

Worth recording, since the rest of this is critical:

- **Caught the wrong profile before writing to it.** `/in/shahariarmunir` is a
  stranger's page; the real one is `/in/shahariar-munir-0b0b56427/`. It noticed
  the "Invite to connect" affordance and re-derived the correct URL through the
  Me menu. That detour cost 6 minutes and prevented an unrecoverable mistake on
  someone else's profile. Correct call.
- **Verified by reloading** rather than trusting the post-save DOM. That is how
  the industry failure was caught at all.
- **Used `select by_text`** for all 14 date/type dropdowns — the right op, zero
  failures.
- **Stopped and reported** instead of grinding further.

In fairness to it, the thing that actually defeated the session — 3b — was a
toolkit bug that reported `ok: true` and handed back a corrupted value. No
amount of care at the agent's level would have surfaced that; it took an event
trace on the live field.

---

## 7. Recommendations, in order

0. ~~Fix `input`'s silent append~~ — **done** (3b, `known-issues.md` #14)
1. **Add `at` to `hover`, or make the schema rejection point at `click`** (5.1)
2. **Mention `force:true` in all three `not_interactable` messages** (5.4)
3. **Put element text in `find`'s shell output** (5.2)
4. **Add the `pick` op for typeaheads** (5.10) — biggest remaining win, and 3a
   is the argument for it: it should verify the field *committed an entity*,
   not just that text landed
5. Unit-label `timeout`; accept DOM key names; accept `diff` everywhere; name
   `/commands` in the singular endpoint's error (5.5–5.8)
6. Reconcile `find`'s `visible` with `click`'s interactability (5.3)
7. Write a LinkedIn playbook and a generic typeahead section in
   `toolkit-workflow.md` (5.11) — including "after a failed save, read the
   form's text; the error may carry no ARIA at all" (3a)
8. Add a "before you reach for `run_js`" table to `toolkit-workflow.md` — the
   46% number is the argument for it
