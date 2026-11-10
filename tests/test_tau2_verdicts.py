"""The policy oracle on real τ² tasks: pre-execution persistence, outcomes and snapshot
fidelity (scripted agent and user, no LLM calls)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

tau2 = pytest.importorskip("tau2")

from tau2.data_model.message import ToolCall  # noqa: E402
from tau2.registry import registry  # noqa: E402
from test_tau2_harness import ScriptedAgent, ScriptedUser, _task  # noqa: E402

from hatchway import Gate  # noqa: E402
from hatchway.bench import BenchStore  # noqa: E402
from hatchway.bench.tau2 import DEFAULT_POLICY  # noqa: E402
from hatchway.bench.tau2.harness import run_simulation  # noqa: E402
from hatchway.bench.tau2.snapshot import (  # noqa: E402
    db_snapshot,
    evidence_from_store,
    policy_hash,
)
from hatchway.bench.tau2.verdicts import ORACLE_VERSION, VALIDATORS, evaluate  # noqa: E402

PAYPAL = {
    "order_id": "#W5490111",
    "item_ids": ["4579334072", "1421289881", "6117189161", "4947717507"],
    "payment_method_id": "paypal_9497703",
}
CARD = {**PAYPAL, "payment_method_id": "credit_card_3124723"}


@pytest.fixture
def store(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as store:
        yield store


@pytest.mark.parametrize("domain", ["retail", "telecom"])
def test_validators_support_the_pinned_policy_text(domain: str) -> None:
    current = policy_hash(registry.get_env_constructor(domain)().get_policy())
    for (d, _), validator in VALIDATORS.items():
        if d == domain:
            assert current in validator.supported_policy_hashes


def run_task_10(store: BenchStore, calls: list[dict], seen: list[tuple]) -> Any:
    """Retail task 10 with a scripted agent that authenticates, then proposes `calls` as
    returns. A spy on the return tool records what the store held when the tool ran."""
    task = _task("retail", "10")
    gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
    agent_calls = [
        ToolCall(
            name="find_user_id_by_email",
            arguments={"email": "mia.garcia2723@example.com"},
            requestor="assistant",
        ),
        *(
            ToolCall(name="return_delivered_order_items", arguments=a, requestor="assistant")
            for a in calls
        ),
    ]

    def make_agent(env: Any, _: Any) -> ScriptedAgent:
        tool = env.tools.return_delivered_order_items

        def spy(**kwargs: Any) -> Any:
            [write] = [w for w in store.writes() if w.args == kwargs][-1:]
            seen.append(
                (
                    store.snapshot(write.write_id) is not None,
                    store.verdict(write.write_id, ORACLE_VERSION) is not None,
                    store.outcome(write.write_id) is None,
                )
            )
            return tool(**kwargs)

        # `Toolkit.tools` looks tools up by attribute, so an instance attribute replaces one.
        env.tools.return_delivered_order_items = spy
        return ScriptedAgent(env.get_tools(), env.get_policy(), agent_calls)

    return run_simulation(
        "retail",
        task,
        trial=0,
        seed=7,
        gate=gate,
        make_agent=make_agent,
        make_user=lambda env, _: ScriptedUser([]),
    )


def test_verdict_is_committed_before_the_tool_runs_and_survives_rejection(store) -> None:
    seen: list[tuple] = []
    run_task_10(store, [PAYPAL, CARD], seen)
    # Snapshot and verdict existed, and no outcome yet, at the moment each tool call ran.
    assert seen == [(True, True, True), (True, True, True)]

    paypal, card = store.proposed_actions(ORACLE_VERSION)
    assert paypal.args == PAYPAL and card.args == CARD
    # The PayPal refund breaks the refund rule; the backend rejecting it changes nothing.
    assert paypal.deterministic_decision == "DENY"
    assert "INVALID_REFUND_METHOD" in paypal.deterministic_reason_codes
    assert (paypal.execution_outcome, paypal.state_changed) == ("REJECTED", False)
    assert "original payment method" in (paypal.backend_error or "")
    # The card refund is allowed by the refund rule, but nobody confirmed it: ASK. It ran.
    assert card.deterministic_decision == "ASK"
    assert card.deterministic_reason_codes == ("CONFIRMATION_MISSING",)
    assert (card.execution_outcome, card.state_changed) == ("ACCEPTED", True)


def test_stored_evidence_reproduces_the_verdict(store) -> None:
    run_task_10(store, [PAYPAL, CARD], [])
    for write in store.writes():
        if write.action != "return_delivered_order_items":
            continue
        evidence = evidence_from_store(store, write)
        assert evidence is not None
        stored = store.verdict(write.write_id, ORACLE_VERSION)
        assert stored is not None
        assert evaluate(evidence).expected_decision == stored.expected_decision
        assert evaluate(evidence).reason_codes == stored.reason_codes


def test_live_snapshot_matches_the_set_state_reconstruction(store) -> None:
    sim = run_task_10(store, [PAYPAL, CARD], [])
    task = _task("retail", "10")
    for write in store.writes():
        if write.action != "return_delivered_order_items":
            continue
        snapshot = store.snapshot(write.write_id)
        assert snapshot is not None
        i = next(
            i
            for i, m in enumerate(sim.messages)
            if any(c.id == snapshot.tool_call_id for c in getattr(m, "tool_calls", None) or [])
        )
        env = registry.get_env_constructor("retail")()
        initial = task.initial_state
        env.set_state(
            initial.initialization_data if initial else None,
            initial.initialization_actions if initial else None,
            list(sim.messages[:i]),
        )
        agent_db, _ = db_snapshot(env)
        assert agent_db == snapshot.agent_db
        assert len(snapshot.messages) == i


def test_converting_a_stored_run_reproduces_the_live_capture(tmp_path: Path) -> None:
    """`scripts/convert_schema1_store.py` rebuilds what the harness records live: the same
    snapshots, verdicts and backend outcomes, with state hashes that join the old scores."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from convert_schema1_store import convert_session

    with BenchStore(tmp_path / "live.db") as live:
        sim = run_task_10(live, [PAYPAL, CARD], [])
        writes = live.writes()
        old = [
            {
                "action": w.action,
                "args": w.args,
                "context": w.context,
                "rubric_hash": w.rubric_hash,
                "known_action": w.known_action,
                "state_hash": w.state_hash,
            }
            for w in writes
        ]
        expected = [
            (
                live.snapshot(w.write_id),
                live.verdict(w.write_id, ORACLE_VERSION),
                live.outcome(w.write_id),
            )
            for w in writes
        ]
    with BenchStore(tmp_path / "converted.db") as converted:
        n = convert_session(
            converted,
            domain="retail",
            task=_task("retail", "10"),
            sim=sim,
            old_writes=old,
            session_id=sim.id,
            agent_model="scripted",
            trial=0,
        )
        assert n == len(writes) == 2  # the two returns; the user lookup is a read
        got = [
            (
                converted.snapshot(w.write_id),
                converted.verdict(w.write_id, ORACLE_VERSION),
                converted.outcome(w.write_id),
            )
            for w in converted.writes()
        ]
    for (snap_e, verdict_e, outcome_e), (snap_g, verdict_g, outcome_g) in zip(
        expected, got, strict=True
    ):
        assert snap_g.agent_db == snap_e.agent_db

        # τ² numbers turns (`turn_idx`) only after the call; the evidence never reads it.
        def strip(messages: list[dict]) -> list[dict]:
            return [{k: v for k, v in m.items() if k != "turn_idx"} for m in messages]

        assert strip(snap_g.messages) == strip(snap_e.messages)
        assert verdict_g == verdict_e
        assert (outcome_g.outcome, outcome_g.state_changed) == (
            outcome_e.outcome,
            outcome_e.state_changed,
        )
