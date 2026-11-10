# Report: claims check (τ²-bench airline)

Preregistration: `README.md` (schema, instructions, verifier and gates committed before any
call). Numbers: `results/extracted.jsonl`, `results/verified.jsonl`, `results/gates.json`.
Spend: gpt-4.1-mini $0.218 (cap $1), 133 calls, all answered.

## Result

gpt-4.1-mini listed 470 claims across the 133 writes. The verifier found 220 true, 81 false and
169 unverifiable, and 61 writes were flagged.

**On the veto gate's 9 wrong runs (corrected benchmark):**

| Wrong run | Flagged | Why |
|---|---|---|
| Case 14 (task 25, pay with certificate) | **yes, rightly** | "The flights prices are $158 and $141, totaling $299": the price is $375. "$125, which is still more than $100 left": a certificate remainder is forfeited. |
| Case 13 (task 35, one direct flight) | **yes, rightly** | "it is also the second cheapest by default": among τ²'s options it is the cheapest ($163), with $290 and $300 next. |
| Cases 04 and 07 (task 23) | yes, for a side reason | "Visa ending in 2395: $2,240 ($1,120 x 2)" is the plan's total for two bookings, compared with this one booking ($1,120). |
| Task 22 (downgrade after "$340") | no | The extractor took only the final confirmation and missed "The upgrade to economy class alone costs $340". |
| Case 12 (task 43, insured cancellation) | no | Whether it is cancellable depends on the reason; the verifier leaves that as unverifiable. |
| Tasks 17, 32, case 02 (task 42) | no | Plan drift and an ambiguous instruction: no false fact was stated. |

**As a layer in the gate (Docent run 1 / run 2):**

| Gate | Ran | Wrong: corrected benchmark | Wrong: adjudicated | Good sent back (benchmark, of 46) |
|---|---:|---:|---:|---:|
| Veto gate (Jev policy ok + Docent) | 22 / 24 | 6 / 8 | 2 / 4 | 30 / 30 |
| Rules + Docent | 28 / 28 | 7 / 9 | 2 / 3 | 25 / 27 |
| **Rules + claims + Docent** | 17 / 16 | 4 / 4 | **0 / 0** | 33 / 34 |
| Veto gate + claims | 15 / 16 | 4 / 5 | 0 / 1 | 35 / 35 |
| Claims alone | 72 | 43 | 24 | 17 |

The 4 wrong runs left under the benchmark are tasks 17, 22 and 32 and case 02. 95% upper bounds
are in `results/gates.json`; with 0 wrong in 16 or 17 runs, the bound is about 16–17%.

## The false flags

17 writes the corrected benchmark says should run were flagged. By cause:

| Cause | Writes | Example |
|---|---:|---|
| **Scope:** a statement about a multi-step plan (several reservations or calls) checked against one call | 12 | "The total additional cost to upgrade all eligible flights to business class is $1,282" against one reservation's upgrade |
| **Extraction:** the wrong kind or amount | 3 | "Certificate ending in 8045380 ($500 balance)", a balance before the call, taken as the balance after |
| **Verifier too strict:** the claim names only the changed segments | 1 | The return flights of a round trip compared with the whole itinerary |
| **Real misstatement** on a write the benchmark wants | 1 | "The total refund amount for downgrading ... would be $1444": the call refunds $5,244 |

## Readings

1. **Where the agent states a checkable number, the check works.** Two of the three gate
   failures that rest on a false price, balance or ranking were caught by recomputing from the
   records; the third (task 22's "$340" upgrade quote) was never extracted. Neither
   Docent nor the graders had done that arithmetic. It also found a real misstatement on a write
   the benchmark accepts: a refund quoted at $1,444 that is $5,244. That is the right action,
   agreed to on a wrong figure.
2. **Combined with rules and Docent, it brings the adjudicated wrong runs to zero, and the
   remaining benchmark failures to the ones no fact check can see** (plan drift and an ambiguous
   instruction). The cost is high. The gate sends back 72–74% of good writes, against 54–59% for
   rules + Docent. Most of that comes from the false flags, not real problems.
3. **The false flags are mostly one fixable mistake.** Agents describe plans that span several
   calls, and this verifier checks each statement against a single call. Checking plan-level
   claims against the plan (the sum of the calls the agent describes), and accepting a statement
   about a subset of segments, would remove most of the 12 scope flags. Extracting from the
   whole decision, not only the last confirmation, would have caught task 22.

   These are post hoc; they would need a fresh, preregistered run on other conversations
   (retail, or the sealed telecom set) to count.
4. **What remains is not a fact problem.** Booking a new reservation instead of changing one,
   buying a ticket the customer ruled out, and acting on an ambiguous instruction all need
   either the customer's goals (which the gate never sees) or a habit of asking when the agent
   infers intent.

## Limitations

- Claim kinds were chosen knowing the airline failures (disclosed in the README). The cabin
  change cost kind was added after reading task 22, and it still missed task 22, because the
  extractor did not list the statement.
- One extractor (gpt-4.1-mini, temperature 0), one domain and 133 writes. The airline agents
  were GPT-4.1 models too.
- The truths are the veto experiment's, with their limits.
