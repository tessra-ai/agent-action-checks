"""The verdicts CLI: recompute from stored snapshots, the review queue, import and agreement."""

from __future__ import annotations

from pathlib import Path

import yaml

from hatchway.bench import BenchStore
from hatchway.bench.store import PreActionSnapshot, VerdictRecord
from hatchway.bench.tau2.verdicts.__main__ import (
    agreement,
    import_reviews,
    main,
    recompute,
    review_queue,
)
from hatchway.bench.tau2.verdicts.registry import ORACLE_VERSION
from hatchway.bench.tau2.verdicts.retail import RETAIL_POLICY_HASHES

DB = {
    "users": {
        "u1": {
            "payment_methods": {
                "cc_1": {"source": "credit_card", "id": "cc_1", "last_four": "1234"},
                "pp_1": {"source": "paypal", "id": "pp_1"},
            },
            "orders": ["#W1111111"],
        }
    },
    "orders": {
        "#W1111111": {
            "order_id": "#W1111111",
            "user_id": "u1",
            "status": "delivered",
            "items": [{"item_id": "i1", "name": "Lamp"}],
            "payment_history": [{"transaction_type": "payment", "payment_method_id": "cc_1"}],
        }
    },
}

# τ² messages as the harness stores them.
MESSAGES = [
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c1", "name": "find_user_id_by_email", "arguments": {"email": "a@b.c"}}
        ],
    },
    {"role": "tool", "id": "c1", "content": "u1", "requestor": "assistant", "error": False},
    {"role": "assistant", "content": "Return the Lamp from #W1111111 to card 1234. Confirm?"},
    {"role": "user", "content": "Yes, go ahead."},
]


def capture(store: BenchStore, session: str, method: str) -> str:
    """A write captured with a snapshot and a verdict from an older oracle version."""
    snapshot = PreActionSnapshot(
        agent_db=DB,
        messages=MESSAGES,
        domain_policy_hash=next(iter(RETAIL_POLICY_HASHES)),
    )
    old = VerdictRecord(oracle_version="old", expected_decision="UNKNOWN", should_execute_now=None)
    write = store.record_write(
        session_id=session,
        action="return_delivered_order_items",
        args={"order_id": "#W1111111", "item_ids": ["i1"], "payment_method_id": method},
        context={},
        rubric_hash=None,
        domain="retail",
        task_id="t",
        pre_execution=lambda w, prior: (snapshot, old),
    )
    return write.write_id


def test_recompute_review_and_agreement(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "b.db") as store:
        allow_id = capture(store, "s1", "cc_1")
        deny_id = capture(store, "s2", "pp_1")
        assert recompute(store) == {"ALLOW": 1, "DENY": 1}
        assert recompute(store) == {}  # never rewritten
        assert store.oracle_versions() == ["old", ORACLE_VERSION]

        queue = review_queue(store, ORACLE_VERSION, audit_rate=0.2, audit_min=3, seed=0)
        assert {(e["write_id"], e["review_kind"]) for e in queue} == {
            (allow_id, "audit_sample"),
            (deny_id, "audit_sample"),
        }
        # The reviewer disagrees with the oracle's ALLOW and agrees with its DENY.
        for e in queue:
            e["decision"] = "ASK" if e["write_id"] == allow_id else "DENY"
            e["reviewer"] = "ana"
        path = tmp_path / "review.yaml"
        path.write_text(yaml.safe_dump(queue))
        assert import_reviews(store, path) == 2

        rows = {r.write_id: r for r in store.proposed_actions(ORACLE_VERSION)}
        assert rows[allow_id].deterministic_decision == "ALLOW"
        assert rows[allow_id].effective_decision == "ASK"  # the adjudication wins
        assert agreement(store, ORACLE_VERSION) == {
            "ALLOW": {"reviewed": 1, "agreed": 0, "reviewer_decisions": {"ASK": 1}},
            "DENY": {"reviewed": 1, "agreed": 1, "reviewer_decisions": {"DENY": 1}},
        }
        # Reviewed writes leave the queue.
        assert review_queue(store, ORACLE_VERSION, audit_rate=1, audit_min=3, seed=0) == []


def test_unknown_verdicts_are_always_queued(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "b.db") as store:
        w = capture(store, "s1", "cc_1")
        rows = review_queue(store, "old", audit_rate=0.0, audit_min=0, seed=0)
        assert [(e["write_id"], e["review_kind"]) for e in rows] == [(w, "unknown_queue")]


def test_cli_runs(tmp_path: Path, capsys) -> None:
    with BenchStore(tmp_path / "b.db") as store:
        capture(store, "s1", "pp_1")
    queue = tmp_path / "q.yaml"
    assert main([str(tmp_path / "b.db"), "--recompute", "--queue", str(queue), "--report"]) == 0
    out = capsys.readouterr().out
    assert "recomputed" in out and "unknown rate: 0.0%" in out
    assert yaml.safe_load(queue.read_text())[0]["oracle_decision"] == "DENY"
