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
