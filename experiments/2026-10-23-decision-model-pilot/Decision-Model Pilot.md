# Decision-Model Pilot

| | |
|---|---|
| **Status** | `directional` · `no-go` |
| **Decision** | `PHASE_2_NO_GO_AS_SPECIFIED` |
| **Ground truth** | Deterministic policy oracle only, unaudited. No independent human validation; not a publishable result. |
| **Scope** | Phases 0–1 only. No new capture. Writes already captured in the targeted stage 1 and the second smoke run were reused. |
| **Report version** | v1 (this file). It supersedes the HTML viewer published on 2026-10-23 as the record of this experiment; see "Interpretation corrections". |

## Question

Does a shared organizational decision model get closer to the product thesis than the fixed
baseline? Three questions were separated:

1. **D vs DC.** Do shared decision concepts carry more signal than the two generic policy
   questions? This is the value of the concepts.
2. **DC vs G1.** Does learning add value over a fixed rule on exactly the same concept inputs?
   This is the value of learning.
3. **Transfer and adaptation.** Does the learned model transfer to an action it never saw, and
   does it adapt from real corrections, without losing safety?

## Arms (frozen before any score was examined)

All three primary arms read one OpenAI Decisions call per write. They share one threshold
procedure: the lowest threshold that escalates at least 95% of the revealed writes whose correct
decision was ASK or DENY.

| Arm | Inputs | Combination |
|---|---|---|
| **D** | `policy_ok`, `matches_request` | Mean of the two answers (the existing baseline) |
| **DC** | Ten shared concepts, each with applicability, assessment, confidence and evidence | Fixed rule: minimum assessment over the applicable correctness concepts. `reversible` is excluded because it measures stakes, not correctness. |
| **G1** | Exactly DC's concept inputs plus coarse `impact` and `reversible` metadata | L2 logistic regression (C = 1.0, balanced class weights, seed 0). The threshold is fitted on family-grouped out-of-fold predictions. No action or domain identity and no action-specific answers; inputs are asserted at fit time. |

- "Not applicable" is a missing assessment with its own indicator. It is never read as satisfied.
- The deterministic hard-DENY layer runs before every arm and cannot be overridden. It is empty
  for τ² because the hard rules (M8) are not built yet.
- Secondary diagnostics, never primary: Jev variants of D, DC and G1; G1 with per-action offsets;
  and G1 on both judges.

## Provenance

| Item | Value |
|---|---|
| Freeze commit (pilot code pinned by hash) | `4f1cb9c529ce748065c70fcab00341519a74ed2c` |
| Report-renderer commit used for the HTML viewer | `4d6a8f4e053a761de45baf20d2c0a1792159cfb7` |
| Definition sha256 | `5b7069c2e16ebb020cf3f59f4f307f707468c1707a79d1cc899567dab4436e24` ([`manifest.json`](manifest.json), verbatim `runs/pilot/pilot.json`) |
| Arm-spec sha256 (D, DC, G1, hard rules) | `f8926d1953240c74d73314aeb38f6d08957986c329111deb8a06fca45ad859e5` |
| Oracle version | `tau2-oracle-1:41ee37217182` (10 validators; adds exchange, item change, cancel, address change, line resume and roaming off) |
| Policy file sha256 (`hatchway/bench/tau2/hatchway.yaml`) | `cd28bff5048b27ff9487fc445236338f3ec66cd0f75bf927739987bde9e4dcc7` |
| Pilot rubric | `pilot-concepts-1:*`, one hash per write action (13 actions; listed in the manifest) |
| Judges | OpenAI Decisions `gpt-6-luna` (primary); Jev `jev-1.14.0` (secondary) |
| τ²-bench | `c5b2d228d850c59b749b93cf32c4745d3aa53967` (pinned and installed) |
| Candidate writes sha256 | `7e9d393530ffa8b1ad2fc255fcaa7104c0f4adc32ddd7f73ce34e0bee6422060` (108 writes, 16 scenario families) |
| Split file sha256 | `c3497ecd0e0f441cef24febbeb4f1ac78941a0f0b5b41be1d3decd9a711a1ea6` ([`results/split.json`](results/split.json); holdout stored as 5 salted family hashes) |
| Final-evaluation output sha256 | `868382abe4b882bc6cc12c896d66ce4845b1f2660036f632b8b57d06d12b9044` ([`results/final.json`](results/final.json); `final-eval` ran once) |
| Fitted arm versions (holdout) | D `D:5c6f69b9cced3136` (t = 0.9925), DC `DC:fa4fb487f21ba69e` (t = 0.4091), G1 `G1:496bf314ec68b977` (t = 0.9995) |
| Merged commit / tag | `2f35f8c` (PR #14) / `experiment/decision-model-pilot-v1`; see [`PROVENANCE.md`](PROVENANCE.md) |

## Data

These are completed simulations only. Scenario families are never split across datasets. The
label-free split is per domain and lands closest to 50/20/30 by write count.

| Dataset | Families | Writes | With a verdict | Retail / telecom writes |
|---|---|---|---|---|
| Revealed (fitting, thresholds, corrections) | 8 | 54 | 54 | 37 / 17 |
| Promotion (accept or reject challengers) | 3 | 22 | 21 | 15 / 7 |
| Holdout (read once by `final-eval`) | 5 | 32 | 30 | 21 / 11 |

The holdout has 9 writes that should run and 21 that should escalate. By action
(allow / ask / deny):

- exchange 0/0/10;
- return 4/2/2;
- enable roaming 4/0/1;
- refuel 0/3/0;
- modify items 1/1/0;
- cancel 0/0/1;
- payment request 0/0/1.

## Results

### Primary comparison (holdout)

| Arm | False allows (of should-escalate) | Asks (of all) | Approvals saved (of should-run) | AUC |
|---|---|---|---|---|
| D | 0/21 | 28/30 | 2/9 | 0.95 |
| DC | 0/21 | 27/30 | 3/9 | 0.72 |
| G1 | 0/21 | 30/30 | 0/9 | 0.84 |

90% intervals are from a family bootstrap over 5 families, 2,000 resamples:

| Difference | False-allow rate | Ask rate |
|---|---|---|
| DC − D | 0 | −4 pts (−11 to +11) |
| G1 − DC | 0 | +10 pts (0 to +13) |
| G1 − D | 0 | +7 pts (0 to +13) |

- **D vs DC (value of shared concepts):** no measurable difference on the holdout.
- **DC vs G1 (value of learning):** none. G1 escalated every holdout write.

### Revealed stream: prequential learning curve

Each write was decided by the arm fitted on every labelled write before it, over 20 frozen
family orderings. Medians after all 54 writes (29 should escalate, 25 should run):

| Arm | False allows | Asks | Approvals saved |
|---|---|---|---|
| D | 3 | 38.5 | 12 |
| DC | 2 | 45.5 | 7 |
| G1 | 2 | 49 | 3 |

### Promotion set and safe evolution

- **Primary arms, fitted on revealed data:**
  - D: 0/18 false allows, 21/21 asks.
  - DC: 3/18 false allows, 17/21 asks, 1/3 approvals saved.
  - G1: 0/18 false allows, 21/21 asks.
- **Champion/challenger:** the starting champion was "escalate everything". No G1 challenger was
  promoted in any of the 20 orderings: each was as safe but escalated no less. Rollback was
  therefore never exercised on real data; the unit tests cover it.

### Within-action (holdout)

Only returns had both should-run and should-escalate writes in any number:

| Arm | Approvals saved | Asks | False allows |
|---|---|---|---|
| D | 1/4 | 7/8 | 0 |
| DC | 2/4 | 6/8 | 0 |
| G1 | 0/4 | 8/8 | 0 |

The other per-action results are in `results/final.json` (`by_action`).

### Held-out-action transfer (holdout)

Only exchange met the coverage rule (at least 10 writes with a verdict and at least 3 that
should escalate). Every other action is inconclusive. See correction 2.

### Adaptation from real corrections (revealed stream)

| Concept | Arm | Later failures caught, other actions | Later failures caught, same action | Should-run writes escalated |
|---|---|---|---|---|
| Prerequisites satisfied | G1 | 27/59 → 45/59 | 68/91 → 81/91 | 145/187 → 162/187 |
| Prerequisites satisfied | DC | 59/59 → 59/59 | 86/91 → 86/91 | 150/187 → 151/187 |
| Consent obtained | G1, DC | No change: every arm already caught these failures | | |

Terms disclosed, ownership / authority and action requested had too few corrections to measure.
See correction 3 before reading these counts.

### Secondary diagnostics (promotion set; never primary)

| Variant | False allows | Asks | Approvals saved | AUC |
|---|---|---|---|---|
| Jev D | 3/18 | 15/21 | 3/3 | 1.00 |
| Jev DC | 0/18 | 20/21 | 1/3 | 0.59 |
| Jev G1 | 0/18 | 21/21 | 0/3 | 0.89 |
| G1 + per-action offsets | 0/18 | 21/21 | 0/3 | 0.81 |
| G1 on both judges | 0/18 | 21/21 | 0/3 | 0.85 |

Three Jev answers failed parsing: the choice probabilities summed to 0.99, outside the 0.001
tolerance. Those writes have no Jev features.

### Cost and latency

- **Spend:** $0.1183 in total against a $1.00 hard cap, over 216 calls. Every call reserved its
  maximum cost first. A rerun of the primary judge made 0 calls.
  ([`results/ledger.json`](results/ledger.json), [`results/score.json`](results/score.json),
  [`results/score-rerun.json`](results/score-rerun.json))
- **Per call:**

  | Judge | Cost | p50 latency | p95 latency |
  |---|---|---|---|
  | OpenAI Decisions | about $0.0007 | 243 ms | 937 ms |
  | Jev | about $0.0003 | 140 ms | 438 ms |

- **One call serves all three arms.** It answers all ten concepts and both baseline questions, so
  D, DC and G1 cost the same.

## Interpretation corrections

These correct how the results were first presented in the HTML viewer of 2026-10-23.

1. **Safety non-inferiority passed; autonomy improvement failed.** The viewer said the safety
   gates "passed". They did: G1's false allows (0/21) were no worse than DC's or D's overall, for
   exchange, and for retail. But that is non-inferiority on safety only, reached because every arm
   escalated nearly everything. The autonomy claim the gates exist to license failed: G1 saved
   0/9 approvals against DC's 3/9 and D's 2/9. A passed gate here is not evidence for G1.
2. **Exchange is one-class, so transfer is inconclusive.** Exchange is the only action that met
   the coverage rule. All 10 of its holdout writes should escalate (9 come from one session), so
   it can test safety only. It has no should-run write to measure autonomy and no AUC. Held-out
   action transfer is therefore unmeasured, not negative.
3. **Repeated adaptation orderings are not independent examples.** The adaptation counts are
   summed over the usable orderings: 16 for prerequisites, 14 for consent. The same writes recur
   in many orderings. Behind the prerequisites sums there are only 18 distinct corrections,
   18 distinct later failures in 4 families, and 25 distinct should-run writes. For consent there
   are 11 distinct corrections and 11 later failures in 3 families. Read "27/59 → 45/59" as a
   direction on a handful of scenarios, not as 59 independent trials. These distinct counts were
   computed after the final evaluation, from revealed data only.

The viewer's banner said "about 105 decisions": that is the writes with a verdict across all
three datasets (54 + 21 + 30), not independent scenarios. There are 16 scenario families.

## Decision: `PHASE_2_NO_GO_AS_SPECIFIED`

- **Learning showed no value.** G1 escalated all 30 holdout writes. Its out-of-fold threshold at
  the 95% catch target sat at 0.9995, and no challenger ever beat "escalate everything" on the
  promotion set.
- **Shared concepts showed no measurable value over the baseline**, and DC was less safe on the
  promotion set (3/18 false allows against D's 0/18).
- **Transfer is unmeasured** (correction 2).
- **The one positive signal is adaptation.** Prerequisite corrections raised G1's catches of
  later prerequisite failures on other actions, at a cost in escalations of writes that should
  run. It rests on 18 distinct failures in 4 families (correction 3).
- **The $8–12 Phase 2 capture would not fix the binding constraint.** It would mostly add trials
  of the same few scenario families (16 in all, 5 in the holdout). It was not started. A
  different Phase 2 needs its own go/no-go: more families per action, and a threshold procedure
  that can pass at this data size.

## What remains unproven

- That shared concepts beat the two generic policy questions. The holdout difference is null,
  and the intervals are wide on 5 families.
- That learning over concepts adds autonomy at equal safety. G1 failed closed here; with more
  families it might not.
- Held-out-action transfer, in either direction.
- That adaptation from real corrections generalizes beyond the 4 families behind it.
- Anything at all against human judgement. The oracle is deterministic and unaudited, and human
  validation is a publication gate.

## Departures from the approved plan

- **DC excludes `reversible`.** This was frozen before scoring.
- **G1's threshold uses family-grouped out-of-fold predictions.**
- **Scenario families are shared across stores, not qualified per store.** This is stricter: one
  scenario never sits on both sides of the split.
- **Concept `evidence` is always null.** Neither judge API returns a text span; the raw responses
  are kept with the scores.
- **The code lives in `hatchway/bench/pilot/`** because `hatchway/decision.py` already exists.

## Reproduction

The stores are local and not in Git (`runs/*.db` is ignored). Recapturing them needs paid τ²
simulations through `configs/targeted-1.yaml` and the smoke config; that is not required to
re-run the analysis from these stores.

```bash
pip install -e '.[dev]' -e ./.tau2-bench   # τ² at c5b2d228…
git checkout 4f1cb9c                       # the frozen pilot code (later commits keep it byte-identical)
python -m hatchway.bench.pilot freeze --dir runs/pilot \
    --store targeted=runs/targeted.db --store smoke2=runs/smoke2.db
python -m hatchway.bench.pilot verdicts   --dir runs/pilot
python -m hatchway.bench.pilot split      --dir runs/pilot
python -m hatchway.bench.pilot score      --dir runs/pilot --judge openai_decisions --judge jev  # ≤ $1, needs API keys
python -m hatchway.bench.pilot analyze    --dir runs/pilot
python -m hatchway.bench.pilot final-eval --dir runs/pilot   # once
python -m hatchway.bench.pilot report     --dir runs/pilot
```

Every command after `freeze` refuses to run if any pinned field differs from the manifest. The
pinned fields are the arm specs, the analysis constants, the five pilot code files, the oracle,
the policy, the rubric hashes, the judges, the candidate writes and τ². With the same stores,
the split, the analyses and the final evaluation are deterministic. Judge answers are not:
re-scoring calls live models.

## Files outside Git

| File | sha256 | Where |
|---|---|---|
| `runs/targeted.db` (stage-1 capture plus pilot scores) | `25af40877af75b1ca037c513d922dc21229ea0ed07f77627e990e1a8af398b33` | Local store; attach to a release |
| `runs/smoke2.db` | `e90b4c792f211d979e76466782b0f5268bf2e4d1b8f74f74f39b9336bcf9e808` | Local store; attach to a release |
| `runs/pilot/report/index.html` (HTML viewer v0) | `a356a774458aeecafe8d831409c7397ab2768f26b991f254b5139d4e466286f6` | Not published |
