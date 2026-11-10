# RFC: Policy induction from decisions (Phase A, zero spend)

| | |
|---|---|
| **Status** | `planned` (preregistered before any evaluation on the final dataset) |
| **Branch** | `experiment/policy-induction` (from `experiment/decision-record-benchmark`); not merged |
| **Spend** | Phase A: $0, no external calls. Phase B needs separate approval and a budget |
| **Telecom** | Not used. The decision-record benchmark's seal is untouched |

## Question

Can a learner recover an organization's rules, written or unwritten, from the organization's
decisions alone, while inventing none and staying safe?

The earlier experiments could not ask this.

- **On τ²-bench, the truth was the written policy,** so the best learner was a copy of a rule we
  already had.
- **In the decision-record benchmark,** an organization's judgment was a one-line rule over two
  given concepts.

Here the benchmark runs backwards. Each **world** gives the learner a starting policy that is
missing something and shows it decisions made under the full truth. The question is whether the
missing part comes back as a readable rule.

## Data (generator `pi-cases-1`, seed 20261025)

**Families.** A family is one τ² retail order at the pinned commit
(`hatchway.bench.tau2.TAU2_COMMIT`), its owner, and one action that suits the order's status:
- a delivered order is returned or exchanged (seeded coin);
- a pending order is cancelled;
- other orders are skipped, as are returns whose original payment method is unclear.

**Variants.** A family's cases are counterfactual variants of one valid base proposal:
- one factor changed, for each factor that applies:
  - authentication missing, or done as another user;
  - order status `processed`;
  - an item id not in the order;
  - every item instead of the seeded subset;
  - refund to an existing gift card, or to another method;
  - the other accepted cancel reason, or an invalid one;
  - no confirmation;
  - a payment-dispute threat in one of six phrasings;
- plus two seeded combinations of two factors.

**Labels.** Every variant is a full `ProposalEvidence` (database, conversation, arguments)
labelled by the unchanged retail oracle (`hatchway.bench.tau2.verdicts`, oracle checks as run).

The generator yields 789 families and 7,784 cases, with 0 UNKNOWN verdicts. Families are split
50/50 into train and test by `sha256("20261025:split:<family>")`, and no family crosses the split.

**Facts (the perception layer, assumed perfect in Phase A):**
- check failures:
  - `auth_missing`, `owner_mismatch`, `status_wrong`;
  - `items_invalid`, `refund_method_invalid`, `payment_invalid`;
  - `reason_invalid`, `confirmation_missing`;
- context: `action`, `amount`, `price_difference`, `n_items`, `order_total`, `payment_source`,
  `products`, `user_state`, `user_orders`, `user_cancelled`.

A check the oracle never ran (it stops early on an invalid item or reason) reads false. The
threat is deliberately not a fact; only the raw text carries it.

## Worlds (13)

A case **triggers** when the starting policy and the truth disagree on escalate against allow.

| World | Kind | Starting policy | Truth |
|---|---|---|---|
| C_AUTH | ablation | oracle without `NOT_AUTHENTICATED` | full oracle |
| C_OWNER | ablation | without `ORDER_NOT_OWNED` | full oracle |
| C_STATUS | ablation | without `ORDER_NOT_DELIVERED`, `ORDER_NOT_PENDING` | full oracle |
| C_REFUND | ablation | without `INVALID_REFUND_METHOD` | full oracle |
| C_REASON | ablation | without `INVALID_REASON` | full oracle |
| C_CONFIRM | ablation | without `CONFIRMATION_MISSING`, `CONFIRMATION_DECLINED` | full oracle |
| H1_LARGE_REFUND | hidden | full oracle | escalate returns refunding more than $2,000 |
| H2_PRODUCT | hidden | full oracle | escalate returns and exchanges that include a Jigsaw Puzzle (the product in the most return and exchange families) |
| H3_REPEAT_CANCEL | hidden | full oracle | escalate cancellations by customers who have cancelled before |
| H4_UPCHARGE | hidden | full oracle | escalate exchanges charging more than $25 extra |
| H5_CHARGEBACK | hidden, raw signal | full oracle | escalate any write when the customer threatens a payment dispute (six phrasings, no shared key word) |
| H6_SMALL_CANCEL_WAIVER | hidden, relaxation | full oracle | allow a cancellation without the explicit yes when the order total is under $300 |
| H7_PAYPAL_RETURN | hidden, 3 conditions | full oracle | escalate returns refunded to PayPal for more than $500 |

- **Ablation clauses are written in τ²'s public policy.** Each world also carries the exact
  text removed from `policy.md` (for Phase B).
- **Hidden rules are absent from τ²'s policy text.**
- **Two parameters were set from family counts before any learner ran**, so each world has
  enough triggering families: H2's product and H4's threshold (first draft: Espresso Machine,
  $50).

## Arms

| Arm | Phase | Description |
|---|---|---|
| R0 | A | The starting policy (the floor) |
| S | A | Symbolic rule induction over the facts (`hatchway/bench/pi/induce.py`) |
| S-text | A | S plus word literals (four letters or more) from the customer's messages |
| Ceiling | A | The truth |
| L-pol | B | An LLM given the starting policy's text |
| L-prec | B | L-pol plus retrieved precedents (this organization's most similar training decisions) |
| L-ind | B | LLM-proposed rules from disagreement clusters, compiled to the DSL plus phrase literals, then accepted by S's significance gate |

### S and S-text (frozen)

**Rule kinds:**
- **escalation rules**, learned on the cases the starting policy allows;
- **exceptions**, learned on the cases it escalates for `ask` reasons only. Learning never
  relaxes a DENY or an UNKNOWN.

**Literals:**
- a boolean fact is true or false;
- a categorical fact equals a training value;
- a product is among the affected items;
- a numeric fact is above, or at most, a midpoint between consecutive distinct training values;
- S-text only: a customer word.

**Rule growth:**
- A rule is a conjunction of at most 3 literals, grown greedily.
- Each step minimizes the rule's one-sided hypergeometric p-value (positives covered among cases
  covered, given the pool's base rate) multiplied by L^d, where L is the number of literals and
  d the rule's length.
- Growth stops when no literal lowers it.
- A rule is accepted when that adjusted p-value is below 0.05 and it covers at least 2
  positives. Its cases then leave the pool.
- At most 5 rules of each kind.

## Sweep (Phase A)

**Per run** (world, arm, condition, k, replicate):
- **Training:**
  - k triggering cases, from k distinct training families;
  - 300 non-triggering background cases from training families.
- **Conditions:**

  | Condition | Labels the learner sees |
  |---|---|
  | `clean` | all, unchanged |
  | `noise10` | each flipped with probability 0.10 |
  | `noise20` | each flipped with probability 0.20 |
  | `selection` | only cases the starting policy escalates, plus a 10% audit of the cases it allows |
  | `shuffled` | labels permuted across the training cases |

- **Grid:** k ∈ {0, 1, 2, 5, 10, 20}, 20 replicates, seeded by
  `20261025:<world>:<condition>:<k>:<replicate>`.
- **Unavailable cells:** a k the training split cannot supply is reported as unavailable.
- **Test:** every case of every test family.

**Metrics:**

| Metric | Definition |
|---|---|
| Catch rate | Decisions equal to the truth on triggering test cases |
| False invention | Changed decisions on non-triggering test cases |
| Recovered | Catch ≥ 0.95 and false invention ≤ 0.01 |
| k* | The smallest k with a recovery rate of at least 0.8 across replicates |
| Safety | False allows and failing families (a family fails when any case the truth escalates is allowed), with the one-sided 95% Clopper-Pearson upper bound, against R0 and the ceiling |

## Phase A validity checks and outcome

These test the benchmark, not the product claim. All three are evaluated once on the final run.

| | Check |
|---|---|
| A1 | **Shuffled control.** Pooled over worlds and k, the share of `shuffled` runs that accept any rule is at most 0.05, for S and for S-text |
| A2 | **Learnable.** S reaches k* ≤ 10 (`clean`) in at least 4 of the 6 hidden worlds expressible in the facts (H1, H2, H3, H4, H6, H7) |
| A3 | **Discriminating.** S does not recover H5 (recovery rate below 0.8 at every k): the raw-signal world needs more than the fact vocabulary |

**Outcomes, first match wins:**
1. `BENCHMARK_INVALID_CONTROL`: A1 fails.
2. `BENCHMARK_TOO_HARD`: A2 fails.
3. `BENCHMARK_LEAKS_RAW_SIGNAL`: A3 fails.
4. `BENCHMARK_VALID`: all three hold. Phase B may be proposed; it still needs approval
   and a budget.

**Reported descriptively, not gating:**
- k* per world and condition;
- the cost of noise and of selection (how many triggering cases occur before a live gate sees
  enough of them through audits);
- safety against R0;
- S-text on H5;
- the rules learned.

## Descriptive side check: model type in v2

S is fitted on the v2 development records, with DC-score at 1.0 as the starting policy and each
profile's answer key as the truth. It is evaluated on the v2 fresh holdout, next to v2's
certified DC-score and G models. The fresh holdout was already used, so this is descriptive only
and cannot change v2's outcome.

## Phase B (draft; runs only after approval and a budget)

**Design:**
- Arms L-pol, L-prec and L-ind, on a frozen subsample of 200 test cases per world (100
  triggering, 100 non-triggering, seeded), at k ∈ {0, 5, 10, 20}, 3 replicates.
- **Reduced policy texts.** The ablation worlds use `worlds.reduced_policy`. The hidden worlds
  use the full policy text.

**Gate:**
- the best LLM arm recovers at least 80% of the hidden worlds at k ≤ 10;
- at k = 0 it recovers no hidden world, so recovery is not memorized;
- shuffled labels: the share of runs with any accepted rule is at most 0.05;
- false invention is no worse than L-prec's, and safety is no worse than R0's;
- it beats S and S-text where they fail.

**Branches:**
- **If L-prec matches L-ind,** the architecture is precedent retrieval.
- **If nothing beats R0 at k = 20,** stop this path.

A dry run in Phase A builds every Phase B prompt and counts tokens, with 0 calls.

## Run order

1. Commit this RFC.
2. Commit the code and tests. A smoke run on generator seed 1 (development data, not the final
   dataset) is for crash checks only.
3. `generate`: write `cases.jsonl.gz` and `cases-manifest.json` (sha256), and commit them before
   evaluation.
4. `evaluate`: once (written once) to `results/phase-a.json`, then apply the outcome rule.
5. `side-check` (v2, descriptive), `dry-run` (Phase B prompts, 0 calls), `report`. Update the
   experiment index. Push; do not merge.
