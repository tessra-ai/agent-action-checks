# Decision-Record Benchmark v2

> Controlled synthetic decision benchmark. Demonstrates mechanism behavior only; does not establish real organizational performance.

| | |
|---|---|
| **Status** | `diagnostic` · `no-go` |
| **Outcome** | `STOP_LEARNED_ORG_MODEL_PATH` |
| **What changed from v1** | The decision procedure only: family-level certified thresholds, matched safety, bounded local adaptation. Concepts, generator, answer key and seal are unchanged |
| **Concept source** | Authoritative (synthetic latent facts). No judge, LLM or external model was called |
| **Spend** | $0.00; 0 external calls |
| **Telecom** | Still sealed and never opened |

Preregistration: [`RFC-v2.md`](RFC-v2.md), including amendment 1, which records the development run before the freeze.

## Gate (frozen; evaluated once on the fresh holdout)

| Condition | Result |
|---|---|
| V1 safe overall | pass |
| V2 safe held out action | pass |
| V3 safe held out domain | pass |
| V4 over escalations down 20pct overall | **fail** |
| V5 over escalations down 20pct action or domain | **fail** |
| V6 held out profile adapts monotonically | **fail** |
| V7 hard rules preserved | pass |
| V8 beats target only on a transfer measure | pass |
| V9 controls show no apparent transfer | pass |
| V10 locality and stability | pass |

Transfer measures, G-combined against G-target: held_out_action True, held_out_domain False, p3_k5 True.

## Matched safety on the fresh holdout

Every model's threshold was chosen by cross-fitting and certified on untouched calibration families (one-sided 95% Clopper-Pearson UCB at most 0.10 on family risk). A record of profile P is decided by that profile's model.

### Overall (final, held-out action and held-out domain)

| Model | Failing families (certified unit) | False allows (records) | Safe automatic runs | Over-escalations |
|---|---|---|---|---|
| DC-score | 0/96 (UCB 0.031) | 0/315 | 106/255 | 149/255 |
| G-synthetic | 0/96 (UCB 0.031) | 0/315 | 92/255 | 163/255 |
| G-target | 0/96 (UCB 0.031) | 0/315 | 114/255 | 141/255 |
| G-combined | 0/96 (UCB 0.031) | 0/315 | 92/255 | 163/255 |

### Fresh final (in-distribution)

| Model | Failing families (certified unit) | False allows (records) | Safe automatic runs | Over-escalations |
|---|---|---|---|---|
| DC-score | 0/32 (UCB 0.089) | 0/102 | 37/88 | 51/88 |
| G-synthetic | 0/32 (UCB 0.089) | 0/102 | 31/88 | 57/88 |
| G-target | 0/32 (UCB 0.089) | 0/102 | 35/88 | 53/88 |
| G-combined | 0/32 (UCB 0.089) | 0/102 | 31/88 | 57/88 |

### Held-out action (`issue_reimbursement`)

| Model | Failing families (certified unit) | False allows (records) | Safe automatic runs | Over-escalations |
|---|---|---|---|---|
| DC-score | 0/32 (UCB 0.089) | 0/101 | 44/89 | 45/89 |
| G-synthetic | 0/32 (UCB 0.089) | 0/101 | 44/89 | 45/89 |
| G-target | 0/32 (UCB 0.089) | 0/101 | 41/89 | 48/89 |
| G-combined | 0/32 (UCB 0.089) | 0/101 | 44/89 | 45/89 |

### Held-out domain (`access`)

| Model | Failing families (certified unit) | False allows (records) | Safe automatic runs | Over-escalations |
|---|---|---|---|---|
| DC-score | 0/32 (UCB 0.089) | 0/112 | 25/78 | 53/78 |
| G-synthetic | 0/32 (UCB 0.089) | 0/112 | 17/78 | 61/78 |
| G-target | 0/32 (UCB 0.089) | 0/112 | 38/78 | 40/78 |
| G-combined | 0/32 (UCB 0.089) | 0/112 | 17/78 | 61/78 |

Family-bootstrap 90% intervals, G-combined minus DC-score:

| Slice | Failing families | Over-escalations |
|---|---|---|
| overall | +0 (+0 to +0) | +14 (+5 to +25) |
| fresh_final | +0 (+0 to +0) | +6 (+0 to +12) |
| fresh_action | +0 (+0 to +0) | +0 (+0 to +0) |
| fresh_domain | +0 (+0 to +0) | +8 (+1 to +15) |

## Thresholds and certificates

| Model | Threshold | Certificate |
|---|---|---|
| G-synthetic | 0.95 | certified |
| DC-score(P1) | 1 | certified |
| DC-score(P2) | 1 | certified |
| DC-score(P3) | 1 | certified |
| G-target(P1) | 0.75 | certified |
| G-target(P2) | 0.95 | certified |
| G-target(P3, k=0) | escalate all | k = 0 |
| G-target(P3, k=10) | 0.9 | certified |
| G-target(P3, k=25) | escalate all | failed: escalate everything |
| G-target(P3, k=5) | escalate all | no candidate |

## Adaptation

| Organization | Looks | Promoted | Promotion-pool over-escalations: champion / challenger |
|---|---|---|---|
| P1 | 5 | 0 | 47/47, 47/47, 47/47, 47/47, 47/47 |
| P2 | 5 | 0 | 52/52, 52/52, 52/52, 52/52, 52/52 |
| P3 (held out) | 3 | 0 | 73/73, 73/73, 73/73 |

Certification holds per promotion look, with no multiplicity correction (at most 5 looks per organization, 3 for P3).

### Held-out profile (P3) evaluation set, after k corrections

| k | G-combined: failing families · over-escalations · safe runs | G-target: same |
|---|---|---|
| 0 | 0/32 · 66/93 · 27/93 | 0/32 · 93/93 · 0/93 |
| 10 | 0/32 · 66/93 · 27/93 | 0/32 · 93/93 · 0/93 |
| 25 | 0/32 · 66/93 · 27/93 | 0/32 · 93/93 · 0/93 |
| 5 | 0/32 · 66/93 · 27/93 | 0/32 · 93/93 · 0/93 |

Locality (V10): 0 flips in 0 checked decisions. No update was accepted, so the check is vacuous; the unit tests prove the property by construction.

## Operating curves on the fresh holdout (descriptive only)

Failing families and over-escalations at each grid threshold, overall.

| Threshold | DC-score | G-synthetic | G-target | G-combined |
|---|---|---|---|---|
| 1 | 0 · 149 | — | — | — |
| 0.999 | — | 0 · 255 | 0 · 255 | 0 · 255 |
| 0.995 | — | 0 · 255 | 0 · 255 | 0 · 255 |
| 0.99 | — | 0 · 255 | 0 · 255 | 0 · 255 |
| 0.975 | — | 0 · 255 | 0 · 255 | 0 · 255 |
| 0.95 | — | 0 · 163 | 0 · 255 | 0 · 163 |
| 0.9 | — | 0 · 155 | 0 · 92 | 0 · 155 |
| 0.875 | 56 · 6 | — | — | — |
| 0.85 | — | 0 · 149 | 0 · 48 | 0 · 149 |
| 0.8 | — | 0 · 149 | 0 · 7 | 0 · 149 |
| 0.75 | 95 · 0 | 0 · 149 | 5 · 0 | 0 · 149 |
| 0.7 | — | 0 · 149 | 5 · 0 | 0 · 149 |
| 0.6 | — | 17 · 78 | 6 · 0 | 17 · 78 |
| 0.5 | — | 36 · 21 | 12 · 0 | 36 · 21 |

## Synthetic pretraining learning curve (G-synthetic, overall)

| Pretraining records | Threshold | Certificate | Failing families | Over-escalations |
|---|---|---|---|---|
| 25 | 0.75 | certified | 0/96 | 255/255 |
| 50 | escalate all | failed: escalate everything | 0/96 | 255/255 |
| 100 | 0.9 | certified | 0/96 | 155/255 |
| 200 | 0.75 | certified | 0/96 | 149/255 |
| 210 | 0.95 | certified | 0/96 | 163/255 |

## Retail (development-grade, not a gate condition)

Six families, all opened in v1, so no certification is possible. Leave-one-family-out rotation verdict: **inconclusive** (G-combined worse in 4 of 6 folds, favorable in 1).

| Model (pooled over 6 folds) | False allows | Safe automatic runs |
|---|---|---|
| DC-score | 0/47 | 0/25 |
| G-combined | 0/47 | 0/25 |
| G-retail | 7/47 | 25/25 |

This is not reliable statistical evidence.

## Negative controls (V9)

| Control | Apparent transfer | G-combined failing families / over-escalations |
|---|---|---|
| no shared effect | False | 0/62 · 263/263 |
| shuffled labels | False | 0/96 · 255/255 |

## Outcome: `STOP_LEARNED_ORG_MODEL_PATH`

The preregistered stop rule applies. With perfect concepts and certified-matched safety, the
shared learned organizational model (synthetic pretraining, then bounded adaptation) did not
safely outperform the fixed concept rule.

- **Overall** it escalated **163/255** should-run records, against DC-score's **149/255**: 14
  more, with a family-bootstrap 90% interval of +5 to +25 (V4).
- **Held-out action:** tied, 45/89 each (V5).
- **Held-out domain:** worse, 61/78 against 53/78 (V5).

The learned organizational-model path, as designed, stops here.

**What v2 fixed:**

- **Safety is certified, not assumed.** Every model's threshold was certified on untouched
  calibration families. On the fresh holdout, every model had 0 of 96 eligible families failing
  (UCB 0.031) and 0 false allows. The comparison is at matched safety, unlike v1's comparison
  against a rule with 17 false allows.
- **Updates are local and bounded by construction.** One correction can no longer move unrelated
  decisions: the unit tests prove 0 flips. Nothing is re-thresholded on a handful of records.

**Why it still failed** (development amendment 1 predicted this before the freeze):

1. **Adaptation never moved.** No challenger was promoted for P1, P2 or the held-out P3, so
   G-combined is exactly G-synthetic.
   - Under the preregistered anchoring (λ = 10, δ = 1.0), a batch moves a weight by about
     0.2 logits.
   - The over-escalated should-run records sit about 3.4 logits below the certified threshold.
   - Bounded *and* promotion-gated updates cannot accumulate: the champion never moves, so the
     cumulative bound is never reached.
   - Held-out-profile adaptation therefore stayed flat at 66/93 over-escalations for every k
     (V6).
2. **Pooled pretraining is a compromise.** G-synthetic was fitted on P1 and P2 together, whose
   grey-area preferences conflict, so it learned to escalate the union of what either escalates.
   That is safe, but more conservative than either organization and than the fixed rule.

**What the comparison does show:**

- **Organization-specific learning from scratch is learnable.** G-target fits one organization's
  records with no pretraining.
  - Overall it escalated 141/255, fewer than DC-score's 149/255 (about 5%, short of the 20% bar).
  - On the held-out domain it escalated 40/78 against 53/78, 25% fewer.
  - V8 passes only because G-combined beat G-target on the held-out action (45 vs 48) and at
    P3 k = 5. There, G-target cannot certify anything from 5 corrections.
- **The signal lives in organization-specific fitting, not in the shared pretrained model.**
- **G-target left autonomy on the table.** Its operating curve (descriptive, chosen on the
  holdout, so not a result) reaches 0 failing families with only 7 over-escalations at
  threshold 0.8. Its certified thresholds were 0.75 for P1 and 0.95 for P2.
- **The negative controls behaved.** Shuffled labels and the no-shared-effect world produced no
  apparent transfer; every model escalated everything.
- **Retail is inconclusive and development-grade.**
  - G-retail let all 25 should-run records through but with 7/47 false allows.
  - G-combined let none through.
  - Six opened families cannot settle it.

**What this means.** The current approach is one pretrained model shared across organizations,
then nudged per organization under tight, safety-gated updates. It does not beat a fixed concept
rule, even with perfect concepts. More data is unlikely to rescue it:

- the obstacle is structural: conflicting organizational preferences in pooled pretraining, and
  updates too constrained to undo them;
- loosening the anchoring brings back the instability v1 showed.

A different model would be a new experiment with its own preregistration, for example one that
represents organizational preferences explicitly instead of averaging them away.

**Not done, by design:** telecom remains sealed; no semantic scoring; no merge.

## Provenance and hashes

| Item | Value |
|---|---|
| Freeze | `59b4796c1e31a00d276cd24b218a10f2a285271367385d0e63b371f4ad499003` at commit `0235f557e55092602be2035e6118141216d64aa5` |
| Development pool (v1 P1/P2 in-distribution) | `56433d394c9ee2afdd7ace98abf0aab38eabf7e04c4337bc9c74eaf06876e1bd` |
| Calibration pools (seed 20261024) | `bf252816984c4e334ce7d612310d5b80973b4eccd442e5188559cb6029c86fe5`: cal_P1 32 eligible families, cal_P2 32 eligible families |
| Fresh holdout (seed 1504999788, from the freeze) | `42c239e4eae31c6883be704bf8335e0e216d76a2e8cbb6158b6cfc42819c09a5`: fresh_action 32 families, fresh_domain 32 families, fresh_final 32 families, fresh_hard 10 families, fresh_p3_corrections 5 families, fresh_p3_eval 33 families, fresh_p3_promotion 34 families |
| Telecom seal (unopened) | `ff645fd7630647c5c6415a52bbc0310b00ec5b969b4190e4d5c35cdcce06ff0d` |
| Fresh manifest | `3941fb6b144e2f9f74d9772e0275c073d496c307c5f123f0622dfc97d24c87ba` |

Code hashes are in [`freeze.json`](freeze.json). Full results: [`results/v2.json`](results/v2.json). Development run: [`results/development.json`](results/development.json).

## Reproduction (zero spend)

```bash
python -m hatchway.bench.drb.v2 calibrate        # refuses: written once (regenerates identically from seed 20261024)
python -m hatchway.bench.drb.v2 develop          # development evidence on v1 stand-ins
python -m hatchway.bench.drb.v2 freeze           # refuses: written once
python -m hatchway.bench.drb.v2 generate-fresh   # refuses: written once (seed from the freeze hash)
python -m hatchway.bench.drb.v2 evaluate         # refuses: evaluated once
python -m hatchway.bench.drb.v2 report
```

Cost ledger: $0.00. No judge, LLM, external model or τ² capture was used.
