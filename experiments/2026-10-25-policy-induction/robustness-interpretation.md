## Reading

All three preregistered checks passed: replication (R1), targeted audits (R3) and certified
exceptions (R4). The two descriptive parts, random rules (R2) and noisy perception (R5), turn
Phase A's anecdotes into curves.

1. **Phase A replicates.**
   - On a fresh generator seed, all 13 worlds landed within one k step of Phase A.
   - The controls behaved the same way.
   - The outcome is again `BENCHMARK_TOO_HARD` (2 of 6 learnable this time). The "too hard"
     verdict is not one dataset's luck.
2. **What is learnable, and when (R2, 114 random rules).**
   - Recovered within 5 examples: 50. Within 10: 69. Within 20: 96.
   - **Rules that need one fact, across all actions, are easy.** Numeric thresholds: 36 of 39
     within 10. Products: 13 of 13 within 5.
   - **Narrow rules are hard.** Scoping a rule to one action or adding a second condition is
     the main cost. One numeric condition on one action: 1 of 10 within 10. Two conditions:
     about a third within 10.
   - **Relaxations are slowest:** 5 of 20 within 10, 15 of 20 within 20.
   - **Why.** The significance gate charges for every extra condition, so narrow rules need
     more evidence.
   - **Rarity was not tested.** The filter kept only rules that change at least 5% of the cases
     in scope (at least 25 training families). How rare an edge case can be and still get
     caught remains open.
3. **Audits must be large, and targeting halves them (R3).**
   - To recover a missing escalation rule from k = 20 to 40 occurrences, random audits needed
     25–100% of allowed cases.
   - Targeted audits (spend half at random, then audit cases matching the most suspicious
     conditions) needed half of random's rate or less in 60 of 119 cells.
   - Targeting did not create false rules: the shuffled control accepted a rule in 0.2% of runs.
   - **Product implication.** Learning a missed risk takes roughly 5–10 audited occurrences.
     Either audit heavily where risk is suspected, or use outcome feedback. A flat 10% audit
     will not find rules.
4. **Certification makes relaxations safe, at the cost of almost all of their gain (R4).**
   - Where a learned exception allowed a case on held-out test families, uncertified S failed
     47% of those families (14,042 of 29,939 across runs).
   - Narrowed, certified exceptions failed 0 of 934.
   - But they rarely passed certification on a 148-family certification split, so they
     retained little: catch at most 0.36, and 0 in most worlds.
   - In the v2 side check, the narrowed rules were close to the planted preferences but still
     failed certification (1 of 18 and 3 of 15 calibration families failing). S-cert fell back
     to DC-score: 0 of 96 failing families, 149 of 255 over-escalations.
   - **Product implication.** Learned relaxations are proposals for a person to approve, not
     automatic changes. Certification with untouched data is what keeps them honest, and it
     needs more held-out families than a small organization has early on.
5. **Perception errors pass through about one to one (R5).**
   - At a 2% fact-error rate, catch stayed around 0.95–0.99, with false invention under 1%.
   - At 10%, catch fell to about 0.85–0.90, with false invention of 1–4%. False invention was
     highest for the removed-clause worlds, where a flipped fact directly flips a decision.
   - The learner does not amplify perception noise, but nothing above it can recover what the
     extractor gets wrong. Extractor accuracy is the ceiling.

**Combined with Phase A.** Policy induction works for escalations once a rule has been seen
about 5–20 times, depending on how narrow it is, and noise and narrowness cost data.

- **It needs targeted audits or outcomes** to see what the gate already allows.
- **It must treat relaxations as human-approved proposals,** certified before they act.
- **Its accuracy is capped by fact extraction.**

None of this has been tested on real organizations, real language or a real extractor; that
is the next step (see [`data-sources.md`](data-sources.md)).
