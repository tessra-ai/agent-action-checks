"""The live gated pass on real τ² tasks with a scripted agent and user and fake judges (no LLM or
judge API calls)."""

from pathlib import Path
from typing import Any

import pytest

tau2 = pytest.importorskip("tau2")

from gated_doubles import FakeJudge, frozen_arm  # noqa: E402
from tau2.data_model.message import (  # noqa: E402
    AssistantMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from test_tau2_harness import (  # noqa: E402
    TELECOM_TASK,
    ScriptedAgent,
    ScriptedUser,
    _gold_calls,
    _task,
    _visible,
)

from hatchway.bench import DENIAL_RESULT, BenchStore  # noqa: E402
from hatchway.bench.gated import GatedGate, SimulatedApprover  # noqa: E402
from hatchway.bench.tau2 import DEFAULT_POLICY  # noqa: E402
from hatchway.bench.tau2.gated import (  # noqa: E402
    executed_trajectory,
    gated_summary,
    main,
    run_gated_batch,
    run_gated_simulation,
)
from hatchway.bench.tau2.harness import run_simulation  # noqa: E402
from hatchway.bench.tau2.label import GroundTruth, match_session, match_store  # noqa: E402
from hatchway.bench.tau2.verdicts import ORACLE_VERSION  # noqa: E402
from hatchway.bench.tau2.verdicts.base import Check, combine  # noqa: E402
from hatchway.policy import load_policy  # noqa: E402

EXCHANGE = "exchange_delivered_order_items"


@pytest.fixture
def store(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as store:
        yield store


@pytest.fixture
def trace_oracle(monkeypatch: pytest.MonkeyPatch):
    """A test oracle for the gated plumbing: a write is ALLOW when it is one of the task's
    reference calls, else DENY. (The real oracle has no validator for exchanges, so it would
    say UNKNOWN and nothing would run.) Returns a setter for the reference calls."""
    gold: list[tuple[str, dict]] = []

    def evaluate(evidence: Any) -> Any:
        ok = (evidence.action, dict(evidence.args)) in gold
        return combine([Check("TRACE", "pass" if ok else "deny")], ORACLE_VERSION)

    monkeypatch.setattr("hatchway.bench.tau2.snapshot.evaluate", evaluate)
    return lambda calls: gold.extend((c.name, dict(c.arguments)) for c in calls)


def _gate(store: BenchStore, domain: str, *, threshold: float, judges=None, approver=None):
    policy = load_policy(DEFAULT_POLICY)
    judges = judges or [FakeJudge("jev", "j-1"), FakeJudge("dec", "d-1")]
    return GatedGate(
        policy,
        store=store,
        arm=frozen_arm(policy, judges, threshold=threshold),
        judges=judges,
        approver=approver or SimulatedApprover("perfect"),
        domain=domain,
        agent_model="scripted",
    )


def _run(domain: str, task: Any, calls: list[ToolCall], gate: GatedGate | None = None):
    """Run plain τ² without a gate, gated otherwise. Returns the simulation and environment."""
    envs = []

    def make_agent(env: Any, _: Any) -> ScriptedAgent:
        envs.append(env)
        return ScriptedAgent(env.get_tools(), env.get_policy(), calls)

    kwargs = dict(
        trial=1,
        seed=7,
        make_agent=make_agent,
        make_user=lambda env, _: ScriptedUser(_gold_calls(task, "user")),
    )
    if gate is None:
        sim = run_simulation(domain, task, **kwargs)
    else:
        sim = run_gated_simulation(domain, task, gate=gate, **kwargs)
    return sim, envs[0]


def _reads(task: Any) -> list[ToolCall]:
    return [c for c in _gold_calls(task, "assistant") if c.name != EXCHANGE]


def _wrong_exchange(task: Any) -> ToolCall:
    """The gold exchange with one item left out: same tool, different arguments (incorrect)."""
    gold = next(c for c in _gold_calls(task, "assistant") if c.name == EXCHANGE)
    args = {**gold.arguments}
    args["item_ids"], args["new_item_ids"] = args["item_ids"][:1], args["new_item_ids"][:1]
    return ToolCall(name=EXCHANGE, arguments=args)


def _tool_results(sim: Any) -> list[str]:
    return [m.content for m in sim.messages if m.role == "tool"]


@pytest.mark.parametrize(("domain", "task_id"), [("retail", "0"), ("telecom", TELECOM_TASK)])
def test_always_allow_gated_run_matches_unwrapped(
    store: BenchStore, trace_oracle: Any, domain: str, task_id: str
) -> None:
    task = _task(domain, task_id)
    calls = _gold_calls(task, "assistant")
    trace_oracle(calls)
    if domain == "retail":  # plus a write the environment rejects with an error
        calls.append(
            ToolCall(
                name="cancel_pending_order",
                arguments={"order_id": "#W2378156", "reason": "no longer needed"},
            )
        )
    with _gate(store, domain, threshold=0.0) as gate:
        plain, plain_env = _run(domain, task, calls)
        gated, gated_env = _run(domain, task, calls, gate=gate)

    assert _visible(gated) == _visible(plain)
    assert gated.reward_info.reward == plain.reward_info.reward
    assert gated_env.get_db_hash() == plain_env.get_db_hash()
    decisions = store.gated_decisions()
    assert [w.write_id for w in store.writes()] == [d.write_id for d in decisions]
    # The extra cancel is not a reference call: DENY, which the always-allow gate lets run.
    # The environment rejects it; nothing else differs from the unwrapped run.
    assert decisions and all(d.decision == "ALLOW" and d.executed for d in decisions)
    outcomes = [store.outcome(d.write_id) for d in decisions]
    assert all(o is not None for o in outcomes)
    if domain == "retail":
        *gold, cancel = outcomes
        assert cancel.outcome == "REJECTED" and cancel.state_changed is False
        assert all(o.outcome == "ACCEPTED" for o in gold)


def test_rejected_write_never_runs_and_returns_exactly_the_denial(
    store: BenchStore, trace_oracle: Any
) -> None:
    task = _task("retail", "0")
    wrong = _wrong_exchange(task)
    with _gate(store, "retail", threshold=1.1) as gate:  # asks on every write
        gated, gated_env = _run("retail", task, [*_reads(task), wrong], gate=gate)
    reads_only, reads_env = _run("retail", task, _reads(task))

    [d] = store.gated_decisions()
    assert (d.decision, d.approver_answer, d.executed) == ("ASK", "reject", False)
    outcome = store.outcome(d.write_id)
    assert outcome is not None and outcome.outcome == "NOT_EXECUTED"
    verdict = store.verdict(d.write_id, ORACLE_VERSION)
    assert verdict is not None and verdict.expected_decision == "DENY"
    [denial] = [m for m in gated.messages if m.role == "tool" and m.content == DENIAL_RESULT]
    assert denial.content.encode() == DENIAL_RESULT.encode() and not denial.error
    # The tool never ran: the database is exactly as if the write was never proposed.
    assert gated_env.get_db_hash() == reads_env.get_db_hash()
    order = gated_env.tools.db.orders["#W2378156"]
    assert order.status == "delivered" and not getattr(order, "exchange_items", None)
    assert gated.reward_info.reward == reads_only.reward_info.reward == 0.0


def test_denial_repeats_are_counted_and_an_approved_write_runs(
    store: BenchStore, trace_oracle: Any
) -> None:
    task = _task("retail", "0")
    trace_oracle(_gold_calls(task, "assistant"))
    wrong = _wrong_exchange(task)
    other = ToolCall(name=EXCHANGE, arguments={**wrong.arguments, "payment_method_id": "x"})
    right = next(c for c in _gold_calls(task, "assistant") if c.name == EXCHANGE)
    calls = [*_reads(task), wrong, wrong, other, right]
    with _gate(store, "retail", threshold=1.1) as gate:
        gated, gated_env = _run("retail", task, calls, gate=gate)
        summary = gated_summary(store, [gated], gate)
    _, gold_env = _run("retail", task, _gold_calls(task, "assistant"))

    decisions = store.gated_decisions()
    assert [d.approver_answer for d in decisions] == ["reject", "reject", "reject", "approve"]
    assert [(d.repeat_same_args, d.repeat_same_action) for d in decisions] == [
        (False, False),
        (True, True),
        (False, True),
        (False, True),
    ]
    assert _tool_results(gated).count(DENIAL_RESULT) == 3
    # Only the approved write ran, so the database matches the gold run.
    assert gated_env.get_db_hash() == gold_env.get_db_hash()
    assert gated.reward_info.db_check.db_match
    assert summary["repeat_attempts"] == {"same_action_same_args": 1, "same_action": 3}
    assert (summary["denials"], summary["approvals"], summary["asks"]) == (3, 1, 4)
    assert summary["intervention_required_recall"] == 1.0 and summary["simulations"] == 1
    assert summary["final_task_outcome"]["pass_rate"] == (
        1.0 if gated.reward_info.reward == 1 else 0.0
    )


def test_live_trace_matches_equal_the_offline_labeler(store: BenchStore, trace_oracle: Any) -> None:
    task = _task("retail", "0")
    trace_oracle(_gold_calls(task, "assistant"))
    wrong = _wrong_exchange(task)
    right = next(c for c in _gold_calls(task, "assistant") if c.name == EXCHANGE)
    with _gate(store, "retail", threshold=1.1) as gate:
        _run("retail", task, [*_reads(task), wrong, right, right], gate=gate)
    writes = store.writes()
    truth = GroundTruth.from_task(task)
    offline = match_session([(w.action, w.args) for w in writes], truth)
    live = store.benchmark_matches()
    assert [live[w.write_id] for w in writes] == offline == ["MISMATCH", "MATCH", "AMBIGUOUS"]
    assert match_store(store, {("retail", "0"): truth}) == {}  # nothing left to match
    # The approver follows the policy verdict, not the trace match.
    assert [d.approver_answer for d in store.gated_decisions()] == ["reject", "approve", "approve"]


def test_without_a_validator_nothing_runs_automatically(store: BenchStore) -> None:
    """The real oracle has no validator for payment changes: UNKNOWN, so even an always-allow
    gate blocks the write, and the verdict stays UNKNOWN."""
    task = _task("retail", "40")
    calls = _gold_calls(task, "assistant")
    right = next(c for c in calls if c.name == "modify_pending_order_payment")
    reads = [c for c in calls if c.name != right.name]
    with _gate(store, "retail", threshold=0.0) as gate:
        _run("retail", task, [*reads, right], gate=gate)
    [d] = store.gated_decisions()
    assert (d.decision, d.ask_reason, d.approver_answer, d.executed) == (
        "ASK",
        "unverified",
        "reject",
        False,
    )
    verdict = store.verdict(d.write_id, ORACLE_VERSION)
    assert verdict is not None and verdict.reason_codes == ("NO_VALIDATOR",)
    outcome = store.outcome(d.write_id)
    assert outcome is not None and outcome.outcome == "NOT_EXECUTED"


def test_judge_timeout_in_a_live_run_asks(store: BenchStore) -> None:
    from hatchway.judges.runner import RetryPolicy

    task = _task("retail", "0")
    policy = load_policy(DEFAULT_POLICY)
    judges = [FakeJudge("slow", "s-1", delay_s=1.0)]
    gate = GatedGate(
        policy,
        store=store,
        arm=frozen_arm(policy, judges, threshold=0.0),
        judges=judges,
        approver=SimulatedApprover("perfect"),
        domain="retail",
        retry=RetryPolicy(max_attempts=1, timeout_s=0.05),
    )
    with gate:
        _run("retail", task, [*_reads(task), _wrong_exchange(task)], gate=gate)
    [d] = store.gated_decisions()
    assert (d.decision, d.ask_reason, d.executed) == ("ASK", "judge_error", False)


def test_spend_cap_stops_new_simulations(store: BenchStore) -> None:
    task = _task("retail", "0")
    judges = [FakeJudge("jev", "j-1", cost_usd=1.0)]
    with _gate(store, "retail", threshold=0.0, judges=judges) as gate:
        report = run_gated_batch(
            "retail",
            [task, task],
            gate=gate,
            num_trials=2,
            spend_cap_usd=0.5,
            make_agent=lambda env, _: ScriptedAgent(
                env.get_tools(), env.get_policy(), _gold_calls(task, "assistant")
            ),
            make_user=lambda env, _: ScriptedUser([]),
        )
        assert gate.judge_cost_usd == 1.0
    # Jobs run in (trial, task) order; the first one spends past the cap.
    assert [(s.task_id, s.trial) for s in report.simulations] == [("0", 0)]
    assert report.failed == []
    assert report.not_run == [
        {"task_id": "0", "trial": 0},
        {"task_id": "0", "trial": 1},
        {"task_id": "0", "trial": 1},
    ]


def test_noisy_approver_flips_reproduce_across_live_runs(tmp_path: Path, trace_oracle: Any) -> None:
    task = _task("retail", "0")
    trace_oracle(_gold_calls(task, "assistant"))
    calls = [*_reads(task), *[_wrong_exchange(task)] * 12]

    def flips(path: Path) -> list[bool | None]:
        with BenchStore(path) as store:
            approver = SimulatedApprover("noisy", seed=11, flip_rate=0.5)
            with _gate(store, "retail", threshold=1.1, approver=approver) as gate:
                _run("retail", task, calls, gate=gate)
            return [d.approver_flipped for d in store.gated_decisions()]

    first = flips(tmp_path / "a.db")
    assert first == flips(tmp_path / "b.db") and any(first) and not all(first)


def test_cli_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_executed_trajectory_drops_denied_calls_and_their_results() -> None:
    read = ToolCall(id="1", name="get_order_details", arguments={"order_id": "#W1"})
    denied = ToolCall(id="2", name="cancel_pending_order", arguments={"order_id": "#W1"})
    also_denied = ToolCall(id="3", name="modify_user_address", arguments={"user_id": "u"})
    messages = [
        UserMessage(role="user", content="Cancel #W1."),
        AssistantMessage(role="assistant", content="Checking.", tool_calls=[read, denied]),
        ToolMessage(id="1", role="tool", content="{}"),
        ToolMessage(id="2", role="tool", content=DENIAL_RESULT),
        AssistantMessage(role="assistant", tool_calls=[also_denied]),
        ToolMessage(id="3", role="tool", content=DENIAL_RESULT),
        AssistantMessage(role="assistant", content="Sorry, that cannot be done."),
    ]
    out = executed_trajectory(messages, {"2", "3"})
    assert [(m.role, m.content) for m in out] == [
        ("user", "Cancel #W1."),
        ("assistant", "Checking."),
        ("tool", "{}"),
        ("assistant", "Sorry, that cannot be done."),
    ]
    assert out[1].tool_calls == [read]
    assert messages[1].tool_calls == [read, denied]  # the saved trajectory is untouched


def test_gated_runs_are_recorded_and_a_crashed_one_is_abandoned(store: BenchStore) -> None:
    task = _task("retail", "0")
    calls = [*_reads(task), _wrong_exchange(task)]

    class CrashingAgent(ScriptedAgent):
        def generate_next_message(self, message: Any, state: int):
            if state == len(calls):  # after its write was gated
                raise RuntimeError("agent LLM unavailable")
            return super().generate_next_message(message, state)

    agents = iter([ScriptedAgent, CrashingAgent])
    with _gate(store, "retail", threshold=1.1) as gate:
        report = run_gated_batch(
            "retail",
            [task, task],
            gate=gate,
            num_trials=1,
            make_agent=lambda env, _: next(agents)(env.get_tools(), env.get_policy(), calls),
            make_user=lambda env, _: ScriptedUser([]),
        )
        summary = gated_summary(store, report.simulations, gate)
    assert len(report.simulations) == 1
    assert report.failed == [{"task_id": "0", "trial": 0, "error": "RuntimeError"}]
    records = {r.session_id: r for r in store.simulations()}
    done = records[report.simulations[0].id]
    assert (done.mode, done.status, done.agent_model) == ("gated", "done", "scripted")
    [crashed] = [r for r in records.values() if r.status == "failed"]
    assert store.abandoned_session_ids() == {crashed.session_id}
    # The crashed session's write was gated and stored, but nothing counts it.
    assert {d.session_id for d in store.gated_decisions()} == set(records)
    assert summary["writes"] == 1


def test_one_store_holds_several_gated_runs_of_the_same_key(store: BenchStore) -> None:
    task = _task("retail", "0")
    for threshold in (0.0, 1.1):  # e.g. two arms, or two approver modes
        with _gate(store, "retail", threshold=threshold) as gate:
            report = run_gated_batch(
                "retail",
                [task],
                gate=gate,
                num_trials=1,
                make_agent=lambda env, _: ScriptedAgent(
                    env.get_tools(), env.get_policy(), _reads(task)
                ),
                make_user=lambda env, _: ScriptedUser([]),
            )
            assert len(report.simulations) == 1 and report.failed == []
    assert [r.status for r in store.simulations()] == ["done", "done"]
