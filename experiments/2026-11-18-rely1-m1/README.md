# Rely-1 M1: label set

| | |
|---|---|
| **Status** | `planned` → waiting for people's labels. The label set and both review sheets are built; the gate needs Prithvi's and a second person's answers |
| **Branch** | `rely/m0-spec` |
| **Question** | Do people agree on the material-contradiction label, and how close is a pre-fill from the existing rulings to Prithvi's labels? |
| **Data** | Train and dev only (M0 splits; 174 actions, packet v1). No test action is read |
| **Spend** | $0. No model or API calls |

## Method

1. **Units** (`units.py`; M0 decision 7): every agent sentence before the proposed action, code
   split as in M0. A list item carries its lead-in line: the non-list line directly above its
   list, when that line ends in a colon.
2. **Selection** (`build.py`; M0 decision 6: the claims check only picks what to look at). The
   earlier extracted claims (`claims_airline1_verified.jsonl`, `claims_retail_verified.jsonl`) are
   placed in the unit(s) they were quoted from. A unit's stratum is the worst verdict among its
   claims: `mismatch` (any false), `unchecked` (any unverifiable), `matched` (all true),
   `no_claim`. Taken: every mismatch unit, every unit that a ruling or grader quotes, then a
   seeded sample of 70 matched, 60 unchecked and 40 no-claim units.
3. **Pre-fill** from Prithvi's rulings and corrections and the graders' reasons, never from the
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
4. **Review sets.** Prithvi: every unit pre-filled MC, plus a seeded random 40 of the units
   pre-filled `not MC` (units with no pre-fill can't be compared, so they are not drawn). Second
   person: a seeded random 30 of Prithvi's set, **blind** (no pre-fill, rulings, reasons or
   claims-check output). Seed `20261118`.

## Review sheets

`review/prithvi_sheet.html` and `review/second_sheet.html` are self-contained pages: open the
file in a browser. Each item shows the statement and its lead-in, the proposed action with its
tool description, the other calls agreed in the same plan, the conversation with the statement's
turn highlighted, the evidence ledger and the policy. Prithvi's sheet adds the action's truth
label, every ruling and reason on the action, the pre-fill and what it came from.

Three answers per statement, as in the model spec: material contradiction (yes / no / unsure),
would correcting it plausibly change the yes (yes / no / unsure), do the records back it
(supported / contradicted / not covered / unsure), and a note.

The consent marker is **not shown**: its definition waits for Prithvi's answer (M0 decision 3).

Answers stay in the browser until "Export answers" saves a JSON file. Put it in `review/` as
`prithvi_answers.json` or `second_answers.json`.

## Gate (from the build plan)

Counts are reported for every combination (`results/summary.json`, Report.md). Pre-filled labels
match Prithvi's on at least 36 of the random 40, and the two people agree on at least 26 of the
30. Both thresholds are proposals. If people cannot agree, fix the definition or the input first.

## Run order

1. M0: `splits.py`, `packets.py` (packet v1, train + dev), `tokens.py` (for the length groups).
2. `python build.py` → `results/label_set.jsonl`, `results/summary.json` (once).
3. `python sheet.py` → `review/prithvi_sheet.html`, `review/second_sheet.html`.
4. People label; their exported answers go to `review/`.
5. Scoring script (written after the answers arrive, before reading them) → Report.md.
