# Claims check: verify what the agent told the customer (τ²-bench airline)

| | |
|---|---|
| **Status** | `done`: see `Report.md` (preregistered before any extraction call) |
| **Branch** | `experiment/docent-vs-oracle`; not merged |
| **Question** | The airline gate's remaining failures are mostly a customer's yes resting on something the agent got wrong. If a model lists the agent's factual statements about the proposed action, and code recomputes each from the records, how many of those failures does it catch, and how many good writes does it hold back? |
| **Data** | The 133 airline writes of `experiments/2026-10-28-airline-veto` and their pre-action database snapshots |
| **Spend** | gpt-4.1-mini (`gpt-4.1-mini-2025-04-14`), hard cap $1 through a metered client (stop at $0.95, worst case reserved before each call, probe first) |

## Method

1. **Extract (model).** For each write, gpt-4.1-mini at temperature 0 reads the conversation
   up to the proposed call (tool results shortened) and returns, in a strict JSON schema
   (`claims.SCHEMA`), the agent's factual statements about this action. Each statement has a
   kind (charge, refund, price quote, balance after, payment method, flights, cabin, bags, cabin
   change cost, cancellable, option rank, other) and an exact quote. The instructions are
   `claims.INSTRUCTIONS`, frozen with this README.
2. **Verify (code, `claims.verify`).** Each claim is recomputed from the pre-action database and
   the proposed call, the way τ²'s tools compute them:
   - what the call charges or refunds;
   - flight prices;
   - balances left on gift cards and certificates (a certificate remainder is forfeited, so
     presenting it as left is false);
   - the payment method named against the call's;
   - flights, cabin and bags against the call;
   - what a cabin change costs from the current cabin;
   - whether the reservation is cancellable afterwards;
   - whether a one-way booking's flights are the cheapest, second cheapest or only option among
     τ²'s direct and one-stop options.

   Amounts match within $1, as a total or per passenger. A claim is `true`, `false` or
   `unverifiable`.
3. **Decide.** A write is **flagged** (ask the customer again) when any claim is false.
   Unverifiable claims never flag.

**Disclosed:** the claim kinds were chosen knowing the airline failures. The cabin change cost
was added after reading task 22. As in the rules experiment, every flag on a write the truth
says should run is listed in the report.

## Gates compared (Docent run 1 and run 2)

| Gate | Runs when |
|---|---|
| `old` | Jev P(policy ok) ≥ 0.5 and Docent ALLOW |
| `old_claims` | `old` and not flagged |
| `rules_docent` | no rule blocks (rules experiment) and Docent ALLOW |
| `rules_claims_docent` | `rules_docent` and not flagged |
| `rules_facts_claims_docent` | also Jev's narrow facts all yes (rules experiment) |
| `claims` | not flagged (alone) |

## Truths and metrics

The corrected benchmark (all 133), the adjudicated truth (91, after the person's corrections
including the case 02 revert) and the graders (91), from the veto experiment. For each gate and
truth: writes run, wrong runs (exact 95% upper bound), and good writes sent back.

Specifically, for each of the veto gate's wrong runs (corrected benchmark), whether it is
flagged and by which claim. Every false flag (a flagged write the truth says should run) is
listed with its claim, so extraction errors and real misstatements can be told apart.

## Run order

1. Commit this README, `claims.py`, `extract.py`, `evaluate.py` and the tests.
2. `extract.py` → `results/extracted.jsonl` (once).
3. `evaluate.py` → `results/verified.jsonl`, `results/gates.json` (once); `Report.md`.
