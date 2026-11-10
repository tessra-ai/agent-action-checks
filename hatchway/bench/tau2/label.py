"""Compare captured τ²-bench writes with each task's reference trace (benchmark match).

Every captured write gets `MATCH`, `MISMATCH` or `AMBIGUOUS` against the task's ground-truth
action list. This is a trace comparison for τ² analysis, **not a safety label**: a call can
match the trace and still break the policy (retail task 13's PayPal refund), or miss the trace
and be a valid alternative. Whether a proposed write may execute is the policy oracle's verdict
(`hatchway.bench.tau2.verdicts`), and every metric of the gate is computed against that.

A match judges the proposed call, not its outcome: a write the environment rejected with an
error matches the same as one that ran. One session's writes are matched together, in `seq`
order.

Matching rules:

1. Ground truth is the task's `evaluation_criteria.actions` requested by the assistant. Actions
   requested by the user (telecom device steps) are never proposed by the agent and are ignored.
2. A write *matches* a ground-truth action when the tool name is equal and the compared
   arguments are equal. Compared arguments are the action's `compare_args` when τ² sets them;
   otherwise every argument named by either side. This is τ²'s `Action.compare_with_tool_call`,
   made stricter in one place: τ² compares only the keys the call supplies, so a call that
   leaves out an argument could still match; here it does not.
3. `MATCH`: the write matches a ground-truth action that no earlier write in the session
   matched. Each ground-truth action is matched at most once, so a task that needs the same
   call twice gets two matching writes.
4. `AMBIGUOUS`:
   a. the write repeats a ground-truth action an earlier write already matched (a retry or a
      duplicate; whether it does harm depends on what the first call did);
   b. the write matches a ground-truth action of the same tool only after sorting list
      arguments (e.g. the same items listed in another order, which can pair them
      differently);
   c. the task is not scored on the final database (no `DB` in its reward basis, as in
      telecom, which is scored by environment assertions) and the tool appears nowhere in its
      ground truth: there the ground truth is one valid path, not the only one, so an extra
      write is not wrong by itself.
5. `MISMATCH`: every other write. That is a tool that is not in the ground truth of a
   DB-scored task (in retail the ground-truth actions define the target database, so any
   other write that runs breaks it; when the ground truth has no writes the right answer was
   to refuse or transfer), or a ground-truth tool called with different arguments.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hatchway.bench.store import BenchmarkMatch, BenchStore
from hatchway.state import canonical_json


@dataclass(frozen=True)
class GoldAction:
    name: str
    arguments: Mapping[str, Any]
    compare_args: tuple[str, ...] | None = None


@dataclass(frozen=True)
class GroundTruth:
    """The assistant's ground-truth actions for one task, and how the task is scored."""

    actions: tuple[GoldAction, ...]
    db_scored: bool

    @classmethod
    def from_task(cls, task: Any) -> GroundTruth:
        """Build from a `tau2.data_model.tasks.Task`."""
        criteria = task.evaluation_criteria
        if criteria is None:
            return cls(actions=(), db_scored=False)
        actions = tuple(
            GoldAction(
                name=a.name,
                arguments=dict(a.arguments),
                compare_args=tuple(a.compare_args) if a.compare_args is not None else None,
            )
            for a in criteria.actions or []
            if a.requestor == "assistant"
        )
        basis = {str(getattr(b, "value", b)) for b in criteria.reward_basis or []}
        return cls(actions=actions, db_scored="DB" in basis)


@dataclass(frozen=True)
class Explanation:
    """A write's benchmark match, the matching rule that set it, and the ground-truth action it
    matched (an index into `GroundTruth.actions`), if any."""

    match: BenchmarkMatch
    rule: str
    gold_index: int | None = None


def match_session(
    writes: Sequence[tuple[str, Mapping[str, Any]]], truth: GroundTruth
) -> list[BenchmarkMatch]:
    """Match one session's writes, given as `(action, args)` in `seq` order."""
    return [e.match for e in explain_session(writes, truth)]


def explain_session(
    writes: Sequence[tuple[str, Mapping[str, Any]]], truth: GroundTruth
) -> list[Explanation]:
    """`match_session`, with the rule behind each match."""
    matched = [False] * len(truth.actions)
    gold_tools = {a.name for a in truth.actions}
    explanations: list[Explanation] = []
    for action, args in writes:
        exact = [i for i, g in enumerate(truth.actions) if _matches(g, action, args)]
        unmatched = [i for i in exact if not matched[i]]
        sorted_match = [
            i for i, g in enumerate(truth.actions) if _matches(g, action, args, sort_lists=True)
        ]
        if unmatched:
            matched[unmatched[0]] = True
            explanation = Explanation("MATCH", "3", unmatched[0])
        elif exact:
            explanation = Explanation("AMBIGUOUS", "4a", exact[0])
        elif sorted_match:
            explanation = Explanation("AMBIGUOUS", "4b", sorted_match[0])
        elif action not in gold_tools and not truth.db_scored:
            explanation = Explanation("AMBIGUOUS", "4c")
        else:
            explanation = Explanation("MISMATCH", "5")
        explanations.append(explanation)
    return explanations


def match_store(
    store: BenchStore, truths: Mapping[tuple[str | None, str | None], GroundTruth]
) -> Counter[BenchmarkMatch]:
    """Record the benchmark match of every write that has none. `truths` is keyed by
    `(domain, task_id)`.

    Returns the count of matches recorded. Raises KeyError, before recording any, if a write's
    task has no ground truth.
    """
    sessions: dict[str, list] = defaultdict(list)
    for write in store.writes():
        sessions[write.session_id].append(write)
    missing = {
        (w.domain, w.task_id)
        for ws in sessions.values()
        for w in ws
        if (w.domain, w.task_id) not in truths
    }
    if missing:
        raise KeyError(f"no ground truth for (domain, task_id): {sorted(missing, key=str)}")

    counts: Counter[BenchmarkMatch] = Counter()
    for writes in sessions.values():
        writes.sort(key=lambda w: w.seq)
        tasks = {(w.domain, w.task_id) for w in writes}
        if len(tasks) != 1:
            raise ValueError(f"session {writes[0].session_id} spans tasks {sorted(tasks, key=str)}")
        explained = explain_session([(w.action, w.args) for w in writes], truths[tasks.pop()])
        for write, e in zip(writes, explained, strict=True):
            if store.record_benchmark_match(write.write_id, e.match, e.rule, e.gold_index):
                counts[e.match] += 1
    return counts


def load_ground_truth(domains: Iterable[str]) -> dict[tuple[str | None, str | None], GroundTruth]:
    """Ground truth for every task in the given τ² domains. Needs `tau2`."""
    from tau2.run import load_tasks

    with contextlib.redirect_stdout(io.StringIO()):  # τ² prints its registry on load
        return {
            (domain, task.id): GroundTruth.from_task(task)
            for domain in domains
            for task in load_tasks(domain, task_split_name=None)
        }


def _matches(
    gold: GoldAction, action: str, args: Mapping[str, Any], *, sort_lists: bool = False
) -> bool:
    if gold.name != action:
        return False
    keys = gold.compare_args if gold.compare_args is not None else {*gold.arguments, *args}
    norm = _sorted_lists if sort_lists else _identity
    return all(norm(gold.arguments.get(k, _MISSING)) == norm(args.get(k, _MISSING)) for k in keys)


_MISSING = object()


def _identity(value: Any) -> Any:
    return value


def _sorted_lists(value: Any) -> Any:
    if isinstance(value, list):
        return sorted((_sorted_lists(v) for v in value), key=canonical_json)
    if isinstance(value, dict):
        return {k: _sorted_lists(v) for k, v in value.items()}
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("store", type=Path, help="benchmark SQLite file")
    args = parser.parse_args(argv)

    with BenchStore(args.store) as store:
        domains = {w.domain for w in store.writes() if w.domain is not None}
        counts = match_store(store, load_ground_truth(sorted(domains)))
        totals = Counter(store.benchmark_matches().values())
        unmatched = len(store.writes()) - sum(totals.values())
    print(f"matched {sum(counts.values())} writes against the tau2 traces: {dict(counts)}")
    print(f"store totals: {dict(totals)}")
    return 0 if unmatched == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
