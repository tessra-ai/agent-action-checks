"""Store schema 2: snapshots, policy verdicts, manual review, outcomes and benchmark matches."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hatchway.bench import BenchStore
from hatchway.bench.outcomes import task_outcome
from hatchway.bench.store import OutcomeRecord, PreActionSnapshot, VerdictRecord


@pytest.fixture
def store(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as s:
        yield s


SNAPSHOT = PreActionSnapshot(
    tool_call_id="call_1",
    agent_db={"orders": {"#W1": {"status": "delivered"}}},
    user_db=None,
    messages=[{"role": "user", "content": "return it"}],
    domain_policy_hash="p" * 64,
)


def verdict(decision: str = "DENY", version: str = "v1") -> VerdictRecord:
    return VerdictRecord(
        oracle_version=version,
        expected_decision=decision,  # type: ignore[arg-type]
        should_execute_now=None if decision == "UNKNOWN" else decision == "ALLOW",
        reason_codes=("INVALID_REFUND_METHOD",) if decision == "DENY" else (),
        explanation="x",
        evidence={"k": 1},
    )


def write(store: BenchStore, session_id: str = "s1", pre_execution=None, **extra):
    return store.record_write(
        session_id=session_id,
        action="return_delivered_order_items",
        args={"order_id": "#W1"},
        context={"conversation": "user: return it"},
        rubric_hash="r" * 64,
        domain="retail",
        task_id="13",
        pre_execution=pre_execution,
        **extra,
    )


def evaluated(store: BenchStore, session_id: str = "s1", decision: str = "DENY"):
    return write(store, session_id, pre_execution=lambda w, prior: (SNAPSHOT, verdict(decision)))


def test_pre_execution_rows_commit_with_the_write(store) -> None:
    seen = []

    def pre(w, prior):
        seen.append((w.seq, w.session_id, prior))
        return SNAPSHOT, verdict()

    w = write(store, pre_execution=pre)
    assert seen == [(0, "s1", [])]
    assert store.snapshot(w.write_id) == SNAPSHOT
    assert store.verdict(w.write_id, "v1") == verdict()


def test_pre_execution_is_all_or_nothing(store) -> None:
    def broken(w, prior):
        raise RuntimeError("oracle failed")

    with pytest.raises(RuntimeError):
        write(store, pre_execution=broken)
    assert store.writes() == []
    for table in ("pre_action_snapshots", "policy_verdicts", "db_blobs"):
        assert store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_identical_databases_are_stored_once(store) -> None:
    evaluated(store, "a")
    evaluated(store, "b")
    assert store._conn.execute("SELECT COUNT(*) FROM db_blobs").fetchone()[0] == 1


def test_outcome_needs_snapshot_and_verdict_first(store) -> None:
    bare = write(store)
    with pytest.raises(sqlite3.IntegrityError, match="snapshot and verdict"):
        store.record_outcome(bare.write_id, OutcomeRecord(outcome="ACCEPTED"))
    # A verdict alone (a write captured without a snapshot) is still not enough.
    store.record_verdict(bare.write_id, verdict())
    with pytest.raises(sqlite3.IntegrityError, match="snapshot and verdict"):
        store.record_outcome(bare.write_id, OutcomeRecord(outcome="ACCEPTED"))

    w = evaluated(store, "s2")
    store.record_outcome(
        w.write_id, OutcomeRecord(outcome="REJECTED", state_changed=False, backend_error="no")
    )
    assert store.outcome(w.write_id) == OutcomeRecord(
        outcome="REJECTED", state_changed=False, backend_error="no"
    )


def test_the_backend_outcome_does_not_touch_the_verdict(store) -> None:
    w = evaluated(store)
    before = store.verdict(w.write_id, "v1")
    store.record_outcome(w.write_id, OutcomeRecord(outcome="REJECTED", state_changed=False))
    assert store.verdict(w.write_id, "v1") == before
    [row] = store.proposed_actions("v1")
    assert (row.effective_decision, row.execution_outcome) == ("DENY", "REJECTED")


@pytest.mark.parametrize(
    "table",
    [
        "pre_action_snapshots",
        "policy_verdicts",
        "manual_verdicts",
        "execution_outcomes",
        "benchmark_matches",
        "db_blobs",
    ],
)
def test_verdict_tables_are_append_only(store, table: str) -> None:
    w = evaluated(store)
    store.record_outcome(w.write_id, OutcomeRecord(outcome="ACCEPTED"))
    store.record_benchmark_match(w.write_id, "MATCH", "3", 0)
    store.record_manual_verdict(
        write_id=w.write_id,
        oracle_version="v1",
        expected_decision="ALLOW",
        reviewer="r",
        review_kind="audit_sample",
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute(f"DELETE FROM {table}")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute(
            f"UPDATE {table} SET ts = 'x'"
            if table != "db_blobs"
            else "UPDATE db_blobs SET data = x'00'"
        )


def test_manual_verdict_overrides_within_its_oracle_version(store) -> None:
    w = evaluated(store, decision="ALLOW")
    store.record_verdict(w.write_id, verdict("ALLOW", "v2"))
    assert not store.record_verdict(w.write_id, verdict("DENY", "v2"))  # never rewritten

    store.record_manual_verdict(
        write_id=w.write_id,
        oracle_version="v1",
        expected_decision="DENY",
        reviewer="ana",
        review_kind="audit_sample",
        reason_codes=["WRONG_LINE"],
    )
    [v1] = store.proposed_actions("v1")
    assert (v1.deterministic_decision, v1.manual_decision) == ("ALLOW", "DENY")
    assert (v1.effective_decision, v1.effective_source) == ("DENY", "manual_review")
    [v2] = store.proposed_actions("v2")  # the v1 review does not leak into v2
    assert (v2.effective_decision, v2.effective_source) == ("ALLOW", "deterministic_oracle")

    # A later adjudication supersedes; a non-adjudicated note does not count.
    store.record_manual_verdict(
        write_id=w.write_id,
        oracle_version="v1",
        expected_decision="ASK",
        reviewer="ben",
        review_kind="audit_sample",
    )
    store.record_manual_verdict(
        write_id=w.write_id,
        oracle_version="v1",
        expected_decision="ALLOW",
        reviewer="cy",
        review_kind="audit_sample",
        adjudicated=False,
    )
    [v1] = store.proposed_actions("v1")
    assert (v1.effective_decision, v1.manual_reviewer) == ("ASK", "ben")
    assert len(store.manual_verdicts("v1")) == 3  # every review is kept


def test_one_row_per_write_whatever_the_number_of_oracle_versions(store) -> None:
    a = evaluated(store, "s1")
    b = evaluated(store, "s1")
    for w in (a, b):
        store.record_verdict(w.write_id, verdict("ASK", "v2"))
    assert [r.write_id for r in store.proposed_actions("v1")] == [a.write_id, b.write_id]
    assert [r.effective_decision for r in store.proposed_actions("v2")] == ["ASK", "ASK"]
    assert store.oracle_versions() == ["v1", "v2"]
    with pytest.raises(KeyError, match="no verdict"):
        store.proposed_actions("v3")
    assert store.proposed_actions("v3", require_verdicts=False) == []


def test_benchmark_match_is_recorded_once(store) -> None:
    w = evaluated(store)
    assert store.record_benchmark_match(w.write_id, "MATCH", "3", 0)
    assert not store.record_benchmark_match(w.write_id, "MISMATCH", "5", None)
    assert store.benchmark_matches() == {w.write_id: "MATCH"}
    assert store.proposed_actions("v1")[0].benchmark_match == "MATCH"
    with pytest.raises(sqlite3.IntegrityError):
        store.record_benchmark_match(evaluated(store, "s2").write_id, "correct", "3", 0)  # type: ignore[arg-type]


def test_task_outcomes_are_per_simulation_not_per_write(store) -> None:
    store.start_simulation(
        session_id="s1",
        mode="wrapped",
        domain="retail",
        task_id="13",
        trial=0,
        agent_model="m",
        user_model="u",
        seed=1,
    )
    for _ in range(3):
        evaluated(store, "s1")
    store.finish_simulation(
        "s1", reward=1.0, agent_cost_usd=None, user_cost_usd=None, simulation="{}"
    )
    outcomes = store.simulation_outcomes()
    assert [(o.session_id, o.final_task_outcome) for o in outcomes] == [("s1", "PASS")]
    assert len(store.proposed_actions("v1")) == 3
    assert "final_task_outcome" not in type(store.proposed_actions("v1")[0]).model_fields


def test_task_outcome() -> None:
    assert task_outcome(1.0) == "PASS"
    assert task_outcome(0.9999999999) == "PASS"
    assert task_outcome(0.5) == "FAIL"
    assert task_outcome(0.0) == "FAIL"
    assert task_outcome(None) is None


def test_verdict_record_checks_should_execute() -> None:
    with pytest.raises(ValueError):
        VerdictRecord(oracle_version="v", expected_decision="UNKNOWN", should_execute_now=False)
    with pytest.raises(ValueError):
        VerdictRecord(oracle_version="v", expected_decision="ALLOW", should_execute_now=None)
