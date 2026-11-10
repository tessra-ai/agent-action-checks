# Report: deterministic rules in front of the judges (τ²-bench airline)

Preregistration: `README.md` (rules, facts and gates committed before any run). Numbers:
`results/rules.jsonl`, `results/facts.jsonl`, `results/gates.json`. Spend: Jev $0.035 (cap
$0.50); rules $0.

## Result

**Rules are precise but do not reach the gate's failures.** The 16 rules blocked 64 of 133
writes. None of those blocks hit a write the corrected benchmark says should run. Against the
adjudicated truth one block was disputed (task 34: a $222 change on a $200 gift card, which the
benchmark also rejects). But Docent had already refused almost all of them: it would have run 1
(run 1) and 2 (run 2) of the 64, and Jev's broad question would have run 15. Of the veto gate's
wrong runs, the rules caught **none**: each of those was stopped by Jev or by nothing.

| Gate (Docent run 1 / run 2) | Ran | Wrong: corrected benchmark | Wrong: adjudicated | Good sent back (benchmark, of 46) |
|---|---:|---:|---:|---:|
| Jev policy ok + Docent (the veto gate) | 22 / 24 | 6 / 8 | 2 / 4 | 30 / 30 |
| Docent alone | 30 / 32 | 8 / 12 | 3 / 6 | 24 / 26 |
| **Rules + Docent** | 28 / 28 | 7 / 9 | 2 / 3 | 25 / 27 |
| Rules + Jev facts + Docent | 18 / 17 | 4 / 4 | 0 / 0 | 32 / 33 |
| Rules alone | 62 | 18 | 12 | 2 |

95% upper bounds are in `results/gates.json`. Every one is above 23%, so differences of one or
two writes are not significant.

## Readings

1. **Rules do what Jev's broad question did, without its cost.** Rules + Docent is as precise as
   the veto gate against the adjudicated truth (2 and 3 wrong, against 2 and 4) and runs 6 and 4
   more writes. Against the corrected benchmark it is one wrong run worse in each Docent run. No
   rule blocked a good write by the benchmark's account. The 2 good writes the rules hold back
   are insured cancellations waiting for the reason fact. As a veto beside Docent, rules replace
   Jev's single "policy ok" question.
2. **On these agents, Docent already refuses nearly every rule break.** It would have run 1 and 2
   of the 64 rule-blocked writes. The rules make that part deterministic, cheap (no model call),
   auditable and stable across Docent's run-to-run noise. They add little accuracy here.
3. **What still gets through is not rule-shaped.** The veto gate's wrong runs that survive rules,
   Jev's fact questions and Docent:
   - booking a new reservation instead of changing the existing one (task 17);
   - a downgrade the customer agreed to after the agent misquoted a price (task 22);
   - a new ticket the customer's instructions rule out (task 32);
   - cancelling the Boston flight on an ambiguous instruction (task 42, case 02; the adjudicated
     truth counts it as run after the person's revert).

   No rule over the records sees any of these.
4. **The narrow facts cut wrong runs, but partly by coincidence and at a high cost.**
   - `insurance_asked` stopped 4 of the gate's wrong bookings (cases 04, 07, 13 and 14) because
     the agent never offered insurance. That is a real policy step. But it is not why
     those bookings were wrong.
   - `reason_covered` stopped the ineligible cancellation (case 12), as designed.
   - `confirmed` is the costly one. Jev said no on 58 of 133 writes, and it disagrees with the
     graders often: it says not confirmed on 19 of 44 writes the graders accept, and confirmed on
     5 of 9 the graders say need asking.
   - As a fact extractor for "did the customer confirm these details?", Jev is not reliable
     enough here. It is the main reason the fact gates send back 32 or more of 46 good writes.
5. **Cases 04 and 07 are not seat duplicates.** The inferred `DUPLICATE_SEAT` rule did not fire
   on them. Aarav and Evelyn were not on the earlier group booking (HATHAT holds Mohamed, Raj
   Sanchez and Liam Wilson). What is wrong is the plan: the agent books the per-passenger
   reservations without cancelling or addressing the group booking they were meant to replace.
   That is plan-level, not a seat check. (The veto report's earlier description is corrected.)

## What this says about the design

- Keep rules as the deterministic veto: zero false blocks against the benchmark, and they
  replace Jev's broad question. Their value is guarantees and audit, not extra catches, on agents
  that Docent already polices well.
- The open problem is consent obtained on the agent's mistake, and plans that drift from the
  customer's goal. Neither rules over records nor a single-transcript judge sees these. This is
  the case for a claims check: verify what the agent told the customer against the records.
  Narrow facts only help if the extractor is accurate, and Jev's `confirmed` answers are not.

## Per rule (fires; false blocks against the corrected benchmark)

| Rule | Fires | False blocks |
|---|---:|---:|
| `CANCEL_ELIGIBLE` | 19 | 0 |
| `BAG_FEE` | 10 | 0 |
| `PAY_BOOK` | 9 | 0 |
| `FLOWN_CANCEL` | 7 | 0 |
| `PAY_UPDATE` | 7 | 0 (1 against the adjudicated truth: task 34) |
| `BASIC_NO_FLIGHT_CHANGE` | 5 | 0 |
| `COMP_CAUSE` | 5 | 0 |
| `SAME_ROUTE` | 4 | 0 |
| `DUPLICATE_SEAT` | 2 | 0 |
| `ROUTE_BOOK` | 2 | 0 |
| `BAGS_NO_REMOVE`, `FLOWN_CABIN`, `PAX` | 1 each | 0 |

## Limitations

- The rule author had seen the airline failures. The rules cite policy clauses and name no task.
  That they caught none of the gate's failures suggests they were not fitted to them.
- 133 writes from two agents (gpt-4.1 and gpt-4.1-mini), one domain. Docent refusing every rule
  break may not hold for weaker agents or other judges.
- The truths are those of the veto experiment, with their own limits (see its report).

Adjudicated numbers reflect the person's revert of the case 02 correction (2026-10-28);
`results/gates.json` was regenerated after it.
