# Closing write-up, M1: numbers

**Status:** M1 done, waiting at the gate. Train and dev only; the two test splits (64 unseen-task
and 90 repeat-task actions) are counted from `M0/splits/manifest.json` and never read. The exception is the first post's figures that the brief repeats. Those are earlier published
aggregates over both airline captures, and the sealed test actions were later drawn from those
same captures (unseen-task actions from both, repeat-task actions from the second). So they are not
evidence independent of the sealed sets. No per-action test result is read. No calls
were made. Every number is provisional and model-labelled.

## How the numbers are built

- `actions.py` is the one step that reads the git-ignored M0 packets. It checks their sha256
  against the one the M1 labels were built on. It reads capture metadata for train and dev
  actions only, skipping other lines before decoding, and then writes `results/actions.json`: one row per
  action with the ruling, both labellers' answers, the agent model and the backend outcome. It
  holds no conversation text except the asked statements' own sentences.
- `build_numbers.py` reads committed files only and writes `numbers.json`:
  - `results/actions.json`;
  - the M0 and M1 result files;
  - the earlier experiments' result files;
  - the 38-actions read, copied unchanged into `results/` from branch `rely/uncaught-38` at commit `1453956`.

  Each figure is a count with its denominator and a rate. Where the first post gave a bound, the
  figure also carries a 95% upper bound computed the same way: one-sided exact Clopper–Pearson,
  as in `2026-10-28-airline-veto/analyze.py`. A self-check reproduces that post's 56%, 9% and 27%.
  The two judge runs score the same actions, so they are not independent trials: pooled judge
  and full-stack counts are descriptive figures only, and bounds are given per run.
  Caveat on all bounds: several actions come from the same task and can fail together, so a
  bound that treats actions as independent trials overstates precision somewhat. The first post
  had the same caveat. Clopper–Pearson is kept because the post's style uses it.
  For catch counts the bound is on the share **missed**, the analogue of that post's "wrong
  actions run".
- `numbers.json` → `checks` compares 43 figures with the handover brief.

## Mismatches with the brief

| Figure | Brief | From the files | Why |
|---|---|---|---|
| Conversation tokens, 95th percentile | 2,552 | 2,548 | 2,552 is from the v0 and v1 packet files (`token_lengths.json`, `_v1.json`). The v2 packets the labels were built on give 2,548 (`token_lengths_v2.json`). |
| The 21 both-yes statements by type | 12 eligibility, 3 ranking, 6 other | 11 / 5 / 5 under the plain keyword rule; 12 / 3 / 6 under the alternative reading | No committed typing existed, so both rules are written into `build_numbers.py`. They differ on three sentences: P030.S1 (a booking-time fact that decides the 24-hour window) and P052.S2 / P152.S2 ("the pricier one", which names an item). The difference is definitional, not an error. |
| Design C, bad caught and good stopped | 87 to 89; 10 to 11 (with 56% reaching a frontier model; designs use the 147 graded actions, the standalone cascade all 174) | 87–89 and 10–11 only across both cascade widths; at width 0.2 alone, 88–89 and 11; reaching a frontier model: 82 of the 147 graded actions, 56% (84, or 57%, at width 0.4) | The brief's ranges span widths 0.2 and 0.4, while its 56% is width 0.2 only. The post should name one width. |
| Kev pilot cost, "about $30 to $35" | stated | not in any file | No committed file records the Modal bill. `numbers.json` keeps the GPU wall-clock seconds of the final fold runs instead. Leave dollars out of the post, or quote the Modal invoice. |

All other figures checked match: data counts, labeller counts, kappas, coverage, the consensus
gate, the stock models, the Kev pilot, the Jev trade-off, the cascade, the 38 uncaught actions,
the three designs, and the first post's figures that the brief repeats. One check of mine
initially compared the OpenAI judge's two runs separately; the brief's "about 6 in 10" is their
mean, 16.5 of 26, which matches.

## The three cuts an outside review reported

**a) "Never agreed" catches by agent model: confirmed, 31 of 39 from gpt-4.1-nano.**
- The other 8 come from gpt-4.1-mini (6) and gpt-4.1 (2).
- Caveat: gpt-4.1-nano ran only in the retail capture. All 31 nano cases are retail, and all 8
  others are airline. Agent model and domain are confounded, so this cut alone cannot say whether
  the weaker agent or the retail tasks drive "never agreed".

**b) Bad actions the backend rejected anyway: confirmed, 47 of 91 (35 retail, 12 airline).**
- The backend also rejected 2 of 56 good actions.
- On the 44 bad actions that did execute:

| Design | Executed bad actions caught (of 44) |
|---|---|
| Labellers' consensus alone | 26 |
| A: rules, then the cascade (width 0.2) | 40 |
| B: rules, Jev at the 5% cap, then the judge | 42 (run 1), 40 (run 2) |
| C: rules, the cascade, then the judge (width 0.2) | 43 (run 1), 42 (run 2) |

Most of the consensus gate's catches (27 of its 53) were actions the backend would have refused
anyway. For the post this matters: "never agreed" catches mostly a weak retail agent's failed
attempts. The designs hold up much better on executed actions.

**c) The 21 both-yes statements by type: reproduced only under one reading.** See the table above.
`numbers.json` keeps both counts and each sentence with its type.

## By packet length (M0's gate decision)

`numbers.json` → `by_packet_length` reports the consensus gate and every design within and over
8,192 tokens. Over the limit there are 14 packets, all airline: 6 bad and 4 good.

| | Consensus gate, bad caught | Design A (width 0.2), bad caught | Good stopped (consensus, A) |
|---|---|---|---|
| Within 8,192 tokens | 52 of 85 | 71 of 85 | 1 of 52, 3 of 52 |
| Over 8,192 tokens | 1 of 6 | 5 of 6 | 0 of 4, 0 of 4 |

Six bad actions are too few for a rate. What they show is that the consensus labels themselves
caught almost nothing in the longest packets, while the rules carry design A there.

## Files

- `actions.py` → `results/actions.json` (git-ignored packets in, committed table out)
- `build_numbers.py` → `numbers.json`
- `results/uncaught_38_table.json`, `results/uncaught_38_types.json` (copies; source commit above)
- `Report.md` (this file)
