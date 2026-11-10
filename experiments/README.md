# Experiments

**Provenance.** This repository is a snapshot of the development repository (commit `015e852`,
2026-11-09). Branch names and commit hashes in the experiment records, including the
preregistration and freeze commits, refer to that development history, which is not published;
they are kept as written. The experiment records themselves (preregistrations, reports, code and
per-action results) are complete here.

Each experiment has its own dated directory: its report, its frozen manifest where it had one,
and the compact metrics it produced. Reports are never replaced. A later experiment that changes
a conclusion gets its own directory and marks the earlier one `superseded`.

Large generated files stay out of Git (`runs/` is ignored): capture stores and HTML viewers.
Each report lists them with their sha256 and where they live. Ground truth depends on the
domain. Retail uses the deterministic policy oracle, which no person has audited. Airline uses
blind Claude graders, replaced by the author's own blind review where they bear on the reported
numbers ("adjudicated"), and τ²-bench's corrected answer key; each report gives results under
each truth. The only human review is the author's; no reviewer independent of the author has
validated these results.

**Status labels:**

- `diagnostic`: checks the method or the pipeline, not the product claim.
- `directional`: a frozen, pre-specified test too small to be conclusive.
- `no-go`: its decision stops the next step as specified.
- `superseded`: a later experiment replaces its conclusion or reuses its data.
- `planned`: preregistered, not run.

## The story so far

1. **Smoke run 1 (2026-10-21).** The pipeline ran end to end, but its labels were τ² task
   outcomes and trace matches. A refund the backend rejected still "passed"; a refund that
   matched the reference trace still broke the refund rule. Task and backend outcomes are not
   policy verdicts.
2. **Policy-verdict correction (2026-10-22).** A deterministic oracle now judges each proposed
   write from the pre-action state and the conversation alone. Of 7 writes that matched τ²'s
   trace, 3 should not have executed. This became the evaluation target for everything after.
3. **Judge and strategy comparison (2026-10-22).** No gate, plain LLM, Jev, OpenAI Decisions, a
   fitted model and a two-judge combination were compared against the verdicts. With 5 held-out
   writes the claims gate blocked every conclusion.
4. **Targeted shadow experiment (2026-10-22).** A cost-capped capture on four validated action
   types. Stage 1 (57 simulations, $2.59) failed its sample gates: 9 held-out writes. It was
   stopped as inconclusive.
5. **Shared-concept decision-model pilot (2026-10-23).** On the already captured writes, with
   ten shared decision concepts, the pilot compared the fixed baseline (D), a fixed concept
   rule (DC) and a learned concept model (G1). It used a sealed holdout.
   - All three arms were equally safe on the holdout (0/21 false allows).
   - The learned model saved no approvals (0/9, against DC's 3/9 and D's 2/9).
   - Transfer could not be measured.
   - Adaptation from real corrections moved in the right direction on 4 families.
   - Decision: `PHASE_2_NO_GO_AS_SPECIFIED`.

6. **Decision-record benchmark, Phase 0 (2026-10-23, branch `experiment/decision-record-benchmark`,
   not merged).** The learner was given perfect concepts: synthetic latent facts and oracle
   checks. A model pretrained on synthetic non-telecom decisions and adapted per organization
   stayed safe, but escalated more than the fixed concept rule.
   - Adaptation was not monotone.
   - Synthetic pretraining made retail adaptation worse.
   - The negative controls behaved.
   - The internal gate failed, so the sealed telecom set was never opened. Decision:
     `STOP_MECHANISM_FAILED`.

7. **Decision-record benchmark v2 (2026-10-23, same branch, not merged).** Only the decision
   procedure changed: family-level certified thresholds, comparison at matched safety, and
   bounded local adaptation. Evaluated once on a fresh holdout.
   - Every model was certifiably safe (0/96 failing families).
   - The shared pretrained-then-adapted model escalated more than the fixed concept rule (163/255
     against 149/255). Its anchored updates never earned a promotion.
   - Decision: `STOP_LEARNED_ORG_MODEL_PATH`.

8. **Policy induction, Phase A (2026-10-25, branch `experiment/policy-induction`, not merged).**
   The benchmark run backwards: the learner starts from a policy that is missing a clause, or
   that lacks an unwritten organization rule, and must recover it from decisions. The data is
   789 counterfactual families built from τ² retail and labelled by the unchanged oracle. A
   symbolic rule learner with a significance gate was used ($0).
   - It invented rules from shuffled labels in 0.26% of runs.
   - It recovered every removed written clause from 5 examples.
   - It recovered 3 of 6 unwritten rules within 10 examples; the bar was 4.
   - Learned relaxations were unsafe without certification.
   - With only the gate's own asks plus 10% audits, no missing escalation rule was ever
     learned.
   - Decision: `BENCHMARK_TOO_HARD`; Phase B (LLM arms) not proposed as frozen.

9. **Policy induction robustness pack (2026-10-25, same branch, not merged).** $0.
   - **Replication:** Phase A replicated on a fresh seed (13 of 13 worlds within one step).
   - **Random rules:** 96 of 114 recovered within 20 examples. Rules over one fact were easy;
     narrow ones (one action, or two conditions) and relaxations needed more.
   - **Audits:** recovering missed escalations needed audits of 25–100% of allowed cases.
     Targeted audits needed half of random's rate or less in about half the cells.
   - **Exceptions:** certification made them safe (0 of 934 test families failing, against
     47% uncertified) but they rarely certified.
   - **Perception:** fact-extraction errors pass through about one to one.

10. **Docent's judge against the policy oracle (2026-10-25, branch `experiment/docent-vs-oracle`, not merged).**
    Transluce's open-source rubric judge (Docent SDK 0.1.88, default prompt and model) was run on
    the 73 real retail writes with the written policy as its rubric. Spend: about $0.50, bounded
    at $1.91.
    - It agreed with the oracle on 66 of 72 (kappa 0.85), and on 69 of 72 for run vs don't run.
    - It denied all 38 writes the oracle denies.
    - Provisional reading of the 7 disagreements: the judge was right in 3 (the later human
      review confirmed 2), including one oracle false allow. In that case the customer said to keep an item, and the oracle's
      confirmation matcher read the sentence as a yes.
    - The oracle's weak spot is reading the customer; the human audit should start there.

11. **Two judges with a veto on airline (2026-10-28, same branch).** 133 writes from gpt-4.1 and
    gpt-4.1-mini agents on τ² airline; an action runs only if Jev's P(policy ok) ≥ 0.5 and
    Docent's majority says ALLOW. Truth: blind Claude graders, a person's review of 14 cases, and
    the benchmark's answer key corrected with τ²-Bench-Verified's fixes. Spend $4.83.
    - The gate ran 22 and 24 writes in two Docent runs, 3 of each wrong by the graders (2 and 4
      by the adjudicated truth). On retail it had run 22, none breaking the policy; the oracle
      would have asked about 1.
    - Most wrong runs by the adjudicated truth (4 of 6, runs pooled) had a real yes from the
      customer resting on a price, a ranking, a balance or a rule the agent stated wrongly; the
      other 2 were a plan that booked the customer twice.
    - In 7 of the 40 tasks the agents acted on, τ²'s reference solution breaks the policy.
12. **Deterministic rules on airline (2026-10-28, same branch).** 16 rules over the pre-action
    snapshot. Spend $0.035 (Jev fact questions).
    - The rules blocked 64 writes and none the corrected benchmark says should run.
    - They caught none of the gate's wrong runs: Docent had already refused almost all of what
      they block (it would have run 1 and 2 of the 64; Jev stopped those).
13. **Claims check on airline (2026-10-28, same branch).** gpt-4.1-mini lists what the agent told
    the customer; a verifier recomputes each claim from the records. Spend $0.218.
    - It caught 2 of the gate's 3 misstatement cases (the $299 price and the "second cheapest"
      flight); it missed the "$340" upgrade quote, which it never extracted.
    - Rules + claims + Docent: 0 wrong runs of 33 by the adjudicated truth (runs pooled), at 62%
      of good writes sent back; 17 of 46 good writes flagged, 12 of them by a plan-scope mismatch.
14. **Claims check on retail, held out (2026-11-05, same branch).** The airline check on the 73
    retail writes it was not built on. Spend $0.083. Two post-hoc verifier fixes, both recorded.
    - 15 of 25 allowed writes flagged: 12 plan scope, 2 superseded statements, 1 real catch.
    - The real catch is the oracle's Gaming Mouse bug, which Docent and Jev had also refused.
15. **Model-drafted rules (2026-11-05, same branch).** Models given the policy, schema and tool
    definitions wrote the deterministic rules; drafts ran unedited in a subprocess. Spend $0.28.
    - Claude Sonnet 5.5: 125 of 133 agreement with the hand-written rules, 14 of 16 rules
      covered, 4 false blocks of 46, all from one rule; it added a seat check.
    - gpt-4.1: one route rule caused 26 of 27 false blocks; gpt-4.1-mini sent back 44 of 46 good writes.
16. **Plan-level claims (2026-11-05, same branch).** Re-verify each claim against the other calls
    of the conversation. $0.
    - The preregistered rules cut false flags (airline 17 to 11, retail 15 to 10) but let the
      Gaming Mouse through.
    - A union-only rule, post hoc, keeps every catch: airline 17 to 13, retail 15 to 12.
17. **Airline hold-out (2026-11-05, same branch).** A second capture of 122 writes on a new seed,
    with the rules, the Claude draft and the plan-aware claims check frozen before its data was
    seen. Spend $5.81.
    - Truth: blind graders, replaced by the person's answers on the 20 writes behind the numbers
      (18 reviewed, 2 carried over from first-capture rulings).
    - Gate: 10 of 51 runs wrong (20%; first capture 13%); rules + Docent 9 of 65 (14%; 9%).
    - Hand rules: no false block (0 of 36 good writes).
    - Rules + claims + Docent: 6 of 41 wrong (15%; first capture 0 of 33), half of good writes
      sent back. Against rules + Docent (14%), adding the claims check did not lower the
      wrong-run rate here; on the first capture it took it from 9% to 0%. Every miss was a yes resting on an agent misstatement the claims check did not
      catch: "second cheapest" never extracted, "the cheapest" on a flight change extracted but
      not rankable by the verifier, refund promises outside its claim kinds.
18. **Docent's judge on other providers (2026-11-05, same branch).** The same judge with Claude
    Sonnet 5.5 and Gemini 3.1 Pro on a seeded 80 of the first airline capture. Spend $9.35
    (Claude) and about $18 (Gemini, over four days of Google's daily request limit).
    - Claude ran 27 of 80 against 18 to 20 for the OpenAI model, with 2 of the 25 graded wrong
      (OpenAI 1 of 18, 4 of 20), and sent back 3 of 26 good writes (OpenAI 9 to 10).
    - Gemini was the strictest in its one run: 15 of 80 ran, 1 of 14 graded wrong, half the good
      writes sent back; that is within the OpenAI judge's run-to-run spread (18 to 20).
    - The rubric transfers across models; the allow threshold does not, and price tier does
      not explain the order: Claude and Gemini, priced alike, sit at opposite ends.

**Current conclusion.** On τ² data of this size, neither shared concepts nor learning shows
value over the fixed two-question baseline. The binding constraint there is the number of
distinct scenarios (16 families), not the number of trials. With perfect concepts on controlled
data, a shared learned organizational model (synthetic pretraining plus bounded adaptation) is
safe but does not beat a fixed concept rule, even at certified-matched safety (v2). That path
stops.

Learning an organization's rules from its decisions (policy induction, Phase A) works for
escalations given enough examples and audits. It is unsafe for relaxations unless they are
certified. A live gate cannot discover what it is missing without audits or outcome feedback.
Every result in items 1–9 rests on an unaudited oracle; items 10–18 audit it and add other truths.

**Next hypothesis (not approved).** Policy induction as a product mechanism, with:
- induced escalation rules proposed to a human;
- exceptions certified on untouched families before they go live;
- audits sized to the rarity of the cases the gate should catch.

Whether an LLM proposer beats the free symbolic and bag-of-words learners (Phase B) needs a new
preregistration and a budget. Real approval logs, with approver consistency measured first,
remain the decisive test.

**Current conclusion for a pre-action monitor (2026-11-09, items 11–18).** A judge that reads
the transcript passes an action whose consent rests on something the agent stated wrongly.
Checking the agent's claims against the records closed that gap on the capture it was built
on (rules + Docent 9% wrong, adding the claims check 0 of 33); on a held-out capture it did not
lower the wrong-run rate (14% and 15%, 9 of 65 and 6 of 41), because new misstatements were
phrased or placed in ways the claims check missed. Deterministic rules can be drafted by a
model, but need a test harness. The judge's allow threshold depends on its model. Write-up:
[Three questions before an AI agent acts](https://tessra.ai/blog/three-questions-before-an-ai-agent-acts).

## Index

| # | Experiment | Status | Question | Code / manifest | Dataset | Result | Decision | Report |
|---|---|---|---|---|---|---|---|---|
| 1 | Smoke run 1 (2026-10-21) | `diagnostic` `superseded` | Does the pipeline run, and do its labels mean what the gate needs? | `main` @ `1374043` (not recorded in the outputs) | 12 simulations, 11 writes, τ² trace labels | Pipeline works; task and trace labels disagree with the policy | Build an independent policy verdict | [README](2026-10-21-smoke/README.md) |
| 2 | Policy-verdict correction (2026-10-22) | `diagnostic` | How often do the trace match and the task outcome agree with the policy verdict? | `56a8d6a`..`4ac8cc5`; oracle `581044662966` | Smoke run 2: 12 simulations, 11 writes | 3 of 7 trace-matching writes should not have run | Adopt policy verdicts as ground truth (M6c) | [README](2026-10-22-policy-verdicts/README.md) |
| 3 | Judge and strategy comparison (2026-10-22) | `diagnostic` `superseded` | Which judge and strategy gates best? | `f08438d` | Smoke run 2: 5 held-out writes | Claims gate blocked: too few writes | No conclusion; run a targeted capture | [README](2026-10-22-judge-strategy-comparison/README.md) |
| 4 | Targeted shadow experiment (2026-10-22) | `diagnostic` `superseded` | Do E or F cut escalations ≥ 10% relative to D at no worse safety? | `29b5af7`; definition `21bd1721…` | Stage 1: 57 simulations, 68 primary writes | Sample gates failed (9 held-out writes) | `INCONCLUSIVE`; stopped | [README](2026-10-22-targeted-shadow/README.md) |
| 5 | Decision-model pilot v1 (2026-10-23) | `directional` `no-go` | Do shared concepts (D vs DC) and learning (DC vs G1) add value, transfer and adapt safely? | `4f1cb9c`; definition `5b7069c2…`; tag `experiment/decision-model-pilot-v1` | 108 writes, 16 families; holdout 30 with a verdict | Safety equal (0/21); G1 saved 0/9 approvals; transfer unmeasured | `PHASE_2_NO_GO_AS_SPECIFIED` | [Decision-Model Pilot](2026-10-23-decision-model-pilot/Decision-Model%20Pilot.md) |
| 6 | Decision-record benchmark, Phase 0 (2026-10-23) | `diagnostic` `no-go` | With authoritative concepts, does a model pretrained on synthetic non-telecom decisions and adapted to an organization beat a fixed concept rule, transfer and adapt? | Branch `experiment/decision-record-benchmark`; freeze `17f09a53…` at `f411777`; telecom seal `ff645fd7…` | 375 synthetic records (5 domains, 3 profiles), 72 retail records; 35 telecom records sealed and never opened | Safe (0/69 false allows against DC's 17/69), but more over-escalations (37/66 against 17/66); adaptation not monotone; pretraining hurt retail (0/5 against 5/5) | `STOP_MECHANISM_FAILED`; telecom not opened; no semantic scoring | [Report](2026-10-23-decision-record-benchmark/Decision-Record%20Benchmark%20Phase%200.md) · [RFC](2026-10-23-decision-record-benchmark/RFC.md) |
| 7 | Decision-record benchmark v2 (2026-10-23) | `diagnostic` `no-go` | At certified-matched safety, with bounded local adaptation, does the shared learned organizational model beat the fixed concept rule and the target-only learner? | Branch `experiment/decision-record-benchmark`; freeze `59b4796c…` at `0235f55`; fresh holdout seed 1504999788 | v1 development pool (210 records); 2 calibration pools (64 families); fresh holdout 950 records (96 gate families, 3 P3 pools); retail rotation (development-grade) | Every model safe (0/96 failing families, UCB 0.031); G-combined = G-synthetic (no promotion), 163/255 over-escalations against DC-score's 149/255; G-target 141/255 | `STOP_LEARNED_ORG_MODEL_PATH`; telecom not opened | [Report](2026-10-23-decision-record-benchmark-v2/Decision-Record%20Benchmark%20v2.md) · [RFC](2026-10-23-decision-record-benchmark-v2/RFC-v2.md) |
| 8 | Policy induction, Phase A (2026-10-25) | `diagnostic` | Can a learner recover an organization's written or unwritten rules from its decisions, inventing none and staying safe? | Branch `experiment/policy-induction`; RFC `2deb66a`; cases `babbb5fb…` at `444237c` | 789 families, 7,784 counterfactual τ² retail cases (oracle-labelled); 13 worlds (6 removed clauses, 7 hidden rules) | Shuffled control 0.26% any-rule; clauses recovered at k = 5; hidden rules 3/6 at k ≤ 10; relaxations unsafe uncertified; no escalation learned under ask-plus-10%-audit selection | `BENCHMARK_TOO_HARD`; Phase B not proposed; $0 | [Report](2026-10-25-policy-induction/Policy%20Induction%20Phase%20A.md) · [RFC](2026-10-25-policy-induction/RFC.md) |
| 9 | Policy induction robustness pack (2026-10-25) | `diagnostic` | Do Phase A's findings hold on a fresh seed, across random rules, with priced audits, certified exceptions and noisy perception? | Branch `experiment/policy-induction`; RFC `87b8736`; cases `ac018a82…` at `c618a3d` | 789 families on fresh seed 20261026; 94 + 20 random rules | R1 pass (13/13); R2 96/114 within 20; R3 pass (targeted ≤ half in 60/119); R4 pass (0/934 certified, 47% uncertified); R5 errors pass through about 1:1 | Supports the design rules (targeted audits; certified, human-approved relaxations); next: real data | [Report](2026-10-25-policy-induction/Policy%20Induction%20Robustness.md) · [RFC](2026-10-25-policy-induction/RFC-robustness.md) · [Data sources](2026-10-25-policy-induction/data-sources.md) |
| 10 | Docent's judge vs the policy oracle (2026-10-25) | `diagnostic` | How often does an LLM rubric judge (Transluce Docent) agree with the deterministic oracle on real writes, and who is right when they differ? | Branch `experiment/docent-vs-oracle`; preregistration `a942fb9`; Docent SDK 0.1.88 | 73 real retail writes (oracle: 25 ALLOW, 9 ASK, 38 DENY, 1 UNKNOWN) | 66/72 agree (kappa 0.85); 69/72 run vs don't run; 38/38 denials matched; 7 disagreements, judge right in 3 on a provisional reading, 2 confirmed by the human review (one oracle false allow) | Audit the oracle's confirmation verdicts first; disagreements are a high-yield review queue | [Report](2026-10-25-docent-vs-oracle/Report.md) · [Preregistration](2026-10-25-docent-vs-oracle/README.md) |
| 11 | Two judges with a veto, airline (2026-10-28) | `diagnostic` | Does the retail veto gate (Jev + Docent) keep its precision on τ² airline? | Branch `experiment/docent-vs-oracle`; preregistration `9093137` | 133 airline writes (gpt-4.1, gpt-4.1-mini agents); blind Claude graders, a person's review of 14, corrected benchmark | Gate ran 22 / 24, wrong 3 / 3 by the graders, 2 / 4 adjudicated (retail: 22 ran, none against the policy); most adjudicated wrong runs rest on agent misstatements the customer agreed to | A transcript judge cannot see a misstatement; ground the check in the records | [Report](2026-10-28-airline-veto/Report.md) · [Preregistration](2026-10-28-airline-veto/README.md) |
| 12 | Deterministic rules, airline (2026-10-28) | `diagnostic` | Do 16 policy rules over the pre-action state catch what the gate missed? | Branch `experiment/docent-vs-oracle`; preregistration `6506258` | Same 133 writes | 64 blocks, none on a write the corrected benchmark says should run (1 disputed by the adjudicated truth); none of the gate's wrong runs caught | Keep rules for audit and certainty, not for recall | [Report](2026-10-28-airline-rules/Report.md) · [Preregistration](2026-10-28-airline-rules/README.md) |
| 13 | Claims check, airline (2026-10-28) | `diagnostic` | Does recomputing what the agent told the customer catch the misstatement cases? | Branch `experiment/docent-vs-oracle`; preregistration `83637ca` | Same 133 writes; gpt-4.1-mini extraction | 2 of the gate's 3 misstatement cases caught; rules + claims + Docent 0 of 33 wrong (adjudicated), 62% of good writes sent back | Test on held-out data (items 14, 17) | [Report](2026-10-28-claims-check/Report.md) · [Preregistration](2026-10-28-claims-check/README.md) |
| 14 | Claims check, retail held out (2026-11-05) | `diagnostic` | Does the airline claims check transfer to data it was not built on? | Branch `experiment/docent-vs-oracle`; preregistration `6b463fb` | 73 retail writes; oracle truth | Verifier transfers; 15 of 25 allowed writes flagged (12 plan scope, 2 superseded, 1 real: the oracle's Gaming Mouse bug) | Plan-level checking (item 16) | [Report](2026-11-05-claims-check-retail/Report.md) · [Preregistration](2026-11-05-claims-check-retail/README.md) |
| 15 | Model-drafted rules (2026-11-05) | `diagnostic` | Can a model write the deterministic rules from the policy, schema and tools? | Branch `experiment/docent-vs-oracle`; preregistration `0290cbe` | 133 airline writes; five drafts (gpt-4.1 ×2, gpt-4.1-mini, Claude Sonnet 5.5 ×2) | Claude: 125 of 133 agreement, 14 of 16 rules, 4 of 46 false blocks from one rule; gpt-4.1 27 of 46; mini 44 of 46 | Drafting works; ship it behind a test harness | [Report](2026-11-05-model-drafted-rules/Report.md) · [Preregistration](2026-11-05-model-drafted-rules/README.md) |
| 16 | Plan-level claims (2026-11-05) | `diagnostic` | Do plan-level rules cut the claims check's false flags without losing its catches? | Branch `experiment/docent-vs-oracle`; preregistration `f9c842e` | Recorded extractions of items 13 and 14 | Preregistered rules: airline 17 → 11, retail 15 → 10, but the Gaming Mouse is lost; union-only (post hoc): 17 → 13, 15 → 12, every catch kept | Extractor must say which call a statement is about | [Report](2026-11-05-plan-level-claims/Report.md) · [Preregistration](2026-11-05-plan-level-claims/README.md) |
| 17 | Airline hold-out (2026-11-05) | `diagnostic` | Do the rules, the drafted rules and the claims check hold on a capture none of them was built on? | Branch `experiment/docent-vs-oracle`; preregistration `26adee7` | 122 new airline writes (seed 301); blind Claude graders with the person's answers on 20 (18 reviewed), corrected benchmark | Gate 10 of 51 wrong (20%); rules + Docent 9 of 65 (14%); hand rules 0 false blocks; full stack 6 of 41 wrong (15%; first capture 0 of 33): the claims check did not lower the rate on held-out data | The design holds; the stack's zero does not: the claims check misses misstatements phrased in new ways | [Report](2026-11-05-airline-holdout/Report.md) · [Preregistration](2026-11-05-airline-holdout/README.md) |
| 18 | Docent's judge on other providers (2026-11-05) | `diagnostic` | Is the judge's behaviour a property of the rubric or of its model? | Branch `experiment/docent-vs-oracle`; preregistration `2f72f52` | Seeded 80 of item 11's writes | Claude ran 27 vs OpenAI 18–20 with a similar wrong-run rate, a third as many good writes sent back; Gemini strictest in its one run (15), within the OpenAI judge's run-to-run spread | Measure a judge's operating point per model | [Report](2026-11-05-judges-other-providers/Report.md) · [Preregistration](2026-11-05-judges-other-providers/README.md) |
