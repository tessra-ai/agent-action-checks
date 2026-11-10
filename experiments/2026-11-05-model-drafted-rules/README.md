# Model-drafted rules against hand-written ones: τ²-bench airline

| | |
|---|---|
| **Status** | `done`: see `Report.md`. Five drafts: three OpenAI ($0.089) and two Claude Sonnet 5.5 calls ($0.189, the first truncated; see Deviation) |
| **Branch** | `experiment/docent-vs-oracle`; not merged |
| **Question** | The 16 airline rules of `experiments/2026-10-28-airline-rules` were written by hand by someone who had seen the failures. Can a model draft rules from the policy text alone, and how do its rules compare on the same 133 writes? |
| **Data** | The 133 airline writes and pre-action snapshots of `experiments/2026-10-28-airline-veto` (`runs/airline/export.db`, read-only). No new conversations |
| **Spend** | Three drafting calls, hard cap $1 through the same metered client as the claims checks. No other calls |

## Why

If the rules layer only works when an expert writes it after seeing the data, it is a service,
not a product. If a model drafts a comparable set from the policy alone, the layer is cheap to
stand up for a new policy and the expert's job becomes review.

## What the drafter sees (`brief.py`)

The airline policy text, verbatim; the database schema with one example record of each kind
(synthetic τ² data); the six write tools and their argument shapes; and the Python interface:
`check(ctx)` returning `(rule_id, reason)` pairs, where `ctx` carries the proposed call, the
database just before it, the user ids the customer typed and the writes that already succeeded.
That is the same input the hand-written rules get (`rules.py`'s `Context`), built by the same
code. The drafter never sees the hand-written rules, any conversation, any write, or any result.
A rule the policy does not state must be prefixed `INFERRED_`, so it can be reported with and
without, as the hand-written `DUPLICATE_SEAT` was.

Rules that need something only the conversation can tell (confirmation, the customer's stated
reason) are out of scope for both sets: the hand-written rules ask Jev for those facts; the
drafts are told to block only on what the records show.

## Drafts

| Name | Model | Temperature |
|---|---|---|
| `gpt41_t0` | `gpt-4.1-2025-04-14` | 0 |
| `gpt41_t1` | `gpt-4.1-2025-04-14` | 1 |
| `gpt41mini_t0` | `gpt-4.1-mini-2025-04-14` | 0 |
| `claude_sonnet55` | `claude-sonnet-5-5` | none accepted (default sampling); 8k output budget, thinking on by default: truncated |
| `claude_sonnet55_b` | `claude-sonnet-5-5` | none accepted; 32k budget, thinking off |

A Claude Sonnet 5.5 draft was planned (`draft_claude.py`, same brief and cap; the model accepts
no temperature, so it runs at its default sampling). It did not run at first
because no Anthropic API key was available in the environment; it ran later, with
`ANTHROPIC_API_KEY` set, and `run_drafts.py` scored it (that needs the local capture store
`runs/airline/export.db`). The metrics were recomputed with the three-draft numbers kept.

Each draft is one call, saved verbatim (`results/drafts/<name>.py`, usage in
`results/drafts.jsonl`). No edits to drafted code, ever: a draft that fails to import scores
as "allows everything"; a rule that raises on a write counts as no block for that write, and
the error is recorded.

## Deviation: a second Claude call

The first Claude call (`claude_sonnet55`, $0.090) stopped at its 8,000-token output budget with
a module cut off mid-statement: the model thinks by default and the script's budget covered
the thinking, not the code. That draft is kept and scored as the README says (it does not
import, so it allows everything). The recorded import error is a `SyntaxError` on line 1:
the reply's opening fence was never closed, so `extract_code` saved the reply whole, fence
line included (fixed afterwards to take the text after an unclosed fence). The outcome is
the same either way: the cut module defines no `check`. A second call (`claude_sonnet55_b`, `draft_claude.py b`) was
made with thinking off and a 32,000-token budget, worst case $0.33, under the same cap. Both
are reported. The budget was the script's mistake, not the model's; the OpenAI drafts had the
same 8,000-token limit and no thinking.

## Metrics (against the same truths as the hand-written report)

For each draft, for the drafts without their `INFERRED_` rules, and for the hand-written rules
(blocks only, with and without `DUPLICATE_SEAT`; and as the report's `rules` gate, where an
unanswered fact also stops the write):

1. **False blocks:** writes blocked that the corrected benchmark says should run (of 46), and
   that the adjudicated truth says should run (of 43). Hand-written: 2 of 46.
2. **Wrong runs:** writes let through that should not run, with the Clopper–Pearson upper
   bound. Hand-written: 18 of 62 ran (corrected benchmark).
3. **Catches:** which of the old gate's wrong runs (`gates.json`, `old_gate_wrong_runs`) each
   draft blocks.
4. **Agreement with the hand-written rules** per write (both block, both allow, one only), and
   per rule: fires, false blocks, and which hand-written rule it corresponds to (read by hand
   in the report).
5. **Draft spread:** the union and intersection of the three drafts; import or runtime errors.
6. With Docent behind each (the veto's `docent_1_run`), the same as the hand-written
   `rules_docent_1` gate. (`evaluate.py` as first run scored only the blocks-only hand arms with
   Docent; it was fixed in review to score the `rules` gate too, without regenerating
   `results/metrics.json`, whose other numbers it reproduces exactly.)

No pass/fail label. The question is descriptive: how close does a draft come to the
hand-written set on false blocks and wrong runs, and what does it miss or add.

## Run order

1. Commit this README, `brief.py`, `draft.py`, `run_drafts.py`, `evaluate.py` and the tests.
2. `draft.py` → `results/drafts/*.py`, `results/drafts.jsonl` (once).
3. `run_drafts.py` → `results/<name>.jsonl` (once per draft; subprocess, no edits).
4. `evaluate.py` → `results/metrics.json` (once); `Report.md`.
