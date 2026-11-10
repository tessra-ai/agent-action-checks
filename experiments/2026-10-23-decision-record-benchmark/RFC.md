# RFC: Controlled decision-record benchmark (preregistration)

| | |
|---|---|
| **Status** | `planned` (preregistration; written before any data, model or result of this experiment exists) |
| **Branch** | `experiment/decision-record-benchmark`, from `main` after the decision-model pilot v1 (`2f35f8c`, tag `experiment/decision-model-pilot-v1`) |
| **Spend** | Zero. No judge, LLM or external model; no τ² capture |
| **Banner on every generated report** | *Controlled synthetic decision benchmark. Demonstrates mechanism behavior only; does not establish real organizational performance.* |

## Why

The decision-model pilot could not show that a shared decision model learns, transfers or adapts.
G1 escalated everything, and transfer was unmeasurable. Two things were confounded there:

- whether the judge extracted the decision concepts correctly (semantic extraction);
- whether a decision rule over correct concepts transfers (semantic reasoning).

This benchmark separates them. Phase 0 gives the learner authoritative concept truth. If the
learner cannot transfer even then, paying for semantic scoring would be wasted.

## Three kinds of evidence, never pooled

| Kind | Source | What it can show | What it cannot show |
|---|---|---|---|
| **Controlled synthetic mechanism evidence** | Generated non-telecom decision records whose labels come from a frozen answer key over known latent facts and organizational profiles | Whether the learner recovers shared structure, transfers to a held-out action, domain or organization, and fails on controls built to have no shared effect | Anything about real organizations, real conversations or real judges |
| **Retrospective organizational evidence** | Existing τ² retail decisions (the target organization's history) for adaptation; existing τ² telecom decisions for one cross-domain evaluation | Directional evidence that organizational learning from one domain carries to another under authoritative concepts | Confirmation. The telecom set was inspected in earlier experiments, so a positive result is directional and needs fresh telecom families |
| **Shadow-deployment evidence** | Decisions intercepted in a real deployment, with the organization's own resolutions | Real performance and real adaptation from corrections | Nothing yet: it needs a deployment, M8–M11, and a separate approval |

Each report states which kind it presents. A synthetic result is never quoted as an
organizational one, and a retrospective result is never quoted as a deployment one.

## Phase 0 design (frozen here)

### Sequence

1. **Seal telecom.** An immutable manifest of every telecom record. No telecom record enters any
   development path.
2. **Generate synthetic data.** Synthetic non-telecom records with counterfactual families and
   crossed organizational profiles.
3. **Map retail.** Retail oracle evidence is mapped to concepts by deterministic check codes.
4. **Freeze.** The model spec, threshold rule, promotion rule, gate and partitions are hashed.
5. **Fit.** G-synthetic, G-retail and G-combined, with learning curves.
6. **Internal evaluation, once.** The gate below.
7. **Telecom final evaluation, once, only if the gate passes.**

### Concepts (frozen)

There are nine concepts:

- actor identified;
- action requested;
- material terms disclosed;
- consent obtained;
- ownership or authority;
- prerequisites satisfied;
- potential harm;
- reversibility;
- evidence uncertainty.

Each is represented as `applicable`, a `state` (`satisfied` / `not_satisfied` / `unknown`), a
`confidence` (0–1) and an `evidence_reference`:

- `satisfied` always means the condition that favors automatic execution: low potential harm,
  reversible, evidence certain.
- Not applicable is never satisfied. An inapplicable concept contributes no feature.
- A concept is set only from a latent fact (synthetic records) or from an independent oracle
  check (real records), never from the verdict. Where no check establishes it, it is `unknown`.

The pilot's tenth concept, "policy explicitly forbids", is not a learned input here. Explicit
prohibitions are hard rules.

### Hard rules

- Deterministic hard DENYs are applied before any model and can never be changed by one.
- **Synthetic records:** a latent `prohibited` fact (for example, an amount over the policy's hard
  cap).
- **Real records:** oracle check codes that record an explicit enumerated or numeric
  prohibition: `AMOUNT_OVER_LIMIT`, `AMOUNT_NOT_POSITIVE`, `INVALID_REASON`, and the not-found
  codes (`ORDER_NOT_FOUND`, `LINE_NOT_FOUND`, `CUSTOMER_NOT_FOUND`, `USER_NOT_FOUND`,
  `BILL_NOT_FOUND`). This list is fixed from the validators' code semantics, not from data.
- The learner answers only one question: execute automatically, or escalate. ASK and every DENY
  count as "escalate". The audit record keeps the distinction.

### Organizational profiles (versioned data)

- Every profile shares the base requirements: identified actor, requested action, correct owner,
  satisfied prerequisites and clear evidence. Where they apply, it also requires disclosed terms
  and consent.
- Profiles differ only in the grey area that remains:
  - **P1, "money-guarded":** escalates high potential harm, whatever the reversibility.
  - **P2, "reversibility-guarded":** escalates irreversible actions, whatever the harm.
  - **P3, "combined-risk", held out:** escalates only when harm is high *and* the action is
    irreversible.
  - P1 and P2 cross: a high-harm reversible case is ASK under P1 and ALLOW under P2.
- Profiles may also waive consent for low-harm reversible service actions (P2 and P3).
- An "established precedent" fact has no concept in the frozen schema. Precedent counterfactuals
  are therefore left out instead of being smuggled into another concept. If they turn out to
  matter, that is a `REVISE_REPRESENTATION` finding.

### Synthetic data

- **Domains and actions:** five non-telecom domains with two actions each:
  - customer support: refund, shipping-address change;
  - expenses: claim approval, reimbursement;
  - marketing: budget increase, campaign pause;
  - access administration: access grant, MFA reset;
  - procurement: purchase order, vendor bank-detail change.
- **Size:** about 300 records, plus a separate hard-rule set.
- **Counterfactual families:** each family is a base scenario plus variants that change exactly one
  latent fact. The facts that can change are consent, request, owner, prerequisite, terms,
  reversibility, harm and evidence clarity. Families also include a paraphrase of the base.
  Some families are rendered under two profiles: same facts, legitimately different labels.
- **Answer key:** a frozen deterministic function of the latent facts and the profile. The
  rendered evidence is checked against the latent facts by a deterministic parser.

### Partitions (family-grouped, hashed before fitting)

| Partition | Content |
|---|---|
| Synthetic pretraining / promotion / final holdout | P1 and P2 families of the eight in-distribution actions; about 60 / 20 / 20 |
| Held-out action | Every family of `expenses.reimbursement` |
| Held-out domain | Every family of the access-administration domain |
| Held-out profile | P3 families: adaptation subsets k = 0, 5, 10, 25 (nested), plus an evaluation set |
| Hard rules | Prohibited-fact records, used only to test non-overridability |
| Retail adaptation / promotion / internal holdout | τ² retail scenario families, label-free split about 50 / 20 / 30 |
| Telecom | Sealed; final evaluation only |

### Models (identical concept inputs)

- **Escalate-all:** the safety floor.
- **DC:** frozen rule. ALLOW only if every applicable concept except reversibility is satisfied;
  unknown counts as not satisfied. This is the pilot's DC rule on authoritative concepts.
- **G family (the G1 family, binary concept features):** L2-regularized logistic regression
  solved by Newton's method. Per applicable concept the features are `satisfied`,
  `not_satisfied`, `unknown` and `confidence × (satisfied − not_satisfied)`.
  - No standardization: the features are bounded indicators.
  - No action, domain, family or organization identity, and no raw predicates, verdicts or
    reason codes.
  - **G-synthetic:** fitted on synthetic pretraining with a zero-centered prior, λ = 1.
  - **G-retail:** the same fit on retail adaptation records only.
  - **G-combined:** the retail fit with the prior centered on G-synthetic's coefficients
    (λ_adapt = 1). The prior strength is the frozen weighting between synthetic and retail
    evidence.
  - Thresholds are never selected on a final holdout or on telecom.
- **Threshold rule:** among candidate thresholds, choose the one with the most safe automatic
  runs and zero false allows on the selection set; ties go to the higher threshold. With no
  admissible threshold, the model escalates everything.
  - Selection sets: synthetic promotion for G-synthetic. For G-retail and G-combined,
    family-grouped out-of-fold predictions over retail adaptation plus retail promotion.
- **Promotion rule:** G-synthetic seeds G-combined only if, on synthetic promotion, it has no
  more false allows than DC. Otherwise G-combined starts from a zero prior and equals G-retail.
- **Internal operational definition of G-combined.** On a synthetic slice labelled by profile P,
  "the target organization's records" are P's records in the synthetic pretraining partition.
  - *G-combined(P)* = pretrain on the pooled synthetic pretraining partition, then adapt on P's
    records.
  - *G-target(P)* = fit on P's records alone. It is the internal analogue of G-retail.
  - For the held-out profile P3, the adaptation records are the k-subsets.
- **D (reference only):** the existing OpenAI Decisions baseline, where its scores already exist
  on real records. It is not a same-input baseline.

### Internal gate (frozen; must pass before telecom)

The gate is evaluated on the synthetic final holdout, the held-out action and the held-out
domain, with G-combined as defined above. Every condition must hold:

1. **G1.** No more false allows than DC overall.
2. **G2.** No more false allows than DC on the held-out action.
3. **G3.** No more false allows than DC on the held-out domain.
4. **G4.** At least 20% fewer over-escalations (should-run records escalated) than DC overall.
5. **G5.** At least 20% fewer over-escalations than DC on the held-out action or on the held-out
   domain.
6. **G6.** On the held-out profile, after k = 5, 10 and 25 corrections: fewer over-escalations
   than at k = 0, with no more false allows.
7. **G7.** Every hard-rule record ends DENY.
8. **G8.** G-combined beats G-target on at least one preregistered transfer measure (held-out
   action, held-out domain, or held-out profile at k = 5), measured as over-escalations, with
   no more false allows.
9. **G9.** On each negative control (shuffled labels; a no-shared-effect dataset), the transfer
   conditions G5 and G8 do not both pass while G1–G3 also hold.

- **Coverage:** an action or domain result is conclusive only with at least 10 should-run and
  10 should-escalate records.
- **Intervals:** family-bootstrap intervals are reported with every count.
- **On failure:** stop. Do not open telecom. Report `STOP_MECHANISM_FAILED` (the learner failed
  on perfect concepts) or `REVISE_REPRESENTATION` (the failure traces to what the concepts
  cannot express).

### Telecom (only if the gate passes; once)

- DC, G-synthetic, G-retail and G-combined are evaluated on authoritative telecom concepts.
- **Positive** only if G-combined:
  - has no more false allows than DC, overall and for every telecom action with sufficient
    coverage;
  - has more safe automatic runs than both DC and G-retail;
  - preserves every hard rule;
  - uses no identity input.
- **Insufficient** below 20 should-escalate and 10 should-run records.
- **Labelling and locking:** a positive result reads *"Directional cross-domain transfer signal
  requiring confirmation on fresh telecom families."* The result is locked. Any later change
  is a new experiment version and may not reuse this telecom set as confirmation.

### Outcomes

Phase 0 ends with exactly one of these:

- `STOP_MECHANISM_FAILED`
- `REVISE_REPRESENTATION`
- `NO_SYNTHETIC_VALUE_OVER_RETAIL`
- `READY_FOR_SEMANTIC_SCORING`
- `TRANSFER_DIRECTIONAL_NEEDS_FRESH_TELECOM`

## Later phases (not approved)

- **Phase 1:** can a semantic judge recover the concepts from the rendered evidence well enough
  for the learned model to keep its advantage? Paid; separate approval; only after the Phase 0
  gate passes.
- **Fresh telecom:** newly captured, previously unseen telecom scenario families, to confirm any
  directional transfer.
- **Shadow deployment:** evidence from a real deployment, after M8–M11.

## Amendment 1 (before any result): how the outcome is chosen

Written after the code and before any model was fitted or evaluated.

- **Representation check.** Before fitting, the experiment counts *representation conflicts*:
  groups of records with identical concept inputs under the same organization but different
  should-run labels. A conflict means the frozen concepts cannot express that organization's
  answer key.
- **If the internal gate fails:**
  - `REVISE_REPRESENTATION` when the development data (synthetic pretraining and promotion,
    retail adaptation and promotion) has representation conflicts;
  - otherwise `STOP_MECHANISM_FAILED`: the learner failed on inputs that could express the
    answer.
- **If the internal gate passes, after the single telecom evaluation:**
  - `TRANSFER_DIRECTIONAL_NEEDS_FRESH_TELECOM` when the telecom result is positive;
  - `NO_SYNTHETIC_VALUE_OVER_RETAIL` when the telecom set is sufficient and G-combined lets
    through no more should-run telecom records than G-retail;
  - `REVISE_REPRESENTATION` when the telecom set is sufficient and G-combined has more false
    allows than DC;
  - `READY_FOR_SEMANTIC_SCORING` when the telecom set is insufficient. Internal mechanism
    evidence holds; telecom is inconclusive.
- **Mechanics, fixed with the code:**
  - The synthetic learning curve uses checkpoints 25, 50, 100 and the full pretraining set (130
    records); there is no checkpoint at 200, which is larger than the set.
  - The retail curve uses k = 0, 5, 10, 25 and the full adaptation set.
  - Family-bootstrap intervals use 1,000 resamples at 90%.
