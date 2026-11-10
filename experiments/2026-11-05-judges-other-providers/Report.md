# Docent's judge with other providers' models: Claude Sonnet 5.5 and Gemini 3.1 Pro

The same Docent judge, rubric and decision procedure as the airline experiments, with only
the model swapped, on a seeded subset of the first airline capture (80 of 133 writes; the
OpenAI runs cover all 133 and are compared on the same 80). Claude Sonnet 5.5: one complete
run, $9.35. Gemini 3.1 Pro: one complete run over four days (Nov 5 to 8), because Google's
daily request limit for the model ran out on three of them; $9.93 billed by Google for Nov 5
and 6, then $8.51 metered for Nov 7 and 8 with thinking tokens counted (Google's billing is the
figure of record). Writes 62 to 80 were parsed with a code-fence strip that removed Docent's
format re-asks (README, review notes). Preregistration, five recorded deviations and the review
notes in `README.md`.

## Result in one paragraph

Swapping the judge's model changes how much the judge lets through more than how often it is
wrong. On the same 80 writes, Docent's OpenAI judge (`gpt-5.6-luna`, low effort) lets 18 to 20
run and is wrong on 1 to 4 of them by the adjudicated truth; Claude Sonnet 5.5 lets 27 run and
is wrong on 2 of the 25 that were graded (the other 2 match the benchmark's reference action);
Gemini 3.1 Pro is the strictest in its one run (within the OpenAI judge's run-to-run spread), letting 15 run with 1 of the 14 graded wrong. Claude
sends back 3 of 26 good writes where the OpenAI judge sends back 9 to 10: a similar wrong-run
rate (2 of 25 against 1 of 18 and 4 of 20) and a third as many good writes sent back; Gemini
sends back 13, half of them. Behind Jev's veto, Claude's
gate runs 18 with 2 wrong (OpenAI: 12 to 13 with 1 to 2). Under the corrected benchmark, which
counts plan drift as wrong, Claude's extra runs cost it: 6 wrong of 27 against 5 of 18 for the
OpenAI judge's first run. The two OpenAI runs disagree with each other on 6 of 80 writes;
Claude disagrees with each of them on 11 to 17, almost always by allowing what they stopped.
The judge's design transfers across providers; its operating point does not, and it is not
set by price: Gemini, priced like Claude, sits at the strict end in its one run.

## Numbers (80 writes)

Adjudicated truth: 26 of the 80 should run (graded writes only). Corrected benchmark: 27 of 80
should run.

| Judge | Ran | Wrong (adjudicated) | Good sent back (of 26) | Ran | Wrong (benchmark) | Good sent back (of 27) |
|---|---|---|---|---|---|---|
| OpenAI run 1 | 18 | 1 | 9 | 18 | 5 | 14 |
| OpenAI run 2 | 20 | 4 | 10 | 20 | 9 | 16 |
| **Claude Sonnet 5.5** | 27 (25 graded) | 2 | 3 | 27 | 6 | 6 |
| **Gemini 3.1 Pro** | 15 (14 graded) | 1 | 13 | 15 | 4 | 16 |
| with Jev's veto: OpenAI 1 / 2 | 12 / 13 | 1 / 2 | 15 / 15 | 12 / 13 | 5 / 6 | 20 / 20 |
| with Jev's veto: Claude | 18 | 2 | 10 | 18 | 5 | 14 |
| with Jev's veto: Gemini | 11 | 1 | 16 | 11 | 4 | 20 |

Gemini's first 34 writes made it look much stricter than this (3 run against 4 to 6 for the
OpenAI judge on those writes); on all 80 it is close to the OpenAI judge's first run and
agrees with it on 75 of 80.

**Agreement per write** (run / stop):

| Pair | both run | both stop | first only | second only |
|---|---|---|---|---|
| OpenAI 1 vs OpenAI 2 | 16 | 58 | 2 | 4 |
| OpenAI 1 vs Claude | 17 | 52 | 1 | 10 |
| OpenAI 2 vs Claude | 15 | 48 | 5 | 12 |
| OpenAI 1 vs Gemini | 14 | 61 | 4 | 1 |
| OpenAI 2 vs Gemini | 13 | 58 | 7 | 2 |
| Claude vs Gemini | 13 | 51 | 14 | 2 |

Claude's rollouts were unanimous on 66 of 80 writes, Gemini's on 68. Labels on the 80:
OpenAI run 1 deny 44, ask 18, allow 18; Claude deny 41, ask 12, allow 27; Gemini deny 48, ask
17, allow 15. Claude says "ask" less often and "allow" more; Gemini says "deny" most.

**The old gate's wrong runs.** Of the 6 writes in this subset that the OpenAI-judged gate ran
and should not have (corrected benchmark), Claude refuses 2, Gemini 2, OpenAI run 1 refuses 1
(it was run 2's), run 2 none. The misstatement cases the claims check caught are not among what any
judge model refuses: the judge reads the transcript, and the consent is real.

## What this says

1. **The design holds across models; the threshold moves.** Same rubric, same decision
   procedure, and a different model draws the allow line in a different place: Claude is more
   willing to call a write allowed, Gemini less, OpenAI between. Precision by the adjudicated
   truth is similar for all three; recall of good writes is not. A deployment has to measure
   its judge's operating point, not assume it from the rubric. The models differ in price tier
   (see Limits), but the two of similar price sit at opposite ends, so tier does not explain
   the order.
2. **The failures a judge cannot see do not move.** The wrong runs that remain are the ones
   from the airline report: a customer's yes resting on a wrong figure. No model fixes that
   from the transcript; the claims check does from the records.
3. **The second OpenAI run is a noise baseline the comparison needs.** Two runs of the same
   judge disagree on 6 of 80; Claude disagrees with them on 11 and 17. The provider effect is
   real and larger than the judge's own noise, but any single run carries a few writes of
   noise, and Gemini's lead in strictness over the OpenAI judge's first run (15 against 18) is
   inside it; against Claude (15 against 27) it is not.

## Limits

- 80 writes, chosen by seed for budget, not 133 (README, Deviation). Gemini's 80 were judged
  over four days; writes 62 to 80 were parsed with the code-fence strip, which takes Gemini's
  first answer where writes 1 to 61 took its re-formatted one (the two agreed on 74 of 75
  re-asks recorded on Nov 7). The three judges are compared on identical
  writes, and the OpenAI judge's full-set numbers are in the airline report.
- One run each for Claude and Gemini; the OpenAI judge's noise is measured, theirs is not.
- Reasoning effort "low" for all three is Docent's mapping of that setting onto each provider's
  thinking controls, not the same amount of thinking.
- The three models are not the same price tier: Docent's default OpenAI model cost about $0.002
  per completed call, Claude Sonnet 5.5 about $0.026 and Gemini 3.1 Pro about $0.03. The
  difference in where they draw the line may be partly one of model size, though Claude and
  Gemini, priced alike, draw it furthest apart. A same-tier comparison (a larger OpenAI model,
  or smaller Claude and Gemini models) was not run.
- Prices used by the meter are the providers' published rates as read that day; the Anthropic
  run spent $9.35 of a $11 cap. The Gemini run's first two days were $4.54 by the meter and $9.93
  by Google's billing, over the $9 cap, because the meter did not see thinking tokens; the third
  and fourth days' $6.05 and $2.46 were metered with them, under extensions the person approved
  (README). The fourth day, with the fence strip, cost about $0.13 a write against $0.22 on the
  third.
- The "Ran" column counts every write the judge would run; "wrong" and "good sent back" by
  the adjudicated truth count only graded writes, so a judge can run more writes than that
  truth can score (Claude: 27, of which 25 graded).
