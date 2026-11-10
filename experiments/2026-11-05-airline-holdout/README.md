# Airline, held out: a second capture with a new seed

| | |
|---|---|
| **Status** | `done`: see `Report.md`. 96 of 100 simulations (4 lost to rate limits), 122 writes, 188 blind readings; the person reviewed 18 writes on 2026-11-09 (`review/`, `adjudicate.py`) |
| **Branch** | `experiment/docent-vs-oracle`; not merged |
| **Question** | Every airline number so far comes from one capture of 133 writes that the rules, the claims check and the plan-level rules were designed on or refined against. On a fresh capture, with the same judges, rules and checks frozen, what do they do? |
| **Data** | A new capture: the same 50 airline tasks, the same two agents (gpt-4.1, gpt-4.1-mini; nano is retired), the same user simulator and τ² commit, seed 301 instead of 300 (`airline2.yaml`). Nothing from this capture has been seen by anything evaluated here |
| **Spend** | OpenAI: capture hard cap $4 (first capture cost $3.08), Docent's judge two runs at $2 each, plan-aware claims extraction $1 across three sets; Jev $2 cap through the ledger. Blind grading runs in session, $0 |
| **Telecom** | Untouched |

## What is frozen and tested as is

Everything below is used exactly as committed before this capture; nothing is tuned to it.

- **The two judges and the gate** of `experiments/2026-10-28-airline-veto`: Jev's single
  question (`hatchway-airline.yaml`), Docent's judge with the airline rubric
  (`judge_airline.py`, two runs), run iff both say run; and the retail cascade.
- **The hand-written rules** (`experiments/2026-10-28-airline-rules/rules.py`, 16 rules) and
  the complete Claude draft (`experiments/2026-11-05-model-drafted-rules/results/drafts/claude_sonnet55_b.py`),
  both run on the pre-action snapshots.
- **The claims check**, with one change made before this capture and recorded here: the
  extraction schema gains two fields per claim, `scope` (`this_call`, `other_call`, `plan`) and
  `target` (the order or reservation id the statement is about, or null), and the verifier uses
  them with the plan rules of `experiments/2026-11-05-plan-level-claims` in their `targeted`
  form: a `this_call` claim is checked against this call; an `other_call` claim against the plan
  call on its target (unverifiable if the plan has none); a `plan` claim against the plan's
  union or sum. The first airline set and the retail set are re-extracted under the same schema
  so the three sets are comparable (`claims_plan.py`).

## Pipeline (the first capture's scripts, paths changed, nothing else)

`capture.py` → `export.py` → `score_jev.py`, `judge_airline.py` ×2 → `gate.py` → blind grading
→ `analyze.py grades` → `benchmark_check.py`, `benchmark_corrected.py` → rules and claims →
`evaluate.py` → `Report.md`.

## Truth

1. **Blind Claude graders**, as before: every write that Jev or either Docent run would let
   run gets 3 independent readings from fresh subagents (`grading/PROMPT.md` of the first
   capture, unchanged); 20 others drawn with seed 20261105 get 1. Majority; ties count as not
   run.
2. **The corrected τ² benchmark**: each write classed against the task's reference actions,
   with the same τ²-Bench-Verified corrections (`benchmark_corrected.py`, the same tasks file,
   sha256 `202f0cdb…`).
3. No person's review in this run: the project owner is not grading it live. Where the graders
   and the benchmark disagree, both numbers are reported; neither is called truth.

## Metrics, each against both truths

1. **The gate**: writes run, wrong runs, Clopper–Pearson upper bound, good writes sent back.
   First capture: 2 to 8 wrong of about 23 run, depending on the truth.
2. **The rules**: false blocks on good writes (first capture: hand-written 0 of 46, Claude draft
   4 of 46) and wrong runs.
3. **The claims check**: false flags on good writes under the plan-aware extraction (first
   capture, per-call: 17 of 46), and flags on writes that should not run.
4. **The stack**: rules + claims + Docent, as in the rules and claims reports.
5. **Agreement between the two truths** on the graded writes.

No pass/fail label. The question is whether the first capture's numbers hold on data none of
this was built on.

## Run order

1. Commit this README, `airline2.yaml`, the copied scripts and `claims_plan.py` with its tests.
2. `capture.py` (background; resumable) → `runs/airline2/`.
3. `export.py` → `data/runs.jsonl`, `data/meta.jsonl`.
4. `score_jev.py`; `judge_airline.py` twice.
5. `gate.py`; blind grading; `analyze.py grades`.
6. `benchmark_check.py`; `benchmark_corrected.py <verified tasks.json>`.
7. Rules on the snapshots; plan-aware claims extraction on the three sets; `evaluate.py`.
8. `Report.md`.

## Deviations (recorded after the run, from the review of 2026-11-06)

**Timeline.** "Frozen before the capture" holds for Jev, Docent's judge, the gate, the hand
rules (`rules.py`, 2026-10-28) and the Claude draft (`claude_sonnet55_b.py`, 2026-11-05 20:57).
The capture ran 21:14 to 21:27 UTC on 2026-11-05 (`runs/airline2/capture.log`); the plan-aware
claims schema, extractor, verifier and their tests were committed at 21:17 (dbc4268), the rules
runner at 21:23 (3999936) and the evaluator at 21:24 (c7f7a0d), all during the capture and
before the export at 21:31 (data committed at 21:45, 3efa615). None of that code saw the data,
but it was not committed before the capture started. Two files changed after the data existed,
both error handling only: `extract_plan.py` (a truncated JSON reply is recorded as a status
error, in 3efa615) and `benchmark_check.py` (tolerates missing review files, in cd313c3).

**Scoring universe.** `verify_plan.py` scored every write in `runs/airline2/export.db` (128),
including 6 writes from the 4 gpt-4.1 simulations that failed on rate limits and that
`export.py` leaves out of `data/runs.jsonl` (122). The by-truth numbers were unaffected (the
truths only cover exported writes), but the claim counts in `Report.md` were over 128 writes.
On 2026-11-06 the script was restricted to the exported ids and re-run (offline, no calls):
465 claims, scopes 366 / 86 / 13, 99 scoped, 55 flagged writes; 16 of 40 and 15 of 43 unchanged.
The 128-write files are in the git history before that commit.

**The truncated extraction.** One write (`01M6PSDXGY13ZCNJB67XE7HFHJ`, task 18, good under
both truths) hit the extractor's output limit; its claims are scored as none, so it is never
flagged and the claims arm counts it as run. Excluding it would give 16 of 39 (graders) and 15
of 42 (benchmark). The preregistration did not say which; the numbers reported are with it in.

**A plan-scope claim never reaches `sum` or `union` when `other` holds.** `claims_plan.py`
asks `plan.plan_verdict` for a plan-scope claim and discards an `other` rescue; because
`plan_verdict` tests `other` first, a plan-scope claim that is true of one other call and also
of the plan's sum or union is reported false. No effect on this capture (0 `sum` or `union`
rescues; the four task 18 plan-scope flight claims rejected as `other` do not match the union
either). The file is frozen; recorded here rather than changed.

**Payment claims on actions that move no money.** The frozen airline verifier marks a
payment-method claim on `update_reservation_passengers` false (its truth is an empty list)
where unverifiable would be right; tasks 17 and 22 are flagged on that alone. With that fix the
claims check's false flags would be 14 of 40 and 13 of 43 instead of 16 and 15. Not changed.
