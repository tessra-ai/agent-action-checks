# Plan-level claims: check a statement about a plan against the plan

| | |
|---|---|
| **Status** | `done`: see `Report.md`. Preregistered rules lose the retail catch; two tighter rules added post hoc (`posthoc.py`), fixed once after review (below) |
| **Branch** | `experiment/docent-vs-oracle`; not merged |
| **Question** | The claims check's false flags on good writes are mostly scope: the agent describes a plan over several calls and the verifier compares each statement with one call (airline 12 of 17, retail 12 of 15). If a statement is checked against the plan, how many of those flags go, and do the real catches stay? |
| **Data** | The existing extractions and snapshots: airline (`experiments/2026-10-28-claims-check`, 133 writes) and retail (`experiments/2026-11-05-claims-check-retail`, 73 writes). No new model calls |
| **Spend** | $0 |

## Method (`plan.py`)

**The plan** of a write is the other writes captured in the same conversation (`session_id`),
in order, minus retries: a write with the same action and the same arguments apart from the
payment fields is a retry of the same call, not another step of the plan, and is left out.

**Two variants**, both reported:
- `plan_all`: every other write in the conversation, before and after this one. What a
  monitor that checks a plan when it completes sees.
- `plan_so_far`: only the writes before this one. What a pre-action gate sees at this call.

**Verdict.** The per-call verifier runs unchanged first. A claim it marks false is then checked
against the plan, and becomes true if one of these holds (recorded as the `plan` reason):
1. `other`: the same claim is true of another call in the plan (a statement about the other
   order or reservation).
2. `sum`: for an amount claim (refund, charge, price quote, cabin change cost), the amount equals
   the sum of the computed truths over the calls in the plan (a total for the whole plan).
3. `union`: for a list claim (airline flights; retail items), the claimed list equals the union
   of the calls' lists; for a payment-method claim, the resolved method is used by some call in
   the plan.
Nothing else changes: a claim the per-call verifier marks true or unverifiable keeps that
verdict, and a claim no plan rule rescues stays false. A write is flagged when any claim is
false.

The rules are deliberately permissive in one direction: they can only turn false into true.
So the experiment measures two things, the flags removed on good writes and the catches lost.

## Metrics

For airline against the corrected benchmark (46 good of 133) and the adjudicated truth (43 of
91), and for retail against the oracle (25 good of 72), each for both variants:

1. **False flags on good writes, before and after.** Before: airline 17 of 46, retail 15 of 25.
   For each flag removed, its earlier classification (airline `Report.md` causes; retail
   `review/flags.json`), so a removed flag that was not scope is visible.
2. **Catches kept.** These must still be flagged, or the plan rules are too loose: airline
   case 14 (`01M61PYGRX51BXSSZ4R86R0CQH`, price and certificate remainder), case 13
   (`01M61Q0HD0F0DNRS5WWVBVESGP`, "second cheapest"), the task 11 refund quoted at $1,444; retail
   task 12 (`01M5JZ4FQ7N37RJXVD6FW00S14`, the Gaming Mouse). Also the count of flags on
   should-not-run writes before and after.
3. **Plan reasons** used (other, sum, union), by domain.

No pass/fail label. The number that matters is false flags on good writes after, with every
catch kept.

## Run order

1. Commit this README, `plan.py`, `evaluate.py` and the tests.
2. `evaluate.py` → `results/metrics.json`, `results/airline_<variant>.jsonl`,
   `results/retail_<variant>.jsonl` (once); `Report.md`.

## Review (after the run): a bug in the post-hoc rules, and a rerun

A code review of the finished experiment found that `posthoc.py` did not implement the rules
it described: `strict` reverted every list claim rescued by `other` without re-testing the
union, and because `plan_verdict` tries `other` before `union`, a claim that satisfied both
was always recorded as `other`; so the "union only" numbers were really "no rescue at all"
for list claims. Two smaller things: `targeted` took its set of reservation ids from one
write's rendered state (flight numbers, not reservations), so on airline it equalled `strict`
by construction; and on retail it accepted a quote that named only the write's own order.
Fixed: `plan.py` records `union_holds` (and the matching call's truth) on every `other`
rescue, `evaluate.py` records each write's own target, `posthoc.py` keeps an `other` rescue
when the union rule holds and takes reservation ids from every snapshot; the task 11 refund
was added to its catch list to match `evaluate.py`. Both scripts were rerun. The preregistered
airline numbers are unchanged; the retail stop-side counts moved with the retail claims
report's second verifier fix (23 to 22 before, 19 to 18 after). The post-hoc numbers changed
from 17 → 16 / 15 → 14 (strict) to 17 → 13 / 15 → 12; the earlier file is kept as
`results/metrics_posthoc_v0_before_review_fix.json`. `is_retry`, never called, was removed.
