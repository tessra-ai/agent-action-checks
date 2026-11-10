"""Extract policy-oracle regression fixtures from a captured smoke store.

For every write in the store's finished wrapped simulations, rebuild the environment as it was
just before the call (τ²'s `Environment.set_state` over the trajectory prefix), build the
oracle's evidence and write it to `tests/fixtures/verdicts/<name>.json` together with what
happened after the call (backend outcome, benchmark match, the simulation's final outcome) and
prints the verdict the current oracle gives. The expected verdicts are checked by hand and
pinned in `tests/test_verdicts_regression.py`, not stored in the fixtures.

Retail databases are sliced to the records the validator reads (the authenticated users, the
order's owner and their orders), and the script checks that the slice gives the same verdict as
the full database.

Needs `tau2`. A store captured before the policy-verdict schema is replayed from its trajectories
(the old `label` column is the benchmark match):

    python scripts/extract_verdict_fixtures.py runs/smoke.db tests/fixtures/verdicts

A schema-2 store already holds each write's pre-action snapshot; the evidence is rebuilt from it
(`snapshot.evidence_from_store`). `--write` picks writes by id:

    python scripts/extract_verdict_fixtures.py runs/smoke2.db tests/fixtures/verdicts \\
        --write 01M5JMJVCJQM1EQ0B0NPQTKHV8
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from tau2.data_model.message import AssistantMessage
from tau2.data_model.simulation import SimulationRun
from tau2.registry import registry
from tau2.run import get_tasks

from hatchway.bench.outcomes import task_outcome
from hatchway.bench.store import BenchStore
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.bench.tau2.snapshot import build_evidence, db_snapshot, evidence_from_store
from hatchway.bench.tau2.verdicts import evaluate, evidence_to_json
from hatchway.bench.tau2.verdicts.retail import authenticated_users
from hatchway.policy import Kind, load_policy

MATCH = {"correct": "MATCH", "incorrect": "MISMATCH", "ambiguous": "AMBIGUOUS"}
SHORT = {
    "gpt-4.1-nano-2025-04-14": "nano",
    "gpt-4.1-mini-2025-04-14": "mini",
    "gpt-4.1-2025-04-14": "gpt41",
}


def slice_retail(db: dict[str, Any], evidence: Any) -> dict[str, Any]:
    users, orders = db["users"], db["orders"]
    keep = set(authenticated_users(evidence.turns))
    order = orders.get(str(evidence.args.get("order_id")))
    if order is not None:
        keep.add(order["user_id"])
    order_ids = {oid for uid in keep for oid in users.get(uid, {}).get("orders", [])}
    if order is not None:
        order_ids.add(order["order_id"])
    out = {
        "users": {u: users[u] for u in sorted(keep) if u in users},
        "orders": {o: orders[o] for o in sorted(order_ids) if o in orders},
    }
    if "products" in db and order is not None:
        # Exchanges and item changes look up the new item among the old item's variants.
        product_ids = {str(i.get("product_id")) for i in order.get("items") or []}
        out["products"] = {p: db["products"][p] for p in sorted(product_ids) if p in db["products"]}
    return out


def fixture_name(
    domain: str, task_id: str, agent_model: str | None, seq: int, session: str | None = None
) -> str:
    """`retail_<task>` or `telecom_roaming_task` (the smoke runs' one telecom task), then the
    model and seq. With `session` (the targeted run: many tasks and trials), the name carries
    the session's last six characters instead of the task."""
    model = SHORT.get(agent_model or "", agent_model)
    if session is not None:
        return f"{domain}_{session[-6:]}_{model}_seq{seq}"
    return f"{domain}_{task_id if domain == 'retail' else 'roaming_task'}_{model}_seq{seq}"


def sliced(evidence: Any) -> Any:
    """Retail evidence with the database sliced, checked to give the same verdict."""
    if evidence.domain != "retail":
        return evidence
    full = evaluate(evidence)
    out = evidence.__class__(
        **{**evidence.__dict__, "agent_db": slice_retail(evidence.agent_db, evidence)}
    )
    assert evaluate(out).to_json() == full.to_json(), (out, full)
    return out


def write_fixture(out_dir: Path, fixture: dict[str, Any], evidence: Any) -> None:
    (out_dir / f"{fixture['name']}.json").write_text(
        json.dumps(fixture, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    )
    verdict = evaluate(evidence)
    print(
        f"{fixture['name']}: {verdict.expected_decision} {list(verdict.reason_codes)} | "
        f"{fixture['after_the_call']}"
    )


def extract_schema2(
    store_path: Path, out_dir: Path, write_ids: set[str] | None, by_session: bool = False
) -> None:
    """Fixtures from a schema-2 store's stored pre-action snapshots."""
    with BenchStore(store_path) as store:
        outcomes = {s.session_id: s.final_task_outcome for s in store.simulation_outcomes()}
        matches = store.benchmark_matches()
        for write in store.writes():
            if write_ids is not None and write.write_id not in write_ids:
                continue
            evidence = evidence_from_store(store, write)
            if evidence is None:
                continue
            outcome = store.outcome(write.write_id)
            fixture = {
                "name": fixture_name(
                    write.domain or "",
                    write.task_id or "",
                    write.agent_model,
                    write.seq,
                    write.session_id if by_session else None,
                ),
                "agent_model": write.agent_model,
                "evidence": evidence_to_json(sliced(evidence)),
                "after_the_call": {
                    "execution_outcome": outcome.outcome if outcome else None,
                    "backend_error": outcome.backend_error if outcome else None,
                    "benchmark_match": matches.get(write.write_id),
                    "final_task_outcome": outcomes.get(write.session_id),
                },
            }
            write_fixture(out_dir, fixture, sliced(evidence))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("store", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--write", action="append", help="write id (schema-2 stores only)")
    parser.add_argument(
        "--by-session", action="store_true", help="name fixtures by session, not by task"
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    version = sqlite3.connect(args.store).execute("PRAGMA user_version").fetchone()[0]
    if version >= 2:
        extract_schema2(
            args.store, args.out, set(args.write) if args.write else None, args.by_session
        )
        return 0
    if args.write:
        parser.error("--write needs a schema-2 store")
    policy = load_policy(DEFAULT_POLICY)

    def is_write(name: str) -> bool:
        spec = policy.actions.get(name)
        return spec is None or spec.kind == Kind.WRITE

    db = sqlite3.connect(args.store)
    db.row_factory = sqlite3.Row
    sims = db.execute(
        "SELECT * FROM simulations WHERE mode = 'wrapped' AND status = 'done' "
        "ORDER BY domain, task_id, agent_model"
    ).fetchall()
    for sim_row in sims:
        writes = db.execute(
            "SELECT * FROM captured_writes WHERE session_id = ? ORDER BY seq",
            (sim_row["session_id"],),
        ).fetchall()
        if not writes:
            continue
        domain = sim_row["domain"]
        sim = SimulationRun.model_validate_json(sim_row["simulation"])
        [task] = get_tasks(domain, task_ids=[sim_row["task_id"]])
        initial = task.initial_state
        final = task_outcome(sim.reward_info.reward if sim.reward_info else None)

        seq = 0
        for i, message in enumerate(sim.messages):
            if not isinstance(message, AssistantMessage) or not message.tool_calls:
                continue
            for j, call in enumerate(message.tool_calls):
                if not is_write(call.name):
                    continue
                write = writes[seq]
                assert write["action"] == call.name and write["seq"] == seq, (write, call)
                prefix = list(sim.messages[:i])
                if j:
                    partial = message.model_copy(update={"tool_calls": message.tool_calls[:j]})
                    prefix += [partial, *sim.messages[i + 1 : i + 1 + j]]
                env = registry.get_env_constructor(domain)()
                env.set_state(
                    initial.initialization_data if initial else None,
                    initial.initialization_actions if initial else None,
                    prefix,
                )
                agent_db, user_db = db_snapshot(env)
                evidence = build_evidence(
                    domain=domain,
                    task_id=sim_row["task_id"],
                    session_id=sim_row["session_id"],
                    seq=seq,
                    action=call.name,
                    args=call.arguments,
                    agent_db=agent_db,
                    user_db=user_db,
                    prior_messages=sim.messages[:i],
                    proposing_text=message.content or "",
                    policy_text=env.get_policy(),
                    prior_writes=[(w["action"], json.loads(w["args"])) for w in writes[:seq]],
                )
                evidence = sliced(evidence)
                result = next(m for m in sim.messages[i + 1 :] if getattr(m, "id", None) == call.id)
                fixture = {
                    "name": fixture_name(domain, sim_row["task_id"], sim_row["agent_model"], seq),
                    "agent_model": sim_row["agent_model"],
                    "evidence": evidence_to_json(evidence),
                    "after_the_call": {
                        "execution_outcome": "REJECTED" if result.error else "ACCEPTED",
                        "backend_error": result.content if result.error else None,
                        "benchmark_match": MATCH.get(write["label"]),
                        "final_task_outcome": final,
                    },
                }
                write_fixture(args.out, fixture, evidence)
                seq += 1
        assert seq == len(writes), (sim_row["session_id"], seq, len(writes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
