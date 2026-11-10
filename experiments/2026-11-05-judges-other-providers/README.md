# Docent's judge with other providers' models: Claude Sonnet 5.5 and Gemini 3.1 Pro

| | |
|---|---|
| **Status** | `done` for Claude Sonnet 5.5 (80 writes, $9.35); `done` for Gemini 3.1 Pro (80 of 80, judged over Nov 5 to 8; $9.93 billed by Google for Nov 5 and 6, then $8.51 metered for Nov 7 and 8 under extensions the person approved; writes 62 to 80 parsed with the code-fence strip, see Deviations) |
| **Branch** | `experiment/docent-vs-oracle`; not merged |
| **Question** | Every judge in this work so far is an OpenAI model (Docent's default `gpt-5.6-luna` at low reasoning effort; Jev). With the same Docent judge, the same rubric and the same decision procedure, and only the model swapped to Claude Sonnet 5.5 or Gemini 3.1 Pro, do the airline numbers change? |
| **Data** | The first airline capture's 133 writes (`experiments/2026-10-28-airline-veto/data/runs.jsonl`), the set with the strongest truths (blind graders, the person's review, the corrected benchmark). The held-out capture if the budget allows, reported separately |
| **Spend** | Anthropic: one run, hard cap $9. Google: one run, hard cap $9. Each run probes one write first and refuses to start if the projection over 133 writes exceeds the cap. Prices used by the meter, from the providers' published tables as read on 2026-11-05: Sonnet 5.5 $2 / $10 per million tokens in / out (cache reads $0.20); Gemini 3.1 Pro preview $2 / $12 (third-party listings; Google's page was not reachable from here). If a run stops at the cap, the writes not judged are reported as missing, never filled in |

## Method (`judge_provider.py`)

Docent SDK 0.1.88, `run_rubric`, majority of 3 rollouts, `max_new_tokens` 6000, the airline
rubric text of `judge_airline.py` verbatim (built from the committed copy of the policy), and
the same output schema. The change is `judge_model` (plus a longer timeout, 240 s against 180,
and lower concurrency, 4 against 8, which do not touch the judgement):

| Run | Provider, model | Reasoning effort |
|---|---|---|
| `docent_1`, `docent_2` (existing) | openai, `gpt-5.6-luna` | low (Docent's default) |
| `claude` | anthropic, `claude-sonnet-5-5` | low (adaptive thinking at low effort, Docent's mapping) |
| `gemini` | google, `gemini-3.1-pro-preview` | low (a thinking budget of a quarter of the output limit, Docent's mapping) |

One run each (the OpenAI judge was run twice to see its noise; the budget allows one run
here, so the noise is not measured for these two).

## Metrics, against the corrected benchmark (46 of 133 should run) and the adjudicated truth (43 of 91 graded)

1. **The judge alone:** writes it would run (label ALLOW), wrong runs, Clopper–Pearson upper
   bound, good writes sent back. Existing: Docent run 1 ran 30 with 8 wrong under the
   corrected benchmark (`benchmark_corrected.json`).
2. **The veto gate** with Jev's stored answers (run iff Jev P ≥ 0.5 and the judge says ALLOW),
   the same way `gate.py` computes it. Existing: gate 1 ran 22.
3. **Agreement with the OpenAI judge** per write (both run, both stop, one only), and with
   each other; rollout unanimity; label counts.
4. **The old gate's wrong runs** (the 9 under the corrected benchmark): which each judge
   refuses.

No pass/fail label. The question is whether the judge's precision and the gate's numbers are
properties of the design or of the model.

## Deviation (recorded before the Gemini run, after its probe)

The Gemini probe (one write, three rollouts, five metered calls) cost $0.081, a projection of
$10.80 over 133 writes, above the $9 cap and the $10 of credit. The run was not started. Rather
than change the judge (fewer rollouts, a smaller model), it runs on 100 of the 133 writes drawn
with seed 20261105 (`judge_provider.py ... 100`), projected $8.10. The 33 writes left out are
reported as not judged, and every comparison with the other judges is on the 100 judged.

**Second deviation (recorded before either run started).** The projection depends on how
many calls Docent's judge makes for one write, which varies with its retries: the Gemini probe
projected $9.92 for 100 writes on the next attempt, and the Claude Sonnet 5.5 probe projected
$12.17 for 133 ($9.15 for 100). Both runs therefore use the same seeded subset of **80** writes
(`... 80`, seed 20261105; projections $7.90 and $7.30), under the same $9 cap. Every comparison
is on those 80.

**Third deviation.** The Claude Sonnet 5.5 probe for 80 writes projected $9.50 (its probe
counted four calls, one a Docent retry). The cap for that one run is raised to $11 through
`HATCH_JUDGE_CAP_USD` (the meter stops at $10.80); within the approved budget. The Gemini
run keeps the $9 cap.

**Fourth deviation.** The Gemini run reached Google's Tier 1 quota for `gemini-3.1-pro`
(250 generate requests per model per day; the probes and the aborted attempts had used part
of it) after 31 of the 80 writes; the other 49 failed with 429 and are recorded as `FAILURE`
with no label. `judge_provider.py` gained a resume mode (`HATCH_JUDGE_RESUME=1`) that judges
only the writes without a label, keeps the earlier verdicts untouched, and adds the spend to
the usage file. The run resumes after the quota resets; until then every comparison with
Gemini is on the 31 writes it judged, and is marked partial.

**Fifth deviation.** The first resume (after the daily quota reset) judged none of the 49:
a 503 "high demand" on the probe was retried quickly by Docent, the retries used up Google's
other Tier 1 limit (25 requests per minute per model), and Docent's default budget of two
retries gave up on every write ($0.12 spent). `judge_provider.py` gained two environment
knobs, `HATCH_JUDGE_CONCURRENCY` (default 4) and `HATCH_JUDGE_RETRIES` (Docent's default
when unset), and the second resume ran with concurrency 2 and six retries, which lets Docent
wait out the provider's retry hint instead of abandoning the write.

**Found in review (after the runs).** Four things about the meter and the evaluation, none
changing a label: (1) Docent's Google provider reports prompt and candidate tokens only, not
Gemini's thinking tokens (billed as output; the judge runs with a 1,500-token thinking budget
per call), so the metered Gemini spend, $4.54 over 233 calls, is a lower bound; up to about
$4 more may have been billed. The Claude figure includes thinking (Anthropic's output count
does). (2) The cap was enforced per attempt, not over the attempts of a resumed run; it now
counts the earlier attempts' spend. (3) The usage file was written only at the end of an
attempt, so two interrupted attempts' usage had to be reconstructed by hand (commits 35b256c
and dc525f3); it is now written after the probe and after the run. (4) `evaluate.py` scored
every judge on the intersection of the writes the provider runs labelled, so once the partial
Gemini file existed it could no longer regenerate the 80-write comparison; it now writes one
block per provider run (`metrics.json`: `blocks.claude` on the 80, `blocks.gemini` on the writes it labelled),
and the numbers in `Report.md` come from those blocks.

**The Gemini cap was exceeded in fact (2026-11-06).** Because of (1), the $9 cap was enforced on
an undercount. The metered figure is $4.54 (1,899,383 input and 62,149 output tokens over 233
completed calls); the thinking budget adds up to about $4.20, and requests that timed out on
our side but completed at Google were never metered. Google's Gemini API spend page shows
$9.93 for the project as read at 20:30 UTC on 2026-11-06 (about $6.6 on Nov 5 and $3.3 on
Nov 6, Pacific days; the page says costs can take a day to show), over the $9 preregistered
cap. Of that, Nov 6 bought 3 judged writes: most of the day's requests were retries of
Google's 503s and timeouts. `judge_provider.py` now adds Gemini's `thoughts_token_count` to the
output tokens before the meter prices them (checked offline on a constructed response: a
typical call is $0.033, not the $0.016 the meter recorded), so any further Gemini run is capped
on billed tokens. The usage file's past figure is left as metered; the README and Report quote
it as a lower bound.

**Where the Gemini money went (Google's dashboard, 2026-11-06).** Google counted about 255
successful requests on each of Nov 5 and Nov 6, the Tier 1 daily limit, and about 1,000 errors
(mostly 429 rate limits, then 503 overload), which are not billed. Of the roughly 510 billed
requests, 233 produced verdicts we kept. The rest were lost to runs stopped before they wrote
their file (the stalled first attempt, a resume stopped after 20 minutes, a run killed by a
container restart; the script then wrote only at the end, since fixed by `HATCH_JUDGE_CHUNK`),
to aborted probes, and to requests our 240-second timeout abandoned while Google finished and
billed them. The last resume runs with `HATCH_JUDGE_TIMEOUT_S=600`, concurrency 2 and three
retries. Per completed call Gemini cost about what Claude did (roughly $0.03 against $0.026);
Docent's default OpenAI model cost about $0.002, so the provider comparison is also a
comparison across price tiers.

**Day 3 (2026-11-07), under a $10 extension the person approved.** The cap was set cumulatively
(`HATCH_JUDGE_CAP_USD=13.74` over the $4.54 metered before; new metered spend stops near $9,
leaving about $1 for requests the meter cannot see), with the thinking-token fix, a 600-second
timeout, concurrency 2 and three retries. Google answered the first probes with 503 overload
errors; a loop retried every 15 minutes, and from 08:33 UTC six chunks judged 27 writes for
$6.05 metered (about $0.22 a write) before Google's daily limit of 250 requests stopped it at 61
of 80. A refused probe no longer writes the usage file. The remaining 19 writes would need about
$4 at that rate, so the last resume is expected to stop on the cap a few writes short of 80.

**Day 4 budget (approved 2026-11-07).** The Google budget was raised by $5 to finish the
run. The cap rises to `HATCH_JUDGE_CAP_USD=16.30` (new metered spend stops near $5.50 above the
$10.59 already metered). Where Gemini's money goes, per today's logs: about 40% of its calls were
Docent asking again because Gemini's answer failed the judge's output-format check (77 of about
190 calls; each re-ask resends the whole conversation), and each chunk judged its probe write
twice. The second is fixed: the probe's verdict is now kept (`judge_provider.py`). Per completed
call Gemini cost about $0.03 against Claude's $0.026; per judged write about $0.22 against
Claude's $0.12, because of the re-asks and the probes.

**Why Gemini's answers are re-asked (checked 2026-11-07).** Docent's judge asks for the answer as
YAML inside `<response>` tags and parses it that way (its default, `output_parsing_mode` XML_KEY;
no output schema is sent to the model in that mode). On Nov 7, 73 of the 77 failed answers were a
correct JSON answer wrapped in a ```json code fence, which the YAML parser rejects; 4 had no
`<response>` tags. Docent then resends the whole conversation and asks again. The re-ask kept
the first answer's label in 74 of 75 readable cases and changed it once (allow to deny). The
re-asks are about 40% of Gemini's calls and count against Google's daily request limit, which
is why that limit (250) ran out after about 190 metered calls. Stripping a code fence before
parsing, or Docent's constrained-decoding mode, would remove almost all of them. At the
person's request the last 19 writes run with the fence stripped before parsing
(`HATCH_JUDGE_STRIP_FENCES=1`; the prompt, the model and the answer are unchanged, only the
parser accepts a fenced answer instead of asking again). So writes 62 to 80 take Gemini's first
answer where writes 1 to 61 took its re-formatted one; on the 75 readable re-asks of Nov 7 the
two agreed 74 times. The 19 are marked in the results by date and reported as such.

**Pre-run audit (2026-11-07).** A dry run of `judge_provider.py` with a fake Gemini (no network,
no spend; resume, chunk of 3, the real cap) judged 3 writes in exactly 9 calls with the fence
strip, kept the file's order and added to the usage file; without the strip the same fenced
answers took 27 calls and produced no verdict. It also found that the probe check never fired:
a probe whose rollouts all fail returns an empty output, not none, so the run went on. Fixed
(the check now needs a label), and the dry run then stopped after the probe. The resume loop and
the Docent environment's exact packages are now in the repository (`run_gemini_loop.sh`,
`requirements-docent.txt`), so a rebuilt container can run the last resume.

**Day 4 (2026-11-08): complete.** The last 19 writes ran from 08:11 to 08:21 UTC with the fence
strip, in four chunks (one probe refused by Google before the first): 6 format re-asks in all,
against 77 the day before for 27 writes, and $2.46 metered, about $0.13 a write against $0.22.
Gemini is complete at 80 of 80. Billing check (2026-11-09): about $2.25 was billed for the day-4 resume against
$2.46 metered; the meter, with thinking tokens now counted, reads slightly high.
That resume was still slow (Google's 503s and 240-second timeouts, about 4.5 minutes per
write), and the script only writes the file at the end, so it gained `HATCH_JUDGE_CHUNK=N`:
a resume judges the first N writes without a label and writes the file, and a shell loop
calls it until nothing is left. The usage file stays cumulative over the chunks.

## Run order

1. Commit this README, `judge_provider.py`, `evaluate.py`.
2. `judge_provider.py google gemini-3.1-pro-preview airline1 results/gemini_airline1.jsonl`
   (with a Google API key in the environment).
3. `judge_provider.py anthropic claude-sonnet-5-5 airline1 results/claude_airline1.jsonl`
   (with an Anthropic API key in the environment).
4. `evaluate.py` → `results/metrics.json`; `Report.md`.
