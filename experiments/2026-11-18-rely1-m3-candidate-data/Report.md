# Candidate M3 data sources: audit only (2026-11-18)

| | |
|---|---|
| **Status** | `diagnostic`. Audit only: **neither dataset is used for anything until Prithvi says so**. Nothing was downloaded into the repository |
| **Question** | Can two public Hugging Face datasets add M3 training volume: licence, overlap with our test task IDs, and how many actions look correct? |
| **Spend** | $0. Public downloads only |
| **Who** | A Claude subagent read the cards and the data; Claude re-checked the licence tags and the Snorkel task mapping independently (below) |

Reference: τ²-bench airline at commit `c5b2d228` (`tasks.json`, `db.json`, `policy.md`); τ²-bench
is MIT (Sierra Research). Test task IDs from M0: unseen set 5, 6, 8, 18, 19, 26, 27, 28, 30, 39,
47 (11 tasks); repeat set 26 tasks, which are also train/dev tasks by design.

## Summary

| | `snorkelai/Tau2-Bench-Airline-With-Code-Agents` | `Henryoung/WRIT-2K` |
|---|---|---|
| Revision read | `81702cb` | `ea52f2f` |
| Licence | Apache-2.0 (API tag, card front matter and card text agree; no LICENSE file) | MIT (API tag and card front matter; no LICENSE file, no licence text in the card) |
| Training / redistribution | Both allowed; keep the notice, state changes | Both allowed; keep the notice |
| What it is | The 50 τ² airline tasks themselves, 5 agent models × 2 agent styles: 500 conversations | 1,000 new synthetic airline scenarios (and 1,000 retail) on the same `c5b2d228` database and policy |
| Conversations from **unseen-set** tasks | **110 of 500** (all 11 tasks, 10 each). Exact | **0 of 1,000** match a τ² task; but 26 reuse a *user* from an unseen-set task. Rough |
| Conversations from **repeat-set** tasks | 260 of 500. Exact | 0 by task; 48 reuse a repeat-set task's user. Rough |
| Write actions | 258 discrete write calls (tool-calling half only; the code-agent half edits the database in Python, so it has no separate actions) | 936 airline write calls in 660 of 1,000 airline trajectories |
| Correctness signal | Task-level reward only (COMMUNICATE + DB) | None in the data |
| Actions that look correct (rough) | 98 of 258 writes are in reward-1 conversations: an upper bound, not per-action truth | All 936 replay without error on `c5b2d228`. 832 (≈89%) follow a customer "yes / proceed / confirm". A rule check on cancellations found 2 with no policy basis. No real verdict |

## Notes per dataset

**Snorkel (Apache-2.0).**
- Every row's `user_scenario.instructions` is identical to `tasks.json` for its `task_id` (500 of
  500, re-checked by Claude). The mapping is certain.
- Training on it as is would put the unseen-set tasks, solved 10 times each, into training. **The
  110 unseen-set rows must be dropped** before any use. The 260 repeat-set rows are the same
  tasks as our repeat test set, so they weaken that set's "new conversations of known tasks"
  reading too, though not its definition.
- The task reward is not a per-action verdict. 78 writes are identical to a τ² reference action,
  but 52 of those sit in failed conversations. And τ²'s reference is not the only valid path.
- Agents: GPT-5, Claude Sonnet 4.5, Gemini 2.5 Pro, Kimi K2, Qwen3-Coder. The user simulator is
  not named. The traces carry no system prompt or policy. Replaying the tool calls against
  `c5b2d228` reproduced 1,847 of 1,849 outputs (two trivial misses).
- Model-output terms of the commercial providers may limit training on their outputs. That is
  not part of the dataset licence, but it needs a check before use.
- The card has copy-paste errors (an "underwriter", a field that does not exist).

**WRIT-2K (MIT).**
- No task IDs, rewards, labels or model names: the card says generation metadata was removed.
  The generating models are undisclosed, so their providers' terms cannot be checked.
- It was mapped to τ² tasks by content: users and reservations against `db.json`, write calls
  against τ² reference actions, and distinctive 5-word phrases from task instructions. No
  trajectory matches a task. 90 of 1,000 airline trajectories use a user that also appears in a τ²
  task: 26 from unseen-set tasks, 48 from the repeat set, 16 other. 25 also touch that task's
  reservation (5 unseen). Spot-reads show different requests. **If used, the 26 unseen-set-user
  trajectories should still be dropped**, since they handle the same customer records.
- Its system prompt is `c5b2d228`'s `policy.md` word for word. All 6,657 airline tool calls
  replay identically, and no tool errors exist at all, so the data was probably filtered to
  clean runs.
- 594 of 2,000 trajectories have scripted user-side perturbations; half the data is retail.
- Two writes look like real policy violations (reservation 3I818F, rows 698 and 785: an economy,
  uninsured cancellation for a delay, and a $150 certificate).

## Bottom line

- **Snorkel** is the most direct match (real τ² tasks, with a task reward), but it is small (258
  writes), carries no per-action truth, and contains our unseen tasks: usable only after dropping
  110 rows, and only as a weakly labelled source.
- **WRIT-2K** is larger (936 airline writes) on the same database and policy, with no labels at
  all. It could feed M3's teacher labelling and planted errors, after dropping the 26
  unseen-set-user trajectories.
- **Exact:** the Snorkel mapping, licence tags, row and write counts. **Rough:** the WRIT entity
  overlap and rule checks, and every "looks correct" figure.

## Checked by Claude

- Licence tags from the Hugging Face API at the revisions above: `license:mit` and
  `license:apache-2.0`; neither is gated.
- Snorkel: 500 rows; instructions identical to `tasks.json` for the same ID in 500 of 500;
  unseen 110, repeat 260, other 130.
- Not re-checked: the WRIT figures and the write and replay counts, which come from the
  subagent's read only.
