# Rely-1 M1: label set

| | |
|---|---|
| **Status** | Built; waiting for people's labels. The gate needs Prithvi's answers and John's (the second labeller) |
| **Branch** | `rely/m0-spec` |
| **Question** | Do people agree on the material-contradiction label, and how close is a pre-fill from the existing rulings to Prithvi's labels? |
| **Data** | Train and dev only (M0 splits; 174 actions, packet v2). No test action is read |
| **Spend** | $0. No model or API calls (the agreement pre-fills were read by Claude subagents in session) |

## Method

1. **Agreement first** (`agreement.py`; Prithvi, 2026-11-18). Each action gets a label: did the
   customer agree to this exact action (yes / no), and which customer messages carry the
   agreement, from the yes through any later message that only adjusts a detail. It replaces M0's
   consent-turn marker. Sources: Prithvi's ruling on the 13 actions whose last customer message
   has no "yes" (final); and pre-fills for every other action, which Prithvi reviews on his
   sheet: a code rule's "yes" for 37 (a clear yes, no write between it and this call, and the
   agent's confirmation names every identifying argument and date of the call) and a Claude
   reading of the other 124 (`review/agreement_prefill.json`). On Prithvi's decision (A,
   2026-11-19) the rule no longer decides any label.
   **Actions with no agreement are not labelled for material contradiction**; they are reported
   as their own group. "unsure" stays in, flagged.
2. **Units** (`units.py`; M0 decision 7): every agent sentence before the proposed action, code
   split as in M0. A list item carries its lead-in line: the non-list line directly above its
   list, when that line ends in a colon.
3. **Selection** (`build.py`; the claims check only picks what to look at). The earlier
   extracted claims (`claims_airline1_verified.jsonl`, `claims_retail_verified.jsonl`) are placed
   in the unit(s) they were quoted from. A unit's stratum is the worst verdict among its claims:
   `mismatch` (any false), `unchecked` (any unverifiable), `matched` (all true), `no_claim`.
   Taken: every mismatch unit, every unit that a ruling or grader quotes, then a seeded sample of
   70 matched, 60 unchecked and 40 no-claim units.
4. **Pre-fill** from Prithvi's rulings and corrections and the graders' reasons, never from the
   claims check. A unit is *cited* when a reason quotes words in it; *as false* when a falsity
   word ("wrongly", "false", "claimed", "never stated", "is not" …) is in the quote's own clause,
   otherwise *as support*.

   | Evidence | MC | Material | Records |
   |---|---|---|---|
   | Quoted as false by Prithvi or a grader | MC | yes | contradicted |
   | Quoted as support only | not MC | — | — |
   | Not quoted; the action has a truth label | not MC | — | — |
   | Not quoted; no truth label | none | — | — |

   The falsity-word rule is review tooling: it decides only what Prithvi is shown first. It
   never runs in the model.
5. **Review sets** (seed `20261118`).
   - Prithvi, three blocks: every unit pre-filled MC; a random 40 of the units pre-filled
     `not MC`; and, outside the random 40, 10 units from packets over 8,192 tokens. Then the 161
     agreement pre-fills.
   - Second person (John): a random 30 of Prithvi's first two blocks, plus 5 of his over-limit 10.

## Review sheets

`review/prithvi_sheet.html`: each statement with its lead-in, the proposed action and tool
description, the conversation with the statement's turn highlighted, the evidence ledger, the
policy, the action's truth label, every ruling and reason, and the pre-fill. Three answers:
material contradiction, would correcting it change the yes, do the records back it. Later calls
are shown only as "not in the main packet (comparison only)". Then the agreement block: action,
pre-fill (yes / no, turns, reason), conversation with the pre-filled turns highlighted, the
evidence ledger; answer yes / no / unsure, the turns, a note. A collapsed list lets Prithvi
override one of his own 13 earlier rulings; `score.py` applies every answer and override.

`review/second_sheet.html` (Prithvi, 2026-11-18) is for a non-technical labeller: one file that
opens by double-click on a laptop or tablet, with no install and no network. A plain-language
intro with the one question and a two-to-three sentence definition; two worked examples from
statements on neither sheet (one yes, one no, each with a one-line reason); then for each
statement only the customer's request and last message, the agent's sentence, the most relevant
company record (`friend.py`: generic token overlap, review tooling only), and the action in
words, with the whole conversation behind "Show more". Yes / No / Not sure, a progress counter,
answers saved as they go, and one "Download my answers" button. Nothing on it shows a label,
pre-fill, ruling, reason or claims-check output (`tests/test_rely1_m1.py` checks the fields).

## Gate (from the build plan, extended by Prithvi on 2026-11-18)

`score.py`, written before any answer exists, reports each number with its denominator, under and
over 8,192 tokens:

- Pre-fill vs Prithvi on the random 40: at least 36 of 40 match.
- (a) How many of the MC pre-fills Prithvi confirms.
- (b) How many MCs Prithvi finds in the random 40, and what that rate (95% Wilson interval)
  implies for the statements pre-filled not MC that nobody reviewed.
- Prithvi vs the second person on the 30: at least 26 agree. The 5 over-limit statements are
  reported apart.
- The agreement pre-fills: how many Prithvi confirms or changes.

Both thresholds are proposals. If people cannot agree, fix the definition or the input first.

## Run order

1. M0: `splits.py`, `packets.py` (packet v2, train + dev), `tokens.py`.
2. `python agreement.py` → `results/agreement.jsonl` (once; needs `review/agreement_prefill.json`).
3. `python build.py` → `results/label_set.jsonl`, `results/summary.json` (once).
4. `python sheet.py` → `review/prithvi_sheet.html`, `review/second_sheet.html`.
5. People label; their answer files go to `review/prithvi_answers.json` and
   `review/second_answers.json`.
6. `python score.py` → `results/gate.json` (once) → Report.md.
