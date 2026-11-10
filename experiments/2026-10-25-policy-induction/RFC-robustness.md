# RFC: Policy induction robustness pack (zero spend)

| | |
|---|---|
| **Status** | `planned`: preregistered before any code runs on the fresh data |
| **Builds on** | [`RFC.md`](RFC.md) and the Phase A results (`BENCHMARK_TOO_HARD`). The Phase A code, cases and results are not modified |
| **Spend** | $0: no model, judge or external calls |

Phase A rests on 13 hand-picked rules, one generator seed, perfect perception and a perfectly
consistent approver. Phase A also suggested two design rules: audits for missed escalations,
and certification for relaxations. This pack tests all of that.

It does not change Phase A's outcome, and it does not open Phase B.

## Data

- **Generator:** the unchanged `pi-cases-1`, run on a **fresh seed, 20261026**. Cases and the
  sampled rules are written to `robustness/` with a manifest, and committed before any
  evaluation.
- **Split.** Families split three ways by `sha256("20261026:split3:<family>") % 5`:

  | Buckets | Share | Used for |
  |---|---|---|
  | 0, 1 | 40% | train |
  | 2 | 20% | certification |
  | 3, 4 | 40% | test |

  R1 instead uses Phase A's own 50/50 split, unchanged.
- **Arms:** S as frozen in Phase A (`induce.py`). S-cert is defined in R4.

## R1: Replication on a fresh seed (confirmatory)

Run Phase A's frozen sweep (`evaluate.run_all`, unchanged) on the fresh cases.

**Passes when:**
- A1 and A3 hold;
- at least 11 of the 13 worlds have `clean` k* (arm S) within one grid step of Phase A. For
  this comparison, "not recovered" is treated as one step beyond 20.

The fresh seed's own A1–A3 outcome label is reported. It does not replace Phase A's.

## R2: Randomly drawn rules (descriptive curve)

Rules are drawn from a grammar with rule-sampling seed 20261026. The first 100 escalation rules
and 20 relaxation rules that pass the filter are kept.

**Escalation rule:** escalate an otherwise allowed case when its condition holds.
- **Scope:** one action (probability 0.7) or any action.
- **Conditions:** one condition (probability 0.5) or two.
- **A condition is one of:**
  - a numeric fact above a threshold. The fact is `amount`, `order_total`, `n_items` or
    `user_orders`, plus `price_difference` for exchanges. The threshold is the q-quantile of
    the fact over ALLOW cases in scope, with q drawn uniformly from [0.6, 0.95], rounded
    (amounts to $50, counts to integers);
  - `payment_source` equal to a value;
  - `user_state` equal to a value drawn from the 10 most common states;
  - the affected items including a product.

**Relaxation rule:** allow a cancellation, return or exchange that the oracle escalates *only*
for a missing confirmation, when one condition (as above) holds.

**Filter** (on the fresh cases, before any learner runs):
- at least 25 training families with a triggering case;
- triggering cases are at most 25% of the cases in scope that the starting policy decides the
  other way;
- the rule's triggering set is not identical to an earlier kept rule's.

**Run:** arm S, `clean` labels, k ∈ {1, 2, 5, 10, 20}, 10 replicates, 300 background cases.

**Reported:**
- the share of rules with k* ≤ 5, ≤ 10 and ≤ 20, by rule type (number of conditions, condition
  kind, relaxation or escalation);
- k* against how often the rule fires.

## R3: Pricing audits (directional)

**Setting:**
- **Rules:** the R2 escalation rules with at least 40 training triggering families, plus H1 and
  H3. H4 is included if it has at least 40 such families on the fresh seed.
- **Training sample:** k ∈ {10, 20, 40} triggering cases plus 300 background cases.
- **What the learner sees:** every case the starting policy escalates, plus an audit of `b`
  of the cases it allows, where `b = round(rate × allowed in the sample)`.
- **Rates:** {0.02, 0.05, 0.10, 0.25, 0.50, 1.00}.

**Audit strategies:**
- **random:** b cases drawn uniformly.
- **targeted (two rounds):**
  1. Half the budget at random.
  2. On those audits, take the three literals with the lowest unadjusted hypergeometric
     p-value among literals covering at least one positive.
  3. Spend the other half on unaudited allowed cases those literals cover. Fill any shortfall
     at random. If round 1 found no positive, round 2 is random.
- **targeted-shuffled (control):** the targeted strategy at rate 0.25, with the training labels
  permuted first.

10 replicates per cell.

**Needed rate** for a (rule, k) cell: the smallest rate with a recovery rate of at least 0.8,
or ∞ if no rate reaches it.

**R3 passes when both hold:**
- among cells where either strategy reaches recovery, targeted needs at most half of random's
  rate in at least 50% of them;
- targeted-shuffled accepts a rule in at most 5% of runs.

## R4: Specific, certified exceptions (confirmatory for the design rule)

**Arm S-cert:** S, with each accepted exception changed in two ways.
1. **Specialized.** The exception becomes the conjunction of every candidate literal that
   holds for all the positives it covered in training (for each numeric fact, the tightest
   bound each way), together with its own literals.
2. **Certified on the certification split.** Take the certification-split cases the exception
   would allow: the starting policy escalates them for `ask` reasons only, and the rule fires.
   - Eligible families are families with such a case.
   - Failing families are those where such a case is one the truth escalates.
   - The exception is kept only if the one-sided 95% Clopper-Pearson bound is at most 0.10.

Escalation rules are left unchanged; they err toward escalating.

**Worlds:** H6 and the 20 R2 relaxation rules on the fresh seed, at k ∈ {5, 10, 20}, 10
replicates, `clean` labels.

**R4 passes when both hold:**
- **The certificate holds out of sample.** Pooled over runs, the test families where an S-cert
  exception allows a case fail (the truth escalates an allowed case) at a rate of at most 0.10.
- **The problem exists.** S's own pooled rate exceeds 0.10.

**Also reported:** catch retained (relaxation cases correctly allowed) for S and S-cert.

**v2 side check, repeated with S-cert (descriptive; v2's holdout was already used):**
- exceptions are specialized on v2's development records;
- they are certified on v2's untouched calibration pools (`cal_P1`, `cal_P2`);
- the result is evaluated on v2's fresh slices.

## R5: Imperfect perception (descriptive)

**Noise model.** Learner-visible facts are corrupted independently per case, seeded by case
and rate, at rate e ∈ {0, 0.02, 0.05, 0.10}:
- each boolean fact is flipped with probability e;
- each categorical fact, with probability e, is replaced by another value seen in the data;
- each numeric fact, with probability e, is replaced by a value drawn from its distribution;
- the product set, with probability e, is replaced by another case's product set.

The noise applies to training and test facts. The starting policy and the truth use the true
checks.

**Worlds and grid:**
- the 13 Phase A worlds, regenerated on the fresh seed, plus the first 30 R2 escalation rules;
- arm S, `clean` labels;
- k ∈ {5, 10, 20}, 10 replicates.

**Reported:** catch and false invention against e. The recovery criterion is too strict to be
meaningful under noise.

## Run order

1. Commit this RFC.
2. Commit the code and tests. Smoke runs use generator seed 1 only.
3. `generate`: fresh cases and sampled rules, with manifest; commit.
4. `evaluate`: once, to `results/robustness.json`.
5. `report`.
