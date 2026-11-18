# Rely-1 M0: spec, splits and length audit

| | |
|---|---|
| **Status** | `diagnostic`: gate **not passed** (packets did not fit). **Accepted by Prithvi on 2026-11-18 with decisions**; packet v1 and CV folds added after the gate (Report.md, "Decisions after the gate") |
| **Branch** | `rely/m0-spec` |
| **Question** | Before anything is labelled or trained: is the input defined, are the splits clean, and does one action packet fit Kev-4B's validated context? |
| **Data** | The 328 frozen write actions: 73 retail (`2026-10-25-docent-vs-oracle`), 133 airline (`2026-10-28-airline-veto`), 122 airline (`2026-11-05-airline-holdout`). Read only; no file in those folders is changed or rerun |
| **Spend** | $0. No model or API calls. Downloads: the Kev code (GitHub) and the Qwen3.5-4B-Base / kev-4b tokenizer files (Hugging Face) |

## Packet format (`packets.py`)

One packet per proposed write, in one generic format for every tool and domain:

- **Conversation** up to the proposed action: every customer and agent message in order. The
  **consent turn** is marked: the last customer message before the call (a rule, not a reading;
  see Report.md for where it misses).
- **Proposed action**: tool name, arguments, and the tool's description and parameters, parsed
  from τ²'s source at the capture commit (`c5b2d228`).
- **Policy**: the domain's `policy.md` at the same commit.
- **Evidence ledger**: every tool call the agent made before the action, in order, with tool,
  kind (`read` / `write` / `generic`, from τ²'s decorator), arguments, result and an error flag.
  The conversation shows only `(lookups L3, L4)` where a call happened, so no record appears
  twice.

**Packet v1** (after the gate): identical repeated lookups become pointers to their last copy,
and a "Later calls in the same customer turn (agreement not verified)" section lists the later
write proposals in the same conversation with no customer message in between.

`render()` turns a packet into the single text document a decision model reads (Kev's `state`).
Truth and metadata (`meta`) travel next to the packet, never inside the rendered text.

Truth per action is rebuilt as each experiment built it: airline 1 = graders' majority with
the person's review and corrections; airline 2 = `adjudicated.json`'s rule (graders, first-capture
rulings, the person's review); retail = the policy oracle with the person's review of 10 writes,
which fixes the Gaming Mouse. Actions with no grade have `truth: null`.

## Splits (`splits.py`, frozen in `splits/`)

Groups are (domain, task ID), so every action of one conversation sits in one split. Seed
`20261118`.

1. **test_unseen**: a random quarter of the airline task IDs (10 of 42), every action with
   those IDs in either capture. The anchor tasks (25, 35) were not eligible.
2. **test_repeat**: the rest of the second airline capture: new conversations for known tasks.
   A second-capture task with no train or dev action (task 47) goes to test_unseen instead.
3. **dev**: a quarter of the remaining task IDs per domain, anchor tasks first.
4. **train**: the rest.

Planted errors made in M3 take the split of the action they are made from. Test splits are not
opened again until M5. In this milestone they were only listed by ID: no token count, sentence
or per-action label of a test action was read (see Report.md, "Disclosure on test data").

## Statement units (`sentences.py`)

An agent message is split at line breaks, then at sentence-ending punctuation followed by
whitespace. The audit asks how often one sentence mixes a statement about the proposed action
with one about something else.

## Length audit (`tokens.py`, `trim_options.py`)

State tokens are counted with `kev.model.encode` (strict, serving limits), so Kev's `<state>`
marker and its escaping of caller text are included. A sample direct question for the longest
agent sentence adds the branch tokens. Kev's code: github.com/jaredpalmer/kev @ `2074cc4`.
Tokenizer: `Qwen/Qwen3.5-4B-Base` @ `1001bb4d`, the base revision pinned in kev-4b v1.0's
`provenance.json` (what `kev.checkpoint` loads). The tokenizer files in `jaredpalmer/kev-4b@v1.0`
are counted too as a cross-check. Train and dev only.

## Material-contradiction definition

`label_definition.md`: the definition, ten rules and 25 worked cases from train.

## Run order

Needs `.tau2-bench/` at `c5b2d228` (as earlier experiments) and, for the token counts, a Python
environment with Kev installed **editable** from its checkout at the commit above
(`uv pip install -e .` in the Kev checkout), so `kev` imports from that checkout and
`tokens.py` can confirm its commit. A plain `pip install .` copies it to site-packages, and
`tokens.py` then stops.

1. `python splits.py` → `splits/` (once; refuses to overwrite; reads IDs and task metadata only)
2. `python packets.py` → `runs/packets.jsonl`, train and dev only (git-ignored; sha256 in
   Report.md). It filters by the frozen splits; `--all` builds all 328 for M5.
3. `python folds.py` → `splits/folds.json`, `splits/folds_manifest.json` (once; added after the
   gate, decision 5)
4. `python sentences.py` → `results/sentence_audit.json`, `review/sentence_sample.json`
5. `kev-venv/bin/python tokens.py` → `results/token_lengths_v1.json` (packet v1; v0's file is kept)
6. `kev-venv/bin/python trim_options.py` → `results/trim_options.json` (v0 record; not rerun)
