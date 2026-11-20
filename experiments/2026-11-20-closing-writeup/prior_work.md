# Prior work: eight papers, read in full

Read 2026-11-20 from the full arXiv PDFs, converted to text. Every statement below points to the
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
  which I have not read.
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
points to Cao et al. on "corrupt success" and to SABER's audit of τ-bench trajectories, neither of
which I have read.

## 8. AuthorizationBench: "Act on Your Behalf, Beyond Your Authorization: Benchmarking LLM Agent Authorization Alignment"

Zhang, Li, Huang, Li (Northeastern, CMU, UNC-Chapel Hill). arXiv 2610.27548. The arXiv page gives a
citation date of 2026-10-20; the text read is v2, stamped 21 Oct 2026.

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

---

## What this means for the post's claims (my reading)

- ***Did the customer agree to this exact action* is not new as a check.** JevAct asks
  consent-like questions with a decision model before execution on τ²-bench (§1 above).
  DelegationBench and AuthorizationBench study the same family. The post can claim a measurement, not
  the question:
  - how often agreement fails in these captures;
  - how much of a judge's work it does;
  - that the failures it targets here were mostly attempts the backend would have rejected anyway:
    of the 39 bad actions the labellers' consensus marks never agreed, the backend rejected 24
    (numbers.json, cut a, never_agreed_backend_rejected). That is a property of the labelled cases,
    not of any gate's decisions.
- **The statement question has prior measurement but, in these eight papers, no pre-execution
  check.** The Agent Knew measures false pre-write statements offline. τ-bench lists wrong
  information as a failure. False success covers completion claims after the fact. This is the
  stronger novelty claim, limited to *among the works read here*.
- **Narrow versus broad:** no paper read here compares a narrow two-question check with a broad
  rubric judge on the same actions. The false-success paper is adjacent: broad judges against cheap
  classifiers, on a different question.
- **Cascade:** none of the eight runs one. JevAct cites a preprint on accepting a decision model's
  answer when it is confident and escalating when it is unsure (title quoted in §1 above). The post
  should not call the cascade new before that preprint is read.
- **Not read, and worth reading before M4:** the escalation preprint JevAct cites (§1); Cao et al. on
  corrupt success, cited by the false-success paper (§7); SABER (Cuadron et al., §7); Wu et al.'s
  position paper on the authorization-execution gap, cited by DelegationBench (§6).
