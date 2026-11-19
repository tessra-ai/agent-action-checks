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

## Model labellers (Prithvi, 2026-11-19)

To cut Prithvi's review time, two independent model labellers, neither of them Claude, label the
whole label set: A is OpenAI's default model through the Codex CLI, B is Google's top Gemini Pro
model through the Antigravity CLI, both on the subscriptions Prithvi already has (no API keys).

**The labeller pack** (`build_pack.py` → `runs/labeller_pack/`, git-ignored; a clean checkout
rebuilds it byte for byte and checks it against the committed key; hashes in
`results/pack_summary.json`). Identical for both labellers:

- `prompt.txt` (source `labeller/prompt.txt`): plain-language instructions; the material
  contradiction definition and the M0 rules in plain words (R1–R7, R9, R10; R8, "only agent
  statements are units", is built into the questions); the agreement question; the output
  format; two worked examples, both statement questions, from statements **not** in the label
  set:
  - yes: retail task 14, T19.2, "I will proceed with returning the mechanical keyboard and the
    mouse" (the call returns the Action Camera). That action has no agreement (the customer
    asked for the keyboard and mouse and was never asked to confirm). No statement on an
    agreed action outside the label set is a clean contradiction: the label set already holds
    every one the claims check or a ruling flagged. The nearest, airline task 9 ("Booking made
    on 2024-05-12 (within 24 hours)"), would answer one of the 14 pre-filled contradictions,
    which is in the same task.
  - no: retail task 19, T19.2, "The refund amount is $54.04." (the call returns that $54.04
    item).

  Flagged `example_exposed`: 31 of the 174 actions (34 of the 380 statements), those in the two
  examples' tasks or whose records hold an order, item or payment ID the examples quote (the
  keyboard customer's orders recur in retail tasks 11 to 14). A-vs-B is reported with and
  without them.
- `packets/`: the 174 train + dev actions as P001 … P174 (seeded shuffle, seed `20261118`); each
  file is the M0 packet v2 main text, then "# Questions". Two kinds of call, one file each:
  `P001-A.txt` asks only the agreement question (`P001.A`), for all 174 actions, including the
  32 already ruled or pre-filled "no agreement"; `P001-S.txt` asks only the statement questions
  (`P001.S1` …, turn order, with turn and lead-in), for the 125 actions with label-set
  statements, 380 in all. Kept apart because the label set leaves out statements of actions
  with no agreement: in one combined file, "no statement questions" would hint "not agreed"
  (Codex review, 2026-11-19). 299 calls per labeller.
- `manifest.json` (IDs per call, allowed answers, file hashes) and `ingest.py`.

Answers are a JSON array, one object per ID: `id`, `answer` (`yes` / `no` / `not_sure` for
statements; `agreed` / `not_agreed` / `not_sure` for agreement), `reason` (20 words at most).
`ingest.py` reads answer files, directories or pasted text, reports missing, duplicate and
unknown IDs, invalid answers, over-long reasons, repeated fields and broken JSON, and refuses
(writes nothing, exit 1) if any fail, naming the calls to rerun. Nothing in the pack carries a
write ID, task ID, pre-fill, ruling, grader reason, truth label or agreement label
(`tests/test_rely1_m1.py`). `results/pack_key.json` maps pack IDs back to write IDs and unit
keys; it stays outside the pack.

## Review sheets

`review/prithvi_sheet.html`: each statement with its lead-in, the proposed action and tool
description, the conversation with the statement's turn highlighted, the evidence ledger, the
policy, the action's truth label, every ruling and reason, and the pre-fill. Three answers:
material contradiction, would correcting it change the yes, do the records back it. Later calls
are shown only as "not in the main packet (comparison only)". Then the agreement block: action,
pre-fill (yes / no, turns, reason), conversation with the pre-filled turns highlighted, the
evidence ledger; answer yes / no / unsure, the turns, a note. A collapsed list lets Prithvi
override one of his own 13 earlier rulings; `score.py` applies every answer and override.

`review/second_sheet.html` (Prithvi, 2026-11-18; `review/second_sheet_artifact.html` is the same page as published to claude.ai, where "Download my answers" asks the viewer to confirm the save, and shows the answers as text to copy if a save is not possible) is for a non-technical labeller: one file that
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
5. `python build_pack.py` → `runs/labeller_pack/`, `results/pack_key.json`,
   `results/pack_summary.json` (once). Labellers A and B run on the pack.
6. People label; their answer files go to `review/prithvi_answers.json` and
   `review/second_answers.json`.
7. `python score.py` → `results/gate.json` (once) → Report.md.
