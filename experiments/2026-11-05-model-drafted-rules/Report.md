# Model-drafted rules against hand-written ones: τ²-bench airline

Five drafts of the airline rules, written by a model from the policy, the schema and the tool
definitions (`brief.py`; the brief also states τ²'s pricing arithmetic and the `Context`
interface, never a rule, write or result), run unedited on the same 133 writes as the 16 hand-written rules: three from
OpenAI models ($0.089) and two calls to Claude Sonnet 5.5 ($0.189; the first truncated, see
the README's deviation). Preregistration in `README.md`; the one analysis added afterwards is
marked post hoc. `results/metrics_three_drafts.json` is the evaluation before the Claude
drafts were added; `results/metrics.json` has all five.

## Result in one paragraph

Which model drafts the rules decides whether the layer is usable. The two gpt-4.1 drafts send
back 27 of the 46 good writes and the gpt-4.1-mini draft 44; the complete Claude Sonnet 5.5
draft sends back 4, against 0 for the hand-written rules, and lets through 23 writes that
should not run, as many as the hand-written set (21 in common). Write for write, the Claude
draft agrees with the hand-written rules on 125 of 133: it has an equivalent of 14 of the 16
rules, including the baggage-fee allowance, the certificate amounts and the gift-card balance
that gpt-4.1 missed, and lacks two, the booking route check and the inferred duplicate-seat
rule; its four false blocks come from one rule (a trip-type check that fires when the number
of segments changes); and it adds one check the expert did not write, seat availability on the
new flight, which stops two task 21 writes the hand-written rules allow and the benchmark says
should not run. In each gpt-4.1 draft, almost all the damage is also one rule: "do not change
origin, destination or trip type" implemented so that every connecting flight and every round
trip fails. Drop that rule and the basic-economy rule (post hoc) and the gpt-4.1 drafts are a
strict subset of the hand-written set, missing the rules that compute money. The mini draft requires a `user_id`
argument on tools that have none and blocks 117 of 133. The drafters' one disagreement with
the hand-written author is a real policy ambiguity: gpt-4.1 reads "basic economy flights cannot
be modified" as covering cabin upgrades, the hand-written rule and the Claude draft only as
covering flight changes; the adjudicated truth sides with gpt-4.1 on task 7 and with the
others on task 44.

## Numbers (preregistered metrics)

Against the corrected benchmark (133 writes, 46 should run) and the adjudicated truth (91
graded writes, 43 should run). "Wrong" = writes let through that should not run.

| Arm | Ran | Wrong | Good sent back (of 46) | Ran | Wrong | Good sent back (of 43) |
|---|---|---|---|---|---|---|
| hand-written, blocks only | 69 | 23 | 0 | 57 | 15 | 1 |
| hand-written, report's `rules` gate (unanswered fact also stops) | 62 | 18 | 2 | 53 | 12 | 2 |
| `claude_sonnet55_b` (thinking off, complete) | 65 | 23 | **4** | 55 | 14 | 2 |
| `claude_sonnet55` (first call, truncated: allows everything) | 133 | 87 | 0 | 91 | 48 | 0 |
| `gpt41_t0` | 51 | 32 | 27 | 38 | 15 | 20 |
| `gpt41_t1` | 49 | 30 | 27 | 36 | 14 | 21 |
| `gpt41mini_t0` | 16 | 14 | 44 | 13 | 8 | 38 |

No draft used an `INFERRED_` rule, so the "stated only" arms equal the drafts. No draft raised
on any write; the truncated Claude draft does not import and scores as the README says. The
union and intersection arms are in `metrics.json` but say little once one draft allows
everything. With Docent behind each arm (`docent_1_run`), the hand-written set and the
complete Claude draft both run 29 with 7 wrong and 24 good sent back (adjudicated: 2 wrong,
16 sent back); the gpt-4.1 drafts run 23 with 6 wrong and 29 sent back. The rules report's own
`rules` gate with Docent, where an unanswered fact also stops the write, runs 28 with 7 wrong
and 25 sent back (recomputed after the fact; `evaluate.py` scores it now, `metrics.json` was
written before it did).

**Catches.** Of the 9 writes the old veto gate ran that should not have (corrected benchmark),
the hand-written rules and the Claude draft block 0, each gpt-4.1 draft 1, the mini draft 4,
by blocking nearly everything. The rules layer, whoever writes it, does not see the gate's
failures; the rules experiment found the same.

**Agreement with the hand-written set, per write** (block / allow):

| Draft | both block | both allow | draft only | hand only |
|---|---|---|---|---|
| `claude_sonnet55_b` | 62 | 63 | 6 | 2 |
| `gpt41_t0` | 48 | 35 | 34 | 16 |
| `gpt41_t1` | 49 | 34 | 35 | 15 |
| `gpt41mini_t0` | 56 | 8 | 61 | 8 |

**Per hand-written rule, how many of the writes it blocks each draft also blocks** (13 of the
16 rules fire on these writes; OWN, ACTIVE and COMP_ELIGIBLE never do, so the table cannot
test them):

| Hand-written rule | blocks | `claude_sonnet55_b` | `gpt41_t0` | `gpt41_t1` | `gpt41mini_t0` |
|---|---|---|---|---|---|
| CANCEL_ELIGIBLE | 19 | 19 | 19 | 19 | 19 |
| PAY_BOOK | 9 | 9 | 9 | 9 | 8 |
| BAG_FEE | 10 | 10 | 1 | 2 | 10 |
| FLOWN_CANCEL | 7 | 7 | 7 | 7 | 7 |
| PAY_UPDATE | 7 | 7 | 4 | 4 | 7 |
| BASIC_NO_FLIGHT_CHANGE | 5 | 5 | 5 | 5 | 5 |
| COMP_CAUSE | 5 | 5 | 0 | 0 | 0 |
| SAME_ROUTE | 4 | 4 | 4 | 4 | 4 |
| DUPLICATE_SEAT (inferred) | 2 | 1 | 1 | 1 | 1 |
| ROUTE_BOOK | 2 | 1 | 1 | 1 | 0 |
| BAGS_NO_REMOVE, FLOWN_CABIN, PAX | 1 each | 1 | 1 | 1 | 1 |

The mini draft's column is inflated by its blanket `user_id` rule; the other columns are
genuine overlap, write by write, which is not the same as rule by rule. Read against the
draft's code, the Claude draft has an equivalent of 14 of the 16 hand-written rules (OWN,
ACTIVE and COMP_ELIGIBLE included, as owner, cancelled-reservation and eligibility checks). It
has no duplicate-seat check and no booking route check: its booking code leaves the trip-type
branch empty ("connections allowed; do not block"). The 1 of 2 it shows on `DUPLICATE_SEAT` and
`ROUTE_BOOK` is coincidence, the one write in each pair being blocked by its payment rules
where the hand-written set also fires `PAY_BOOK`; the other write in each pair it lets through.

## Where the false blocks come from

| Draft | Rule | Fires | False (corrected) | What it does |
|---|---|---|---|---|
| `claude_sonnet55_b` | MODIFY_TRIP_TYPE | 11 | 4 | "trip type must stay the same" checked as "the number of segments must not change": a 3-segment to 2-segment change on the same route fails (tasks 30 and 33). The adjudicated truth says the task 33 writes should not run anyway, so under it the rule has 2 false blocks (task 30 and task 34; the task 34 write is also blocked by the hand-written `PAY_UPDATE` and by the draft's `MODIFY_PAYMENT_INSUFFICIENT_BALANCE`, which therefore has 1 adjudicated false block of its own) |
| `gpt41_t0` | MODIFY_ORIGIN_DEST_TYPE | 42 | 26 | requires every new segment to run from the reservation's origin to its destination: fails on any connection or return leg |
| `gpt41_t0` | MODIFY_BASIC_ECONOMY | 11 | 6 | blocks any update of a basic economy reservation, including a cabin upgrade with the flights unchanged |
| `gpt41_t1` | MODIFY_ORIGIN_NOCHANGE, MODIFY_DEST_NOCHANGE | 46 each | 27 | reads `origin` off the call's flight entries, which carry only number and date; `None` never matches |
| `gpt41_t1` | MODIFY_BASIC_ECONOMY_FLIGHT | 11 | 6 | as above |
| `gpt41mini_t0` | MODIFY_1, CANCEL_1, PASS_1, BAG_1 | 104 | 41 | requires `args["user_id"]`, which the reservation tools do not take; blocks every one |
| `gpt41mini_t0` | BOOK_4 | 13 | 3 | payment limits applied wrongly |

Every other rule in the Claude and gpt-4.1 drafts has zero false blocks on the corrected
benchmark (under the adjudicated truth, one more Claude rule has one, as the table says). The
route rule accounts for 26 of `gpt41_t0`'s 27 false blocks (the other is `MODIFY_BASIC_ECONOMY`
on task 44) and for all 27 of `gpt41_t1`'s. The Claude draft has 21 rules that fire; the
hand-written set has 16, of which 13 fire on these writes.

### What the Claude draft adds

`MODIFY_NO_SEATS` blocks two task 21 flight changes because the new flight has no economy seats
left on that date. The hand-written rules never checked seat availability (the policy says a
flight "can be booked" only when available seats are listed; the expert read that as the
`available` status and stopped there). Both writes should not run under the corrected
benchmark; one is graded and the adjudicated truth agrees. That is a correct block the expert
missed, found by a drafter that had only the policy. Two qualifications: both writes were
rejected by the τ² backend itself ("Not enough seats on flight HAT229"), so they could not
have executed, and the benchmark marks them wrong for booking the wrong flights (`other_args`),
not for the seats.

### Post hoc: the gpt-4.1 drafts with the broken route rule removed

Not preregistered; an ablation to see what those drafts are apart from one bug.

| Arm | Ran | Wrong | Good sent back (46) | Ran | Wrong | Good sent back (43) |
|---|---|---|---|---|---|---|
| hand-written, blocks only | 69 | 23 | 0 | 57 | 15 | 1 |
| `gpt41_t0` minus the route rule | 84 | 44 | 6 | 64 | 22 | 1 |
| `gpt41_t0` minus route and basic-economy | 94 | 48 | 0 | 68 | 25 | 0 |
| `gpt41_t1` minus the two route rules | 83 | 43 | 6 | 63 | 21 | 1 |
| `gpt41_t1` minus those and basic-economy | 93 | 47 | 0 | 67 | 24 | 0 |

With the route rule alone removed, each gpt-4.1 draft still blocks six writes the hand-written
set allows (the basic-economy cabin upgrades below). With the basic-economy rule removed as
well, the set of writes a gpt-4.1 draft blocks is contained in the set the hand-written rules
block. What those drafts lack is the arithmetic: the free-bag allowance by
membership and cabin, the certificate amounts, the gift-card balance against the charge, the
booking route. The Claude draft has all of it.

### The basic-economy reading

"Basic economy flights cannot be modified." Both gpt-4.1 drafts block every update of a basic
economy reservation; the hand-written rule and the Claude draft block only when the flights
change, so a cabin upgrade on the same flights passes. The six writes gpt-4.1 blocks and the
others allow are all cabin upgrades on unchanged flights (tasks 7, 22 and 44). The corrected
benchmark says all six should run. The adjudicated truth says the two task 7 writes should not
and the graded task 44 write should. So the reading is not settled by the data: it is one of
the clauses a policy owner has to decide, and the drafters surfaced it.

## What this says

1. **The drafter's model decides whether the layer is a product.** gpt-4.1 drafted the shape of
   the rules and not the arithmetic; Claude Sonnet 5.5, thinking off, drafted both, matched the
   hand-written set on 125 of 133 writes with an equivalent of 14 of its 16 rules, and added a
   seat check the expert left out. Standing
   up the rules layer for a new policy is one call and a review, if the drafter is good enough.
2. **In the usable drafts, one rule does almost all the damage.** The Claude draft's trip-type
   proxy is its only rule with a false block; a route rule accounts for 26 of 27 and 27 of 27
   of the gpt-4.1 drafts' false blocks (the rest is the basic-economy reading below). The mini
   draft has five rules with false blocks, four of them the same `user_id` pattern, and the
   truncated draft has no rules at all. A rules layer needs a harness the drafter is run against,
   not a one-shot prompt: run the draft on known-good writes, show it what it blocked, let it
   fix. For the Claude draft that is four writes to look at; for gpt-4.1 it is the first good
   write.
3. **The expert's job is review and the ambiguities.** The one place the drafters disagreed with
   the hand-written author is a clause the policy leaves open. The one rule the Claude draft
   got wrong is a proxy for a concept the policy names but does not define (trip type under a
   change of segments). Those are decisions, not code.
4. **Budget the output for thinking.** The first Claude call spent an 8,000-token budget mostly
   on thinking and returned a truncated module. The lesson is on the caller: a drafting call
   needs either thinking off or a budget sized for both.

## Limits

- One brief, one policy, five drafts from three models. A different brief (with the fee tables
  spelled out, or with the harness of point 2) would give different drafts; this measures the
  one-shot case. The Claude draft ran at the model's default sampling (it accepts no
  temperature), the OpenAI drafts at 0 and 1.
- The second Claude call is a deviation from "one call per draft", made because the first
  call's budget was mis-set; both are reported and the first is scored as it came back.
- The ablation is post hoc. It answers "what is the draft apart from one bug", not "what would a
  model produce".
- The hand-written rules were written after seeing the failures (their README says so); the
  drafts were not. The comparison favours the hand-written set.
