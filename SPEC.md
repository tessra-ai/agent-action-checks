# Hatchway: Earned Autonomy Gate — Thesis, PRD and Action Plan

Oct 19, 2026 · @Prithvi

> **Naming.** The source doc used the working name EAG (Earned Autonomy Gate), package `eag`.
> The project is now **Hatchway**: Python package `hatchway`, policy file `hatchway.yaml`,
> CLI `hatchway`. "Earned autonomy gate" still describes what it does. Everything else is
> transcribed from the original doc. Build order and status: see [MILESTONES.md](MILESTONES.md).

## Summary

We will build a small open-source library that decides which agent actions need a human, and
learns to ask less. It plugs into the approval hook every agent framework already has. It scores
each write action (refund, plan change, cancellation) with a typed decision model such as
TypeSafe Jev or OpenAI Decisions, routes it to auto-execute, ask a human, or deny, writes an
append-only, integrity-linked receipt event, and promotes each action type to autonomy as
approvals and outcomes build a track record.

This doc is the original design: the thesis (why), the PRD (what), the week 1 experiment (how),
and build instructions a coding agent can follow step by step.

**Status:** this is the design as written before any code. What has been built is tracked in
[MILESTONES.md](MILESTONES.md); what the experiments found is in
[experiments/README.md](experiments/README.md). Several of the bets below (learned thresholds,
shared concepts) were tested and did not pay off.

---

## Thesis

The durable layer around business agents is not the judge or the approval UI, which are both
commoditizing. It is the policy that decides when to ask a human, learned from outcomes.

### Problem

- **Agents now execute writes that cost money when wrong.** In Voiceflow's 320 controlled
  customer-service trials, all four models tested made refund errors.
- **Agents are inconsistent.** On τ-bench, GPT-4o succeeded on fewer than 50% of tasks and on
  all 8 retries less than 25% of the time in retail.
- **Teams pick between asking a human about every write (slow, approval fatigue) and asking
  about none (risky).** Hand-written rules like `amount > 1000` miss context.

### Insight

- **The hook exists everywhere.** The OpenAI Agents SDK and Vercel's AI SDK accept a function
  that decides per call whether approval is needed; the Claude Agent SDK, LangGraph and Mastra
  have equivalents.
- **Typed decision models now return probabilities and confidence cheaply:** TypeSafe's Jev and
  OpenAI's Decisions API.
- **But confidence is not comparable across providers;** one gateway's docs advise comparing
  choices and scores across models, not confidence. Furthermore, recalibrating a single scalar
  score per action only shifts the cutoff without changing which calls rank as riskier.
- **Missing piece:** multivariate risk modeling with held-out calibration over typed rubric
  questions, learned from approvals and outcomes, with graduated autonomy shipped as a drop-in
  function.

### Why now

- Decision APIs are new in 2026, and gateways like LiteLLM already translate between OpenAI's
  and TypeSafe's formats.
- 66% of customer service organizations ran AI agents in 2026, up from 39% in 2025.
- Claude Code's auto mode shows the mechanic works: a classifier runs before every tool call and
  only risky actions get blocked or prompted. While platform-native tools exist inside single
  vendor ecosystems, independent multi-framework libraries for business actions are nascent.

---

## Landscape

| Category | Players | What they cover | What they lack |
|---|---|---|---|
| **Decision models** | TypeSafe Jev, OpenAI Decisions | Typed scores with probabilities | Thresholds, approvals, learning |
| **SDK approval hooks** | OpenAI Agents SDK, Vercel AI SDK, Claude Agent SDK, LangGraph, Mastra | Pause and resume a tool call | Deciding when to pause |
| **Human-in-the-loop delivery** | Pushary, HumanLayer (moving toward coding IDE) | Reaching the person, keeping a record | Deciding when to ask |
| **Runtime guardrails** | Salus, Airia, NeMo Guardrails | Rules and LLM checks before execution | Learning from outcomes |
| **Meta-harness** | Databricks Omnigent | Stateful ALLOW / ASK / DENY policies | Learned policies; audience is coding agents |
| **Platform-native** | Claude Code auto mode | Classifier per tool call | Single-vendor ecosystem only |
| **Audit and insurance** | AIUC (AIUC-1) | Point-in-time certification, insurance | Per-action runtime decisions |
| **Research** | Hedwig (CAIS '26) | Autonomy that adapts to user trust | Productized for business actions |

### What we own

1. **Multivariate Risk Modeling & Calibration:** per action type and per judge, combining vector
   rubric scores and session trajectory features into estimated, calibrated probabilities,
   learned from approvals and outcomes.
2. **Graduated Autonomy:** conservative promotion (upper-bound miss check over candidate `ALLOW`
   denominator) and automatic demotion (lower-bound statistical breach or window miss-rate
   threshold) of action types, with Inverse Propensity Scored (IPS) random audits on both
   `ALLOW` and `DENY` decisions so neither bad approvals nor false blocks drift unseen.
3. **Receipts as an Append-Only, Integrity-Linked Event Ledger:** every decision, its scores, who
   decided, and the delayed outcome stored as append-only events linked by hash chains in the
   user's own store.
4. **Evidence:** published results on business-action benchmarks.

### Risks

| Risk | Mitigation |
|---|---|
| **Agent SDKs add a learned approval function natively** | Move fast; stay cross-framework and judge-agnostic; own the outcome data and the published evidence |
| **Thin layer, no moat** | Moat comes from accumulated outcome data, multivariate calibration, and validated sub-slice discovery; paid hosted control plane later |
| **Learned thresholds do not beat fixed ones** | Week 1 kill test evaluates multivariate rubric vectors against training-tuned per-action fixed baselines before building anything else |
| **Outcomes rarely reported back** | Answered human approvals are labels by default; random audits on `ALLOW` and `DENY` with IPS weighting keep unbiased labels flowing |
| **Decision APIs are early and unstable** | Pluggable judges; recorded fixtures in tests |
| **Humans stop paying attention or drift goes unnoticed** | Stepped random audits (10% for first 200 auto calls, 2% steady-state on `ALLOW`, 5% on `DENY`) + session-level auto caps |
| **Benchmarks prove method, not demand** | Week 2 ships an installable library; measure adoption |

---

## PRD

v0 is a Python library that gates an agent's write actions with learned per-action policies and
writes an integrity-linked receipt event for every decision, installable in five minutes.

### Goals and non-goals

**Goals for v0:**

- Gate any write action through one call, `gate.check()`, from any framework.
- Start every action type in `shadow` or `ask` mode, and promote it to `auto` on statistical
  evidence.
- Support two judges (Jev, OpenAI Decisions) plus an LLM baseline, and calibrate each over
  multi-question vectors.
- Store receipts locally by default in an append-only, integrity-linked event log.
- Ship one framework adapter (OpenAI Agents SDK) and a local HTTP server for everything else.

**Not in v0:** a hosted service, a web dashboard (CLI reports only), training our own judge model,
coding agents, the MCP proxy, the Omnigent adapter, outbound product telemetry of any kind.

### Users

- **Builder:** a developer shipping a business-action agent (support, operations, billing) on the
  OpenAI Agents SDK or Vercel's AI SDK.
- **Approver:** the ops person who answers `ASK` requests in Slack or the terminal.
- **Owner:** the person who reviews promotion proposals and signs off on autonomy.
- **Researcher:** runs the benchmark harness and replays policies offline.

### User stories

1. As a **builder**, I add the gate to my refund tool in under 10 lines and nothing changes until
   I turn it on (`shadow` mode).
2. As an **approver**, I get a Slack message (or terminal prompt) with the action, the judge's
   reason, and approve/reject buttons.
3. As an **owner**, I run `hatchway report` and see, per action type, how often I agreed with the
   judge and a proposal to promote it.
4. As an **owner**, I approve a promotion and that action type auto-executes from then on, with
   10% of `ALLOW`s sampled for audit during ramp-up, 2% in steady state, and 5% of `DENY`s
   sampled to catch false blocks.
5. As a **builder**, I report a bad outcome (refund reversed) with one call, and the gate
   automatically demotes the action type and notifies the owner if audited misses breach the
   demotion rule.
6. As a **researcher**, I replay any policy offline against logged receipts without re-running
   agents.

---

## Architecture

Seven parts, each replaceable:

| Part | Responsibility |
|---|---|
| **Policy file (`hatchway.yaml`)** | Action types, mode per action, hard rules, session auto caps, judge questions, promotion/demotion settings, redaction |
| **Hard rules** | Safe AST expressions that always `DENY` or `ASK`, evaluated before any judge call |
| **Judge adapters** | Send state plus typed questions to Jev, OpenAI Decisions, or an LLM baseline; return raw question-level score vectors (external calls include configured judges and optional Slack webhook notifications) |
| **Calibrator** | Maps raw question vectors + session/arg metadata to estimated, calibrated probabilities P(action is correct) per action type per judge using held-out calibration; combines judges |
| **Gate** | Applies hard rules, session auto caps, threshold logic, and stepped `ALLOW`/`DENY` audit sampling; returns `ALLOW`, `ASK`, or `DENY` with a reason |
| **Receipt store** | Append-only, integrity-linked event log of decisions, human resolutions, and delayed outcomes (SQLite default, Postgres) |
| **Learner** | Fits IPS-weighted multivariate risk models and thresholds from labeled receipts; proposes promotions and triggers automatic demotions |

### Decision logic

1. **Classify:** a tool marked `kind: read` passes with no judge call and no receipt. An unknown
   tool is treated as a write in `ask` mode.
2. **Hard rules:** any matching `deny_if` returns `DENY`; any matching `ask_if` forces `ASK`.
   Rules always win over scores.
3. **Session cap:** count prior auto-executed writes in the current `session_id`. If
   `session_auto_count >= max_auto_per_session`, force `ASK` with `decided_by='session_cap'`.
4. **Score:** build the state (request, policy excerpt, proposed call, prior actions this
   session), redact sensitive fields, call the configured judges in parallel, and collect the
   full question score vector.
5. **Calibrate to $p_{\text{ok}}$:** map the vector of question responses (e.g.,
   `[p_policy_ok, p_matches_request, p_risk]`), numeric argument features, and prior session
   write count to an estimated, calibrated probability $p_{\text{ok}} \in [0, 1]$ using held-out
   cross-validation.
6. **Mode:**
   - `shadow`: score and log, return `ALLOW`.
   - `ask`: return `ASK` with the score and top failing rubric question as the reason.
   - `auto`: candidate decision is `ALLOW` if $p_{\text{ok}} \ge t_{\text{auto}}$, `DENY` if
     $p_{\text{ok}} \le t_{\text{deny}}$, otherwise `ASK`.
7. **Audit (both `ALLOW` and `DENY`):** in `auto` mode, seeded random sampling converts a fraction
   of candidate `ALLOW`s and `DENY`s into `ASK` with `audit=True` and
   `intended_decision='ALLOW'|'DENY'`:
   - *Auditing `ALLOW`s (catching bad executions):* uses `initial_audit_rate` (default `0.10`)
     for the first `initial_audit_decisions` (default `200`) candidate `ALLOW`s after promotion,
     then steps down to `audit_rate` (default `0.02`).
   - *Auditing `DENY`s (catching false blocks):* uses `deny_audit_rate` (default `0.05`) so
     wrongly blocked good actions are surfaced to humans and recalibrated rather than silently
     degrading agent capability.
8. **Unanswered `ASK`s and timeouts:**
   - *Judge error/timeout:* any judge error or timeout (default 3 s) fails closed and returns
     `ASK`.
   - *Human approval timeout:* if an `ASK` receives no human response within
     `approval_timeout_s` (or is abandoned), the action **remains blocked (never executed)**,
     and its outcome remains `unknown` (never treated as a `bad`/`rejected` label in the
     learner). Only explicitly resolved `ASK`s or confirmed downstream outcomes become training
     labels.
9. **Record:** write one immutable `DECISION` event per gated call to the receipt store.

### Calibration, promotion, and demotion math

- **Multivariate risk model & calibration:** Recalibrating a single scalar score per action is a
  monotonic transformation that cannot change the relative risk ranking of calls. Instead,
  Hatchway calibrates over the full question vector $\mathbf{q} = [q_1, q_2, \dots, q_k]$,
  numeric argument features, and prior session write count. Below 50 labels, use
  $L_2$-regularized logistic regression; at or above 50 labels, fit per-question isotonic
  regression followed by a logistic combiner using held-out cross-validation. With two judges,
  include both calibrated vectors plus a judge disagreement feature
  ($|p_{\text{jev}} - p_{\text{openai}}|$).
- **Inverse Propensity Scoring (IPS) & active training label selection:** In `auto` mode, labels
  arrive from answered `ASK` calls ($w = 1.0$), audited `ALLOW` calls
  ($w = 1 / r_{\text{allow\_audit}}$), and audited `DENY` calls
  ($w = 1 / r_{\text{deny\_audit}}$). Unanswered `ASK`s (`outcome='unknown'`) are excluded from
  training. **Label precedence rule:** when training the learner, the receipt's realized outcome
  (`realized_outcome`) is used when present (`ok`/`bad`); otherwise, the human decision
  (`human_decision`) is used as the supervisory label. Weighting audited rows by $w$ ensures
  recalibration covers the full score distribution without bias.
- **Promotion (conservative upper bound over candidate allows):** The learner proposes `auto`
  mode for an action type when it has at least `min_candidate_allows: 100` decisions that the
  frozen policy *would* have classified as `ALLOW`, and the **Clopper-Pearson 95% upper
  confidence bound** on the miss rate is at most `max_miss_bound: 0.03`. (`ASK` and `DENY`
  examples do not establish autonomous safety.)
  - *Note on stakes:* `max_miss_bound: 0.03` is a pragmatic default for standard actions (0
    misses in 100 candidate allows yields a 2.95% upper bound). High-stakes actions (e.g., large
    refunds or account deletions) should configure `max_miss_bound: 0.01`,
    `min_candidate_allows: 300`, and strict demotion rules.
- **Demotion (lower bound + non-overlapping window rule):** Using an upper confidence bound for
  demotion would immediately demote newly promoted actions when the audit count is small. To
  avoid continuous-monitoring false-alarm accumulation over overlapping windows, automatic
  demotion triggers immediately (and notifies the owner) when there is positive evidence of
  degradation defined as any of:
  1. **Statistical lower bound:** the **Clopper-Pearson 95% lower confidence bound** on audited
     `ALLOW` misses exceeds `max_miss_bound` (we are 95% confident the true miss rate is worse
     than the limit), OR
  2. **Non-overlapping window rule:** in a fixed, non-overlapping inspection window of 50
     audited `ALLOW`s, audited misses reach `demote_on_misses` (`4` for 0.03 bound, or `2` for
     0.01 bound), OR
  3. **Version change:** the judge model ID or `policy_version` changes.
- **Separation of supervision vs. ground truth:** Training labels are derived from simulated
  human decisions containing 5% noise (and automation-bias variants), whereas test/safety
  metrics use benchmark ground-truth. In promotion simulations, report results once using noisy
  supervisory approvals and once using true downstream outcomes. In the production schema,
  `human_decision` and `realized_outcome` are strictly separate fields; an operator approval is
  recorded as evidence, not absolute truth.
- **Week 2 extensions (sub-slices, expected-cost, cascade):** When an action as a whole fails
  promotion, the learner can search depth-1 parameter splits (e.g., `args.amount <= 75`) on a
  training fold and validate the candidate slice on a **strictly held-out validation split**
  before proposing promotion. Similarly, expected-cost gating and two-judge cascade routing plug
  into the same calibrated $p_{\text{ok}}$ interface in Week 2.

---

## Policy file (`hatchway.yaml`)

```yaml
version: 1
judges: [jev, openai_decisions]
store: sqlite:///hatchway.db

defaults:
  mode: shadow
  initial_audit_rate: 0.10
  initial_audit_decisions: 200
  audit_rate: 0.02
  deny_audit_rate: 0.05
  judge_timeout_s: 3
  approval_timeout_s: 3600   # unanswered ASKs stay blocked with outcome='unknown'
  max_auto_per_session: 3
  redact: [args.card_number, args.email]

actions:
  get_order:
    kind: read
  refund_order:
    kind: write
    mode: ask
    hard_rules:
      deny_if: 'args.amount > 500'
      ask_if: 'args.method != context.original_payment_method'
    questions:
      policy_ok:
        type: yes_no
        text: 'This refund follows the refund policy.'
      matches_request:
        type: yes_no
        text: 'This action matches what the customer asked for.'
      risk:
        type: choice
        options: [low, medium, high]
    promotion:
      min_candidate_allows: 100
      max_miss_bound: 0.03
      demote_on_misses: 4
      demote_window: 50   # non-overlapping inspection blocks
```

Hard rules use a safe AST expression evaluator over `args` and `context` (no `eval`). Question
types map to the judges: `yes_no` is Jev's `noul` and OpenAI's `predicate`; `choice` and `score`
map one to one.

---

## Public API

```python
import hatchway

gate = hatchway.Gate('hatchway.yaml')

d = gate.check('refund_order', args, context)  # Decision(result, reason, receipt_id, p_ok)

gate.resolve(d.receipt_id, approved=True, by='alice@example.com', human_decision='approve')

gate.record_outcome(d.receipt_id, ok=False, source='refund_reversed', realized_outcome='bad')

# Decorator form
@gate.action('refund_order')
def refund_order(order_id, amount, method):
    ...

# OpenAI Agents SDK adapter
from hatchway.adapters.openai_agents import needs_approval

tool = function_tool(refund_order, needs_approval=needs_approval(gate, 'refund_order'))
```

**CLI:** `hatchway init`, `hatchway report`, `hatchway promote <action>`,
`hatchway demote <action>`, `hatchway verify` (integrity-linked hash chain), `hatchway export`,
`hatchway serve` (local HTTP with `/check`, `/resolve`, `/outcome` for non-Python agents such as
Vercel's AI SDK).

---

## Receipt schema (append-only event ledger)

To ensure the ledger is strictly append-only and integrity-linked while supporting asynchronous
human approvals and delayed reversals, the store writes immutable events (`DECISION`,
`RESOLUTION`, `OUTCOME`) linked by `receipt_id`, and exposes a joined view (`receipts_view`) for
the learner. *(Note: unanchored suffixes can be verified against an external checkpoint or root
hash if deletion of trailing uncommitted rows is a threat model concern.)*

| Field | Type | Notes |
|---|---|---|
| `event_id` | ULID | Primary key for each immutable event row; sortable by time |
| `receipt_id` | ULID | Ties `RESOLUTION` and `OUTCOME` events back to the original `DECISION` |
| `event_type` | text | `DECISION` \| `RESOLUTION` \| `OUTCOME` |
| `ts` | timestamp | UTC |
| `session_id`, `agent`, `actor` | text | Actor = user the agent acts for, when known |
| `action` | text | Tool name |
| `args_redacted` | JSON | After redaction (`DECISION` event) |
| `args_hash` | text | HMAC-SHA256 of canonicalized arguments using a local store secret |
| `policy_version` | text | Hash of the policy file in force |
| `judge_scores` | JSON | Raw per-question answers per judge, with model IDs |
| `p_ok` | float | Estimated, calibrated probability |
| `mode`, `decision` | text | `shadow`/`ask`/`auto`; `ALLOW`/`ASK`/`DENY` |
| `intended_decision` | text | `ALLOW`/`ASK`/`DENY` before audit override (distinguishes `ALLOW` audits from `DENY` audits) |
| `decided_by` | text | `auto`, `human:<id>`, `rule:<name>`, `session_cap`, `timeout`, `oracle` |
| `reason` | text | Shown to the approver |
| `audit`, `ips_weight` | bool, float | `True` when sampled for audit; `1.0` for answered `ASK`, `1/r_allow` for audited `ALLOW`, `1/r_deny` for audited `DENY` |
| `human_decision` | text | Supervisory approval record (`approve`/`reject`) — treated as evidence, not ground truth |
| `realized_outcome` | text | Downstream outcome (`ok`/`bad`/`unknown`) |
| `outcome_source` | text | Source of the outcome label (`resolution`, `reversal_hook`, `oracle`) |
| `prev_hash`, `hash` | text | SHA-256 hash chain over `receipt_events` rows for tamper evidence |

Receipts never leave the user's store. Outbound calls are limited strictly to configured judge
APIs and optional operator Slack webhooks.

---

## Non-functional requirements

- Gate overhead, excluding judge calls, under 20 ms at p95.
- Fail closed on every error path (and keep unanswered `ASK`s blocked).
- No network calls in tests; judges are tested against recorded fixtures.
- Seeded randomness for audits so replays are reproducible.
- Python 3.11+, Apache 2.0 license.

## Success metrics

| Metric | Target | When |
|---|---|---|
| **Reduction in test-split human asks vs best training-tuned fixed threshold, at the 95% per-action training catch-rate operating point** | 30% or more | Week 1 |
| **Calibration error (ECE) after 200 labels per action** | 0.05 or less | Week 1 |
| **Time to first gated call for a new user** | Under 5 minutes | Week 2 |
| **External repos using the library** | First 10 | Weeks 3–4 |

---

## Week 1 experiment

**Question:** Do learned multivariate per-action policies cut human asks by 30% or more on the
test split, when per-action thresholds for all arms are set on the training split to catch 95% of
incorrect writes within each action type?

### Setup

- **Benchmark:** τ²-bench (repo commit `c5b2d228d850c59b749b93cf32c4745d3aa53967`, the last
  commit that supports Python 3.11; pinned in M4), retail and telecom domains, `base` task split;
  airline if time allows. Each task has a simulated customer, domain tools, a policy document,
  and a target database state; success is an exact match of the final state.
- **Agents:** two or three agent models through `tau2`'s runner, several trials per task, to get
  thousands of write actions.
- **Interception:** wrap the environment's tool functions. Reads pass through; every write goes
  through `gate.check()` in `shadow` mode, so agent behavior is unchanged.
- **Capture, then score:** the shadow wrapper only captures writes (one row per tool invocation,
  duplicates included); it makes no judge calls. A separate, resumable batch job scores captured
  writes, calling each judge once per `(state_hash, rubric_hash, judge_name, model_id)`. Judge
  errors are retried, then stored as `status='error'`, never as `ASK`; the production 3 s
  fail-closed rule is simulated offline in replay. See [MILESTONES.md](MILESTONES.md) for the
  coverage, common-support and end-to-end evaluation rules.
- **Split strategy:** grouped, time-ordered 60/40 split by conversation/task ID so no task or run
  appears on both sides, preventing scenario overfitting.
- **Training supervision & evaluation labels:**
  - *Training labels (supervisory):* simulated human decisions with 5% noise (and
    automation-bias variants). When training, the learner uses `realized_outcome` if present,
    otherwise falling back to `human_decision`.
  - *Test and safety metrics (ground-truth evaluation):* an independent policy verdict on each
    proposed write (`ALLOW` / `ASK` / `DENY` / `UNKNOWN`), from deterministic validators over the
    pre-action state and the conversation, with manual review of unknowns and an audit sample
    (MILESTONES.md, M6c). Matching τ²'s reference trace is not policy correctness, a backend
    rejection does not make a proposal valid, and the task's final outcome is reported per
    simulation, separately.
- **Simulated approver:** the policy verdict (approve `ALLOW`, reject `ASK` and `DENY`; an
  `UNKNOWN` cannot be verified and stays blocked), with 5% of answers flipped uniformly at random
  to mimic human error. (An automation-bias simulator follows in Week 2 offline replays.)

### Arms and fair operating-point protocol

Run the agents once in `shadow` mode with every judge scoring every write across all rubric
questions, then replay each policy offline against the same receipts. One run, many policies.

| Arm | Policy | What it tests |
|---|---|---|
| **A** | No gate | Baseline error rate |
| **B** | LLM-as-judge, fixed global & per-action threshold (tuned on 60% train split) | The do-it-yourself option |
| **C** | Jev, fixed global & per-action threshold (tuned on 60% train split) | Jev out of the box (TypeSafe Jev) |
| **D** | OpenAI Decisions, fixed global & per-action threshold (tuned on 60% train split) | OpenAI out of the box (OpenAI Decisions API) |
| **E** | Best single judge, **learned multivariate risk model + per-action thresholds** (fit on 60% train split) | Value of the multivariate learner over single-score threshold tuning |
| **F** | **Both judges**, multivariate calibrated, disagreement routed to `ASK` (fit on 60% train split) | Value of cross-judge calibration |

**Protocol for "equal catch rate" (per action type + overall):**

1. Split receipt events 60% train / 40% test grouped by task/conversation ID in strict time
   order.
2. **Per-action 95% catch target on the 60% training split:** every per-action arm (the
   per-action fixed baselines in B, C, and D, as well as the learned risk models in E and F)
   tunes its threshold for each action type on the 60% training split so that **at least 95% of
   incorrect writes within that action type are caught** (sent to `ASK` or `DENY`). If a rare
   action type has fewer than 5 incorrect writes in the training split, fall back to the arm's
   global 95%-catch threshold. Global-only sub-variants in B, C, and D tune a single threshold
   across all training writes to catch 95% of total incorrect writes.
3. Freeze those thresholds and evaluate all arms on the **held-out 40% test split**: report
   **both per-action catch/ask rates and overall aggregate catch/ask rates** on the test split.
   In addition to the primary 95% per-action operating point, plot the full test-split ask-rate
   vs. catch-rate frontier across target catch rates ∈ [0.85, 0.90, 0.95, 0.98].
4. After the replay, run one live gated (not shadow) pass with the best arm to measure the change
   in task pass rate (reported twice: once using the noisy simulated approver, once using a
   perfect ground-truth approver).

### Metrics

- **Catch rate (per action type and overall):** share of incorrect writes denied or sent to `ASK`
  on the 40% test split.
- **Auto rate (per action type and overall):** share of correct writes auto-executed on the 40%
  test split.
- **Ask rate (per action type and overall):** share of all writes sent to a human on the 40% test
  split.
- **Calibration error (ECE):** per judge, before and after multivariate calibration.
- **Autonomy curve:** per action type, auto rate against number of labeled decisions.
- **Cost and latency:** per gated call, per judge.
- **Task pass rate change:** in the live gated run.

### Kill or continue

- **Continue:** Arm E or F cuts the overall test-split ask rate by 30% or more against the best
  training-tuned per-action fixed arm while maintaining the 95% per-action catch-rate target.
- **Rethink:** 10–30%. Test expected-cost gating / sub-slices on the logged receipts or add
  ITSMBench before deciding.
- **Stop:** under 10%. The learner adds little over a tuned per-action threshold, so the library
  would be plumbing around someone else's judge.

### Deliverables

- The autonomy-curve chart, ask-vs-catch frontier, and a one-page write-up.
- The receipts dataset (judge question vectors, decisions, labels), exported for reuse.
- A replay notebook anyone can rerun.

**Open questions:** API access and credits for Jev and OpenAI Decisions; the cost of the τ² user
simulator across thousands of conversations.

---


## Instructions for coding agents

Build one milestone at a time, in the order given in [MILESTONES.md](MILESTONES.md), and stop at
each milestone's acceptance tests before moving on. Do not build beyond v0 scope (see PRD,
non-goals).

Week 1 builds only the benchmark path (M1–M7): core types, a minimal policy, a flat benchmark
store, capture-then-score, replay and the live pass. Hard rules, `policy_version`, the
event ledger, hash chain, HMAC and redaction are deferred to week 2 (M8–M9). The build steps
below describe the complete v0 and are finished in week 2.

To use this with a coding agent: tell the agent *"Read SPEC.md and MILESTONES.md. Build milestone
N only. Stop when its acceptance tests pass."*

### Repo layout

The planned v0 layout. The code has since moved (the τ²-bench harness and replay live under
`hatchway/bench/`); the source tree is authoritative.

```
hatchway/                  # repo root
  pyproject.toml
  hatchway/
    __init__.py            # exports Gate, Decision
    policy.py              # load and validate hatchway.yaml (pydantic v2)
    rules.py               # safe AST expression evaluator for hard rules
    state.py               # build judge state text and session write counts from call and context
    judges/
      base.py              # Judge protocol, Question and QuestionVector types
      jev.py               # TypeSafe System One
      openai_decisions.py  # OpenAI Decisions API
      llm_baseline.py      # chat model asked yes/no per question
      oracle.py            # returns labels; tests and benchmark only
    calibrate.py           # multivariate logistic + isotonic per action x judge; two-judge combiner; IPS weights
    gate.py                # decision logic, session cap, stepped ALLOW and DENY audit sampling
    receipts.py            # append-only receipt_events store (SQLite, Postgres), receipts_view, hash chain, redaction
    learner.py             # thresholds, upper-bound promotion (candidate allows), lower-bound + window demotion
    bench/                 # week 1 benchmark path
      store.py             # flat SQLite: captured_writes (one row per invocation), scores (cached per judge key)
      score.py             # resumable batch scoring of captured writes
      __init__.py          # DENIAL_RESULT: fixed tool result for denied writes in the live pass
    cli.py                 # init, report, promote, demote, verify, export, serve
    server.py              # HTTP: /check, /resolve, /outcome
    adapters/
      openai_agents.py
  bench/
    tau2/
      harness.py           # wraps tau2 write tools with capture-only gate.check in shadow mode
      label.py             # proposed write vs ground-truth actions
      replay.py            # offline replay of arms A-F (tuned on grouped 60% train at 95% per-action catch rate)
      report.ipynb
  examples/
    support_agent/
  tests/
```

### Build steps

1. **Policy and integrity-linked event receipts.**
   - Load and validate `hatchway.yaml`; invalid files fail with a message naming the field.
   - `receipt_events` is strictly append-only; `hatchway verify` recomputes the hash chain and
     detects any edited, inserted, or deleted event row (with optional external checkpoint
     anchoring for unanchored suffixes).
   - Redaction removes listed fields before storage and before any judge call; argument hashes
     use HMAC-SHA256 over canonicalized arguments with a local store secret.
2. **Gate in shadow mode.**
   - `kind: read` tools pass with no judge call and no receipt.
   - Every write produces exactly one `DECISION` event in `receipt_events`.
   - A judge that raises or times out yields `ASK` (test with a failing fake judge).
3. **Judges.**
   - Jev (TypeSafe Jev) and OpenAI Decisions (OpenAI Decisions API) adapters map `yes_no`,
     `choice`, and `score` questions into a structured `QuestionVector` preserving per-question
     scores.
   - Tests run against recorded fixtures with no network access.
   - A timeout returns `ASK` within the configured limit.
4. **τ² harness and labeler.**
   - On a small sample, the shadow-wrapped run's pass rate matches the unwrapped run within
     noise.
   - Every write gets a label of `correct`, `incorrect`, or `ambiguous`.
5. **Replay and learner (Arms A–F).**
   - Replay splits logged receipts 60% train / 40% test grouped by task/conversation ID in strict
     time order.
   - Per-action variants of Arms B, C, and D tune one scalar threshold per action type on the 60%
     train split so that 95% of incorrect writes within each action type are caught; Arms E and F
     fit multivariate risk model calibration and tune per-action thresholds on the 60% train
     split to hit the same 95% per-action catch rate.
   - Evaluates all arms on the held-out 40% test split, outputting both per-action and overall
     metrics in JSON, the autonomy-curve chart, and the ask-vs-catch frontier.
   - The same seed reproduces the same numbers.
6. **Ask and auto modes.**
   - `resolve()` and `record_outcome()` append immutable `RESOLUTION` and `OUTCOME` events linked
     by `receipt_id` without mutating prior rows or breaking the hash chain (storing
     `human_decision` and `realized_outcome` as separate fields).
   - Unanswered `ASK`s that exceed `approval_timeout_s` remain blocked with
     `outcome='unknown'` and are excluded from learner training.
   - Audit sampling is seeded: candidate `ALLOW`s are sampled at `initial_audit_rate` (0.10) for
     the first `initial_audit_decisions` (200) calls and `audit_rate` (0.02) thereafter;
     candidate `DENY`s are sampled at `deny_audit_rate` (0.05). Audited rows carry IPS weight
     $1 / r_{\text{active}}$.
   - Promotion requires an owner command (`hatchway promote`) and requires at least
     `min_candidate_allows: 100` decisions that the frozen policy would have allowed, with a
     Clopper-Pearson 95% **upper** bound on the miss rate ≤ `max_miss_bound` (0.03 default).
   - Demotion triggers automatically and notifies the owner only when the Clopper-Pearson 95%
     **lower** bound on audited `ALLOW` misses exceeds `max_miss_bound`, OR when audited `ALLOW`
     misses reach `demote_on_misses` (4 default for 0.03 bound) within a non-overlapping
     inspection block of `demote_window` (50) audited `ALLOW`s, OR when the judge model /
     `policy_version` changes.
   - Session cap forces `ASK` when prior auto-executed writes in the same `session_id` reach
     `max_auto_per_session`.
7. **Adapters and server.**
   - The example support agent runs end to end with the OpenAI Agents SDK adapter.
   - `hatchway serve` answers `/check`, `/resolve`, and `/outcome`; a TypeScript client example
     calls it.

### Conventions

- Python 3.11+, type hints throughout, pydantic v2, pytest, ruff, scikit-learn / scipy (for
  multivariate calibration and exact Clopper-Pearson binomial bounds).
- No network calls in tests. Secrets only from environment variables: `TYPESAFE_API_KEY`,
  `OPENAI_API_KEY`.
- Never log or store raw arguments before redaction.
- Every external API is new and changing: check the request and response shapes against the
  current docs for TypeSafe System One, the OpenAI Decisions API, and the `tau2-bench` repo
  before writing each adapter, rather than relying on this spec's descriptions.

---

## Sources

- τ-bench paper (ICLR 2025)
- τ²-bench benchmark description (arXiv)
- τ²-bench repository
- TypeSafe Jev introduction
- LiteLLM: `/v1/decisions` and `/v1/systemone`
- Vercel AI Gateway: OpenAI Decisions
- Orq.ai: Decisions
- OpenAI Agents SDK: human in the loop
- AI SDK: human-in-the-loop recipe
- Developers Digest: approvals in 5 SDKs
- Databricks: introducing Omnigent
- Omnigent docs: contextual policies
- Omnigent docs: custom policies
- Google Research: Harness²
- Pushary vs HumanLayer
- Techzine: Claude Code auto mode
- Hedwig: dynamic autonomy for coding agents
- Tian Pan: earned autonomy
- Voiceflow CX policy-check trials
- YourGPT on ecommerce customer service
- Salus (Y Combinator)
- AIUC Series A coverage
