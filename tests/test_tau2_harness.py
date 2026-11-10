"""The τ² capture harness on real τ² tasks with a scripted agent and user (no LLM calls)."""

import asyncio
import random
from pathlib import Path
from typing import Any

import pytest

tau2 = pytest.importorskip("tau2")

from tau2.agent.base import LocalAgent  # noqa: E402
from tau2.data_model.message import (  # noqa: E402
    AssistantMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.environment.toolkit import ToolType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.run import load_tasks  # noqa: E402
from tau2.user.base import BaseUser  # noqa: E402

from hatchway import Gate  # noqa: E402
from hatchway.bench import BenchStore  # noqa: E402
from hatchway.bench.score import SKIP_NO_REQUEST, score_store  # noqa: E402
from hatchway.bench.tau2 import DEFAULT_POLICY  # noqa: E402
from hatchway.bench.tau2.config import CONFIG_DIR, load_run_config  # noqa: E402
from hatchway.bench.tau2.harness import (  # noqa: E402
    SpendTracker,
    compare_pass_rates,
    render_transcript,
    run_batch,
    run_simulation,
    trial_seeds,
)
from hatchway.bench.tau2.label import GroundTruth, match_store  # noqa: E402
from hatchway.policy import Kind, load_policy  # noqa: E402

DONE = "That is everything, thank you."
TELECOM_TASK = "[mobile_data_issue]data_mode_off|data_usage_exceeded[PERSONA:None]"


class ScriptedAgent(LocalAgent):
    """Sends each scripted tool call in turn, then tells the user it is done."""

    def __init__(self, tools: Any, domain_policy: str, calls: list[ToolCall]) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.calls = calls

    def get_init_state(self, message_history: Any = None) -> int:
        return 0

    def generate_next_message(self, message: Any, state: int) -> tuple[AssistantMessage, int]:
        if state < len(self.calls):
            call = self.calls[state].model_copy(update={"id": f"call_{state}"})
            return AssistantMessage(role="assistant", tool_calls=[call]), state + 1
        return AssistantMessage(role="assistant", content=DONE), state

    def set_seed(self, seed: int) -> None:
        pass


class ScriptedUser(BaseUser):
    """Makes its scripted device tool calls, asks for help, and stops once the agent is done."""

    def __init__(self, calls: list[ToolCall]) -> None:
        super().__init__(instructions="scripted")
        self.calls = calls

    def get_init_state(self, message_history: Any = None) -> int:
        return 0

    def generate_next_message(self, message: Any, state: int) -> tuple[UserMessage, int]:
        if state < len(self.calls):
            call = self.calls[state].model_copy(update={"id": f"user_call_{state}"})
            return UserMessage(role="user", tool_calls=[call]), state + 1
        if isinstance(message, AssistantMessage) and message.content == DONE:
            return UserMessage(role="user", content="###STOP###"), state
        return UserMessage(role="user", content="Please go ahead."), state

    @classmethod
    def is_stop(cls, message: UserMessage) -> bool:
        return message.content is not None and "###STOP###" in message.content

    def set_seed(self, seed: int) -> None:
        pass


def _task(domain: str, task_id: str) -> Any:
    return next(t for t in load_tasks(domain, task_split_name=None) if t.id == task_id)


def _gold_calls(task: Any, requestor: str) -> list[ToolCall]:
    return [
        ToolCall(name=a.name, arguments=a.arguments, requestor=requestor)
        for a in task.evaluation_criteria.actions
        if a.requestor == requestor
    ]


def _run(domain: str, task: Any, agent_calls: list[ToolCall], gate: Gate | None = None):
    user_calls = _gold_calls(task, "user")
    return run_simulation(
        domain,
        task,
        trial=1,
        seed=7,
        gate=gate,
        make_agent=lambda env, _: ScriptedAgent(env.get_tools(), env.get_policy(), agent_calls),
        make_user=lambda env, _: ScriptedUser(user_calls),
    )


def _visible(sim: Any) -> list[tuple]:
    """What the agent and user saw, without timestamps and ids."""
    return [
        (m.role, m.content, [(c.name, c.arguments) for c in getattr(m, "tool_calls", None) or []])
        for m in sim.messages
    ]


@pytest.fixture
def store(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as store:
        yield store


@pytest.mark.parametrize("domain", ["retail", "telecom"])
def test_policy_lists_every_agent_tool_with_tau2_kind(domain: str) -> None:
    policy = load_policy(DEFAULT_POLICY)
    tools = registry.get_env_constructor(domain)().tools
    for name in tools.tools:
        expected = Kind.WRITE if tools.tool_type(name) is ToolType.WRITE else Kind.READ
        assert policy.actions[name].kind is expected, name


def test_wrapped_retail_run_matches_unwrapped_and_captures_only_writes(store: BenchStore) -> None:
    task = _task("retail", "0")
    calls = _gold_calls(task, "assistant")
    # A write that fails: the order is delivered, not pending. The agent sees the same error.
    calls.append(
        ToolCall(
            name="cancel_pending_order",
            arguments={"order_id": "#W2378156", "reason": "no longer needed"},
        )
    )
    gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")

    plain = _run("retail", task, calls)
    wrapped = _run("retail", task, calls, gate=gate)

    assert _visible(wrapped) == _visible(plain)
    assert wrapped.reward_info.reward == plain.reward_info.reward
    assert any(m.role == "tool" and m.error for m in wrapped.messages)

    writes = store.writes()
    assert [(w.action, w.args) for w in writes] == [
        (c.name, c.arguments)
        for c in calls
        if c.name in ("exchange_delivered_order_items", "cancel_pending_order")
    ]
    for seq, w in enumerate(writes):
        assert (w.domain, w.agent_model, w.task_id, w.trial) == ("retail", "scripted", "0", 1)
        assert (w.session_id, w.seq, w.known_action) == (wrapped.id, seq, True)
        assert w.context["policy"] == registry.get_env_constructor("retail")().get_policy()
        assert w.rubric_hash == gate.policy.actions[w.action].rubric_hash
    # The judge sees the conversation up to the proposed call, including read results.
    assert "assistant -> get_order_details" in writes[0].context["conversation"]
    assert '"#W2378156"' in writes[0].context["conversation"]
    assert "exchange_delivered_order_items" not in writes[0].context["conversation"]

    counts = match_store(store, {("retail", "0"): GroundTruth.from_task(task)})
    assert counts == {"MATCH": 1, "MISMATCH": 1}


def test_telecom_user_tools_and_initial_state_are_not_captured(store: BenchStore) -> None:
    task = _task("telecom", TELECOM_TASK)
    assert task.initial_state.initialization_actions  # replayed at start, never captured
    calls = _gold_calls(task, "assistant")
    gate = Gate(DEFAULT_POLICY, store=store, domain="telecom", agent_model="scripted")

    plain = _run("telecom", task, calls)
    wrapped = _run("telecom", task, calls, gate=gate)

    assert _visible(wrapped) == _visible(plain)
    assert wrapped.reward_info.reward == plain.reward_info.reward == 1.0
    assert any(c.requestor == "user" for m in wrapped.messages for c in m.tool_calls or [])
    assert [(w.action, w.args) for w in store.writes()] == [
        (c.name, c.arguments) for c in calls if c.name == "refuel_data"
    ]
    assert match_store(store, {("telecom", task.id): GroundTruth.from_task(task)}) == {"MATCH": 1}


def test_scripted_go_ahead_conversation_is_skipped_before_scoring(store: BenchStore) -> None:
    """The scripted user only ever says "Please go ahead.": no customer request, no judge call."""
    task = _task("retail", "0")
    gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
    _run("retail", task, _gold_calls(task, "assistant"), gate=gate)
    writes = store.writes()
    assert writes and "user: Please go ahead." in writes[0].context["conversation"]

    class NeverCalled:
        name, model_id = "never", "never-1"

        async def score(self, state_text: str, questions: Any) -> Any:
            raise AssertionError("judge called for a skipped write")

    summary = asyncio.run(score_store(store, gate.policy, [NeverCalled()]))
    assert summary.calls == 0 and summary.skipped_writes == len(writes)
    assert set(store.skips().values()) == {SKIP_NO_REQUEST}
    assert summary.skipped_by_task == [
        {"task_id": "0", "agent_model": "scripted", "writes": len(writes)}
    ]


def test_store_failure_stops_the_run_instead_of_reaching_the_agent(store: BenchStore) -> None:
    task = _task("retail", "0")

    class BrokenStore:
        def record_write(self, **kwargs: Any) -> None:
            raise RuntimeError("disk full")

    gate = Gate(DEFAULT_POLICY, store=BrokenStore(), domain="retail")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="disk full"):
        _run("retail", task, _gold_calls(task, "assistant"), gate=gate)


def test_gate_domain_must_match(store: BenchStore) -> None:
    gate = Gate(DEFAULT_POLICY, store=store, domain="telecom")
    with pytest.raises(ValueError, match="domain"):
        _run("retail", _task("retail", "0"), [], gate=gate)


def test_render_transcript_stops_before_the_pending_call() -> None:
    first = ToolCall(id="1", name="get_order_details", arguments={"order_id": "#W1"})
    pending = ToolCall(id="2", name="cancel_pending_order", arguments={"order_id": "#W1"})
    sibling = ToolCall(id="3", name="modify_user_address", arguments={"user_id": "u"})
    messages = [
        UserMessage(role="user", content="Cancel #W1."),
        AssistantMessage(role="assistant", tool_calls=[first]),
        ToolMessage(id="1", role="tool", content='{"status": "pending"}'),
        AssistantMessage(
            role="assistant", content="Cancelling now.", tool_calls=[pending, sibling]
        ),
    ]
    assert render_transcript(messages, pending) == (
        "user: Cancel #W1.\n"
        'assistant -> get_order_details({"order_id":"#W1"})\n'
        'tool (assistant): {"status": "pending"}\n'
        "assistant: Cancelling now."
    )


def test_trial_seeds_match_tau2() -> None:
    random.seed(300)
    assert trial_seeds(300, 3) == [random.randint(0, 1000000) for _ in range(3)]


def test_compare_pass_rates() -> None:
    same = compare_pass_rates([True, False] * 5, [True, False] * 5)
    assert same["difference"] == 0 and same["within_noise"]
    far = compare_pass_rates([True] * 10, [False] * 10)
    assert far["difference"] == 1 and not far["within_noise"]
    near = compare_pass_rates([True] * 6 + [False] * 4, [True] * 4 + [False] * 6)
    assert near["within_noise"]


# --- Resumable capture and the spend cap -------------------------------------------------------

AGENT_COST, USER_COST = 0.003, 0.001
FAILING_CANCEL = ToolCall(
    name="cancel_pending_order",
    arguments={"order_id": "#W2378156", "reason": "no longer needed"},
)


class Killed(BaseException):
    """Stands in for the process being killed: not an Exception, so nothing catches it."""


class PricedAgent(ScriptedAgent):
    """A scripted agent whose messages carry a cost, and that can be killed mid-simulation."""

    kill_at: int | None = None  # the agent turn at which the process "dies"

    def generate_next_message(self, message: Any, state: int) -> tuple[AssistantMessage, int]:
        if self.kill_at is not None and state >= self.kill_at:
            raise Killed
        reply, state = super().generate_next_message(message, state)
        return reply.model_copy(update={"cost": AGENT_COST}), state


class PricedUser(ScriptedUser):
    def generate_next_message(self, message: Any, state: int) -> tuple[UserMessage, int]:
        reply, state = super().generate_next_message(message, state)
        return reply.model_copy(update={"cost": USER_COST}), state


def _batch(store: BenchStore, tasks: list, **kwargs: Any):
    gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
    kill_at = kwargs.pop("kill_at", None)

    def make_agent(env: Any, task: Any) -> PricedAgent:
        agent = PricedAgent(env.get_tools(), env.get_policy(), [FAILING_CANCEL])
        agent.kill_at = kill_at
        return agent

    return run_batch(
        "retail",
        tasks,
        num_trials=2,
        seed=300,
        store=store,
        gate=gate,
        agent_model="scripted",
        user_model="scripted-user",
        make_agent=make_agent,
        make_user=lambda env, task: PricedUser([]),
        **kwargs,
    )


def test_killed_capture_run_resumes_without_redoing_finished_simulations(
    store: BenchStore,
) -> None:
    tasks = [_task("retail", "0"), _task("retail", "1")]
    first = _batch(store, tasks)
    assert (first.ran, first.resumed, len(first.simulations)) == (4, 0, 4)
    finished = {s.id for s in first.simulations}
    writes_before = len(store.writes())
    assert writes_before == 4  # one captured cancel per simulation

    # Same jobs again: everything is loaded from the store, nothing runs or is captured.
    again = _batch(store, tasks)
    assert (again.ran, again.resumed) == (0, 4)
    assert {s.id for s in again.simulations} == finished
    assert [s.model_dump() for s in again.simulations] == [
        s.model_dump() for s in first.simulations
    ]
    assert len(store.writes()) == writes_before

    # A third task, killed after its first write was captured.
    tasks.append(_task("retail", "2"))
    with pytest.raises(Killed):
        _batch(store, tasks, kill_at=1)
    abandoned = store.abandoned_session_ids()
    assert abandoned and not abandoned & finished
    assert {w.session_id for w in store.writes()} & abandoned  # its partial write was captured

    resumed = _batch(store, tasks)
    assert (resumed.ran, resumed.resumed) == (2, 4)
    assert [(s.task_id, s.trial) for s in resumed.simulations] == [
        (t, trial) for trial in (0, 1) for t in ("0", "1", "2")
    ]
    # Finished simulations keep their sessions; the killed ones ran again under new ones.
    done = store.done_simulations()
    assert len(done) == 6 and not {d.session_id for d in done.values()} & abandoned
    assert {s.id for s in resumed.simulations} == {d.session_id for d in done.values()}


def test_abandoned_writes_are_not_scored(store: BenchStore) -> None:
    with pytest.raises(Killed):
        _batch(store, [_task("retail", "0")], kill_at=1)
    assert store.writes()

    class NeverCalled:
        name, model_id = "never", "never-1"

        async def score(self, state_text: str, questions: Any) -> Any:
            raise AssertionError("judge called for an abandoned write")

    summary = asyncio.run(score_store(store, load_policy(DEFAULT_POLICY), [NeverCalled()]))
    assert summary.abandoned_writes == len(store.writes()) and summary.calls == 0


def test_spend_cap_stops_starting_new_simulations(store: BenchStore) -> None:
    tasks = [_task("retail", t) for t in ("0", "1", "2")]
    probe = _batch(store, tasks[:1], spend=SpendTracker())
    per_sim = probe.cost_usd / probe.ran
    assert per_sim > 0 and probe.simulations[0].agent_cost is not None

    # Two jobs are already done; the cap allows one more simulation to start.
    spend = SpendTracker(cap_usd=per_sim * 0.5)
    capped = _batch(store, tasks, spend=spend)
    assert (capped.resumed, capped.ran, capped.not_started) == (2, 1, 3)
    assert spend.spent_usd == pytest.approx(per_sim) and spend.reached()
    assert spend.unpriced == 0

    # A rerun with room for everything finishes the rest.
    rest = _batch(store, tasks, spend=SpendTracker(cap_usd=1.0))
    assert (rest.resumed, rest.ran, rest.not_started) == (3, 3, 0)


def test_failed_simulation_is_recorded_and_rerun(store: BenchStore) -> None:
    tasks = [_task("retail", "0")]
    calls = {"n": 0}

    def flaky_user(env: Any, task: Any) -> PricedUser:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("user simulator unavailable")
        return PricedUser([])

    gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
    common: dict[str, Any] = dict(
        num_trials=1,
        seed=300,
        store=store,
        gate=gate,
        agent_model="scripted",
        user_model="scripted-user",
        make_agent=lambda env, task: PricedAgent(env.get_tools(), env.get_policy(), []),
        make_user=flaky_user,
    )
    first = run_batch("retail", tasks, **common)
    assert first.failed == [{"task_id": "0", "trial": 0, "error": "RuntimeError"}]
    assert [s.status for s in store.simulations()] == ["failed"]
    second = run_batch("retail", tasks, **common)
    assert (second.ran, second.failed) == (1, [])


def test_resuming_with_a_different_user_model_is_refused(store: BenchStore) -> None:
    tasks = [_task("retail", "0")]
    _batch(store, tasks)
    gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
    with pytest.raises(ValueError, match="user model"):
        run_batch(
            "retail",
            tasks,
            num_trials=2,
            seed=300,
            store=store,
            gate=gate,
            agent_model="scripted",
            user_model="another-user",
            make_agent=lambda env, task: PricedAgent(env.get_tools(), env.get_policy(), []),
            make_user=lambda env, task: PricedUser([]),
        )


# --- Committed run configs -----------------------------------------------------------------------


def _ground_truth_writes(domain: str) -> dict[str, list[str]]:
    tools = registry.get_env_constructor(domain)().tools
    writes = {n for n in tools.tools if tools.tool_type(n) is ToolType.WRITE}
    return {
        t.id: [
            a.name
            for a in t.evaluation_criteria.actions or []
            if a.requestor == "assistant" and a.name in writes
        ]
        for t in load_tasks(domain, task_split_name="base")
    }


@pytest.mark.parametrize("name", ["pilot", "smoke"])
def test_config_task_ids_match_tau2_ground_truth(name: str) -> None:
    config = load_run_config(CONFIG_DIR / f"{name}.yaml")
    for domain, tasks in config.domains.items():
        assert tasks.task_split == "base"
        truth = _ground_truth_writes(domain)
        for task_id in tasks.write_task_ids:
            assert truth[task_id], f"{domain} {task_id} has no ground-truth write"
        for task_id in tasks.no_write_task_ids:
            assert truth[task_id] == [], f"{domain} {task_id} has a ground-truth write"


def test_pilot_covers_every_write_tool_the_base_split_uses() -> None:
    config = load_run_config(CONFIG_DIR / "pilot.yaml")
    for domain, tasks in config.domains.items():
        truth = _ground_truth_writes(domain)
        used = {tool for tools in truth.values() for tool in tools}
        chosen = {tool for t in tasks.write_task_ids for tool in truth[t]}
        assert chosen == used, domain
