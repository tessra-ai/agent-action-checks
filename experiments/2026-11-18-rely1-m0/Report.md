# Rely-1 M0 report: spec, splits and length audit

**Gate: not passed.** The splits are clean, but packets do not fit. Train+dev packets have a
95th percentile of **10,382** state tokens, against Kev-4B's validated 8,192. **20 of 174** are
over 8,192. As the plan says, this stops here with the options below. Nothing has been labelled
or trained. Spend: **$0** (no model or API calls).

**Accepted by Prithvi on 2026-11-18 with decisions** (see "Decisions after the gate" at the end).
The packet is now v1: identical repeated lookups are pointers, and later calls in the same
customer turn are context. Re-measured on train+dev: p95 **9,087**, max 12,436, **14 of 174**
over 8,192, all airline. The sections above describe v0 as gated; they are kept as written.

## 1. Paths in "What already exists"

Every path listed in the build plan exists. Counts match the plan.

| Asset | Found | Note |
|---|---|---|
| `2026-10-28-airline-veto/data/runs.jsonl` | 133 actions | with `data/meta.jsonl` (task, session) |
| `2026-10-25-docent-vs-oracle/` `data/runs.jsonl` | 73 actions | task IDs in `data/truth.jsonl`; no session ID (11 tasks) |
| `2026-11-05-airline-holdout/data/runs.jsonl` | 122 actions | 35 task IDs, 33 also in the first capture (confirmed) |
| `claims_{airline1,airline2,retail}_verified.jsonl` | 538 + 465 + 237 = **1,240** statements | in `2026-11-05-airline-holdout/results/` |
| `adjudicated.json`, `grades.jsonl`, `metrics_adjudicated.json`, `*_metrics.json` | all present | `adjudicated.json` is in airline-holdout only; airline-veto has `metrics_adjudicated.json`; retail's equivalent is `adjudication.json` (provisional, Claude-read) plus the person's `review/answers.json` |
| `jev.jsonl`, `docent_1.jsonl`, `docent_2.jsonl` | present for both airline captures | — |
| `2026-11-05-judges-other-providers/` | present | — |
| claims-check folders (3) | present | — |
| `2026-11-05-model-drafted-rules/` | present | — |
| M1 review files: `review/answers.json`, `review/corrections.json`, `results/grades.jsonl`, `2026-11-05-claims-check-retail/review/flags.json` | present | `corrections.json` exists for both airline captures, not for retail |

Nothing is missing. The plan does not list two inputs the packet needs: τ²'s `policy.md` and
tool source at the capture commit (`c5b2d228`). They come from the git-ignored `.tau2-bench/`
checkout, as in the earlier experiments.

The anchor cases, found from the earlier experiments' own "catches":

| Anchor | Write ID | Task | Truth | Split |
|---|---|---|---|---|
| second cheapest | `01M61Q0HD0F0DNRS5WWVBVESGP` | airline 35 | should not run (person's review) | dev |
| certificate balance | `01M61PYGRX51BXSSZ4R86R0CQH` | airline 25 | should not run (person's review) | dev |
| Gaming Mouse | `01M5JZ4FQ7N37RJXVD6FW00S14` | retail 12 | should not run (person's review) | dev |

## 2. Packet format and loader

`packets.py` builds all **328** packets in one format (README.md, "Packet format"); it ran over
all 328 without error while being written. By default it now writes **train and dev only**
(174 packets); `--all` is for M5. `runs/packets.jsonl` is git-ignored and rebuilt
deterministically: sha256 `a5397ef8538343250a61bcd124625140133c1f4788ad5f9e1bd77ce7e213375d`.

- **Truth coverage:** 240 of 328 actions have a truth label. Airline 1: 91 (43 run, 48 not).
  Airline 2: 76. Retail: 73 (27 run, 46 not). The other 88 airline actions were never graded.
  The plan's 108 good / 131 bad used the oracle alone for retail and the graders for airline 2.
  The loader applies the person's retail review, which moves 3 actions from "not run" to "run",
  1 from "run" to "not run" (the Gaming Mouse), and gives the oracle's one UNKNOWN a "not run".
- **Consent turn:** marked as the last customer message before the call. On train, 120 of 133
  marked turns contain an affirmative word. The other 13 are instructions ("Please use the gift
  card with the next smallest balance") or no consent at all ("Wait, what? I specifically want
  the refund on my credit card"). In several of those, the agent acted without a yes. That is
  a signal for the judge, but the marker does not mean "a yes" there.
- **Ledger:** 2,372 `read`, 256 `write` (earlier writes in the same conversation) and 185
  `generic` (`calculate`, transfers) entries across 328 packets. Earlier writes are kept,
  because their results are records too.
- **Tool parameters** are taken from τ²'s Python signature and docstring, not a JSON Schema. Types
  are shown as written (`List[FlightInfo]`). That is enough to read; it is not a validator.

## 3. Material-contradiction definition

`label_definition.md`: the definition, ten rules (this exact action; plan totals against the
plan; direction; later agreement overrides; the proposed call is a record; customer echo;
not covered is not contradicted; only agent statements are units; out of scope; hedges), and
**25 worked cases from train**. These are Claude's reading, to be confirmed by Prithvi in M1.

Two findings for M1 from writing them:

- **The claims check's "false" was wrong twice in 25 cases read** (a fare total compared with a
  charge; a card the call does use marked false). M1 should not pre-fill "contradicted" from
  the claims check without a reader confirming it.
- **Plan totals and rankings need records outside one packet.** A statement that totals several
  calls ("$1,282 for all upgrades") cannot be checked when the other calls have not run. Q2 in
  the definition needs a decision before M1 labels these.

## 4. Splits (frozen)

Seed **20261118**. `splits/manifest.json` holds each list's sha256.

| Split | Actions | Task IDs | Notes |
|---|---|---|---|
| train | 133 | airline 23, retail 8 | airline 77, retail 56 |
| dev | 41 | airline 8 (1, 13, 14, 23, **25**, **35**, 38, 40), retail 3 (**12**, 14, 84) | all three anchors |
| test_repeat | 90 | 26 airline tasks, every one also in train or dev | second capture only |
| test_unseen | 64 | airline **5, 6, 8, 18, 19, 26, 27, 28, 30, 39** (random) + **47** | 32 from the first capture, 32 from the second |

Checks (recomputed from the saved lists):

- No task ID is shared between train, dev and test_unseen, and test_unseen shares none with
  test_repeat: **pass**.
- No conversation (session) appears in two splits: **pass** (0 overlaps).
- test_repeat shares task IDs with train (19) and dev (7) **by design**: that is what a repeat set
  measures. The plan's gate wording ("no task ID in more than one split") cannot hold for the
  repeat set as the plan defines it, so the strict check covers train, dev and test_unseen.
  test_repeat includes new conversations of the anchor tasks 25 and 35.
- **Deviation, stated:** the anchor tasks were excluded from the random draw so that they stay
  development cases (the plan calls them regression checks), then put in dev. The quarter is 10
  of 42 airline task IDs (42 / 4 = 10.5, rounded half to even), drawn from the 40 eligible.
- **Second deviation, stated:** task 47 appears only in the second capture (1 action), so it has
  no train or dev conversation and is not a repeat. It goes to test_unseen with the random ten.
  Found by the Codex pre-commit review; the first draft had it in test_repeat.

Two consequences to note now:

- **Dev is small:** 11 actions that should run (4 retail, 7 airline) and 26 that should not.
  Setting a threshold at an agreed limit for good actions sent back on 11 good actions moves in
  steps of 9%. M4 will need a range, not a point.
- **The unseen-task set took 32 airline actions out of the first capture.** Train has 77 airline
  actions, 22 of them graded "should run".

## 5. Packet lengths (Kev's encoder and tokenizer, train + dev)

Tokenizer: **`Qwen/Qwen3.5-4B-Base` @ `1001bb4d826a52d1f399e183466143f4da7b741b`**
(`Qwen3_5Tokenizer`, transformers 5.23.0). That is the base revision pinned in
`jaredpalmer/kev-4b` v1.0's `provenance.json`, and the one `kev.checkpoint` loads to serve the
adapter. The kev-4b repo's own tokenizer files (tag `v1.0`) gave **identical counts** on all 174
packets. Kev code: github.com/jaredpalmer/kev @ `2074cc44` (package 0.1.0). The model ID
`jaredpalmer/kev-4b` resolves (public, Apache-2.0, LoRA on Qwen/Qwen3.5-4B-Base); only tokenizer
files were downloaded, no weights.

| State tokens (incl. `<state>`) | n | median | p95 | max | over 8,192 | over 7,552 (trained length) |
|---|---|---|---|---|---|---|
| all | 174 | 4,306 | **10,382** | 14,479 | **20** | 30 |
| airline | 101 | 4,665 | 10,717 | 14,479 | 15 | 20 |
| retail | 73 | 3,883 | 9,455 | 12,995 | 5 | 10 |
| + one direct question (longest sentence) | 174 | 4,402 | 10,481 | 14,578 | 21 | 30 |

By section (each counted on its own):

| Section | median | p95 | max |
|---|---|---|---|
| conversation | 865 | 2,552 | 3,851 |
| proposed action | 263 | 472 | 656 |
| policy | 1,695 (airline) / 1,458 (retail) | — | — |
| ledger | 1,649 | 6,270 | 9,929 |

The plan expected conversations near 8,500 tokens at p95 from a character count. Once lookups
move to the ledger, the conversation text is short: 2,552 at p95. **The ledger is the long
part:** 59% of all tokens in the 20 packets over the limit.

## 6. Sentence audit (train)

4,222 agent sentences in 133 train actions (a list marker such as "1." stays with its item); 267 carry one of the earlier extracted claims.

- **Proxy** (a sentence carrying claims scoped both to this call and to another call): 3 of 267.
  It undercounts, because the extractor gave one scope per claim. A claim whose words appear in
  two different sentences (10 of 490) is not attached to either. When the same sentence occurs
  twice ("- Total price: $255" in two turns), the claim goes to the first; the text is the same
  either way, but the turn it came from is not known.
- **Reading a random 40 of the 267** (Claude, one read; `review/sentence_sample_reading.json`):
  **4 of 40** mix the proposed action with another call (3 clear, 1 ambiguous). In every clear
  case the mix is **several targets in one clause**: "I will now proceed to exchange the
  luggage set … and the skateboard …" (two calls), "All three reservations are eligible for
  cancellation". Clause splitting would not separate them.
- **The other problem is the opposite: units too small.** 14 of 40 are list items, and 5 of
  those cannot be read without their lead-in ("- Total price: $255" under "To proceed with the
  booking, I will use the following details:"). Of the 490 train claims, 69 span two code-split
  sentences and 59 were quoted by joining a lead-in to a list item.

**Recommendation:** keep sentences, don't move to clauses. Two generic changes: carry a list
item's lead-in line with it as context, and let the question ask about "this exact action" so a
multi-target sentence can be judged per call. 4 of 40 is one reader's judgement on a small
sample; M1's labels settle it.

## Gate

| Check | Result |
|---|---|
| No task ID in more than one split (train, dev, unseen) | **pass** |
| Split lists saved with hashes | **pass** (`splits/manifest.json`) |
| 95th-percentile packet under 8,192 tokens | **fail**: 10,382 (train+dev, 174 packets) |

### Options (decision for Prithvi)

Measured on train+dev with Kev's encoder (`results/trim_options.json`). None is adopted.

| Option | p95 | max | over 8,192 | Cost |
|---|---|---|---|---|
| A. As is | 10,382 | 14,479 | 20 | — |
| B. Generic trim: a lookup repeated with the same tool, arguments **and result** becomes a pointer to its last copy | 9,000 | 12,419 | 14 | Lossless: a repeat whose result changed (after a write) is kept. Not enough on its own |
| C. B, then cut every result to its first 1,000 tokens | 8,739 | 12,419 | 14 | Lossy: what is cut may be what a statement contradicts |
| D. B, then cut every result to its first 500 tokens | 8,240 | 12,419 | 11 | Lossy; still over at p95 |
| E. Evidence selection: a step that picks the lookups relevant to each statement | not measured | — | — | A second model or retrieval step at run time; must stay kind-agnostic |
| F. Larger Kev: Kev-27B is validated to 65,536 tokens | fits all | — | 0 | Full 51 GB weights, an 80 GB GPU; changes target 3's cost per action |
| G. Kev-4B past 8k: fine-tune Rely-1 with `max_state` ≈ 15k (Kev's trainer allows up to 65,536) | fits all | — | 0 | Kev-4B's own card measured −1.1 pp [−3.4, +1.2] at 16k on contracts, just outside its tolerance; Rely-1's accuracy at those lengths would have to be shown on dev |

Kev-9B has the same 8,192 validated context as Kev-4B, so it does not help. A combination
(B plus G, or B plus E) is possible. My recommendation, as an input only: **B plus G**. B is
lossless and generic. G keeps the model size the plan wants, and trains on the real length
distribution rather than relying on Kev's general-purpose validation. If G's dev results at
lengths over 8k are worse, F is the fallback.

## Files

- `packets.py`, `splits.py`, `folds.py`, `sentences.py`, `tokens.py`, `trim_options.py`
- `label_definition.md`
- `splits/{train,dev,test_repeat,test_unseen}.json`, `splits/manifest.json`, `splits/folds.json`,
  `splits/folds_manifest.json`
- `results/token_lengths.json` (v0), `results/token_lengths_v1.json`, `results/trim_options.json`
  (v0), `results/sentence_audit.json`
- `review/sentence_sample.json`, `review/sentence_sample_reading.json`, `review/consent_13.json`
- `runs/packets.jsonl` (git-ignored; train and dev only). v1 sha256
  `1e0443d79df58982ad5bad031d543a18a96321efe95bafefffa92673e76b7023`; the v0 hash above is history

**Disclosure on test data.** While checking the loader, before the splits existed, Claude
printed per-capture truth totals (for example "airline 2: 40 should not run, 36 should run").
Those totals are the ones already published in `adjudicated.json` and the earlier reports, and
they cover actions now in the test splits. No per-action test label, conversation or length was
read, and nothing in this milestone was chosen from them. The unseen draw used only task IDs and
the seed.

**Codex pre-commit review.** Seven review rounds ran on the uncommitted change. None found a P0
or P1. These P2/P3 findings were fixed: lookup dedup was lossy; task 47 was in the repeat set;
the τ² commit check; claims matched to an ambiguous sentence; closing quotes; list markers split
off as sentences; the train/dev disjointness check skipped a pair; test packets were written in
M0 (now train and dev only, and the second capture's truth is not rebuilt); Kev's editable
install; the audits now refuse an incomplete packet file. Three were left, with reasons:
identical repeated sentences (above); the first capture's truth comes from one grades file that
covers every action, so it is read whole and filtered in memory, and nothing from test actions
is written or used; and the new test imports experiment files that the source distribution
leaves out, as the existing experiment tests already do. Reviews were Codex's default review
(this repository has no AGENTS.md).

All numbers are from one deterministic run. The sentence-mixing rate and the worked-case labels
are one reader's judgement (Claude's), not a person's.

## Decisions after the gate (Prithvi, 2026-11-18)

1. **Packet length.** Remove repeated identical lookups (lossless only), and plan to fine-tune
   Kev-4B on longer inputs. No trimming and no evidence selection. Kev-27B is a reference point
   only. **From now on every result is reported separately for packets under and over 8,192
   tokens**, and the M2 pilot includes the over-limit packets.
2. **Totals over several calls.** The packet carries the other calls the customer agreed to in
   the same plan, and a stated total is checked against all of them.
3. **Consent marker.** Not kept as is. The 13 train actions whose marked message has no "yes" go
   to Prithvi first (`review/consent_13.json`); the marker changes only after his answer.
4. **Split deviations.** Both accepted (anchor tasks in dev; task 47 in test_unseen).
5. **Thresholds.** Not set on dev alone: cross-validation over train + dev, grouped by task.
   Test sets stay sealed.
6. **M1 pre-fill.** The claims-check verdict only picks which statements to look at, never a
   label. Pre-fill comes from Prithvi's rulings, his corrections and the graders' reasons.
7. **Statement unit.** Sentences, with a list item's lead-in line carried as context.

### What changed (packet v1)

- `packets.py`: `dedup_ledger()` (decision 1) and `plan_calls()` with a new rendered section,
  "Later calls in the same customer turn (agreement not verified)" (decision 2). A call is listed
  when it is a later write proposal in the same conversation, its history contains this call, and
  no customer message comes between them. This call may have run inside a batch with other
  calls. Distinct calls other than this one (a retry of the same call is not another call), in
  proposal order.

**Decision 2 is implemented narrower than asked, pending Prithvi.** The decision says "the other
calls the customer agreed to". "No customer message in between" does not show agreement: the
Gaming Mouse return is itself such a later call (the agent returned the mouse right after the
other items, with no customer message, against the customer's "keep the mouse"). Found by the
Codex pre-commit review. Telling which later calls were agreed needs a reading, not code, so the
section is titled "agreement not verified", and the review sheet asks the reviewer to judge
agreement when checking a total. Options: keep it so (the model judges agreement too); or add a
per-call "agreed?" question to the M1 sheet and keep only agreed calls in later packets.
- `trim_options.py` is kept as the v0 record and is not used further.

**One caveat on decision 2.** No captured action proposes more than one call at a time: every
later call was proposed *after* this one ran. In the captures they are known; a live gate
checking the first call would not have them, unless the agent states its plan or proposes the
calls together. 21 of 174 train+dev packets carry later calls. Training on them teaches the
model to use information a live first call lacks. The packet keeps the section separate, so a
run without it can be measured. That comparison is worth having before M4.

### Lengths, packet v1 (Kev encoder and tokenizer as above; train + dev)

| State tokens | n | median | p95 | max | over 8,192 |
|---|---|---|---|---|---|
| all | 174 | 4,278 | **9,087** | 12,436 | **14** |
| train | 133 | 4,455 | 8,377 | 12,436 | 8 |
| dev | 41 | 3,932 | 11,042 | 11,043 | 6 |
| airline | 101 | 4,694 | 9,352 | 12,436 | 14 |
| retail | 73 | 3,900 | 6,964 | 7,443 | 0 |

Sections (median / p95 / max): conversation 865 / 2,552 / 3,851; proposed action
263 / 472 / 656; later calls 18 / 87 / 418; policy 1,695 (airline), 1,458 (retail); ledger
1,632 / 4,853 / 7,416.

The over-limit group is small: **4 good, 6 bad, 4 ungraded** actions (train + dev). Every
over/under result will rest on those counts and will say so. The three anchors are all under
(3,355 to 5,328 tokens).

### Good and bad actions per split and fold

Folds: `folds.py`, k = 5, seed 20261118, grouped by (domain, task) over train + dev, balanced on
the larger share of good or bad. Hashes in `splits/folds_manifest.json`.

| | actions | good | bad | ungraded | tasks |
|---|---|---|---|---|---|
| train | 133 | 45 | 65 | 23 | 31 |
| dev | 41 | 11 | 26 | 4 | 11 |
| fold 0 | 34 | 11 | 18 | 5 | 8 (6 airline, 2 retail) |
| fold 1 | 31 | 12 | 18 | 1 | 6 (3, 3) |
| fold 2 | 41 | 11 | 18 | 12 | 11 (9, 2) |
| fold 3 | 36 | 11 | 18 | 7 | 9 (8, 1) |
| fold 4 | 32 | 11 | 19 | 2 | 8 (5, 3) |

Each fold's good-action rate moves in steps of about 9% (one action in 11). A threshold set
across all five folds rests on 56 good actions.

### Consent: the 13 cases (`review/consent_13.json`)

Claude's read of each full conversation, for Prithvi's answer:

| Read | Count | Write IDs |
|---|---|---|
| Agreed earlier; the marked message only chooses or changes the payment | 5 | `01M61PXM3NRZ465H5C04ZSK9HS`, `01M61PXMEYT40YTMG6Z2179RRR`, `01M61Q71WGYZWHH0AW1FCWVKP6`, `01M61Q95BW3S5HF0MZV7BCFSZS`, `01M61Q96DSP7Z14FDFD7DBCK08` |
| Agreed in the marked message without a yes-word | 2 | `01M5JZ4HDTBD3TFZNSCV5SF34S` (asks for the return), `01M5JZ91W7FWACM25ZX0E5W1KG` ("Alright, fine. Return everything …") |
| Refused this call in the marked message | 2 | `01M5JZ53BEFJZ298SGE8SY5R9V`, `01M61Q1KSECAJ17000CGCZRZ6J` |
| Never agreed to this call (asked for something else, or never confirmed specifics) | 4 | `01M5JZ53HDAV2K8DP4RDA51Y1V`, `01M5JZ5BZQ37Z0YKPTD97HJA3A`, `01M5JZ4D5E6CMP314QYVP9GPAN`, `01M61QBD9PW1G7Y0B2Y885TT4F` |
