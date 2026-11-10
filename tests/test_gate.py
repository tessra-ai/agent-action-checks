import logging
import statistics
import time
from pathlib import Path

import pytest

from hatchway import Gate, Result
from hatchway.bench import BenchStore

FIXTURE = Path(__file__).parent / "fixtures" / "spec_policy.yaml"


@pytest.fixture
def gate(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as store:
        yield Gate(FIXTURE, store=store, domain="retail", agent_model="agent-x")


def test_reads_pass_and_are_not_captured(gate: Gate) -> None:
    decision = gate.check("get_order", {"order_id": "1"}, session_id="s1")
    assert decision.result is Result.ALLOW
    assert decision.receipt_id is None
    assert gate.store.writes() == []


def test_each_write_is_captured_once_and_allowed(gate: Gate) -> None:
    args = {"order_id": "1", "amount": 20, "method": "card"}
    decisions = [
        gate.check("refund_order", args, {"conversation": "refund"}, session_id="s1", task_id="t")
        for _ in range(2)
    ]
    assert all(d.result is Result.ALLOW for d in decisions)

    writes = gate.store.writes()
    assert [w.write_id for w in writes] == [d.receipt_id for d in decisions]
    assert writes[0].rubric_hash == gate.policy.actions["refund_order"].rubric_hash
    assert writes[0].known_action
    assert (writes[0].domain, writes[0].agent_model, writes[0].task_id) == (
        "retail",
        "agent-x",
        "t",
    )
    assert writes[0].args == args


def test_unknown_actions_are_captured_unscored_with_one_warning(
    gate: Gate, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="hatchway"):
        for _ in range(3):
            decision = gate.check("delete_account", {"user": "u1"}, session_id="s1")
            assert decision.result is Result.ALLOW

    assert [r.message for r in caplog.records] == [
        "action 'delete_account' is not in the policy; capturing it unscored"
    ]
    writes = gate.store.writes()
    assert len(writes) == 3
    assert all(not w.known_action and w.rubric_hash is None for w in writes)


def test_store_errors_are_raised_not_turned_into_decisions(gate: Gate) -> None:
    gate.store.close()
    with pytest.raises(Exception, match="closed"):
        gate.check("refund_order", {"amount": 1}, session_id="s1")


def test_check_overhead_p95_under_20ms(gate: Gate) -> None:
    context = {"conversation": "x" * 2000, "policy": "y" * 4000}
    timings = []
    for i in range(1000):
        start = time.perf_counter()
        gate.check("refund_order", {"amount": i}, context, session_id=f"s{i % 50}")
        timings.append((time.perf_counter() - start) * 1000)
    p95 = statistics.quantiles(timings, n=20)[-1]
    assert p95 < 20, f"p95 {p95:.2f} ms"
