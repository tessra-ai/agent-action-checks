# Rely-1 M1 report: label set (built; waiting for labels)

**Status:** the label set and both review sheets are built. The gate needs people's answers,
so M1 stops here. Spend: **$0**. Train and dev only; no test action was read.

## What is in the set

**401 statements** from **147 actions** (train + dev, packet v1).

All 5,842 agent sentences in train + dev were split into units. The earlier claims check
extracted 658 claims in these actions: 122 false, 331 true, 205 unverifiable. They were placed in
units only to choose what to look at. The complete quote is tried first; a quote no single unit
holds is cut into pieces and goes to every unit holding one.

| Claim placed | false | true | unverifiable |
|---|---|---|---|
| in one unit | 89 | 217 | 141 |
| same words in several units (latest taken) | 6 | 13 | 14 |
| spanning several units (all taken) | 19 | 44 | 36 |
| customer text: not a unit | 4 | 20 | 7 |
| tool-call string: not a unit | 2 | 9 | 0 |
| too short to place | 2 | 12 | 3 |
| not found | 0 | 16 | 4 |

(The "spanning" row includes 14 claims where one piece also appeared in an earlier unit; the
latest was taken. `results/summary.json` lists them apart. A piece found only in a list's lead-in
goes to the lead-in's own unit, not to an item under it.)

Every false claim that is agent text is in a unit, so every mismatch is in the set. The 8 false
claims left out are the customer's words, tool-call strings or two-word fragments.

| Why in the set | Statements |
|---|---|
| a mismatch (any false claim) | 141 |
| quoted by a ruling or a grader, not a mismatch | 90 |
| sample of matched | 70 |
| sample of unchecked | 60 |
| sample of no-claim | 40 |

## Counts by combination

Every count is statements. "Good" / "bad" is the M0 truth of the action; "over" means its packet
is over 8,192 tokens (decision 1). The full five-way table (stratum × pre-fill × truth × length ×
split) is in `results/summary.json`.

| Stratum | good | bad | ungraded | under 8,192 | over 8,192 | train | dev |
|---|---|---|---|---|---|---|---|
| mismatch | 48 | 79 | 14 | 105 | 36 | 97 | 44 |
| unchecked | 21 | 34 | 18 | 64 | 9 | 59 | 14 |
| matched | 38 | 40 | 8 | 79 | 7 | 67 | 19 |
| no claim | 55 | 42 | 4 | 87 | 14 | 80 | 21 |
| **all** | 162 | 195 | 44 | 335 | 66 | 303 | 98 |

| Pre-fill | good | bad | ungraded | under | over |
|---|---|---|---|---|---|
| MC (quoted as false) | 1 | 13 | 0 | 14 | 0 |
| not MC | 161 | 182 | 0 | 286 | 57 |
| of which quoted as support | 47 | 35 | 0 | 74 | 8 |
| none | 0 | 0 | 44 | 35 | 9 |

Of the 343 `not MC` pre-fills, 82 are quoted as support (nothing more is pre-filled for them: a
support quote may be the grader's own inference). The other 261 rest only on "the action has a ruling and no reason quotes this sentence". That is weak
evidence, and the random 40 tests it.

**48 mismatches sit on good actions** (plan step 3): each is labelled like any other, since a
good action can still have been agreed on a false price.

## Review sets

| Sheet | Statements | MC pre-fill | not MC | none | under / over 8,192 | good / bad / ungraded actions |
|---|---|---|---|---|---|---|
| Prithvi | 54 (14 MC + random 40 of the not-MC) | 14 | 40 | 0 | 48 / 6 | 20 / 34 / 0 |
| Second person (blind) | 30, drawn from Prithvi's 54 | 8 | 22 | 0 | 26 / 4 | 13 / 17 / 0 |

## Findings so far

- **A quote is not a judgement.** 96 statements are quoted by a reason. Read by Claude, most
  quotes are support: "the agent listed '3 checked bags (all free as a gold member)' and the user
  said yes". Treating every quote as a contradiction would pre-fill 96 MC. Reading the falsity
  word in the quote's own clause leaves 14 quoted as false (13 on bad actions, including the
  second-cheapest and certificate-balance anchors) and 82 as support. On Claude's read, 12 of the
  14 are real false statements; 2 are mis-fires (a quoted "change of plan" in a clause saying it
  "is not covered", and a quote of the customer's words). The Gaming Mouse is not among them:
  retail has no graders' reasons to quote it. The support quotes still say the statement
  mattered, but they are not taken as evidence that the records back it.
- **Prithvi's own reasons rarely quote.** 4 of his 14 airline answers and 6 of 10 retail answers
  have a written reason. Of 156 citations in the set, 152 are the graders' and 4 Prithvi's (all
  from his corrections). The pre-fill is mostly the graders' reading, which Prithvi then checks.
- **Long packets are thin in the review.** No MC pre-fill comes from a packet over 8,192 tokens.
  Prithvi's set has 6 over-limit statements and the second set 4, against 66 in the label set
  (36 of them mismatches). Agreement on long packets cannot be measured from these sheets as
  drawn. Adding a fixed number of over-limit statements to both sheets (for example 15 of the 32
  over-limit mismatches) would fix that. It changes the plan's "random 40", so it is Prithvi's
  call.
- **The falsity-word rule still misses and over-fires** (the two mis-fires above). A reason
  that calls a quote wrong in another clause does not fire. Prithvi sees every MC pre-fill, and
  the random 40 covers the misses.
- **A quote of a list's lead-in does not cite its items.** "a change of plans" quoted from a
  lead-in no longer marks the list item under it (an eligibility claim) as supported; found by the
  Codex pre-commit review.
- **Later calls are shown, but not as agreed.** The packet's later-calls section (M0 decision 2)
  lists what the agent proposed next with no customer message in between. That includes calls
  the customer did not agree to (the Gaming Mouse return). The sheet asks the reviewer to judge
  agreement when a total covers several calls.

## Codex pre-commit review

Rounds on this change (M0 decisions + M1): the first found a P1, the later-calls section
presenting calls as agreed (fixed: "agreement not verified"; see M0 Report, decision 2). Fixed
P2s: a retry of the proposed call listed as another call; multi-line claims placed on one
fragment; a lead-in quote citing the items under it; bold headings not taken as lead-ins; sheet
answers bound to the full sheet content, imports without a reload, progress counting only
complete answers; the v0 trim record protected; the falsity word read in the quote's own clause
(it had marked three correct "change of plan" units MC, which also took them out of the random
40's pool); a unit cited both ways taking the false citation; token counts checked against the
packet file; support quotes no longer pre-fill "supported" or "material"; an indented line inside a
list keeps the list's lead-in. The random 40 are now drawn only from units pre-filled `not MC` (a P1: drawn
from all non-MC units, 5 had no pre-fill, so the "36 of 40" gate could not be met); a claim
fragment found only in a list's lead-in goes to the lead-in, not to an item under it. Left: the
two remaining falsity-word mis-fires above, which Prithvi reviews (Codex raised this pattern in
four rounds, last naming `01M61Q3RXQGMXJ4EH3VB7AR7B2:T3.3` and `:T6.5`, both from a reason saying
"change of plan" "is not covered"; one narrowing was made, and further tuning of a review heuristic is not worth it);
later calls are now found when this call ran inside a batch (21 packets carry them, not 16; the
label set did not change).

## Waiting on

1. Prithvi's answers on `review/prithvi_sheet.html` (54 statements).
2. A second person's blind answers on `review/second_sheet.html` (30). Who that is, is
   Prithvi's decision.
3. Prithvi's answer on the consent marker (M0 Report, `review/consent_13.json`), and on the
   later-calls wording (M0 Report, decision 2).

When the answers arrive, the scoring is written and committed first, then run once: pre-fill
against Prithvi on the random 40; Prithvi against the second person on the 30; every number
under and over 8,192 tokens.

## Files

- `units.py`, `build.py`, `sheet.py`, `sheet_template.html`
- `results/label_set.jsonl` (389 statements, sha256 in `results/summary.json`),
  `results/summary.json`
- `review/prithvi_sheet.html`, `review/second_sheet.html`
