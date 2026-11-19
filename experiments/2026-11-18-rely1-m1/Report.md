# Rely-1 M1 report: label set (built; waiting for labels)

**Status:** the agreement labels, the label set and both review sheets are built. The gate needs
people's answers, so M1 stops here. Spend: **$0** (no model or API calls; Claude subagents read
conversations in session for the agreement pre-fill). Train and dev only; no test action was
read.

Rebuilt on 2026-11-18 after Prithvi's second set of decisions: agreement labels replace the
consent marker, no-agreement actions are left out, packet v2 (no later calls in the main text),
an over-limit block on both sheets, a plain-language second sheet, and two more gate figures.

## Agreement (`agreement.py`, `results/agreement.jsonl`)

| Source | Agreed | No agreement | Unsure | Actions |
|---|---|---|---|---|
| Prithvi's ruling (the 13 with no "yes") | 7 | 6 | 0 | 13 |
| Code-rule pre-fill, **for Prithvi's review** | 37 | 0 | 0 | 37 |
| Claude (subagent or in-session) pre-fill, **for Prithvi's review** | 96 | 26 | 2 | 124 |
| **All train + dev** | **140** | **32** | **2** | **174** |

- **Decision A (Prithvi, 2026-11-19): the code rule no longer decides anything.** Its 37 "yes"
  answers are pre-fills like the others, on his sheet, so all 161 non-ruled actions are reviewed.
  The rule's "obvious" needs a clear yes, no write between it and this call, and the agent's
  confirmation (or the yes) naming **every** identifying argument of the call (reservation,
  order, item and flight IDs, each as often as the call uses it) **and every date** ("2024-05-28"
  or "May 28"). It was tightened three times after Codex pre-commit reviews:
  - one shared identifier was enough: it accepted `01M61Q97RQ2PHBHM7S9KVFPCEJ`, where the customer
    agreed to upgrade only the outbound flight and the call upgrades both legs (24 actions moved
    to reading; that one came back "no");
  - repeats were not counted (no action moved);
  - dates were ignored: it accepted `01M61PXKGCSJZJETM64WV2AHM4`, where the customer approved
    "HAT082 and HAT085 on May 28" and the call books HAT085 on May 29. Claude read it and
    pre-filled **unsure**: it may be the overnight connection the agent's summary got wrong.
  Claude had spot-read 11 cases of the loosest rule; all 11 were agreements.
- One Codex finding was not taken: it flagged `01M61Q79VR8ABNANRCE8DF12JV` (the call books HAT069
  on both legs) as a rule mistake. The agent's own confirmation listed "Return: May 25, HAT069",
  and the customer said yes to exactly that, so the agreement label stands. The wrong statement
  ("Return … HAT069", a JFK–SEA flight) is a material-contradiction candidate in the label set,
  not an agreement failure. Prithvi decides it on his sheet like every other pre-fill.
- The pre-fills are one read each against a written rubric, with the 13 rulings as calibration.
  Claude checked three of the "no" pre-fills against the conversations: a phone-number request
  answered by an address change, and a delay-compensation request answered by a passenger change,
  are clear; the third (an upgrade covering a flight the customer was never quoted) is a judgement
  call for Prithvi. The one "unsure" (a card "ending in 7334") is settled by its own records: the
  profile lookup shows `credit_card_9074831` ends in 7334. That is attached as a note; the
  pre-fill is left as read.
- **The no-agreement group** (32 actions, 27 retail and 5 airline): **none is graded "should
  run"** (28 bad, 4 ungraded). They hold 770 statements, 21 of them mismatches; none is labelled.
  Until Prithvi reviews the 26 pre-filled "no", their exclusion is provisional; `score.py` applies
  his answers before counting.
- **The Gaming Mouse anchor is in the no-agreement group** (pre-fill: the customer said to keep
  the mouse). Under the decision it is not labelled for material contradiction: it is a wrong
  action the customer never agreed to, which the plan's limits give to the judge. The other two
  anchors are pre-filled as agreed (second cheapest by the rule, certificate balance by a
  reading); Prithvi confirms both.

## What is in the label set

**380 statements** from **125 agreed (or unsure) actions**, out of 5,072 agent sentences in
those actions. The claim placement is computed over all train + dev actions:

| Claim placed | false | true | unverifiable |
|---|---|---|---|
| in one unit | 89 | 217 | 141 |
| same words in several units (latest taken) | 6 | 13 | 14 |
| spanning several units (all taken) | 19 | 44 | 36 |
| customer text: not a unit | 4 | 20 | 7 |
| tool-call string: not a unit | 2 | 9 | 0 |
| too short to place | 2 | 12 | 3 |
| not found | 0 | 16 | 4 |

| Why in the set | Statements |
|---|---|
| a mismatch (any false claim) | 120 |
| quoted by a ruling or a grader, not a mismatch | 90 |
| sample of matched | 70 |
| sample of unchecked | 60 |
| sample of no-claim | 40 |

## Counts by combination

Every count is statements. "Good" / "bad" is the M0 truth of the action; "over" means its packet
(v2, main text) is over 8,192 tokens. The five-way table is in `results/summary.json`.

| Stratum | good | bad | ungraded | under 8,192 | over 8,192 | train | dev |
|---|---|---|---|---|---|---|---|
| mismatch | 48 | 60 | 12 | 86 | 34 | 83 | 37 |
| unchecked | 18 | 41 | 14 | 66 | 7 | 57 | 16 |
| matched | 37 | 33 | 16 | 81 | 5 | 65 | 21 |
| no claim | 51 | 44 | 6 | 82 | 19 | 79 | 22 |
| **all** | 154 | 178 | 48 | 315 | 65 | 284 | 96 |

| Pre-fill | good | bad | ungraded | under | over |
|---|---|---|---|---|---|
| MC (quoted as false) | 1 | 13 | 0 | 14 | 0 |
| not MC | 153 | 165 | 0 | 261 | 57 |
| of which quoted as support | 47 | 35 | 0 | 74 | 8 |
| none | 0 | 0 | 48 | 40 | 8 |

Of the 318 `not MC` pre-fills, 82 are quoted as support (nothing more is pre-filled for them: a
support quote may be the grader's own inference). The other 236 rest only on "the action has a
ruling and no reason quotes this sentence". That is weak evidence, and the random 40 tests it.
7 statements sit on the two "unsure" actions; they stay in, flagged.

## Review sets

| Sheet | Statements | MC pre-fill | not MC | none | under / over 8,192 | good / bad / ungraded actions |
|---|---|---|---|---|---|---|
| Prithvi | 64: 14 MC + random 40 + 10 over-limit | 14 | 49 | 1 | 50 / 14 | 23 / 40 / 1 |
| Second person (John) | 35: 30 from Prithvi's first two blocks + 5 of his over-limit 10 | 9 | 26 | 0 | 28 / 7 | 13 / 22 / 0 |

Prithvi's sheet also carries the 161 agreement pre-fills (37 from the rule, 124 read).

The second sheet was checked in a headless browser at iPad, iPhone and laptop sizes: no script
errors, no sideways scrolling, answers survive a reload, and "Download my answers" saves one file
(`my-answers-second.json`). On a tablet it must be opened in a browser (Safari, Chrome), not a
file preview, which does not run the page; the sheet says so. Its worked examples come from tasks
with no statement on either sheet (the first choice, "Total price: $255", shared a booking
conversation with a scored card; found by the Codex review): `01M61Q2296XPPCWSA5259X6BSB`
("Since the booking was made within the last 24 hours, you are eligible for cancellation with a
full refund": yes; the record shows it was booked on 2024-05-02, and the conversation takes place
on 2024-05-15) and `01M61Q4QYXR822DYYJRZFTS68K` (a $1,698 upgrade fare for an upgrade the customer
turned down: no). Both are Claude's reading (M0 `label_definition.md`, cases 5 and 9).

## Good and bad actions behind each number (agreed or unsure actions only)

| | actions | good | bad | ungraded | (no agreement: bad / ungraded) |
|---|---|---|---|---|---|
| train | 112 | 45 | 48 | 19 | 17 / 4 |
| dev | 30 | 11 | 15 | 4 | 11 / 0 |
| fold 0 | 21 | 11 | **6** | 4 | 12 / 1 |
| fold 1 | 24 | 12 | 12 | 0 | 6 / 1 |
| fold 2 | 37 | 11 | 14 | 12 | 4 / 0 |
| fold 3 | 34 | 11 | 18 | 5 | 0 / 2 |
| fold 4 | 26 | 11 | 13 | 2 | 6 / 0 |

The folds (M0) were balanced on all actions. With no-agreement actions out, fold 0 has only 6 bad
actions: most of its retail tasks were not agreed. The folds stay frozen; a fold-0 catch rate
will rest on 6 actions and will say so.

## Findings so far

- **A quote is not a judgement.** 96 statements are quoted by a reason; most quotes are support
  ("the agent listed '3 checked bags (all free as a gold member)' and the user said yes").
  Reading the falsity word in the quote's own clause leaves 14 quoted as false (13 on bad
  actions; including the second-cheapest and certificate-balance anchors) and 82 as support. On
  Claude's read, 2 of the earlier MC pre-fills were mis-fires; after the no-agreement exclusion
  the remaining set still includes the "change of plan … is not covered" units
  (`01M61Q3RXQGMXJ4EH3VB7AR7B2`), which Prithvi reviews.
- **Prithvi's own reasons rarely quote.** 4 of his 14 airline answers and 6 of 10 retail answers
  have a written reason; almost every citation is a grader's.
- **Retail is mostly not agreed.** 27 of 73 retail actions have no agreement on the current
  labels (the retail capture's agent proposed many calls the customer never confirmed).

## Codex pre-commit review

First M1 build: nine rounds; two P1s fixed (later calls shown as agreed; random 40 drawn from
units with no pre-fill), about fifteen P2/P3s fixed; the falsity-word mis-fire left for review.

This rebuild: P1s fixed, each the first time it was raised: the agreement rule accepting a call
wider than the yes (two tightenings: every identifier, then dates); the scorer ignoring
Prithvi's agreement corrections; a worked example sharing a booking with a scored card. One P1
declined, with reason (above: `01M61Q79VR8ABNANRCE8DF12JV`). P2s fixed: stale or incomplete
answer files refused, and the sheets bound to the label-set and agreement files; full records,
lookup arguments and the policy under "Show more"; the gate marked unevaluable when agreement
answers shrink its samples; the ledger and an override path on the agreement cards; the missed-MC
estimate made per length group.

**Handed to Prithvi under the retry cap, and decided:** after three fixes, Codex flagged the
agreement rule a fourth time (it ignores payment terms and the operation; its example,
`01M61Q79VR8ABNANRCE8DF12JV`, read card balances in brackets as amounts, but the gap is real).
Prithvi chose to drop the rule as a decider (decision A): its 37 answers are now pre-fills he
reviews, so nothing bypasses review and the rule's gaps cost review time, not label quality.

After decision A, five more rounds found no P0 or P1. Fixed: turn citations checked (customer
turns of that conversation, from the sheet itself; a changed "yes" must cite them; reversed
ranges refused); records on the second sheet labelled as looked up or changed before / after the
sentence, with their arguments, and preferring what the agent knew when it spoke; lookup IDs
kept under "Show more"; unsure answers bounded in the missed-MC estimate; final agreement labels
keep the pre-fill's reasoning apart from Prithvi's decision and note. **Left (P2/P3, not
blocking):** a reservation ID starting with digits (`59XX6W`) is not matched to its record on
one second-sheet card (it is under "Show more"); a repeated lookup's pointer is not resolved when
ranking records, so one card shows an older lookup; a rejected turn citation is reported as a
count, not by action.

## Waiting on

1. Prithvi's answers on `review/prithvi_sheet.html`: 64 statements and 161 agreement pre-fills.
2. John's answers on `review/second_sheet.html` (35 statements).

When both answer files are in `review/`, `score.py` (committed now, before any answer) runs once.
It refuses answer files from another sheet version or with unanswered items, and applies
Prithvi's agreement answers first: statements on actions he marks "no agreement" leave every
count, and actions he moves to "agreed" are listed for a follow-up review (the result is then
marked provisional).

## Files

- `agreement.py`, `units.py`, `build.py`, `sheet.py`, `friend.py`, `score.py`,
  `sheet_template.html`, `friend_template.html`
- `results/agreement.jsonl`, `results/label_set.jsonl` (sha256 in `results/summary.json`),
  `results/summary.json`
- `review/agreement_prefill.json`, `review/prithvi_sheet.html`, `review/second_sheet.html`
