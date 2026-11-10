"""Convert a schema-1 benchmark store (trace labels, no snapshots) into a schema-2 copy.

For viewer and replay checks without new API calls. For every finished wrapped simulation of the
old store, each captured write is recorded again in a new store exactly as the τ² harness now
records it: the pre-action state is rebuilt with τ²'s `Environment.set_state` over the
trajectory before the call, and the write, its snapshot and its deterministic policy verdict are
committed together. The backend outcome comes from the stored tool result (REJECTED on an error,
else ACCEPTED) and `state_changed` from the database hashes before and after the call. The judge
scores are copied as they were: every recomputed state hash must equal the old one, so they
join unchanged. The τ² trace match is recomputed with `match_store`.

The new results directory gets the simulations' results files and a `summary.json` marking the
store as converted. Gated simulations of the old store are left out.

    python scripts/convert_schema1_store.py runs/smoke.db runs/smoke runs/smoke_converted.db \\
        runs/smoke_converted
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tau2.data_model.message import AssistantMessage
from tau2.data_model.simulation import SimulationRun
from tau2.registry import registry
from tau2.run import get_tasks

from hatchway.bench.store import BenchStore, OutcomeRecord, PreActionSnapshot, ScoreRecord
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.bench.tau2.label import load_ground_truth, match_store
from hatchway.bench.tau2.snapshot import build_evidence, db_hash, db_snapshot, verdict_record
from hatchway.bench.tau2.verdicts import evaluate
from hatchway.judges.base import QuestionVector
from hatchway.policy import Kind, load_policy

CONVERTED_NOTE = (
    "converted from a schema-1 store for viewer and replay checks; no new API calls. Verdicts "
    "come from the current oracle over rebuilt pre-action state"
)


def _env_at(domain: str, task: Any, messages: Sequence[Any]) -> Any:
    env = registry.get_env_constructor(domain)()
    initial = task.initial_state
    env.set_state(
        initial.initialization_data if initial else None,
        initial.initialization_actions if initial else None,
        list(messages),
    )
    return env


def _prefix(sim: SimulationRun, i: int, j: int) -> list[Any]:
    """The messages before call `j` of message `i`, with any earlier calls of the same message
    and their results (τ² runs a message's calls in order)."""
    message = sim.messages[i]
    prefix = list(sim.messages[:i])
    if j:
        partial = message.model_copy(update={"tool_calls": message.tool_calls[:j]})
        prefix += [partial, *sim.messages[i + 1 : i + 1 + j]]
    return prefix


def _hook(
    *,
    domain: str,
    task_id: str,
    agent_db: dict[str, Any],
    user_db: dict[str, Any] | None,
    prior_messages: list[dict[str, Any]],
    proposing_text: str,
    policy_text: str,
    tool_call_id: str,
) -> Any:
    """The harness's pre-execution hook (`snapshot.live_proposal`), over a rebuilt state."""

    def pre_execution(write: Any, prior_writes: Any) -> tuple[PreActionSnapshot, Any]:
        evidence = build_evidence(
            domain=domain,
            task_id=task_id,
            session_id=write.session_id,
            seq=write.seq,
            action=write.action,
            args=write.args,
            agent_db=agent_db,
            user_db=user_db,
            prior_messages=prior_messages,
            proposing_text=proposing_text,
            policy_text=policy_text,
            prior_writes=prior_writes,
        )
        snapshot = PreActionSnapshot(
            tool_call_id=tool_call_id,
            agent_db=agent_db,
            user_db=user_db,
            messages=prior_messages,
            proposing_text=proposing_text,
            domain_policy_hash=evidence.domain_policy_hash,
        )
        return snapshot, verdict_record(evaluate(evidence))

    return pre_execution


def convert_session(
    store: BenchStore,
    *,
    domain: str,
    task: Any,
    sim: SimulationRun,
    old_writes: Sequence[dict[str, Any]],
    session_id: str,
    agent_model: str | None,
    trial: int | None,
) -> int:
    """Record one simulation's writes in `store` as the harness records them. `old_writes` are
    the old rows (dicts with action, args, context, rubric_hash, known_action, state_hash) in
    `seq` order. Returns the number of writes recorded."""
    policy = load_policy(DEFAULT_POLICY)

    def is_write(name: str) -> bool:
        spec = policy.actions.get(name)
        return spec is None or spec.kind is not Kind.READ

    seq = 0
    for i, message in enumerate(sim.messages):
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            continue
        for j, call in enumerate(message.tool_calls):
            if not is_write(call.name):
                continue
            old = old_writes[seq]
            if old["action"] != call.name or old["args"] != call.arguments:
                raise ValueError(f"{session_id} write {seq} does not match the trajectory")
            before = _env_at(domain, task, _prefix(sim, i, j))
            agent_db, user_db = db_snapshot(before)
            prior_messages = [m.model_dump(mode="json") for m in sim.messages[:i]]

            pre_execution = _hook(
                domain=domain,
                task_id=task.id,
                agent_db=agent_db,
                user_db=user_db,
                prior_messages=prior_messages,
                proposing_text=message.content or "",
                policy_text=before.get_policy(),
                tool_call_id=call.id,
            )
            write = store.record_write(
                session_id=session_id,
                action=call.name,
                args=call.arguments,
                context=old["context"],
                rubric_hash=old["rubric_hash"],
                known_action=bool(old["known_action"]),
                domain=domain,
                agent_model=agent_model,
                task_id=task.id,
                trial=trial,
                pre_execution=pre_execution,
            )
            if write.state_hash != old["state_hash"]:
                raise ValueError(
                    f"{session_id} write {seq}: state hash changed; scores would not join"
                )
            result = next(m for m in sim.messages[i + 1 :] if getattr(m, "id", None) == call.id)
            # The state just after this call: the same prefix, now including the call's result.
            after = _env_at(domain, task, _prefix(sim, i, j + 1))
            agent_after, user_after = db_snapshot(after)
            hashes_after = (db_hash(agent_after), db_hash(user_after))
            store.record_outcome(
                write.write_id,
                OutcomeRecord(
                    outcome="REJECTED" if result.error else "ACCEPTED",
                    state_changed=hashes_after != (db_hash(agent_db), db_hash(user_db)),
                    backend_error=result.content if result.error else None,
                    agent_db_hash_after=hashes_after[0],
                    user_db_hash_after=hashes_after[1],
                ),
            )
            seq += 1
    if seq != len(old_writes):
        raise ValueError(
            f"{session_id}: {len(old_writes)} old writes, {seq} found in the trajectory"
        )
    return seq


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old_store", type=Path)
    parser.add_argument("old_results", type=Path, help="the old run's results directory")
    parser.add_argument("new_store", type=Path)
    parser.add_argument("new_results", type=Path)
    args = parser.parse_args(argv)
    if args.new_store.exists():
        parser.error(f"{args.new_store} exists; the conversion writes a new store")

    old = sqlite3.connect(f"file:{args.old_store}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    sims = old.execute(
        "SELECT * FROM simulations WHERE mode = 'wrapped' AND status = 'done' ORDER BY rowid"
    ).fetchall()
    with BenchStore(args.new_store) as store:
        n = 0
        for row in sims:
            writes = [
                {**dict(w), "args": json.loads(w["args"]), "context": json.loads(w["context"])}
                for w in old.execute(
                    "SELECT * FROM captured_writes WHERE session_id = ? ORDER BY seq",
                    (row["session_id"],),
                )
            ]
            [task] = get_tasks(row["domain"], task_ids=[row["task_id"]])
            sim = SimulationRun.model_validate_json(row["simulation"])
            store.start_simulation(
                session_id=row["session_id"],
                mode="wrapped",
                domain=row["domain"],
                task_id=row["task_id"],
                trial=row["trial"],
                agent_model=row["agent_model"],
                user_model=row["user_model"],
                seed=row["seed"],
            )
            n += convert_session(
                store,
                domain=row["domain"],
                task=task,
                sim=sim,
                old_writes=writes,
                session_id=row["session_id"],
                agent_model=row["agent_model"],
                trial=row["trial"],
            )
            store.finish_simulation(
                row["session_id"],
                reward=row["reward"],
                agent_cost_usd=row["agent_cost_usd"],
                user_cost_usd=row["user_cost_usd"],
                simulation=row["simulation"],
            )
        for s in old.execute("SELECT * FROM scores"):
            fields = dict(s)
            del fields["ts"]
            if fields["question_vector"] is not None:
                fields["question_vector"] = QuestionVector.model_validate_json(
                    fields["question_vector"]
                )
            store.put_score(ScoreRecord(**fields))
        for k in old.execute("SELECT * FROM scoring_skips"):
            store.put_skip(k["state_hash"], k["rubric_hash"], k["reason"])
        domains = sorted({r["domain"] for r in sims})
        match_store(store, load_ground_truth(domains))

    args.new_results.mkdir(parents=True, exist_ok=True)
    for f in args.old_results.rglob("*.json"):
        if f.name in ("summary.json", "score.json"):
            continue
        target = args.new_results / f.relative_to(args.old_results)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, target)
    old_summary_path = args.old_results / "summary.json"
    old_summary = json.loads(old_summary_path.read_text()) if old_summary_path.exists() else {}
    (args.new_results / "summary.json").write_text(
        json.dumps(
            {
                "config": old_summary.get("config"),
                "seed": old_summary.get("seed"),
                "hatchway_commit": old_summary.get("hatchway_commit"),
                "converted": CONVERTED_NOTE,
                "converted_from": str(args.old_store),
            },
            indent=2,
        )
    )
    print(f"converted {len(sims)} simulations and {n} writes into {args.new_store}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
