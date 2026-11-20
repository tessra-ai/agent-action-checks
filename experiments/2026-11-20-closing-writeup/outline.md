# Closing post: outline (M3)

Working title: **"Two questions before an AI agent acts: what a week of trying to build a model
for them found"**. It is a follow-up to "Three questions before an AI agent acts".

Voice: as the first post. Plain sentences and short paragraphs. Tables of counts with
denominators, then a percentage, then a one-sided 95% upper bound where the first post gave one.
First person singular ("I"), since the first post's "we" was a single author.

Rules for the draft (M4):
- every figure comes from `numbers.json`, cited below by key;
- every claim about a paper comes from `prior_work.md`;
- nothing goes beyond **Limits**;
- the sealed test sets are never mentioned as evaluated;
- "Docent" is used as a label only.

## 1. Summary

Four or five bullets, the first post's shape:
- **Two narrow questions instead of one broad judge.**
  - Did the customer agree to this exact action?
  - Is any agent statement a material contradiction (false against the records, and likely to
    change the yes)?
  - On 174 train and dev actions, the labellers' consensus on those two questions stops 53 of the
    91 bad actions and 1 of the 56 good ones (`consensus_gate`).
- **A cheap decision model answers both well, but not alone.**
  - Stock Jev's AUC is 0.93 on statements and 0.97 on agreement (`stock`).
  - At cut-offs chosen on the other folds to stop at most 5% of their good actions, it catches 43 bad
    actions and stops 4 good (`jev_tradeoff.cap_5pct`).
  - A cascade that sends Jev's unsure cases to the frontier labellers gets 55 and 3, sending 36% of
    actions (`cascade."selection cap 5%, width 0.2"`).
- **Rules plus the cascade catches 76 of 91 and stops 3 of 56.** 22% of graded actions reach a
  frontier model (`designs."A: …width 0.2"`). Adding the broad rubric judge after A's stages
  (C, width 0.2, both runs) catches 88–89 but stops 11 good actions. B, a different design (rules,
  Jev alone at the 5% cap, then the judge), catches 86–88 and stops 12 (`designs.B/C`).
- **The model I set out to build did not beat a stock one.** A fine-tuned open 4B model rose from
  0.43 to 0.81 statement AUC and stayed clearly below stock Jev (`kev_pilot`).
- **What it is made of:**
  - of the 39 bad actions the consensus marks never agreed, 31 came from the weakest agent
    (gpt-4.1-nano, retail only) and the backend rejected 24 anyway. These are two separate counts
    over overlapping groups (`cut_a`);
  - the 11 bad actions with a flagged false statement and the customer's agreement all executed;
    the 3 flagged actions where the labellers split on agreement were rejected
    (`coverage_bad_by_backend`; these are action counts, not statement counts).

## 2. What I tried to build

The first post's open middle question ("is it true"). The plan for a small reliance model (Rely-1),
fine-tuned from Kev. How the label narrowed:
1. "the customer relied on it";
2. a *material contradiction*;
3. two questions, once "never agreed" turned out about three times as common as a false statement.

One paragraph; no numbers beyond the labeller counts.

## 3. Setup and data

- **Data:** 174 actions from the first post's retail and first airline captures (train 133, dev
  41). 147 have a good/bad ruling (91 bad, 56 good) and 27 are ungraded (`data`).
- **Sealed:** two test splits, 64 unseen-task and 90 repeat-task actions, stayed sealed. This post
  reports no test result (`data.test_*_sealed`).
- **Packet:** conversation up to the action, proposed call, policy, lookups. The 95th percentile is
  8,996 tokens, and 14 of 174 packets exceed 8,192 (`data`).
- **Questions asked:** 380 agent statements were sampled, those an earlier check flagged or a
  ruling quoted, plus one agreement question per action (`labels`).

## 4. Ground truth

- **Good/bad rulings:** from the first post: graders, adjudication, a deterministic retail checker,
  and my corrections. These are independent of this week's labels.
- **Statement and agreement labels:**
  - Two frontier labellers: A (Codex CLI, GPT-6.2-sol, reasoning high) and B (Gemini app, 4 Neon,
    thinking high).
  - Agreement: 366 of 380 statements (kappa 0.74); 158 of 174 agreement answers (kappa 0.79). Both
    said yes on 21 statements, and both said "not agreed" on 46 actions (`labels`).
  - A rerun of A without reasoning changes almost nothing (kappa 0.89, `labels`).
- **The anchors** (`labels.anchors`):
  - the "second cheapest" booking: both flagged it;
  - the certificate balance: true but misleading, ruled out of scope.
- **No person has reviewed this week's labels.** Say it here and again in Limits.

## 5. The two questions

- **Definitions,** with one example each:
  - a *material contradiction*: P033, the "second cheapest" anchor;
  - "never agreed": a reworded or never-confirmed action.
- **Coverage of the 91 bad actions** (`coverage_bad`):
  - never agreed only: 38;
  - false statement in an agreed action: 11;
  - both or split: 4;
  - neither: 38.
- **On good actions:** 1 flag, which looks like a wrong ruling, and 0 "never agreed"
  (`coverage_good`).
- **Chart 1, `bad_actions_by_question.png`:** the same counts split by executed vs rejected.

## 6. Results

- **Table** (all `designs` / `jev_tradeoff` / `cascade` / `consensus_gate`): bad caught (of 91),
  the missed share with its 95% upper bound, good stopped (of 56) with its bound, and the share
  reaching a frontier model. Rows:
  1. rules alone;
  2. Jev at the 5% and 20% caps;
  3. consensus alone;
  4. the cascade;
  5. A;
  6. B, both runs;
  7. C at width 0.2, both runs.

  Name the width once, per the M1 mismatch note.
- **Chart 2, `tradeoff.png`.**
- **One paragraph on the choice of cut-offs.** The pilot rule (bad-caught rate minus good-stopped
  rate) lands near 20% of good stopped. The earlier 51 / 5 came from fixed 0.5 cut-offs picked while
  looking at this data (`stock.jev_cutoffs_tuned_on_same_data`). It is a different operating point
  from the out-of-fold 43 / 4 at the 5% cap. Present them side by side, not as one inflating the
  other.
- **Length split:** the 14 packets over 8,192 tokens are all airline, with 6 bad actions
  (`by_packet_length`).

## 7. What the consent result is made of

- **Never agreed** (`cut_a`):
  - 31 of the 39 never-agreed bad actions came from gpt-4.1-nano, all in retail;
  - the backend rejected 24 of those 39 anyway.
  - Model and domain are confounded.
- **The backend rejected 47 of the 91 bad actions anyway.** On the 44 that executed (`cut_b`):

  | Design | Executed bad actions caught (of 44) |
  |---|---|
  | Consensus alone | 26 |
  | A | 40 |
  | B | 42 / 40 |
  | C | 43 / 42 |

- **Chart 3, `executed_only.png`.**
- **All 11 bad actions with a flagged false statement and agreement executed** (`coverage_bad_by_backend`). The statement
  question carries more weight than its count suggests.
- **The 21 both-yes statements by type:** eligibility, ranking and other. Give both readings, 11/5/5
  and 12/3/6 (`cut_c`), or neither.

## 8. Narrow versus broad

- **Without rules:** the cascade (narrow, two questions) gets 55 and 3. With rules, A gets 76 and 3.
- **With the broad judge on top:** B and C (width 0.2, both runs) get 86–89 but stop 11–12 good actions. B stops 6 good in
  each domain, against 1 (airline) and 2 (retail) for A (`designs.…by_domain`).
- **What A still misses:**
  - the retail refund-method mistakes, a policy error neither question asks about (9 of A's 15
    misses, `designs.A.missed_refund_method`);
  - skipped steps.
- **One rule would likely cover the refund cases.** That rule is not written or measured, so the
  post gives no "about 85" figure.
- **The anchor:** B misses the "second cheapest" booking; A and C catch it (`checks`).
- **Caveat on circularity:** the frontier layer in the cascade is the same consensus that defines the
  statement labels. The good/bad rulings are independent, so the A, B and C counts are not
  circular, but the cascade's inner layer is.

## 9. The failed fine-tune

- **What was trained** (`kev_pilot`):
  - Kev-4B, five task-grouped folds, about 435–488 training records per fold;
  - planted edits written mostly by Codex, which also checked them: 118 of 157 planted contradictions;
  - natural consensus labels.
- **Results:** statement AUC 0.81 against Jev's 0.93; agreement AUC 0.89 against 0.97. 55 of 91 bad
  caught, 19 of 56 good stopped, under the same protocol as Jev's 66 / 16.
- **Verdict as recorded:** improved over stock, clearly below Jev, not pursued.
- **Chart 4, `finetune.png`.**
- **Why it is a weak test of Kev:** small, synthetic and same-family data. Do not claim Kev can't
  learn the task. No dollar figure: the bill is not in a committed file.

## 10. Prior work

From `prior_work.md` only:
- **JevAct** (closest): a pre-execution gate on τ²-bench with GPT-4.1 agents and compiled consent
  questions. So the consent question is not new as a check. It has no statement-truth question, no
  broad-judge comparison, no cascade and no retail.
- **The Agent Knew:** false statements before 26% of 227 policy-violating writes in published
  τ²-bench airline runs, measured offline. It does not ask a model before the write.
- **τ-bench:** the confirmation rule is in its policy but not in its score; wrong information
  appears only in a manual failure analysis.
- **DelegationBench and AuthorizationBench:** asking before acting, and acting beyond authorization.
  The first uses synthetic or pre-staged decision points; the second is post hoc and outside τ-bench.
- **AuthorizationPairs and Consent Integrity:** pre-execution permission or approval integrity,
  without a conversation or statement truth.
- **False success:** broad completion judges at or below AUC 0.65, against 0.83 for cheap
  classifiers; post hoc, on public τ²-bench runs.
- **Claims allowed:**
  - the statement question has no pre-execution check *among these eight papers*;
  - none of the eight compares two narrow questions with a broad judge on the same actions.
- **Claims not made:** that the cascade is new. JevAct cites an escalation preprint I have not
  read.

## 11. What is still open

- **The held-out test,** with a design that avoids the frontier labels grading the frontier layer:
  the good/bad rulings as truth, and the labellers blind to the design.
- **The refund-method rule and a narrow skipped-steps question,** unmeasured.
- **True but misleading statements** (one example).
- **A fair test of a small open model:** more and real data.
- **Current agents:** the false-success paper's public τ²-bench runs as a source.
- **The four unread papers** from `prior_work.md`.

## 12. Limits

- Model-made labels, unreviewed by a person.
- The frontier layer is scored partly against labels it helped define.
- No held-out test; wording and design were shaped on this data.
- Small counts: 21 both-yes, 91 bad, 56 good. Differences of 2–3 actions are noise.
- Bounds treat actions as independent, though several come from one task.
- One benchmark, simulated customers, GPT-4.1-family agents. Model and domain are confounded for
  "never agreed".
- Sampled statements: 380, not every sentence.
- Uneven labeller setup (a CLI against a consumer app).
- Rules written by someone who had seen the failures; retail has none.
- The fine-tune was a weak test.

## 13. Method and reproduction

- `actions.py` → `build_numbers.py` → `numbers.json` (46 checks against the handover brief; the 3
  mismatches recorded in `Report.md`); `charts.py`; `check_prior_work.py`.
- Experiment folders: `2026-11-18-rely1-m0`, `-m1`, `2026-11-20-uncaught-38`, and this one.
- Each step was reviewed before commit. The labels came from subscriptions, not paid API calls.
  The paid calls were Jev's at cents and the Kev pilot's GPU time.

## 14. Disclosure

As in the first post: Tessra builds deterministic policy checks (the "is it allowed" question). Add:
- AI models labelled the data and helped write the code;
- the planted training data was written and checked by the same model family as labeller A.

## Charts

| File | Section | Drawn from |
|---|---|---|
| `charts/bad_actions_by_question.png` | 5 | `coverage_bad_by_backend` |
| `charts/tradeoff.png` | 6 | `jev_tradeoff`, `consensus_gate`, `cascade`, `designs` |
| `charts/executed_only.png` | 7 | `cut_b_backend_rejected` |
| `charts/finetune.png` | 9 | `stock`, `kev_pilot` |

All four are drawn by `charts.py` from `numbers.json` only. They are static PNGs on the light
surface, using the dataviz reference palette (blue, orange, aqua and a neutral grey), validated
all-pairs in light mode, with direct value labels on every mark.
