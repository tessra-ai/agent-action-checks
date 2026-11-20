# Kev-4B fine-tuning pilot: plan and cost (NOT STARTED; waiting for Prithvi's go)

Written 2026-11-20. Nothing here has been run. All labels are provisional and model-labelled (the
labellers' consensus). Only train and dev data; no test data.

## The bar (fixed before any training)

Same statements as stock Jev: the 21 both-yes and 345 both-no statements (train+dev). Kev's score for
each statement comes from the fold model that did not see that statement's task (out-of-fold).
Pooled over the five folds, the pilot passes only if both hold:

1. AUC above stock Jev's 0.926.
2. At the cut-off where Kev flags at most 13 of the 345 both-no statements (Jev's count at 0.5), Kev
   catches more than 12 of the 21 both-yes.

With 21 positives, one statement is about 5 points of catch rate, and the AUC is uncertain by about
±0.05. A win by less than that is reported as "not separable", not as a win. Stock Kev-4B scored AUC
0.428 on the same statements.

Also reported, but not part of the bar:

- Agreement: Kev vs Jev's AUC of 0.971 against the consensus.
- The two questions combined per action, next to Jev's table.
- The skill's forgetting check on 300 public records.

## Test: cross-validation grouped by task

- M0 `splits/folds.json`: k=5, seed 20261118, grouped by task (42 tasks, 174 actions).
- Fold model *k* trains only on conversations from tasks outside fold *k*, and is scored only on fold
  *k*'s statements and agreement questions.
- No planted or natural example from a fold-*k* task enters fold *k*'s training, so the same
  conversation never appears on both sides.

## Training data (built per fold)

**Source.** Train-split conversations only: 133 actions, 40 conversations, 31 tasks. Per fold, about
four fifths of these (about 105 actions). Dev conversations are only ever tested, never trained on.

**Record shape.** One record is one action's packet, the same state the labellers and Jev saw, with
several yes/no questions on that state. The instructions are word-for-word the labellers' wording, as
used for Jev:

- the statement question on 4–6 agent sentences;
- the agreement question.

### Planted errors (about 400 across the 133 train actions; about 320 per fold)

Every planted positive must be material under the M0 definition: it bears on whether the proposed
action should run. Every untouched sentence asked as "no" must be checked the same way, since one could
already hold a real contradiction. The check is a fresh Codex call on the edited packet with the
labellers' wording. A planted positive it doesn't call "yes" is dropped. An untouched sentence it calls
"yes" is dropped from the negatives. Drop rates are reported.

Each copy plants exactly one error into an action's packet, by rewriting one agent sentence said before
the action. The planted sentence is asked as "yes"; 3–5 untouched sentences in the same copy are asked
as "no". There are three copies per action, each with a different sentence and kind of error.

1. **Value swaps (programmatic, about 2/3).** Start from the M0 claim audit: 490 claims in train, 267
   sentences with a claim checkable against the records. Swap the stated value for a wrong but plausible
   one: an amount, date, count, order or flight ID, cabin, status, or item option. Take the wrong value
   from elsewhere in the same records where possible. A script confirms that the new value contradicts
   the record the claim cites.
2. **Policy and eligibility flips (Codex, about 1/3).** Examples: "is eligible" → "is not eligible";
   "refundable" → "non-refundable"; a wrong fee or a wrong rule.
   - Written by Codex CLI on the subscription, with no API key, in the same isolated, read-only setup
     as labeller A.
   - A planted error is kept only if a fresh Codex call, given the edited packet, answers "yes".
   - Caveat: Codex is labeller A, so this part leans toward A's reading. Reported apart.
3. **Hard negatives (asked as "no"):**
   - true rephrasings of claim sentences (Codex, checked the same way);
   - "true but misleading" sentences, like P112.S4, which is out of scope by Decision B.

### Natural statements

The other folds' consensus statements from train-split actions only (both filters: not in fold *k*,
and in `train.json`) are added as questions on their original packets: 172–222 "no" and 8–15 "yes" per
fold.

### Agreement examples

- **Natural.** The other folds' consensus on train-split actions only (the same two filters): both
  agreed means true, both not agreed means false. Splits are left out. 90–98 per fold.
- **Planted "not agreed", about 60 per fold.** Built from both-agreed train actions in two ways. The
  edited copy is labelled false, and the unedited original true, so the two differ only in the edit.
  - **Consent edit.** Rewrite the customer's go-ahead turn into a decline, a hedge ("let me think
    about it"), or a question.
  - **Argument edit.** Change one argument of the proposed action away from what the customer asked
    for: a different item, flight, payment method or amount.

### Size per fold

- About 500 records and 2,500–3,000 labels.
- Plus the skill's 2,000 public replay records, one epoch, warm-starting the released Kev-4B delta.
- Learning rate: the default, 2e-5.

## Context length (the one code change)

- The fine-tune wrapper (`skills/kev-finetune/scripts/kev_modal.py`) trains at the 384-token state
  default.
- Our states are long: median 4,306 tokens, p95 10,382, and 30 of 174 are over 7,552.
- `kev.train` accepts `--max_state` up to 64k. The patch passes `--max_state 7552`, the length Kev-4B
  was trained on, through the wrapper.
- Packets over 7,552 tokens are trimmed with the M0 trim (dropping early records the action doesn't
  cite), not cut from the end. The trainer's own truncation would cut the end and lose the action.
- The 63 test statements in states over 8,192 tokens are reported apart, as for Jev.

## GPU time and cost

The skill's figure of about $1 and 12 minutes per run applies to short states. Ours are about 10× longer,
so step 1 measures the real throughput before anything else.

| Step | GPU | Time | Cost |
| --- | --- | --- | --- |
| 1. Smoke run: fold 0, 100 records, measure tokens/s | H100 | ~15 min | ~$1 |
| 2. Five fold runs, about 500 records + 2,000 replay each | H100 | ~45–60 min each, ~4–5 h total | ~$16–20 |
| 3. Out-of-fold scoring: about 75 statements + 35 agreement questions per fold | H100 / L4 | ~5 min each | ~$2 |
| Data generation: scripts plus Codex on the subscription | none | ~1 h wall clock | $0 |
| **Total** | | **~5–6 GPU-hours** | **~$20 expected; hard cap $40** |

- Each run gets a `--timeout` so the cap holds.
- If step 1 shows throughput more than 2× worse than assumed, I stop and re-quote before step 2.
- Modal can't run from this container (its gRPC traffic doesn't pass the proxy), so each step is one
  command on your Mac, as for the stock Kev deploy. That's about 7 commands in all.

## What I would deliver

`results/kev_pilot.json` with:

- out-of-fold scores;
- the bar verdict;
- the per-fold numbers;
- agreement and combined tables next to Jev's;
- the forgetting check.

Plus the data builder and the patch. No M2 work.
