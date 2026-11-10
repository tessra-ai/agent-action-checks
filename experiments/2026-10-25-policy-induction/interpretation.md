## Outcome: `BENCHMARK_TOO_HARD`

The preregistered learnability check (A2) failed. Arm S recovered 3 of the 6 fact-expressible
hidden rules within 10 examples, and the bar was 4 (H1, H3 and H4 passed).

The other three needed more data:

- **H6, a relaxation:** recovery rate 0.75 at k = 20.
- **H7, a three-condition rule:** 0.45 at k = 20.
- **H2, a product rule:** 0.50 at k = 10. Its training split has only 16 triggering families,
  so k = 20 was impossible.

Under the RFC's rule, Phase B is not proposed on this benchmark as frozen. The controls behaved:

- **Shuffled labels** produced an accepted rule in 0.26% of runs.
- **The raw-signal world (H5)** was out of reach for S, as designed.

**What the run shows** (synthetic retail data, perfect perception, an unaudited oracle):

1. **The learner almost never invents rules from noise.** The significance gate made
   "learning" from random labels essentially impossible.
2. **A written clause the starting policy lacks comes back from about 5 examples** when
   perception supplies the fact.
   - All six removed clauses were recovered at k = 5 with no false invention.
   - Safety went from 386 of 391 failing families to 0.
   - The difficulty here sits in perception, which Phase A assumed perfect.
3. **Unwritten rules take about 10 examples, and the thresholds are approximate.**
   - Single-condition rules (H1, H3, H4) were recovered at k = 5 to 10.
   - Learned thresholds land between the nearest examples: "refunds over $1,741" for a $2,000
     rule, "upcharge over $6.30" for $25. That is right on the data and wrong as policy text,
     so a human reviewer should confirm a rule's wording before it goes live.
4. **Simplicity is safe for escalations and dangerous for relaxations.**
   - For H7 the learner kept the simpler "escalate every PayPal return". It over-escalates
     (about 35 cases at k = 20) but never wrongly allows.
   - For the H6 waiver, the learned exceptions wrongly allowed cases the organization
     escalates: about 21 failing families, against 0 for the starting policy.
   - The v2 side check shows the same thing. Learned exceptions removed all 149 of DC-score's
     over-escalations but failed 49 of 96 families. P1's learned exception was its planted
     preference (allow irreversible actions when harm is low), but without "and everything
     else is fine".
   - **Design rule:** escalation rules may generalize. Exceptions must be specific, certified
     on untouched families (v2's procedure) and approved by a person before they go live.
5. **A live gate cannot find what it is missing from its own traffic.**
   - Under `selection` (labels only for what the gate escalates, plus a 10% audit of what it
     allows), no missing escalation rule was learned in any world at any k ≤ 20. A 10% audit
     sees about 2 of 20 occurrences.
   - Relaxations were learned as well as with full labels (H6), because people answer the
     asks.
   - **Product implication:** a gate learns to say yes more from its asks, but catching
     unwritten edge cases needs audits of allowed actions or outcome feedback. At a 10% audit
     rate, that means roughly 50 to 100 occurrences of the case.
6. **Inconsistent approvers are expensive.**
   - With 20% of labels flipped, clauses needed about 4 times as many examples (5 to 20).
   - Most hidden rules were not recovered within 20.
   - Measuring approver consistency is the first step on any real data.
7. **A raw signal needs text.** S never recovered the chargeback rule. A bag-of-words learner
   (S-text) recovered it across six phrasings at k = 20, with recovery rate 0.85. That is the
   bar an LLM arm would have to beat.

**Not shown:**

- Anything about LLM arms. Phase B is a dry run only, measured at about 63M input tokens as
  designed, almost all of it L-prec.
- Anything about real organizations.
- Anything about imperfect perception.

**Not done, by design:** no model calls, no telecom, no merge.
