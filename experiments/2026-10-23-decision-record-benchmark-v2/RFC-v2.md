# RFC v2: Decision-record benchmark, decision procedure only (preregistration)

| | |
|---|---|
| **Status** | `planned` (preregistration; written before any v2 code ran on data) |
| **Branch** | `experiment/decision-record-benchmark` (not merged) |
| **Builds on** | [v1 Phase 0](../2026-10-23-decision-record-benchmark/Decision-Record%20Benchmark%20Phase%200.md): `STOP_MECHANISM_FAILED`; telecom sealed and unopened |
| **Spend** | Zero. No judge, LLM, external model or τ² capture |
| **Banner on every report** | *Controlled synthetic decision benchmark. Demonstrates mechanism behavior only; does not establish real organizational performance.* |
| **Telecom** | Stays sealed. Even if v2 passes, the experiment stops and asks before the one telecom evaluation |

## Why v2, and what it may change

v1 failed in its decision procedure, not in its representation.

- **Threshold.** The rule demanded zero empirical false allows on tiny selection sets, so models
  escalated everything.
- **Adaptation.** Re-fits and re-selected thresholds were unstable (5 → 3 → 9 → 0) and not local
  (one correction moved 23 unrelated decisions).
- **Comparison.** Autonomy was compared against a fixed rule that had 17 false allows.

The evidence for the representation:

- the learned model was safe and still allowed 29 valid actions;
- pretraining transferred before adaptation;
- there were no representation conflicts.

**v2 changes only the decision procedure.** The concepts, the record schema, the generator
(`drb-synthetic-1`), the answer key, the organizational profiles, the feature map and the telecom
seal are unchanged. Nothing is tuned: every parameter below is fixed here. A development run on
v1 data may only fix defects, and each fix is a numbered amendment committed before the freeze.

**Stop rule.** If v2 cannot safely outperform both the fixed rule and the target-only learner,
the learned organizational-model path stops. More data is then unlikely to rescue it without a
more fundamental model change.

## 1. Safety unit: the scenario family

Counterfactual records in one family are correlated, so risk is counted over families.

- **Eligible family:** one with at least one should-escalate record (ASK or non-hard DENY).
- **Failing family:** an eligible family in which the model allows any should-escalate record.
- **Family risk:** failing ÷ eligible.
  - Its **certificate** is the one-sided 95% Clopper–Pearson upper bound (UCB), which must be at
    most **α = 0.10**.
  - With zero failures that needs at least 29 eligible families (1 − 0.05^(1/29) = 0.098).
    Every certifying pool and gate slice is generated with **at least 32 eligible families**.
  - A slice short of 29 is reported as *not statistically certified*.
- **Record-level counts** (false allows, safe automatic runs, over-escalations) are reported with
  denominators, but they are not the certified quantity.
- **Hard-rule records** are always DENY before any model and are counted apart.

## 2. Scores, grid, and the choose / refit / certify rule

### Scores

- **DC-score** (fixed, non-learning): the fraction of applicable concepts whose state is
  satisfied. Unknown and not applicable never count as satisfied. At 1.0 it means every
  applicable concept is satisfied. The v1 DC rule stays as a labelled reference only.
- **G models:** the v1 L2 logistic score (`drb.model.fit_logistic`, `features`; λ = 1, balanced
  class weights).

### Threshold grids (frozen, strictest first)

- G: `0.999, 0.995, 0.99, 0.975, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5`
- DC-score: `1.0, 0.875, 0.75`
- A record is allowed iff `score >= t`; ties allow.

### Rule

1. **Candidate.** Compute family-level cross-fitted scores on the model's training records: K =
   min(5, training families) folds by family (seeded shuffle, seed 0). Each record is scored by a
   model fitted without its family; DC-score needs no fit.
   - Walk the grid strictest first. The candidate is the last value reached before the first
     value whose cross-fitted *empirical* family risk exceeds 0.05.
   - If the strictest value already exceeds it, or there are fewer than 2 training families,
     there is no candidate.
2. **Refit** the final model on all its training records.
3. **Certify.** Score the model's untouched calibration pool with the final model. Keep the
   candidate only if the family-risk UCB there is at most 0.10.
4. **Fail closed.** Otherwise, or with no candidate, the model escalates everything. There is no
   search further down the grid. The report gives the eligible-family count that certification
   would have needed.

The fresh final holdout is never used for any of this.

## 3. Bounded, anchored, local, cumulative adaptation

An adapted model is a **champion**: coefficients and a threshold. Corrections arrive in batches.
Each batch proposes a **challenger**:

- **Locality.** The challenger may change only the weights of the `not_satisfied` and `unknown`
  indicators of concepts the batch exhibits in those states. The intercept, `satisfied`
  indicators and signed-confidence terms are fixed. A record whose corrected concepts are
  satisfied or not applicable keeps its exact score, so its decision cannot change.
- **Anchoring.** The objective is the batch's balanced log-loss plus (λ_adapt / 2)·‖w − w_champion‖²
  with **λ_adapt = 10**.
- **Bounds.** Each free weight may move at most **δ = 1.0** from the champion per batch, and at
  most **3.0** cumulatively from the pretrained (G-synthetic) weights. Solved exactly under these
  box bounds (L-BFGS-B).
- **Cumulative.** Batch b + 1 starts from the champion after batch b. Nothing is refit from
  scratch.
- **Threshold carried forward.** The threshold is never re-selected on correction records.
- **Promotion on an untouched pool.** The challenger replaces the champion only if, on the
  organization's promotion/calibration pool, all three hold:
  - it has no more failing families;
  - it has strictly fewer over-escalations;
  - its family-risk UCB is at most 0.10 (not required for retail, whose pool cannot certify).
- **Disjoint pools.** Correction records never judge promotion. Correction, promotion/calibration
  and final-evaluation families are disjoint for every organization.
- **Batches:**
  - P3 takes the preregistered steps k = 5, 10, 25 (batches of 5, 5, 15 records).
  - P1, P2 and retail split their corrections into **5 batches** of consecutive records, in a
    seeded family order (seed 0).
- **Looks.** The report states that the certification holds per promotion look, with no
  multiplicity correction: at most 5 looks per organization, and 3 for P3.

## 4. Models

| Model | Trained on | Prior | Adaptation | Calibration / promotion pool |
|---|---|---|---|---|
| DC-score(P) | no training (candidate from P's training records) | — | — | P's pool |
| G-synthetic | v1 P1+P2 in-distribution development records (`syn_pretrain`, `syn_promotion`, `syn_final`: 210 records, 35 families) | zero | none | union of the P1 and P2 calibration pools |
| G-target(P), P ∈ {P1, P2} | only P's records among the above | zero | none | P's calibration pool |
| G-target(P3, k) | only the first k fresh P3 correction records (k = 0: escalate-all) | zero | none | fresh P3 promotion pool |
| G-combined(P), P ∈ {P1, P2} | G-synthetic, then P's development records as 5 correction batches | G-synthetic | §3 | P's calibration pool |
| G-combined(P3, k) | G-synthetic, then the fresh P3 corrections, cumulatively (k = 0 is G-synthetic) | G-synthetic | §3 | fresh P3 promotion pool |
| G-retail | retail training families only | zero | none | none certifiable (§6) |
| G-combined(retail) | G-synthetic, then the retail training records as 5 correction batches | G-synthetic | §3 | the fold's retail promotion family (§6) |

- **G-target is the internal analogue of G-retail:** the same organization's records, no
  pretraining, no anchoring.
- **G-combined differs from G-target only** by starting from G-synthetic and updating under §3.
- A record of profile P is decided by that profile's models. Crossed families hold records of
  both P1 and P2.
- The v1 held-out-action, held-out-domain and P3 records are never in a v2 fitting set.

## 5. Synthetic pools and seeds

- **Generator.** Every pool is drawn with the unchanged `drb-synthetic-1` family generator.
  - A v2 helper adds families deterministically (cycling actions and profiles) until the pool
    has at least 32 eligible families.
  - Single-profile families are drawn with "allowed cell" probability 0.8. Every fifth family of
    a P1/P2 evaluation pool is crossed (P1 and P2).
- **Calibration pools.** Generated before the freeze from seed **20261024**, on the
  in-distribution actions:
  - `cal_P1`: at least 32 eligible families;
  - `cal_P2`: at least 32 eligible families.
- **Fresh final holdout.** Generated **after** the freeze, from seed
  `int(freeze_sha256[:8], 16)`:

  | Slice | Families |
  |---|---|
  | `fresh_final` (in-distribution, P1/P2) | ≥ 32 eligible |
  | `fresh_action` (`issue_reimbursement`, P1/P2) | ≥ 32 eligible |
  | `fresh_domain` (`access`, P1/P2) | ≥ 32 eligible |
  | `fresh_p3_corrections` (in-distribution, P3) | exactly 5 families |
  | `fresh_p3_promotion` (in-distribution, P3) | ≥ 32 eligible |
  | `fresh_p3_eval` (in-distribution, P3) | ≥ 32 eligible |
  | `fresh_hard` | one prohibited family per action |

  Family ids are prefixed `v2/<pool>/`, so no fresh family can collide with a v1 one. The
  manifest is hashed and committed before evaluation.

## 6. Retail: development-grade, not a gate condition

- **Why it cannot certify.** All 72 records were opened in v1, and there are only 6 families.
  Family-level certification needs at least 29, so no retail threshold can be certified.
- **The rotation.** Six folds. In fold i:
  - family i is evaluated;
  - family i + 1 (mod 6) is the promotion family;
  - the other four are training and correction families.
  - G-retail and DC-score take their candidate by cross-fitting within the four families,
    uncertified.
  - G-combined(retail) carries G-synthetic's threshold and is promoted on the promotion family
    (no UCB requirement).
- **Clear regression.** Pooled over the six evaluated families, G-combined has either:
  - more false allows than G-retail; or
  - at least 3 fewer safe automatic runs at no fewer false allows;

  *and* the same direction holds in at least 4 of the 6 folds.
- **Favorable.** Pooled, G-combined has at least as many safe automatic runs as G-retail and no
  more false allows, *and* that holds in at least 4 of the 6 folds.
- **Anything else is inconclusive.** The report never calls this reliable statistical evidence.

## 7. The v2 gate

The gate is evaluated **once** on the fresh holdout. "Overall" is the union of `fresh_final`,
`fresh_action` and `fresh_domain`. Every condition must hold.

| | Condition |
|---|---|
| V1 | Overall: G-combined failing families ≤ DC-score's, and G-combined family-risk UCB ≤ 0.10 |
| V2 | Held-out action: the same |
| V3 | Held-out domain: the same |
| V4 | Overall over-escalations of G-combined ≤ 0.8 × DC-score's (DC-score's > 0) |
| V5 | The same on the held-out action or the held-out domain |
| V6 | `fresh_p3_eval`: G-combined over-escalations non-increasing over k = 0, 5, 10, 25 and strictly lower at 25 than at 0; failing families never above k = 0's |
| V7 | Every hard-rule record denied by every model |
| V8 | G-combined beats G-target on one of: held-out action, held-out domain, or P3 at k = 5. "Beats" means strictly fewer over-escalations and no more failing families |
| V9 | Shuffled-label and no-shared-effect worlds (development pool, calibration pools and fresh holdout relabelled alike) run through the full v2 procedure show no apparent transfer (V1 ∧ V2 ∧ V3 ∧ V5 ∧ V8) |
| V10 | Locality: 0 decision flips, after any accepted update, on records whose corrected concepts are satisfied or not applicable. Stability: between P3 steps, decisions change only on records exhibiting the new batch's concept states |

Family-bootstrap 90% intervals (1,000 resamples, seed 7) and exact record and family
denominators accompany every count.

## 8. Outcome (first match wins)

1. `STOP_LEARNED_ORG_MODEL_PATH`: V4, V5 or V8 fails. G-combined does not safely outperform the
   fixed rule or the target-only learner.
2. `STOP_MECHANISM_FAILED`: any other gate condition fails.
3. `NO_SYNTHETIC_VALUE_OVER_RETAIL`: the gate passes and retail shows a clear regression.
4. `INCONCLUSIVE_NEEDS_REAL_DATA`: the gate passes and retail is neither a clear regression nor
   favorable. Telecom stays
   sealed pending approval.
5. `GATE_PASSED_AWAITING_TELECOM_APPROVAL`: the gate passes and retail is favorable. Telecom
   stays sealed until its one evaluation is approved.

Outcomes 3 and 4 are checked in the order listed: a clear regression wins over inconclusive.

v1's results and files are not modified. The v1 freeze must still verify after v2.

## Amendment 1 (after the development run, before the freeze): no defect, no change

The development run used v1 stand-ins: the v1 held-out action, domain and P3 records, with no
fresh final slice. It completed without error and is kept in `results/development.json` as
development evidence.

**No code defect was found, and no parameter changed.** The run did show one behavior of the
preregistered parameters, recorded here so it cannot be mistaken for tuning:

- **No challenger was ever promoted** (P1, P2, P3), so G-combined equals G-synthetic.
- **Each update moves in the right direction.** A P2 batch of 21 records moves the harm weight by
  about +0.24 and reversibility by about −0.17.
- **The over-escalated should-run records are far from the threshold.** They score 0.39–0.50,
  about 3.4 logits below the certified 0.95 threshold.
- **Why nothing can change.** At λ_adapt = 10 and δ = 1.0, no single batch can cross that gap.
  Without a promotion, the champion never moves, so the cumulative bound is never reached.

The size-limited stand-ins also could not certify V1–V3; the fresh holdout is sized to.

The parameters stay as preregistered. Whether they suffice is what the fresh evaluation decides.
