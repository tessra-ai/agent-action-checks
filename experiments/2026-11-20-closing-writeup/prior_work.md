# Prior work: twelve papers, read in full

Papers 1–8 read 2026-11-20 and papers 9–12 read on 2026-11-20 after M4, from the full arXiv PDFs, converted to text. Every statement below points to the
section that supports it, with a short quote in quotation marks. Every quote was checked
mechanically against the paper's text. Statements that could not be pointed to were cut.
Statements of the form *does not* rest on the paper's own scope, method or limitations section,
quoted. Where they rest only on a search finding no mention, that is said. The **Relation to this
work** lines are my reading, marked as such.

*This work* means: pre-execution checks of τ²-bench airline and retail write actions by GPT-4.1
agents, using two narrow questions. The first asks whether the customer agreed to this exact action.
The second asks whether any agent statement is a material contradiction. A cheap decision model
(Jev) answers them, with frontier models only when it is unsure. The comparison is with
hand-written rules and a broad rubric judge.

---

## 1. JevAct: "Think Before You Act: Decision Gate for LLM Agents"

Shoham, David, Akrabi, Bilgory, Levy, Marreed, Zeltyn, Shlomov (IBM). arXiv 2610.38620v1, 28 Oct 2026.

**Status: read in full.**

**What it does**
- A gate between the agent proposing an action and running it. A flagged action is discarded and
  the agent revises. (Abstract: "intercepts selected agent actions before execution"; §3.2: "flagged
  message is discarded: it is never executed and never stored.")
- An LLM compiles each domain policy offline into yes/no questions per write tool, a Boolean
  allow-rule, and code that computes facts from tool records. (§3.1: "Offline, an LLM turns each
  domain’s policy into yes/no"; §4.3: Claude Opus 4.6 compiles the checks.)
- Code checks facts held in tool records; the decision model answers questions about the
  conversation. (§3.4: "Kev answers focused questions that require interpreting the conversation,
  such as whether the user")
- Some compiled questions ask whether the user requested and explicitly confirmed the action. (App.
  A.1: "Did the user actually request to cancel this reservation (not just inquire about it)?"; "Did
  the agent list the cancellation details and did the user explicitly confirm (say yes)")
- The judge is Kev, an open "Jev-like" decision model, fine-tuned from Qwen3.8-27B. It returns
  option probabilities. In the write gate, a question counts as answered no only when Kev is
  confident; the gate can also flag a call on its code checks alone. (§1: "Kev (an open sourced Jev-like"; §3.4: "Kev-27B, a fine-tune of Qwen3.8-27B"; §3.5: "P (yes) ≤ 0.05")
- Evaluated on τ²-bench airline and telecom and on BFCL, across eleven agent models including GPT-4.1.
  The τ²-bench runs use a GPT-4.1 user simulator. (Abstract; §4.1: "We use two domains. Airline (50 tasks)"; "The user
  simulator is GPT-4.1")
- GPT-4.1 on airline: pass@3 rises from 66.0% to 82.0%. (§5: "GPT-4.1’s pass@3 rises from 66.0% to
  82.0%")

**What it does not do**
- No retail domain: the τ²-bench domains are airline and telecom (§4.1).
- No check of whether the agent's statements to the user are true. The compile prompt's question
  categories are policy conditions, argument correctness, whether the action is wanted, and prior
  steps (App. A.1). The code checks the call's arguments against records (§3.3: "returns any
  violations those records establish"). The paper has no sentence excluding statement checks; this
  rests on those enumerated categories.
- Some wrong calls pass its questions. On 260 labelled development write calls, 42 of the 101
  incorrect calls "break no compiled question, because the questions encode the policy rather than
  the user’s request." (§6) These are separate from the request and confirmation questions listed
  above, which it does compile.
- No broad-judge comparison: alternative judges answer the same compiled questions. (Table 4
  caption: "different judges answering its compiled questions")
- No cascade: one judge, Kev-27B, "used as is, for every agent LLM and benchmark." (§4.3) Its related
  work cites a separate preprint, "Jev-as-a-judge: Accept when confident, escalate when unsure",
  now read in full (§9 below).
- Its headline comparisons do not isolate the judge's contribution: "these comparisons evaluate the
  full harness, not the judge in isolation" (§1). Its ablation does separate them, in one trial with
  a GPT-4.1 agent on airline: code checks alone reach 68.0% and Kev's questions alone 57.1%, from a
  50.0% base, against 72.0% for the full gate. (§5.1, Table 3)

**Relation to this work (my reading).** This is the closest prior work. It is a pre-execution gate
on τ²-bench write calls with GPT-4.1 agents, using a probability-returning decision model on typed
questions, some of which are a consent question. So the consent question is not new as a check.
What JevAct does not have is a statement-truth question, a broad-judge comparison, a cascade and
retail. Its own caveat, that the questions encode the policy rather than the user's request, is the
gap this work's agreement question addresses.

## 2. "The Agent Knew: Internal States Forecast Unauthorized Actions and Stop Them, and the Lies That Follow"

Fayyazi, Kamal, Pedram (USC). arXiv 2610.17301v1, 12 Oct 2026.

**Status: read in full.**

**What it does**
- Builds CAPE-Bench: paired tasks in two worlds that differ in one fact deciding whether an action
  is authorized. (§2: "in two worlds that differ in one fact, such as a policy line,")
- Forecasts a violation before the action is written, from a linear readout of the agent's own
  internal states, and gates on it. (App. I: "The frozen readout reaches AUROC 0.941 overall";
  §5: "Screen every action, not the first one.")
- Analyses published τ²-bench airline runs of frontier agents, GPT-4.1 among them. A policy oracle
  labels each write from the policy and database (App. N: "A policy oracle labels each write ALLOWED
  or NOT ALLOWED from the policy document and the database"). A judge flags "a false statement to
  the customer, made before the write, that makes the write look permitted." (App. N)
- Finds such a false statement before 26% of 227 policy-violating writes and before none of 667
  allowed writes. (§4.1: "before 26% of 227 policy-violating writes"). For GPT-4.1 the count is 14
  of 43 violating writes and 0 of 152 allowed ones. (App. N table)

**What it does not do**
- "Authorization" is a permission from a policy, owner or ticket, applied by a simulated approver. It
  is not the customer agreeing to an action. (§2; §3.4: "The approver is the environment’s approval
  channel,")
- The false-statement finding is an offline measurement on logged trajectories, not a gate. The gate
  reads internal states, which need open weights (§4). Its limitations note that "closed frontier agents enter only" through published τ²-bench trajectories. (§7)
- Its gate did not reduce violations in the τ²-bench tests it reports. In the end-to-end trial with an
  open agent (gpt-oss, airline), "the gate did not reduce them (episodes with a violation 0.142 vs
  0.150" (App. N). At replayed frontier decision points, gated gpt-oss and Gemma-4 did not reduce
  violations either: "the gate did not reduce violations (gpt-oss 0.42 vs 0.43" (App. N). Read from
  frontier transcripts, it separated violating from allowed writes only weakly: "within-tool AUROC
  0.59" (App. N). Its prevention test on knowing violations was not run: "No condition reached the
  preregistered 10% of informed violations" (App. N).
- No retail: the τ²-bench analysis is airline (§7; App. N).
- All tools in its own benchmark are mock: "All tools are mock tools." (App. C)

**Relation to this work (my reading).** This is the strongest prior evidence for this work's
*material contradiction* question: false pre-write statements accompany a quarter of
policy-violating writes in published τ²-bench airline runs. But it measures them offline and does
not ask a model, before the write, whether a statement is false. Its gate is a different mechanism
(internal states), and it did not reduce violations in the τ²-bench tests it reports.

## 3. τ-bench: "A Benchmark for Tool-Agent-User Interaction in Real-World Domains"

Yao, Shinn, Razavi, Narasimhan (Sierra). arXiv 2406.12045v1, 17 Jun 2024.

**Status: read in full.**

**What it does**
- A benchmark in which an LM-simulated user talks to a tool-using agent bound by a domain policy, in
  retail and airline. (Abstract: "a language agent provided with domain-specific API tools and policy
  guidelines.")
- Its policies require explicit confirmation before consequential writes. (App. B.1, retail: "Before
  taking consequential actions that update the database (cancel, modify,"; airline: "you must list
  the action details and obtain explicit user")
- Grades by comparing the final database with the goal state and checking required strings in the
  replies. (§3, Reward: "database is identical to the unique ground truth outcome database")
- Its manual failure analysis has a category where the agent gives the user wrong information that
  changes what the user does. (§5.2: "user with incorrect information that causes the user request to
  diverge")

**What it does not do**
- The reward does not check confirmation, as the authors note: the agent "might issue the return
  without explicit user confirmation, which violates the policy." (§3, Reward)
- It does not grade agent statements beyond required strings: in its worked example, the replies must
  contain two amounts, 54.04 and 41.64, "as substrings." (§3). Wrong information appears only in the
  manual analysis (§5.2).
- No judge: LM checks are a future direction. (§6: "LM checks that certain rules are followed")
- Not a pre-execution check: the reward is computed "Once the episode ends". (§3)
- This is τ-bench v1; τ²-bench is later work (a search of the text finds no mention).

**Relation to this work (my reading).** The benchmark states the consent rule but leaves it out of
its score, and it names wrong-information failures only in a manual analysis. This work turns both
into per-action checks.

## 4. Consent Integrity: "What You Approve Is What Executes: Consent Integrity for Black-Box LLM Agents"

Weng (Bournemouth University). arXiv 2606.02668v1, 1 Jun 2026.

**Status: read in full.**

**What it does**
- Targets coding agents' approval dialogs, where "the human approves a summary the agent writes."
  (Abstract)
- Defines Consent Integrity: the action shown to the human must "be rendered by a trusted mediator from the real action at the" moment of approval. The agent's narration is treated as "untrusted display data." (Abstract; §I)
- Binds approval to "the canonical hash of the exact action". (§VI)
- The prototype is a deterministic static analyzer "in approximately 500 lines of dependency-free
  Python". (§VIII)

**What it does not do**
- Not conversational consent: whether a human understands what they approve is "out of scope".
  (§I; §III: "Out of scope. Whether a human comprehends a faithfully")
- It does not judge whether the agent's narration is false; it replaces it (§I).
- No τ-bench (a search of the text finds no mention); it evaluates GTFOBins, tldr and a small
  controlled set (§IX).
- No model and no cascade (§VIII). Its only baseline is described as "intentionally weak" (§IX-B).
- Total mediation and the trusted path are "specified but assumed, not implemented." (Abstract)

**Relation to this work (my reading).** It shares the premise that the agent's account of an action
cannot be trusted at approval time. It solves this for shell actions by rendering from the real
action, not by asking whether a customer agreed or was misled.

## 5. AuthorizationPairs: "Same Operation, Different Permission: Evaluating Whether Guardrails Honor Authorization"

Jing, Chen, Hu, Liu, Shi, Xie, Li, Song (HKUST). arXiv 2610.16838v1, 12 Oct 2026.

**Status: read in full.**

**What it does**
- A benchmark of guardrail permission decisions. Its language track holds one operation fixed and
  varies the authorization evidence. (§1: "Its language track has fifty scenarios."; §3.1: a case is
  "(request, policy, evidence, effect, source).")
- On its language track, decisions are checked before execution: only an ALLOW "decision runs the
  operation in a local" sandbox (§3.4). Its other track does not execute: "The native-policy track runs
  no effects," and is scored against the policy engine's reference (§4.2).
- Evaluates eight guardrail configurations. (§1: "We evaluate eight guardrail configurations.")
- Counts false blocks of lawful requests as a cost. A second reviewer after Qwen3.5-27B removes one
  incorrect approval but "rejects 171 lawful requests". (§5.3)

**What it does not do**
- No user–agent dialogue: the input is a request, a policy and authorization evidence (§3.1). The
  task is permission review of a given operation, "not planning or tool choice." (§3.4)
- No τ-bench (a search of the text finds no mention).
- Not a narrow-versus-broad comparison: every reviewer answers the same permission question, and "we
  compare complete configurations" (§4.1).
- Its reviewer chains are all-must-allow and replayed from cache: "counterfactual selections of archived independent" responses. (App. F.1) A cheap-first chain saves output tokens "but loses 109"
  lawful approvals (App. F.1). It does not escalate on uncertainty.

**Relation to this work (my reading).** It is the nearest work on per-action, pre-execution
permission review that treats false blocks as a cost. Its question is whether evidence permits a
request, not whether a customer agreed in conversation or was misled.

## 6. DelegationBench: "Measuring When AI Agents Should Ask Before Acting"

Pochampally. arXiv 2610.05532v1, 4 Oct 2026.

**Status: read in full.**

**What it does**
- 156 short synthetic scenarios. A model chooses to act, ask permission, ask for information, or
  refuse. (§1: "we built DelegationBench, a set of 156 short scenarios.")
- Matched pairs vary one feature. One is scope: "whether the user asked for this action or for
  something narrower." (§3)
- The main study asks, before execution, whether a proposed action is authorized by the user's
  instruction. (App. B: "You evaluate whether a proposed action is sufficiently authorized by a
  user"; "Do not execute the action.")
- Adapts 17 decision points from τ-bench retail. Each is run with the user's confirmation present and
  absent. (§4: "points adapted from τ -bench retail tasks with executable tools."; App. N: "Each
  fixture is run with confirmation present and with it absent.") On these, the three models it tests
  "made every decision correctly". (§5.4)

**What it does not do**
- Uses τ-bench only as single pre-staged decision points: "This study tests a single decision point
  before execution. It does not measure full-task τ -bench success, realistic conversations". (App. N)
- Does not check whether agent statements are true. Any question counts as intervening; "we do not
  check whether the question itself is adequate." (App. N)
- Synthetic scenarios: "They are not drawn from real deployments". (Limitations)
- No cascade (a search of the text finds none); its comparisons are question formats and judging
  versus acting (§4).

**Relation to this work (my reading).** Its scope pairs and confirmation-present/absent points are
the closest prior test of *did the user ask for this action*. Its near-ceiling result with an
explicit rule fits this work's high agreement-question AUC. It does not test misleading statements
or a cascade, and it does not use real benchmark conversations end to end.

## 7. False success: "From Confident Closing to Silent Failure: Characterizing False Success in LLM Agents"

Advani (University of Colorado). arXiv 2606.09863v1, 1 Jun 2026; ICML 2026 workshop (FAGEN).

**Status: read in full.**

**What it does**
- Uses public τ²-bench leaderboard runs. (§3.1: "We obtain agent trajectories from the public tau2-bench")
- Agents are 8 recent frontier families. (§3.1: "We collect submissions from 8 model families")
  GPT-4.1 is not among them (Table 1).
- Defines false success as a closing message that claims a completed action the environment shows
  did not happen, labelled by regex. (§3.3; App. A: "applied to the closing message (final assistant
  turn) of each tau2-bench failure trajectory.")
- Broad post-hoc judges ask "Did the agent successfully complete the user’s task?" (App. D). None
  "exceeds AUROC 0.65" (§4.3). Cheap TF-IDF detectors reach "task-disjoint AUROC 0.83" (Abstract).

**What it does not do**
- Not pre-execution: it ranks finished trajectories for review (§4.4: "the system flags the top r% of
  trajectories").
- Checks only the agent's claim that its own action completed, not other statements against records.
  The author calls for "methods that verify trajectory-environment consistency" directly, rather than reading surface text. (§4.4)
- No consent question. Required confirmations appear only as one item inside a broad checklist prompt
  (App. D: "(4) Were any required confirmations obtained?").
- No cascade: a fixed-weight ensemble "improves AUROC from 0.834 to 0.855." (§4.4)

**Relation to this work (my reading).** It is the nearest result that broad *did it succeed* judges
lose to cheap specialised models, on a different question (completion claims) and after the fact.
Its corpus is the public τ²-bench runs that a check of current agents would use. Its related work
points to Cao et al. on "corrupt success" and to SABER's audit of τ-bench trajectories, both now
read in full (§11 and §10 below).

## 8. AuthorizationBench: "Act on Your Behalf, Beyond Your Authorization: Benchmarking LLM Agent Authorization Alignment"

Zhang, Li, Huang, Li (Northeastern, CMU, UNC-Chapel Hill). arXiv 2610.27548. The arXiv page gives a
citation date of 2026-10-20; the text read is v2, stamped 21 Oct 2026.

**Status: read in full.**

**What it does**
- Defines authorization alignment: whether an agent stays within the scope its principal granted,
  whether or not harm follows. (§2: "absent such enforcement and absent any adversary, do LLM agents
  themselves act within")
- Encodes each case as a contract with a list of out-of-authorization actions. (§3.1: "delegation
  boundary as an authorization contract A = (I, C, O).")
- 286 executable tasks from 44 documented real cases (§3.4), run in its own sandbox (§3.3).
- Agents act out of authorization in 19.2% of 6,864 trajectories, from 10.5% to 26.6% by setting
  (Finding 1). Of completed trajectories, 19.1% contain out-of-authorization behaviour (Finding 2).
- A post-hoc frontier judge (Claude Opus 5.5) checks for the listed actions. It agrees with a human
  on "97% of out-of-authorization labels" (§4.1).

**What it does not do**
- Not pre-execution. The authors place gating in prior work and "instead ask a complementary,
  behavioral" question (§2). The judge reads "the full trajectory" after the run (§4.1).
- Authorization is fixed in advance by the contract, not read from the conversation for each action
  (§3.1). A simulated principal acknowledges in-scope proposals and refuses out-of-scope ones
  (§3.3: "refuses proposed out-of-authorization actions"), but its answers do not change the
  contract. Whether the agent asked is measured as consultation (Finding 6).
- No misrepresentation check. Claims are checked against the record only for completion criteria (App.
  F.4: "Verify the claim against the").
- No τ-bench tasks: it uses its own mock services (§3.4: "informed by AgentDojo"). GPT-4.1 appears
  only in task construction (App. C.2, C.3).
- No cascade: the evaluation judge is a single frontier model (§4.1: "Claude Opus 5.5"). No
  broad-judge comparison; broader review is future work (§5: "Future work can conduct open-ended").

**Relation to this work (my reading).** It is the closest benchmark on acting beyond what the
principal authorized, the family this work's agreement question belongs to. It measures that after
the run, against a list fixed in advance, outside τ-bench.

## 9. JEV-as-a-Judge: "JEV-as-a-Judge: Accept When Confident, Escalate When Unsure"

Li, Miao, Krishnan, Padman (Carnegie Mellon). arXiv 2609.26550. The text read is v6, 29 Oct 2026
(v1 22 Sep 2026). JevAct v1 is dated 28 Oct, so it cites v5 or earlier; v5 (9 Oct) has the same
abstract and page count, and I compared its text with v6 by script but did not read it separately.
Appendix B says earlier editions used a smaller sample with a different headline figure.

**Status: read in full** (v6, main text and Appendices A–Q).

**What it does**
- Uses Jev as a judge of finished model outputs and routes on its confidence. (Abstract: "accepting
  confident verdicts and escalating the rest"; Limitations, under "Agentic tasks", describes the
  study as judging finished outputs.)
- Data: public evaluation benchmarks (RewardBench and JudgeBench preference pairs, HaluEval
  evidence-grounded factuality, final-answer adjudication), with follow-ups and a live test on two
  new workloads. (§3; §9)
- Confidence is the largest label probability. Below a threshold, the item "goes to a stronger
  judge, which judges it" independently (§8), here GPT-6 Astra and other fallbacks.
- The threshold is chosen on labelled items from the target workload: the most permissive one
  "whose accuracy loss stays within two points" of the fallback, or, in the recommended version,
  one whose one-sided 95% lower confidence bound on the cascade-minus-fallback accuracy difference
  is at least minus two points. (§8)
- Results: with a threshold frozen before evaluation, the cascade is "0.9 points more accurate than
  GPT-6 on 1,610 held-out pairs at 41% of its fee" (Abstract), escalating the "other 31.5%" of pairs
  (§8). That figure pools two benchmarks; on JudgeBench the cascade was below GPT-6 (Table 4), and
  the frozen policies are "offline simulations" (Table 3 caption). The prospective test ran live
  (§9). In the prospective test on two new workloads the
  cascade "matched GPT-6’s accuracy exactly while escalating 74%" of pairs. (§1)
- Where routing weakens: the signal is weaker on style-adversarial pairs and "fails on
  reference-free prose" (Conclusion). On evidence-grounded factuality, Jev is close to GPT-6 (§6).
- It cites earlier cascades of the same kind (§2, "Confidence and escalation"): FrugalGPT; Jung et
  al. (2025), "Closest to our setting"; and Xu et al. (2025), who route uncertain reward-model
  comparisons to a strong LLM judge.

**What it does not do**
- No agent actions: under "Agentic tasks" (Limitations) it says that whether Jev's decisions and
  confidence are as useful inside an agent is not tested.
- Short inputs: "the longest input in the study is about 3,600 tokens" (App. A).
- No band around a tuned cut-off: one threshold on the largest label probability, set for an
  accuracy tolerance, not for a cap on a particular kind of error (§8).
- One fallback judge, independent of the labels it is scored against; shared errors stay: "errors
  that both judges share cannot be fixed" (Limitations).

**Relation to this work (my reading).** This is the source of the cascade. Accepting Jev's answer
when it is confident and escalating the rest to stronger LLM judges, with the cut-off chosen on
labelled data from the workload, is published here, with a held-out and a prospective test that
this work does not have. What this work adds is narrow and empirical: the same idea applied to
pre-execution checks of agent write actions, which the paper leaves untested, with packets
whose 95th percentile (numbers.json) is more than twice that study's longest input. The
differences are of detail: a band of fixed width around a cut-off selected out of fold under a cap
on good actions stopped, and a fallback (two frontier labellers in agreement) that also made the
labels, so the frontier layer is partly graded by itself. Nothing in it contradicts the post's
results; its evidence-grounded results are consistent with the statement question working, since
that question gives Jev the records.

## 10. SABER: "SABER: Small Actions, Big Errors — Safeguarding Mutating Steps in LLM Agents"

Cuadron, Yu, Liu, Gupta (Amazon AGI Foundations). arXiv 2512.07850v1, 26 Nov 2025.

**Status: read in full** (v1, the only version; including Appendices A–D). Read by a subagent; the
quotes below were re-checked against the text by script.

**What it does**
- Argues that agent errors concentrate in mutating (state-changing) actions, from a regression of
  task success on deviations from reference trajectories (§3, Table 1).
- Before each mutating action, an auxiliary model "reformulates the tool call into a concise
  natural-language summary" and "requests user confirmation" (§4.2). "Non-mutating actions bypass
  verification entirely." (§4.2) It also injects a reflection of the policy constraints at that point
  and filters context (§4.1–4.2).
- Data: τ-bench airline and retail, and its own corrected version of them, with Claude Sonnet 4,
  GPT-5 and Qwen3-235B agents (§5–6). It says the annotation problems "persist even in the recently
  released" τ²-bench, whose domains were not updated (§5.1).

**What it does not do**
- No check of whether the agent's statements to the user are true against the records (no such
  check is described in §4).
- No cascade: "each model serves as both the main agent (actioning) and the auxiliary agent" (§6.1).
- No narrow-versus-broad comparison; its ablation switches its own components on and off (§6.1,
  Table 3). No GPT-4.1-family agents.

**Relation to this work (my reading).** A pre-execution safeguard on write actions in the same two
domains. It obtains consent by asking the user to confirm each write, rather than judging from the
conversation whether the customer already agreed. With JevAct, it means that pre-execution gating of
writes, and consent at the point of a write, are not new. Its finding of annotation errors in the
benchmark's reference trajectories does not touch this work's good and bad rulings, which come from
the first post's graders and policy checker, not from τ-bench's gold actions.

## 11. Corrupt success: "Beyond Task Completion: Revealing Corrupt Success in LLM Agents through Procedure-Aware Evaluation"

Cao, Driouich, Thomas (Amadeus). arXiv 2603.03116v1, 3 Mar 2026.

**Status: read in full** (v1, the only version; including Appendices A–F). Read by a subagent; the
quotes below were re-checked against the text by script.

**What it does**
- Evaluates finished agent transcripts on τ-bench airline and retail, with GPT-5, Kimi-K2-Thinking
  and Mistral-Large-3 as agents (§4.1).
- Among its procedural-integrity checks is data faithfulness: does the agent report retrieved data
  accurately, "or does it fabricate details such as prices, dates, or confirmation numbers?" (§3.2)
  Others check policy compliance, statements about policy, and whether claimed actions were taken.
- A GPT-5 judge scores the semantic metrics: "LLM-as-judge evaluation with GPT-5" (§4.1). Counts
  such as turns, tokens and tool calls come from the logs.
- Finds that many reported successes break at least one check: "Corrupt success is not a rare edge
  case but the dominant failure mode" (§6).

**What it does not do**
- Not pre-execution: it audits completed runs (§3–4).
- No consent question of its own; confirmation problems fall under policy compliance and intent
  adherence (§3.2).
- No narrow-versus-broad comparison and no cascade: the same GPT-5 judge scores every semantic
  metric (§4.1).

**Relation to this work (my reading).** The closest prior measurement to the statement question in
these domains: whether the agent's statements match what its tools returned, judged after the run,
without this work's test of whether the error would change the customer's yes.
It does not ask it before a write executes, so this work's narrower claim holds. It supports the
premise that false or unsupported statements to customers are common in τ-bench airline and retail.

## 12. "The Authorization-Execution Gap Is a Major Safety and Security Problem in Open-World Agents"

Wu, Liu, Bibi, King, Lyu (CUHK-Shenzhen, NUPT, Oxford, CUHK, SUNY Buffalo). arXiv 2605.11003v1,
10 May 2026. A position paper.

**Status: read in full** (v1, the only version; it has no appendix). Read by a subagent; the quotes
below were re-checked against the text by script.

**What it does**
- Argues that the gap between what a principal intends to authorize and what an agent executes is a
  central safety problem, and that it needs checks during execution, not only up front or after
  (Abstract).
- Proposes five checks, one of them before an action takes effect: "check whether the proposed step
  falls within the interpreted authorization scope" (§4.3).
- Argues "not for a generic monitoring layer, but for checks grounded in the structural sources" of
  divergence (§5).

**What it does not do**
- No experiments or data; its numbers are an illustrative booking (§3.2).
- No check of the agent's statements against records, and no cascade (§4.3 describes neither).
- Its checks are "not a full defense architecture" (§4.3).

**Relation to this work (my reading).** It argues for the shape of this work's agreement question
(a scope check before an action takes effect) and for targeted checks over a generic monitor, but
tests neither. The post can claim an empirical comparison of narrow questions with a broad judge,
not the idea.

---

## Cited but not read

- **Not read:** Rao and Callison-Burch (2026b), a Jev-first cascade replayed against cheap LLM rubric
  judges; Jung et al. (2025), *Trust or escalate*; Xu et al. (2025), routing uncertain reward-model
  comparisons to a strong judge; FrugalGPT. All are cited by §9 as earlier or concurrent cascades.
  Skipped because the post no longer claims anything about the cascade's novelty, so they cannot
  change a claim.

## What this means for the post's claims (my reading)

- ***Did the customer agree to this exact action* is not new as a check.** JevAct asks
  consent-like questions with a decision model before execution on τ²-bench (§1). SABER asks the user
  to confirm every write before it runs, on τ-bench airline and retail (§10). Wu et al. argue for a
  scope check before an action takes effect (§12). DelegationBench and AuthorizationBench study the
  same family. The post can claim a measurement, not the question:
  - how often agreement fails in these captures;
  - how much of a judge's work it does;
  - that the failures it targets here were mostly attempts the backend would have rejected anyway:
    of the 39 bad actions the labellers' consensus marks never agreed, the backend rejected 24
    (numbers.json, cut a, never_agreed_backend_rejected). That is a property of the labelled cases,
    not of any gate's decisions.
- **The statement question has prior measurement but, in these twelve papers, no pre-execution
  check.** Cao et al. judge after the run whether the agent's statements match what its tools
  returned, on τ-bench airline and retail (§11). The Agent Knew measures false pre-write statements
  offline. τ-bench lists wrong information as a failure. False success covers completion claims
  after the fact. The claim stays limited to *among the works read here*.
- **Narrow versus broad:** no paper read here compares a narrow two-question check with a broad
  rubric judge on the same actions. Wu et al. argue for targeted checks over a generic monitor
  without testing it (§12); Cao et al. score several narrow dimensions with one judge without a
  comparison (§11). The false-success paper is adjacent: broad judges against cheap classifiers, on
  a different question. The post can claim the comparison, not the idea.
- **Cascade: not new.** JEV-as-a-Judge publishes the design (accept Jev's answer when confident,
  escalate the rest, cut-off set on local labels) with held-out and prospective tests (§9), and cites
  earlier cascades. This work applies it to pre-execution checks of agent actions, which that paper
  leaves untested, without a held-out test of its own.
- **Still not read:** the cascade papers listed under *Cited but not read*.
