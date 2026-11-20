# Kev-4B fine-tuning pilot: plan and cost (APPROVED 2026-11-20, hard cap $40)

Prithvi approved the plan with five changes, all folded in below: a wider bar, outcome rules, a
trimmed / not-trimmed split, planted results kept apart from natural ones, and step-by-step Mac
commands. Everything here was fixed before any Kev training ran. All labels are provisional and
model-labelled (the labellers' consensus, or a planted edit). Only train and dev data; no test data.

## The bar (fixed in advance)

Kev is compared with stock Jev (jev-1.14.0) on the same data and folds, on three things. Kev's
scores are out-of-fold: each comes from the fold model that never trained on that action's task.

- **(a) Statements.** The 21 both-yes and 345 both-no statements:
  - AUC above Jev's 0.926;
  - more than 12 of 21 caught at the cut-off where at most 13 of the 345 are flagged.
- **(b) Agreement.** AUC against the labellers' consensus (112 both agreed, 46 both not agreed),
  versus Jev's 0.971.
- **(c) Combined per action.** An action is stopped when any of its statements scores at or above a
  statement cut-off, or its P(agreed) is below an agreement cut-off. Counted: bad caught of 91, good
  stopped of 56.
  - Cut-offs are chosen per held-out fold, never on that fold. Selection uses the dev actions in the
    other four folds (22–38 actions per fold). No fold model trains on those, so the selection is
    clean for Kev, and Jev uses the same selection set.
  - The rule: maximise bad-caught rate minus good-stopped rate. Ties go to fewer good stopped, then
    more bad caught, then the stricter cut-offs. The grid is 0.1 to 0.9 in steps of 0.1 for each
    question, or that question off.
  - Jev rerun under this protocol: **66 of 91 bad caught, 16 of 56 good stopped** (ungraded 18 of
    27). The earlier 51 and 5 used cut-offs picked on the same data they were scored on. With every
    other-fold action as Jev's selection set instead, Jev gets 59 and 11. That variant is reported
    for comparison only, because Kev can't use trained-on actions for selection.
  - This rule was chosen before any Kev result existed. Jev's rerun numbers were seen after the rule
    was written into the scorer, and the rule was not changed.

**Noise.** Paired bootstrap of Kev minus Jev, resampling the 42 tasks: 2,000 draws, fixed seed. It
covers (a) AUC and catch rate, (b) AUC, and (c) bad-caught and good-stopped rates.

## Outcome rules (fixed in advance)

- **Pass:** Kev matches or beats Jev on (c) within the measured noise, and is not clearly worse on
  (a) or (b).
  - (c) matches when, for bad caught, Kev ≥ Jev or the 95% CI of the difference includes 0. Good
    stopped must hold the same way: Kev ≤ Jev or the CI includes 0.
  - "Clearly worse" on (a) or (b) means the 95% CI of Kev minus Jev lies wholly below 0. For (a)
    this applies to either the AUC or the catch rate.
- **Retry once:** not a pass, but statement AUC ≥ 0.70 (stock Kev: 0.43). In that case I tell you the
  cost of one more run with about three times the planted data, under the same cap rules, and wait.
- **Stop:** statement AUC below 0.60 (barely moved).
- **Between 0.60 and 0.70:** I report and ask; there's no automatic retry.

## Test: cross-validation grouped by task

- M0 `splits/folds.json`: k=5, seed 20261118, grouped by task (42 tasks, 174 actions).
- The fold-*k* model trains only on train-split actions outside fold *k*.
- It is scored on every fold-*k* action: train and dev, every statement and the agreement question.
  The packets are exactly the ones the labellers and Jev saw.
- Questions without a consensus label are scored too, since the combined check needs them, but they
  are kept out of every metric that needs a label. In Kev's files they sit in records marked
  "unknowable", which Kev's own metrics and temperature fit skip.

## Training data (per fold, from train-split actions outside the fold)

The instructions are word-for-word the labellers' wording, as used for Jev. Records are packed so
that each one fits Kev's own `fits()` check at a 7,552-token state. A record with too many questions
for that is split into several records on the same state.

- **Natural packets.** The consensus statements, plus up to 5 untouched sentences per action asked as
  "no" (each confirmed "no" by the Codex check), plus the consensus agreement label.
- **Planted statement copies.** One edit per copy: the edited sentence plus 3 checked untouched
  sentences asked as "no".
  - Value swaps (by script): 232 made across 119 actions. A stated amount, date, flight, item,
    order or reservation ID that appears in the records is swapped for a wrong but plausible one:
    amounts ×0.5–2, dates ±1–3 days, other IDs of the same kind taken from the same records.
  - Policy and eligibility flips: written by Codex, one per action where something fits.
  - True rephrasings: written by Codex, asked as "no".
- **Planted "not agreed" copies,** for both-agreed actions only:
  - consent edits: Codex rewrites the customer's go-ahead turn;
  - argument edits: by script, one argument of the proposed action changed to another value of the
    same kind from the records; a date is shifted.
- **The check.** Every planted edit and every untouched "no" sentence goes to a fresh Codex call. It
  gets the labellers' full prompt, the packet, and the edit described as a variant. An edit is kept
  only when the check gives the intended answer.
  - Checking one call per action, rather than one call per edited copy, is a cost choice:
    subscription usage, not money.
  - Make and keep counts per kind are reported.
- **Codex disclosure:** Codex (gpt-6.2-sol, high, labeller A's setup) wrote about a third of the
  planted edits and checked all of them. It is also labeller A. The planted set therefore leans
  toward A's reading, and planted results are reported apart from natural ones.
- **Not done:** the "true but misleading" hard negatives like P112.S4. Writing them reliably needs
  more than a rewrite prompt; left out of this pilot.
- **Training recipe:**
  - 2,000 public replay records;
  - one epoch, warm-starting the released Kev-4B delta;
  - lr 2e-5, batch 2, accum 4;
  - `--max_state 7552`.

  These are Kev-4B v1.0's own recipe values.

## Long packets: what changed from the plan

The plan said packets over 7,552 tokens would be trimmed with the M0 trim. That trim (dedup plus
caps) still leaves 14 of 174 packets over 7,552, because the length is in the conversation, not the
ledger. So nothing is trimmed:

- **Training:** packets over 7,552 tokens are left out; the count per fold is reported.
- **Test:** both models score the full, untrimmed packets, the same data.

Results are reported separately for test packets within 7,552 tokens and over 7,552 tokens. The
long ones are longer than anything Kev trained on.

## Code changes

`labeller/kev_modal_rely1.py` is a patched copy of the skill's `kev_modal.py`. The full diff is in
`labeller/kev_modal_rely1.patch`.

- `--max_state 7552` is passed to `kev.train`.
- Calibration and development are scored at the serving limits. Unpatched, the scorer uses the
  384-token training limit and would reject every packet.
- triton is pinned to 3.8.0: 3.9 breaks flash-linear-attention 0.5.2, as in the stock Kev deploy.

## GPU time and cost (hard cap $40)

| Step | GPU | Timeout (cost ceiling) | Expected |
| --- | --- | --- | --- |
| Smoke run: 100 fold-0 records, 6 test packets | H100 | 45 min ($2.96) | ~15 min, ~$1 |
| Five fold runs | H100 | 90 min each ($5.93 each, $29.63 total) | ~30–50 min each, ~$12–17 |
| **Ceiling** | | **$32.59** | **~$15–20** |

- Modal's `--timeout` stops a run at its ceiling, so even a run that hangs can't push the total past
  $33. Ceilings are at $3.95/h, the wrapper's own H100 rate.
- After the smoke run I re-estimate the per-fold time from its measured speed. If a fold would need
  more than 90 minutes, I stop and re-quote before any fold runs.
- Modal can't run from this container, so each step is one command on Prithvi's Mac. Each step prints
  a short JSON block to paste back.

## Changes made while running (2026-11-20, Prithvi's approval)

- **GPU: A100-80GB, not H100.** Both H100 and H200 sat in Modal's queue for over 8 minutes; the
  A100-80GB started at once. The smoke run (`rely1-kev-smoke-4`) trained 100 records plus 2,000
  replay in about 30 minutes and scored 46 full-length packets in about 13. Modal's actual rate,
  including CPU and memory, was about $3.15/h.
- **The stock-Kev baseline and the forgetting check were dropped** (`--no-baseline --regression 0`)
  to save about a quarter of each fold's cost. Neither feeds the outcome rules: the only stock-Kev
  number they use is its statement AUC of 0.43, already measured on the same statements. Both can
  be run later on the saved checkpoints for under $1 if the pilot passes.
- **Fold timeout: 8,400 seconds.** At about $3.15/h that is about $7.35 per fold at worst, so the
  five folds plus the smoke runs stay under $40. If a fold times out after training, its checkpoint
  is saved and is scored on its own.
- **Planted set, after Codex's check:** the check kept 39 of 232 value swaps. Most changed a value
  that was false but not material to the proposed action, such as another order's total or a card
  the customer did not choose. So 118 of the 157 planted contradictions (75%) are written by Codex,
  not the planned third. Codex also checked all of them, and it is labeller A. Planted results are
  reported apart from natural ones.

- **Folds 0–2 ran at batch 1, accumulation 8.** Their first runs at batch 2 ran out of GPU memory
  partway through training (steps 160, 280 and 80 of about 305), when two long packets landed in
  one batch. They were re-run as `rely1-kev-f{0,1,2}-b1`. Folds 3 and 4 finished at batch 2,
  accumulation 4. Both settings put 8 records into each optimizer step.
- **Planted results apart from natural ones:** every test number is on natural statements and
  agreement questions only. The planted edits are training data, and no planted example was held
  out, so there is no separate planted test score. What is reported for the planted set is how
  many edits were made and kept (`planted` in `results/kev_pilot.json`).

## Result (2026-11-20)

`results/kev_pilot.json`; the five fold exports are in `results/kev_pilot_folds/`. Under the
fixed rules the verdict is **RETRY ONCE**: statement AUC 0.813 (stock Kev 0.43), above the 0.70
retry line, but short of the bar and clearly worse than Jev on (a), (b) and (c).

To replay the score from the committed exports: the scorer also needs git-ignored inputs that
are rebuilt, not committed. These are the M0 packets (`../2026-11-18-rely1-m0/runs/packets.jsonl`,
from M0's `packets.py`), the labeller pack (`build_pack.py`), Jev's raw replies (`stock_models.py
run`, `jev` and `jev_agreement`, about $0.08), and this pilot's data build (`kev_pilot.py jobs`,
both Codex steps, `checks`, `build`). With those in place, put the committed exports where the
scorer reads them:

    mkdir -p runs/kev_pilot/results && cp results/kev_pilot_folds/fold*.json runs/kev_pilot/results/
    python kev_pilot.py score

### Retry cost estimate (awaiting Prithvi's decision; nothing started)

A retry means one more five-fold run with about three times the planted data.

- **Data:** 6 value swaps and about 3 Codex flips, rephrasings and consent edits per train action.
  - At the first run's keep rates (17% of swaps, 94% of flips), that is about 470 planted
    contradictions instead of 157, about three quarters of them Codex-written again.
  - Codex generation and checks run on the subscription, at no money cost and about 2–3 hours of
    wall time. Usage limits may pause them.
- **GPU:** about 900–1,000 of our records per fold instead of about 470, at batch 1 on A100-80GB.
  - About 2.5 hours of training plus 20 minutes of scoring per fold, at about $3.15/h, so about $9
    per fold and about $45 for five.
  - With 3.5-hour timeouts the ceiling is about $55.
- **Total:** about $45 expected, $55 worst case, on top of about $35 spent on this run. That is
  beyond the original $40 cap, so it needs a new budget.

## What I deliver

`results/kev_pilot.json`:

- the verdict under the rules above, and (a), (b), (c) for Kev, Jev and stock Kev under the same
  protocol;
- bootstrap CIs;
- within / over 7,552 tokens;
- planted make and keep counts, apart from the natural results;
- per-fold run facts and the forgetting check.

No M2 work.
