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
