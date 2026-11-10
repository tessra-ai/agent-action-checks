"""Addendum 2: check known τ²-bench issues against our pinned version and retail runs.

Read-only, no model calls. Three checks:

1. Replay each of our retail tasks' reference actions on a fresh environment and list any that
   raise (the class of τ²-bench issue #499).
2. Find conversations the simulated customer ended in the same message that confirmed a pending
   write (τ²-bench issue #182), and count our 73 actions that come from them.
3. List multi-item `modify_pending_order_items` calls on task 100 and whether their pairs are
   in the reference order (τ²-bench issues #318 and #325).

Needs the `tau2` extra and the store copies in `runs/docent/` (see `export_runs.py`).

    python experiments/2026-10-25-docent-vs-oracle/tau2_issues_check.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tau2.domains.retail.environment import get_environment, get_tasks

from hatchway.bench.store import BenchStore

HERE = Path(__file__).parent
STORES = ("runs/docent/targeted.db", "runs/docent/smoke2.db")
ORACLE_VERSION = "tau2-oracle-1:41ee37217182"
ASKS_TO_CONFIRM = re.compile(r"confirm|proceed\?|\(yes", re.I)
SAYS_YES = re.compile(r"\byes\b|go ahead|proceed", re.I)


def failing_reference_actions(task_ids: set[str]) -> dict[str, list[str]]:
    tasks = {t.id: t for t in get_tasks()}
    out = {}
    for tid in sorted(task_ids, key=int):
        env = get_environment()
        errors = []
        for a in tasks[tid].evaluation_criteria.actions or []:
            try:
                env.make_tool_call(a.name, requestor=a.requestor, **a.arguments)
            except Exception as e:  # any tool error counts
                errors.append(f"{a.action_id} {a.name}: {e}")
        out[tid] = errors
    return out


def stopped_on_yes(sim: dict) -> bool:
    msgs = sim["messages"]
    users = [m for m in msgs if m["role"] == "user"]
    if sim.get("termination_reason") != "user_stop" or not users:
        return False
    last = users[-1]
    before = [m for m in msgs[: msgs.index(last)] if m["role"] == "assistant"]
    asked = bool(before) and ASKS_TO_CONFIRM.search(before[-1].get("content") or "")
    said = last.get("content") or ""
    return "###STOP###" in said and bool(asked) and bool(SAYS_YES.search(said))


def main() -> None:
    ours = {json.loads(line)["write_id"] for line in (HERE / "data/runs.jsonl").open()}
    gold = {t.id: t for t in get_tasks()}["100"].evaluation_criteria.actions
    gold_pairs = next(
        list(zip(a.arguments["item_ids"], a.arguments["new_item_ids"], strict=True))
        for a in gold
        if a.name == "modify_pending_order_items"
    )
    task_ids: set[str] = set()
    early: list[tuple[str, str, float | None]] = []
    from_early = 0
    modify: list[tuple[str, str, bool, float | None]] = []
    for path in STORES:
        store = BenchStore(path)
        early_ids = set()
        for s in store.simulations("done"):
            if s.domain != "retail":
                continue
            task_ids.add(s.task_id)
            sim = json.loads(s.simulation)
            if stopped_on_yes(sim):
                early_ids.add(s.session_id)
                early.append((path, s.task_id, s.reward))
            for m in sim["messages"]:
                for c in m.get("tool_calls") or []:
                    a = c["arguments"]
                    if c["name"] == "modify_pending_order_items" and len(a["item_ids"]) > 1:
                        pairs = list(zip(a["item_ids"], a["new_item_ids"], strict=True))
                        modify.append((path, s.task_id, pairs == gold_pairs, s.reward))
        from_early += sum(
            r.write_id in ours and r.session_id in early_ids
            for r in store.proposed_actions(ORACLE_VERSION, require_verdicts=False)
        )
        store.close()
    print("1. Reference actions that raise on replay:")
    for tid, errors in failing_reference_actions(task_ids).items():
        print(f"   task {tid}: {'; '.join(errors) or 'none'}")
    print(f"2. Conversations ended by the customer on a yes: {len(early)} {early}")
    print(f"   Of our 73 actions, from those conversations: {from_early}")
    print("3. Multi-item modify_pending_order_items (store, task, reference order, reward):")
    for row in modify:
        print("  ", row)


if __name__ == "__main__":
    main()
