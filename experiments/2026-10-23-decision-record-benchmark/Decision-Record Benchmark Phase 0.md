# Decision-Record Benchmark, Phase 0

> Controlled synthetic decision benchmark. Demonstrates mechanism behavior only; does not establish real organizational performance.

| | |
|---|---|
| **Status** | `diagnostic` · `no-go` |
| **Recommendation** | `STOP_MECHANISM_FAILED` |
| **Concept source** | Authoritative: synthetic latent facts and deterministic oracle checks. No judge, LLM or external model was called |
| **Spend** | $0.00; 0 external calls |
| **Telecom** | still sealed: the internal gate failed, so the telecom holdout was not opened |

Preregistration: [`RFC.md`](RFC.md) (with amendment 1, committed before any fit).

## Internal gate (frozen)

| Condition | Result |
|---|---|
| G1 no more false allows overall | pass |
| G2 no more false allows held out action | pass |
| G3 no more false allows held out domain | pass |
| G4 over escalations down 20pct overall | **fail** |
| G5 over escalations down 20pct action or domain | **fail** |
| G6 held out profile improves at 5 10 25 | **fail** |
| G7 hard rules preserved | pass |
| G8 beats target only on a transfer measure | **fail** |
| G9 controls show no apparent transfer | pass |
| coverage (≥10 should-run and ≥10 should-escalate per slice) | pass |

Gate **failed**. Transfer measures, G-combined against G-target: p3_k5 False, syn_holdout_action False, syn_holdout_domain False.

## Synthetic results

G-combined(P) pretrains on the pooled synthetic pretraining partition (P1 and P2), then adapts on profile P's own pretraining records. G-target(P) fits P's records alone.

### All gate slices (final holdout, held-out action, held-out domain)

| Model | False allows | Safe automatic runs | Over-escalations | Escalations (all) |
|---|---|---|---|---|
| DC | 17/69 | 49/66 | 17/66 | 69/135 |
| G-combined | 0/69 | 29/66 | 37/66 | 106/135 |

### Synthetic final holdout

| Model | False allows | Safe automatic runs | Over-escalations | Escalations (all) |
|---|---|---|---|---|
| escalate-all | 0/29 | 0/16 | 16/16 | 45/45 |
| DC | 11/29 | 12/16 | 4/16 | 22/45 |
| G-synthetic | 0/29 | 6/16 | 10/16 | 39/45 |
| G-target | 0/29 | 6/16 | 10/16 | 39/45 |
| G-combined | 0/29 | 6/16 | 10/16 | 39/45 |

### Held-out action (`issue_reimbursement`)

| Model | False allows | Safe automatic runs | Over-escalations | Escalations (all) |
|---|---|---|---|---|
| escalate-all | 0/13 | 0/17 | 17/17 | 30/30 |
| DC | 0/13 | 12/17 | 5/17 | 18/30 |
| G-synthetic | 0/13 | 12/17 | 5/17 | 18/30 |
| G-target | 0/13 | 6/17 | 11/17 | 24/30 |
| G-combined | 0/13 | 6/17 | 11/17 | 24/30 |

### Held-out domain (`access`)

| Model | False allows | Safe automatic runs | Over-escalations | Escalations (all) |
|---|---|---|---|---|
| escalate-all | 0/27 | 0/33 | 33/33 | 60/60 |
| DC | 6/27 | 25/33 | 8/33 | 29/60 |
| G-synthetic | 0/27 | 16/33 | 17/33 | 44/60 |
| G-target | 0/27 | 17/33 | 16/33 | 43/60 |
| G-combined | 0/27 | 17/33 | 16/33 | 43/60 |

Family-bootstrap 90% intervals for G-combined minus DC (1,000 resamples):

| Slice | False allows | Over-escalations |
|---|---|---|
| union | -17 (-27 to -8) | +20 (+10 to +30) |
| syn_final | -11 (-17 to -5) | +6 (+0 to +12) |
| syn_holdout_action | +0 (+0 to +0) | +6 (+0 to +12) |
| syn_holdout_domain | -6 (-12 to +0) | +8 (+2 to +14) |

### Held-out organizational profile (P3), adaptation after k corrections

| k | G-combined: false allows / over-escalations / safe runs | G-target: same |
|---|---|---|
| 0 | 0/19 · 5/11 · 6/11 | 0/19 · 11/11 · 0/11 |
| 10 | 0/19 · 9/11 · 2/11 | 0/19 · 9/11 · 2/11 |
| 25 | 0/19 · 0/11 · 11/11 | 4/19 · 0/11 · 11/11 |
| 5 | 0/19 · 3/11 · 8/11 | 2/19 · 3/11 · 8/11 |

### Synthetic pretraining learning curve (G-synthetic, on the gate slices)

| Pretraining records | False allows | Safe runs | Over-escalations | Brier |
|---|---|---|---|---|
| 25 | 0/69 | 0/66 | 66/66 | 0.273 |
| 50 | 0/69 | 0/66 | 66/66 | 0.193 |
| 100 | 0/69 | 34/66 | 32/66 | 0.117 |
| 130 | 0/69 | 34/66 | 32/66 | 0.113 |
| DC (reference) | 17/69 | 49/66 | 17/66 | — |

## Retail adaptation (target organization, internal holdout)

| Model | False allows | Safe automatic runs | Over-escalations | Escalations (all) |
|---|---|---|---|---|
| escalate-all | 0/16 | 0/5 | 5/5 | 21/21 |
| DC | 0/16 | 0/5 | 5/5 | 21/21 |
| G-synthetic | 0/16 | 0/5 | 5/5 | 21/21 |
| G-retail | 0/16 | 5/5 | 0/5 | 16/21 |
| G-combined | 0/16 | 0/5 | 5/5 | 21/21 |

| Retail adaptation records k | G-retail: false allows · safe runs | G-combined: false allows · safe runs |
|---|---|---|
| 0 | 0/16 · 0/5 | 0/16 · 0/5 |
| 5 | 0/16 · 4/5 | 0/16 · 0/5 |
| 10 | 0/16 · 4/5 | 0/16 · 0/5 |
| 25 | 0/16 · 4/5 | 0/16 · 0/5 |
| 37 | 0/16 · 5/5 | 0/16 · 0/5 |

Retail coverage by action (ALLOW / ASK / DENY): cancel_pending_order 6/0/1; exchange_delivered_order_items 0/1/11; modify_pending_order_items 1/1/0; modify_user_address 0/0/2; return_delivered_order_items 18/7/24. Left out: {'no_verdict': 0, 'unknown_verdict': 1}. Six scenario families in all; no missing action or class was filled with synthetic records.

## Controls

| Control | Apparent transfer | G-combined false allows | G-combined over-escalations |
|---|---|---|---|
| shuffled labels | False | 1/70 | 62/65 |
| no shared effect | False | 0/43 | 92/92 |

- **Paraphrase:** 71/71 pairs decided identically.
- **Irrelevant context:** 71/71 pairs decided identically. These two are structural in Phase 0: authoritative concepts give identical inputs.
- **Contradictory evidence:** 20/20 escalated.
- **Locality:** adapting G-synthetic on 1 reversibility-only correction(s) changed 23/83 decisions on records where reversibility was satisfied.
- **Representation conflicts in development data:** 0 of 61 input groups.
- **Hard rules:** every hard-rule record was denied by every model (20 records).

## Recommendation: `STOP_MECHANISM_FAILED`

The learned decision rule failed the frozen internal gate. It failed even with perfect concepts,
where semantic extraction cannot be the excuse. By the preregistered rule (RFC amendment 1), a
gate failure with no representation conflict is `STOP_MECHANISM_FAILED`. The development data
had 0 conflicting groups out of 61, so the frozen concepts could express every organization's
answer key, and the failure lies in the learner and its decision procedure. Telecom was not
opened, and paid semantic scoring is not recommended.

**What held:**

- **Safety (G1–G3).** G-combined let no should-escalate record through: 0/69 across the gate
  slices, against DC's 17/69.
  - DC is not a safe reference here. It ignores reversibility, so it runs irreversible actions
    that profile P2 escalates.
- **Hard rules (G7).** All 20 hard-rule records were denied by every model.
- **Negative controls (G9).** Neither shuffled labels nor the no-shared-effect world produced
  apparent transfer. The benchmark does not report transfer by default.

**What failed:**

1. **No autonomy gain (G4, G5).**
   - G-combined over-escalated 37/66 should-run records, against DC's 17/66, which is 20 more.
     The family-bootstrap 90% interval is +10 to +30.
   - The held-out action and domain were no better: 11/17 against 5/17, and 16/33 against
     8/33.
   - The learned models buy safety by escalating. Under the frozen threshold rule (zero false
     allows on the selection set), one high-scoring should-escalate record makes a model
     escalate everything. That happened to G-combined(P2), to G-target(P2) and to G-combined on
     retail.
2. **Adaptation was not monotone (G6).** On the held-out profile, over-escalations went 5 → 3
   → 9 → 0 at k = 0, 5, 10 and 25. Thresholds re-selected on the k adaptation records swing with
   each correction.
3. **Pretraining did not beat target-only fitting on any transfer measure (G8).**
   - On the held-out action, G-combined and G-target were identical.
   - At k = 5, G-combined avoided two false allows that G-target made, but did not reduce
     over-escalations (3/11 each). The preregistered measure is over-escalations, so this does
     not count.
4. **Synthetic pretraining hurt the target organization.**
   - On the retail internal holdout, G-retail safely let all 5 should-run records through (0/16
     false allows).
   - G-combined, starting from the synthetic prior, let none through. Its retail curve stays at
     0/5 from k = 0 to the full 37 records.
   - The synthetic profiles escalate high-impact and irreversible actions, and the τ² retail
     policy does not. At the frozen adaptation strength, 37 retail records did not overcome
     that prior.
5. **Adaptation is not local.** One reversibility-only correction changed 23 of 83 decisions on
   records where reversibility was satisfied. A correction moves the intercept and the
   threshold, not just the concept it is about.

**Reading against the interpretation matrix.** "G-combined fails internal perfect-concept gate →
decision representation or learner failed; do not pay for semantic scoring." The evidence points
at the learner and its threshold and adaptation procedure, not at the concept schema.

**One diagnostic outside the gate.** Without any adaptation, G-synthetic matched DC on the
held-out action: 12/17 should-run records allowed and 0/13 false allows, where G-combined allowed
6/17. On the held-out domain it allowed 16/33 with 0/27 false allows; DC allowed 25/33 but with
6/27 false allows. The shared structure carried to an unseen action safely. What cost autonomy
was the adaptation and threshold step. This is a diagnostic, not a gate result: the gate tests
G-combined.

**What this does not show:**

- **That shared concepts cannot work.** G-synthetic's learning curve, at 0 false allows, went
  from 0/66 to 34/66 should-run records allowed as pretraining grew from 50 to 100 records, and
  the controls show it is not memorizing.
- **Anything about telecom**, which remains sealed and unused.
- **Anything about real organizations.** This is a controlled synthetic benchmark.

**If the work continues, it is a new experiment version (`decision-record-benchmark-v2`) with
its own preregistration.** These results may not be re-scored under a changed rule. Candidate
changes:

- a threshold procedure that tolerates a bounded false-allow rate with an upper confidence bound,
  instead of zero on a tiny selection set;
- adaptation that regularizes the threshold as well as the coefficients;
- a pretraining mixture that includes an organization like the target's.

The telecom set would stay sealed for that version too: it was not opened here.

## Provenance and hashes

| Item | Value |
|---|---|
| Freeze | `17f09a53072e2816c213768a0a31c685034b29f4ff05471da28b6e61e94857a0` at commit `f4117779ae59b83415dcd548261ca83e793a9858` |
| Model spec (`drb-model-1`) | `14e490f3a53d7cb0605974a9a2174a0278335e649dac36a7e6c8394961161377` |
| Synthetic dataset | `17ce6f9e3b853a0ec9af7d4e8094ac0460323511bdf34b4f2655c358e50a7b00` (375 records, generator `drb-synthetic-1`, seed 20261023) |
| Retail dataset | `c3be30ab7ff062132dc05c2d60f5be533055d7bf01b001ff8d5c08753d860655` (72 records, oracle `tau2-oracle-1:41ee37217182`, mapping `drb-realmap-1`) |
| Telecom seal | `ff645fd7630647c5c6415a52bbc0310b00ec5b969b4190e4d5c35cdcce06ff0d` (35 records, 10 families, 33 with a verdict) |
| Synthetic pretraining set | `37b0e8012927a66a1612a4c819c537502b9edb6a9fda59803bc6892cd17b9066` |
| Retail adaptation set | `65a6d38acd3f35e245ed8e91550df4fef13fa956c5a35ccdabc42b5b37b795fd` |
| G-synthetic | `G-synthetic:147f1f367c6e8c87` |
| Promotion | false allows 0 <= DC's 0; 12 should-run records allowed |

Code hashes are listed in [`freeze.json`](freeze.json); full results are in [`results/internal.json`](results/internal.json).

## Reproduction (zero spend)

```bash
pip install -e '.[dev]' -e ./.tau2-bench      # τ² at c5b2d228…; stores runs/targeted.db, runs/smoke2.db
python -m hatchway.bench.drb seal-telecom     # refuses: the seal is written once
python -m hatchway.bench.drb generate         # regenerates the synthetic records (identical hash)
python -m hatchway.bench.drb map-retail
python -m hatchway.bench.drb freeze           # refuses: written once
python -m hatchway.bench.drb develop          # refuses: written once (delete results/ in a scratch copy to rerun)
python -m hatchway.bench.drb final-eval       # refuses: the internal gate failed
python -m hatchway.bench.drb report
```

Cost ledger: $0.00; no judge, LLM, external model or τ² capture was used.
