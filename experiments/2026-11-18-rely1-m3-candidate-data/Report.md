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
| Conversations from **unseen-set** tasks | **110 of 500** (all 11 tasks, 10 each). Exact | **0 of 1,000** match a τ² task; but 26 reuse a *user* from an unseen-set task (re-checked; now excluded) |
| Conversations from **repeat-set** tasks | 260 of 500. Exact | 0 by task; 44 to 49 reuse a repeat-set task's user, by definition |
| Write actions | 258 discrete write calls (tool-calling half only; the code-agent half edits the database in Python, so it has no separate actions) | 936 airline write calls in 660 of 1,000 airline trajectories |
| Correctness signal | Task-level reward only (COMMUNICATE + DB) | None in the data |
| Actions that look correct (rough) | 98 of 258 writes are in reward-1 conversations: an upper bound, not per-action truth | All 936 replay without error on `c5b2d228`. 746 to 849 (80–91%) follow a customer confirmation word, by word list. A rule check on cancellations found 2 with no policy basis (re-checked). No real verdict |

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
  trajectory matches a task. 84 to 91 of 1,000 airline trajectories (by definition; see "Checked
  by Claude") use a user that also appears in a τ² task: 26 from unseen-set tasks, 44 to 49 from
  the repeat set, 14 to 16 other. The helper's spot-reads show different requests. **The 26
  unseen-set-user trajectories are dropped** (`writ2k_exclude.json`), since they handle the same
  customer records.
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
  all. It could feed M3's teacher labelling and planted errors, with the 26
  unseen-set-user trajectories dropped.
- **Exact:** the Snorkel mapping, licence tags, row and write counts. **Rough:** the WRIT entity
  overlap and rule checks, and every "looks correct" figure.

## Checked by Claude

- Licence tags from the Hugging Face API at the revisions above: `license:mit` and
  `license:apache-2.0`; neither is gated.
- Snorkel: 500 rows; instructions identical to `tasks.json` for the same ID in 500 of 500;
  unseen 110, repeat 260, other 130.
- **WRIT-2K, re-checked by Claude with its own scripts** (`writ_check.py`,
  `writ_check_definitions.py`; file sha256 in `writ2k_exclude.json`). User IDs are those in each
  τ² airline task (`tasks.json` at `c5b2d228`), kept if they exist in `db.json`.

  | Figure | Helper | Claude | Note |
  |---|---|---|---|
  | Rows (airline / retail) | 1,000 / 1,000 | 1,000 / 1,000 | exact |
  | Airline write calls | 936 | 936 | exact; same split by tool (cancel 290, book 209, flights 193, passengers 101, baggages 99, certificate 44) |
  | Airline trajectories with a write | 660 | 660 | exact |
  | Trajectories using a τ² task's user | 90 | 84 (from tool-call arguments) to 91 (any mention) | depends on the definition |
  | … of which unseen-set users | 26 | **26** | the same 26 rows under both definitions |
  | … repeat / other | 48 / 16 | 44 / 14 to 49 / 16 | depends on the definition |
  | … also touching that task's reservation (unseen) | 25 (5) | 23 (5) | tool-call definition |
  | Writes right after a "yes / proceed / confirm" turn | 832 | 746 to 849 | depends on the word list; a rough proxy only |
  | Cancellations with no policy basis | 2 (rows "698, 785") | 2: file rows **1374 and 1569** | the helper's row numbers were positions among airline rows. Reservation 3I818F: economy, no insurance, booked 2024-05-02, flight delayed (not cancelled). **Both** rows also send a $150 certificate, not one |

  Not re-checked: the full replay of 6,657 tool calls and the remaining cancellation-rule
  counts.

## WRIT-2K exclusion (Prithvi, 2026-11-18)

The 26 airline trajectories whose tool calls name a customer from an unseen-set task are dropped:
`writ2k_exclude.json` lists their file rows, the tasks and the 8 customers involved
(`amelia_davis_8890`, `amelia_rossi_1297`, `amelia_sanchez_4739`, `james_taylor_7043`,
`mei_brown_7075`, `olivia_gonzalez_2305`, `omar_davis_3817`, `sophia_taylor_9065`). That leaves
974 airline trajectories. **Neither dataset is used until Prithvi says so.**
