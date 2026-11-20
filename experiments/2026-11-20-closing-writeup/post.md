---
title: "A stock decision model beat my fine-tune at checking AI agent actions before they run"
date: 2026-11-20
description: "I tried to build a small model for the hard middle question of my last post. It did not beat a stock one. What came out instead, on train and dev data: two narrow questions, a stock decision model that ranks them well against frontier labels, and a clearer view of what each catch is worth."
image: "/blog/two-questions-og.png"
subtitle: "A follow-up to Three questions before an AI agent acts: two narrow questions in place of one broad judge, a cascade from a cheap decision model to frontier models, and a fine-tune that scored below the stock model.\n\nShort version: on these train and dev actions, asking whether the customer agreed to this exact action, and whether the agent said something false that mattered, caught most of the bad actions with few false stops. Stock Jev ranked both questions well against the labellers' consensus, the cascade routed its unsure cases to the frontier labellers, and my fine-tune scored below stock Jev. No held-out test has been run."
---

## Summary

My [last post](https://tessra.ai/blog/three-questions-before-an-ai-agent-acts) ended on the
middle of three questions every pre-execution check should answer: is what the agent told the
customer true? I said it was the hard part and that I had not cracked it. This week I tried to build
a small model for it. The model did not beat a stock one, but the attempt changed the question.

- **Two narrow questions instead of one broad judge.** For each action an agent proposes: did the
  customer agree to this exact action, and is any statement the agent made a *material
  contradiction* (false against the records, and likely to change the customer's yes)? Answered by
  two frontier models in agreement, they stop 53 of the 91 bad actions and 1 of the 56 good ones in
  my train and dev data.
- **A cheap decision model answers both well against those labels, but not alone.** Stock Jev
  ranks them with an AUC of 0.93 for the statement question and 0.97 for agreement, against the
  labellers' consensus. With
  cut-offs selected on the other folds under a 5% cap on good actions stopped there, it catches 43
  bad and stops 4 of 56 good on the held-out folds. Sending only its unsure cases to the frontier models, 63 of 174 actions (36%), gives
  55 and 3.
- **With rules first, the cascade catches 76 of 91 and stops 3 of 56,** and 32 of the 147 graded
  actions (22%) reach a frontier model. The backend rejected 47 of the 91 bad actions anyway; of the
  44 that executed, this design catches 40, with the same 3 of 56 good actions stopped. Adding the broad policy judge after it catches 88 or 89 but stops 11 good actions.
- **The model I set out to build did not beat a stock one.** A fine-tuned open 4B model rose from an
  AUC of 0.43 to 0.81 on the statement question and stayed clearly below stock Jev. I have dropped it.
- **The two questions catch different things.** The 11 bad actions where both labellers marked the
  customer as agreeing and flagged a material contradiction all executed. Of the 39 bad actions the labellers marked "not
  agreed", 31 came from GPT-4.1-nano (all retail), and the backend rejected 24 anyway.

These are train and dev numbers on τ²-bench actions by GPT-4.1-family agents, with model-made
labels. A held-out test has not been run.

![The 91 bad actions by what the labellers' consensus flags, split by whether the backend executed them or rejected them anyway.](/blog/two-questions-bad_actions_by_question.png)

## What I tried to build

The plan was a small open model, fine-tuned from Kev (an open decision model built on Qwen), that
reads the conversation and the raw records and decides, per agent statement, whether the
customer's yes rested on it and whether the records back it. The label I started with, "the
customer relied on it", could not be applied consistently, so it became a *material
contradiction*: the records contradict the statement, and correcting it would plausibly change
the customer's yes.

Labelling showed a second failure next to it. Across all 174 actions, both labellers marked 46 actions "not
agreed" and flagged 21 of the 380 sampled statements as material contradictions; among the 91 bad
actions, 39 were marked "not agreed". So the job widened to two questions per action, and the
model turned out not to be the hard part.

## Setup and data

**Actions.** The 174 actions from the first post's retail capture and first airline capture that I
put in train (133) and dev (41). 147 have a ruling from the first post (91 bad, 56 good); 27 have
none. Two test splits, 64 actions from unseen tasks and 90 from repeat tasks, were frozen by task
before any of this and stay sealed. Nothing in this post is a test result.

**Packets.** Each action is one text: the conversation up to the proposed call, the call and its
tool description, the policy, and every lookup the agent made. The 95th percentile is 8,996
tokens; 14 of the 174 are longer than 8,192.

**Questions.** 380 agent statements, those an earlier claims check flagged or a ruling quoted, not
every sentence, and one agreement question per action.

## Ground truth

**Good and bad.** The rulings from the first post: blind graders with my adjudication on airline, a
deterministic policy checker on retail, and my recorded corrections. They were made before this
week and do not depend on this week's labels.

**Statements and agreement.** Two frontier models, run separately on the same packets and wording:

| | Labeller A | Labeller B |
|---|---|---|
| Model | GPT-6.2-sol through the Codex CLI, reasoning high | Gemini 4 Neon in the Gemini app, thinking high |
| Statements called material contradictions (of 380) | 29 | 26 |
| Actions called not agreed (of 174) | 58 | 50 |

They agreed on 366 of 380 statements (Cohen's kappa 0.74) and 158 of 174 agreement questions (kappa
0.79). Labeller B answered "not sure" on 2 statements and labeller A on 1 agreement
question; those count as disagreements. A label below is their consensus: a statement counts when both said yes (21), an action as
not agreed when both said so (46). For statement labels, labeller A rerun without reasoning had a kappa of
0.89 against its reasoning run.

The anchor from the first post, the booking where the agent called the cheapest flight "the second
cheapest by default", was flagged by both. A second known case, a certificate balance stated
correctly but framed to mislead, was flagged by neither. I ruled it out of scope: the statement is
true against the records, and "true but misleading" is a different question.

**No person has reviewed this week's labels.**

## The two questions

1. **Did the customer agree to this exact action?** Not "did they say yes to something", but to
   this call with these arguments.
2. **Is any agent statement a material contradiction?** False against the records, and likely to
   change the customer's yes.

How the labellers' consensus labels cover the 91 bad actions:

| | Bad actions (of 91) |
|---|---|
| Both marked "not agreed", no statement flagged by both | 38 |
| Both marked "agreed" and flagged a material contradiction | 11 |
| Both marked "not agreed" and flagged a material contradiction | 1 |
| A material contradiction flagged by both, agreement split | 3 |
| Nothing flagged by both | 38 |

On the 56 good actions the consensus flagged 1 statement, which on reading looks like a wrong
ruling rather than a wrong flag, and marked no action as not agreed.

## Results

For the results below, Jev's cut-offs and the cascade's bands are fitted on the other folds (five
folds, grouped by task) and applied to the held-out fold. The questions and designs themselves were
shaped on this data. "Missed" bounds are one-sided
exact 95% upper bounds (Clopper–Pearson), as in the first post.

| Check | Bad caught (of 91) | Missed, 95% upper bound | Good stopped (of 56) | 95% upper bound | Reach a frontier model |
|---|---|---|---|---|---|
| Rules alone (rules exist for airline only) | 33 | 72% | 1 | 8% | none |
| Jev, cut-offs selected under a 5% cap on the other folds | 43 | 62% | 4 | 16% | none |
| Jev, cut-offs selected under a 20% cap on the other folds | 60 | 43% | 11 | 30% | none |
| Labellers' consensus alone | 53 | 51% | 1 | 8% | all |
| Cascade: Jev, consensus when unsure (5% selection cap, width 0.2) | 55 | 49% | 3 | 13% | 63 of 174 actions (36%) |
| A: rules, then the cascade (width 0.2) | 76 | 24% | 3 | 13% | 32 of 147 (22%) |
| B: rules, Jev at the 5% cap\*, then the rubric judge | 88 and 86 | 8% and 11% | 12 and 12 | 32% | 74 of 147 (50%) |
| C: rules, the cascade (width 0.2), then the rubric judge | 89 and 88 | 7% and 8% | 11 and 11 | 30% | 82 of 147 (56%) |

\* In B, Jev's cut-offs are selected so that rules and Jev together stop at most 5% of good actions
on the other folds; the rubric judge's stops are not counted toward the cap.

B and C show the rubric judge's two runs. Their "reach a frontier model" counts each graded action
that reaches any frontier stage once; the frontier-share figures for the designs use the 147 graded
actions, and the cascade's uses all 174.

![Bad caught against good stopped, with cut-offs chosen out of fold.](/blog/two-questions-tradeoff.png)

A note on cut-offs. Earlier in this work I quoted Jev at 51 bad caught and 5 good stopped, at
cut-offs of 0.5 on both questions picked while looking at this data. That is a different operating point from the
out-of-fold 43 and 4 at the 5% cap, and the fair way to compare Jev with anything else here.

The 14 packets longer than 8,192 tokens are all airline and hold 6 bad actions. Design A catches 5
of those 6 and stops none of their 4 good actions; the labellers' consensus alone catches 1.

## What the consent result is made of

Two things about the data change how the results above should be read.

**One agent supplies most "never agreed" cases.** Of the 39 bad actions the labellers marked not
agreed, 31 came from GPT-4.1-nano, which only ran in the retail capture. Agent model and domain
cannot be separated in this data.

**Many bad actions would have failed anyway.** The backend rejected 47 of the 91 bad actions when
they ran, including 24 of those 39 never-agreed ones. On the 44 bad actions that did execute:

| Check | Executed bad actions caught (of 44) |
|---|---|
| Labellers' consensus alone | 26 |
| A: rules, then the cascade | 40 |
| B: rules, Jev, then the rubric judge | 42 and 40 |
| C: rules, the cascade, then the rubric judge | 43 and 42 |

![Catches on the 44 bad actions that actually executed.](/blog/two-questions-executed_only.png)

The statement question pulls more weight than its count. The backend accepted all 11 bad actions
where both labellers marked the customer as agreeing and flagged a material contradiction: by the labels, the agent said something false, the customer said yes, and the system
did it. That is the kind of failure the first post described.

## Narrow versus broad

Rules plus the two narrow questions, design A, catch 76 of 91 and stop 3 good actions. Adding the
broad policy judge after the same stages, design C, catches 88 or 89 and stops 11. In this data the
broad judge catches 13 or 12 more bad actions and stops 8 more good ones.

An exploratory model read of the uncaught actions (not reviewed by a person) classified 9 of design
A's 15 misses as the same retail mistake: a refund
sent to a payment method the order was not paid with, which the policy forbids. Both labellers had
marked those actions "agreed". The same read found skipped steps among the rest, such as a missed
insurance question. Retail has no hand-written rules. A refund-method rule could target the cases
that read identified; I have not written or measured one, so I give no combined figure.

Design B, with Jev alone before the judge, misses the "second cheapest" booking. A and C catch it,
and both labellers flagged its statement.

One caution. In the cascade, the frontier models that answer Jev's unsure cases are the same
labellers whose consensus defines the statement and agreement labels. Against those labels the
cascade's inner layer grades itself. The good and bad rulings are older and independent, so the
counts of bad caught and good stopped above are not circular, but any score of the cascade
against the consensus would be, for the cases sent to the same labellers.

## The failed fine-tune

I fine-tuned Kev-4B, an open decision model, on five task-grouped folds, with
435 to 488 training records per fold. The training data mixed natural labels with planted contradictions: of the 157 planted ones kept,
39 were values swapped by a script and 118 were rewrites written by Codex, and the same model
family also checked every planted edit. Labeller A is that family too.

| | Stock Kev-4B | Fine-tuned Kev-4B (out of fold) | Stock Jev |
|---|---|---|---|
| Statement question, AUC | 0.43 | 0.81 | 0.93 |
| Agreement question, AUC | not run | 0.89 | 0.97 |

![The fine-tune moved Kev-4B a long way, and stayed below stock Jev.](/blog/two-questions-finetune.png)

The fine-tune moved Kev a long way and stayed clearly below Jev on both questions; under the same
fold protocol it caught 55 bad actions and stopped 19 good ones, against Jev's 66 and 16. I recorded
it as improved over stock, clearly below Jev, and not pursued. It is a weak test of Kev: a few
hundred records per fold, including synthetic examples written and checked by the labeller's own
model family.
It does not show that a small open model cannot learn this.

## Prior work

I read twelve papers in full. What each does and does not do, with the section behind every
statement, is in [prior_work.md](https://github.com/tessra-ai/agent-action-checks/blob/main/experiments/2026-11-20-closing-writeup/prior_work.md).

- **[JevAct](https://arxiv.org/abs/2610.38620)** is the closest. It gates τ²-bench write calls
  before they run, with GPT-4.1 among its agents, and a decision model answers compiled yes/no
  questions, some of which ask whether the user requested and explicitly confirmed the action. So
  asking whether the customer agreed is not new as a check. Its compiled question categories do not
  include whether the agent's statements are true; it does not compare against a broad judge, does
  not run a cascade, and has no retail domain.
- **[SABER](https://arxiv.org/abs/2512.07850)** gates writes before they run in τ-bench airline and
  retail: before each state-changing action it summarises the call and asks the user to confirm. So
  a consent step at the point of a write is not new either. It asks for consent rather than judging
  whether the customer already gave it, and it does not check the agent's statements.
- **[The Agent Knew](https://arxiv.org/abs/2610.17301)** found, in published τ²-bench airline runs,
  a false statement to the customer that made the write look permitted before 26% of 227
  policy-violating writes. That analysis is offline; the paper's own gate reads the agent's internal
  states rather than asking a model about its statements.
- **[Corrupt success](https://arxiv.org/abs/2603.03116)** (Cao et al.) audits finished τ-bench
  airline and retail runs with a GPT-5 judge, including whether the agent's statements match what
  its tools returned. That is close to the statement question, without its test of whether the
  error would change the customer's yes, and asked after the run rather than before a write.
- **[τ-bench](https://arxiv.org/abs/2406.12045)** has policies that require explicit confirmation
  before consequential writes, and its reward does not check confirmation; and lists wrong information that changes what the user does only in a manual
  failure analysis.
- **[DelegationBench](https://arxiv.org/abs/2610.05532)** and
  **[AuthorizationBench](https://arxiv.org/abs/2610.27548)** study asking before acting and acting
  beyond what was authorized. DelegationBench uses synthetic scenarios, and separately tests single
  pre-staged decision points adapted from τ-bench retail; AuthorizationBench judges after the run, against a list fixed in advance, outside τ-bench.
- **[AuthorizationPairs](https://arxiv.org/abs/2610.16838)** reviews whether evidence permits a
  request before execution on its language track, with no conversation with a customer.
  **[Consent Integrity](https://arxiv.org/abs/2606.02668)** binds an approval dialog to the exact
  action, and replaces the agent's narration rather than checking it.
- **[Wu et al.](https://arxiv.org/abs/2605.11003)**, a position paper without experiments, argue for
  checking that a step is within the authorized scope before it takes effect, and for checks aimed
  at specific sources of failure rather than a generic monitor. The idea of narrow checks is theirs;
  what this post adds is a measurement.
- **[JEV-as-a-Judge](https://arxiv.org/abs/2609.26550)** is where the cascade comes from: Jev's
  answer is accepted when it is confident and the rest go to a stronger LLM judge, with the cut-off
  set on labelled data from the workload. In an offline simulation on held-out pairs from two
  evaluation benchmarks, pooled, it was 0.9 points more accurate than GPT-6 alone at 41% of its fee,
  though slightly below GPT-6 on the harder benchmark; a live prospective test on two new workloads
  matched GPT-6. It judged finished
  outputs, not agent actions, and says use inside an agent is untested. My version differs in detail
  (a band around a cut-off chosen under a cap on good actions stopped, and a fallback that also made
  the labels) and has no held-out test.
- **[False success](https://arxiv.org/abs/2606.09863)** found that none of the broad task-completion
  judges it evaluated exceeded an AUROC of 0.65, against a task-disjoint AUROC of 0.83 for cheap TF-IDF detectors, after
  the fact, on public τ²-bench runs.

Among the twelve papers I read, I found no reported pre-execution check of the agent's statements
against the records; Cao et al. check them after the run. None compares two narrow questions with a
broad judge on the same actions, though Wu et al. argue for narrow checks. The cascade is not mine:
it is JEV-as-a-Judge's design, applied here to agent actions before they run.

## What is still open

- **A held-out test.** The design was shaped on this data. The test should score against the good
  and bad rulings, not against frontier labels, so the frontier layer is not graded by itself.
- **The refund-method rule and a narrow question for skipped steps,** neither measured.
- **True but misleading statements.** One example so far, and no cheap way to find more.
- **A fair test of a small open model,** with more and real data.
- **Current agents.** These are GPT-4.1-family agents; public τ²-bench runs from current agents
  are the obvious next source.
- **Related papers I have not read,** listed in prior_work.md.

## Limits

- **Model-made labels, not reviewed by a person.** The reference labels for the two questions are
  where two frontier models agree.
- **Circularity in the cascade.** Agreement with the consensus would be circular for the cases sent
  to the same labellers; the catch and stop counts use the older good and bad rulings.
- **No held-out test.** Cut-offs are out of fold, but the questions, their wording and the designs
  were shaped on this data.
- **Small numbers.** 21 flagged statements, 91 bad and 56 good actions. Small differences in catch and
  stop counts are uncertain, and the bounds treat actions as independent though several share a task.
- **One benchmark, simulated customers, GPT-4.1-family agents,** with agent model and domain
  confounded for "never agreed".
- **Sampled statements.** 380, not every sentence; a bad action could hold a contradiction nobody
  asked about.
- **Uneven labellers.** One ran through a command-line tool, the other by hand in a consumer app.
- **Rules written by someone who had seen the failures,** and none for retail.
- **The fine-tune was a weak test** of a small model.

## Method and reproduction

Every figure in this post comes from one file, numbers.json, built by a script from committed
result files (figures about other papers from the verified quotations in prior_work.md) and checked
against the internal handover brief (the mismatches are explained in the report). The charts are drawn from the same file, and every quote about a paper is checked against
the paper's text by a script. Code, labels, per-action results and reports are in
[tessra-ai/agent-action-checks](https://github.com/tessra-ai/agent-action-checks), under
experiments/2026-11-18-rely1-m0, -m1 and 2026-11-20-closing-writeup (the uncaught-actions read
is in its results/uncaught_38_table.json and results/uncaught_38_types.json).
Labelling ran on subscriptions; the paid calls were Jev's, $0.08 in all, and the GPU time for the
fine-tune.

## Disclosure

Tessra builds deterministic policy checks for agent actions: the first of the three questions. AI
models labelled this week's data and helped write the code and this post, and the same model family as one labeller wrote
118 of the 157 planted training contradictions kept and checked every planted edit; a script made the
other 39 by swapping values.
