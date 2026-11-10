"""The hard spend cap (`hatchway.bench.budget`): every call reserves its maximum first, nothing
starts that could exceed a cap, spend persists, interruptions count at their reservation, and
reruns make no new calls."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from test_bench_score import NO_RETRY, POLICY, FakeJudge, _distinct_writes

from hatchway.bench import BenchStore
from hatchway.bench.budget import BudgetRefused, Caps, Ledger, chars_to_tokens, llm_call_max_usd
from hatchway.bench.score import BudgetedJudge, judge_call_max_usd, score_store
from hatchway.judges.base import Question, QuestionType
from hatchway.judges.runner import JudgeError, RetryPolicy, score_with_retry

CAPS = Caps({"capture": 9.0, "scoring": 3.0}, total=12.0)


@pytest.fixture
def ledger(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db"):
        pass
    with Ledger(tmp_path / "bench.db", CAPS) as led:
        yield led


# --- The ledger ----------------------------------------------------------------------------------


def test_a_call_that_could_exceed_the_remaining_budget_is_refused(ledger: Ledger) -> None:
    ledger.settle(ledger.reserve("a", "scoring", 2.5), 2.5)
    with pytest.raises(BudgetRefused):
        ledger.reserve("b", "scoring", 0.6)  # 2.5 + 0.6 > 3
    ledger.settle(ledger.reserve("c", "scoring", 0.5), 0.2)  # exactly 3.0 reserved: allowed
    assert ledger.committed("scoring") == pytest.approx(2.7)
    assert ledger.remaining("scoring") == pytest.approx(0.3)


def test_exact_nine_plus_three_aggregate_under_concurrency(ledger: Ledger) -> None:
    """Many threads race for $0.25 reservations: exactly the caps' worth succeed."""
    granted = {"capture": 0, "scoring": 0}
    lock = threading.Lock()

    def take(category: str) -> None:
        try:
            r = ledger.reserve(f"t-{category}", category, 0.25)
        except BudgetRefused:
            return
        ledger.settle(r, 0.25)
        with lock:
            granted[category] += 1

    threads = [
        threading.Thread(target=take, args=(c,)) for c in ["capture"] * 60 + ["scoring"] * 30
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert granted == {"capture": 36, "scoring": 12}
    assert ledger.committed("capture") == pytest.approx(9.0)
    assert ledger.committed("scoring") == pytest.approx(3.0)
    assert ledger.committed() == pytest.approx(12.0)


def test_the_aggregate_cap_binds_across_categories(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "b.db"):
        pass
    with Ledger(tmp_path / "b.db", Caps({"capture": 9.0, "scoring": 3.0}, total=10.0)) as led:
        led.settle(led.reserve("x", "capture", 9.0), 9.0)
        with pytest.raises(BudgetRefused):
            led.reserve("y", "scoring", 1.5)  # scoring has 3 left, the total only 1


def test_an_interrupted_call_counts_at_its_reservation(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "b.db"):
        pass
    with Ledger(tmp_path / "b.db", CAPS) as led:
        led.reserve("in flight", "capture", 0.4)  # the process dies before settling
    with Ledger(tmp_path / "b.db", CAPS) as led:  # a new process
        assert led.committed("capture") == pytest.approx(0.4)  # counted, not free
        assert led.recover() == 1
        assert led.committed("capture") == pytest.approx(0.4)
        assert led.summary()["rows"][0]["status"] == "settled"


def test_spend_persists_after_every_call(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "b.db"):
        pass
    with Ledger(tmp_path / "b.db", CAPS) as led, led.call("one", "capture", 0.5) as call:
        call.cost = 0.123
    with Ledger(tmp_path / "b.db", CAPS) as led:
        assert led.committed("capture") == pytest.approx(0.123)


def test_a_failed_call_settles_at_its_reservation(ledger: Ledger) -> None:
    with pytest.raises(RuntimeError), ledger.call("boom", "capture", 0.3):
        raise RuntimeError("connection dropped")
    assert ledger.committed("capture") == pytest.approx(0.3)


def test_conservative_maxima() -> None:
    assert chars_to_tokens(4000) >= 2000  # about twice a real tokenizer's count
    assert llm_call_max_usd(1000, 100, 2e-6, 8e-6) == pytest.approx(0.0028)


# --- Scoring --------------------------------------------------------------------------------------


QUESTIONS = [Question(name="policy_ok", type=QuestionType.YES_NO, text="Follows policy.")]


class Flaky(FakeJudge):
    """Fails retryably `failures` times, then answers."""

    def __init__(self, failures: int) -> None:
        super().__init__("jev", "jev-1.14.0", cost=0.0001)
        self.failures = failures

    async def score_with_cost(self, state_text: str, questions: Any) -> Any:
        if self.failures:
            self.failures -= 1
            raise JudgeError("HTTP 503", retryable=True)
        return await super().score_with_cost(state_text, questions)


def test_each_retried_attempt_is_reserved(ledger: Ledger) -> None:
    judge = BudgetedJudge(Flaky(failures=2), ledger)

    async def no_sleep(_: float) -> None:
        return None

    record = asyncio.run(
        score_with_retry(
            judge,
            "state",
            QUESTIONS,
            state_hash="h",
            rubric_hash="r",
            policy=RetryPolicy(max_attempts=4),
            sleep=no_sleep,
        )
    )
    assert record.status == "ok" and record.attempts == 3
    rows = ledger.summary()["rows"]
    assert sum(r["calls"] for r in rows) == 3  # one reservation per attempt
    # The two failures had no reported cost: each counts at its reservation.
    maximum = judge_call_max_usd(judge.inner, "state", QUESTIONS)
    assert ledger.committed("scoring") == pytest.approx(2 * maximum + 0.0001)


def _jev() -> FakeJudge:
    return FakeJudge("jev", "jev-1.14.0", cost=0.0001)


def test_scoring_stops_at_the_cap_and_a_cached_rerun_calls_nothing(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "bench.db") as store:
        _distinct_writes(store, 6)
        judge = _jev()
        maxima = [
            judge_call_max_usd(
                judge, w.state_text, list(POLICY.actions[w.action].questions.values())
            )
            for w in store.writes()
        ]
        maximum = max(maxima)
        assert maximum < 1.01 * min(maxima)  # the states are nearly the same length
        judge.cost = min(maxima) / 2  # a real call costs less than its reserved maximum
        # Room for three and a half calls' maxima.
        with Ledger(store.path, Caps({"scoring": 3.5 * maximum})) as led:
            first = asyncio.run(
                score_store(store, POLICY, [judge], ledger=led, retry=NO_RETRY, concurrency=1)
            )
            assert first.spend_cap_reached
            # Each call settles at half its maximum, freeing budget: five fit, and the sixth
            # reservation would pass the cap, so it is never sent.
            assert sum(judge.calls.values()) == 5
            assert led.committed("scoring") <= 3.5 * maximum
        with Ledger(store.path, Caps({"scoring": 1.0})) as led:
            asyncio.run(score_store(store, POLICY, [judge], ledger=led, retry=NO_RETRY))
            assert sum(judge.calls.values()) == 6
            before = led.summary()["rows"]
            again = _jev()
            asyncio.run(score_store(store, POLICY, [again], ledger=led, retry=NO_RETRY))
            assert sum(again.calls.values()) == 0  # cached: nothing reserved, nothing called
            assert led.summary()["rows"] == before


def test_a_judge_without_a_price_is_refused_before_calling(ledger: Ledger) -> None:
    with pytest.raises(BudgetRefused):
        judge_call_max_usd(FakeJudge("mystery", "m-1"), "state", QUESTIONS)


def test_scoring_action_filter(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "bench.db") as store:
        _distinct_writes(store, 2)
        judge = _jev()
        summary = asyncio.run(
            score_store(store, POLICY, [judge], retry=NO_RETRY, actions={"refuel_data"})
        )
        assert summary.filtered_writes == 2 and sum(judge.calls.values()) == 0


# --- Capture ----------------------------------------------------------------------------------


def _fake_completion(cost_tokens: int = 1000) -> Any:
    from litellm import ModelResponse

    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return ModelResponse(
            model=kwargs["model"],
            choices=[
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            usage={"prompt_tokens": cost_tokens, "completion_tokens": 5, "total_tokens": 1005},
        )

    completion.calls = calls  # type: ignore[attr-defined]
    return completion


MINI = "gpt-4.1-mini-2025-04-14"


def test_capture_calls_reserve_first_and_refuse_past_the_cap(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("tau2")
    import tau2.utils.llm_utils as llm_utils
    from tau2.data_model.message import UserMessage

    from hatchway.bench.tau2.harness import budget_guard

    fake = _fake_completion()
    monkeypatch.setattr(llm_utils, "completion", fake)
    messages = [UserMessage(role="user", content="hello " * 200)]
    with budget_guard(ledger):
        llm_utils.generate(model=MINI, messages=messages, max_tokens=100)
        # Settled at litellm's cost of the response, not at the reservation.
        assert ledger.committed("capture") == pytest.approx(1000 * 4e-7 + 5 * 1.6e-6)
        with pytest.raises(BudgetRefused):  # no output cap: no maximum, no call
            llm_utils.generate(model=MINI, messages=messages)
        assert len(fake.calls) == 1
        ledger.settle(ledger.reserve("fill", "capture", ledger.remaining("capture") - 1e-6), None)
        with pytest.raises(BudgetRefused):
            llm_utils.generate(model=MINI, messages=messages, max_tokens=100)
        assert len(fake.calls) == 1  # the refused call was never sent
    assert llm_utils.completion is fake  # restored


def test_a_budget_refusal_abandons_the_simulation_and_its_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A simulation the budget stops midway is recorded as failed: its writes are abandoned, so
    nothing downstream analyses them. A rerun with budget left completes it under a new session,
    and a duplicate run does nothing."""
    pytest.importorskip("tau2")
    import tau2.utils.llm_utils as llm_utils
    from tau2.data_model.message import ToolCall, UserMessage
    from test_tau2_harness import ScriptedAgent, ScriptedUser, _task

    from hatchway import Gate
    from hatchway.bench.tau2 import DEFAULT_POLICY
    from hatchway.bench.tau2.harness import budget_guard, run_batch

    task = _task("retail", "13")
    refund = ToolCall(
        name="return_delivered_order_items",
        arguments={
            "order_id": "#W5490111",
            "item_ids": ["4579334072"],
            "payment_method_id": "credit_card_3124723",
        },
        requestor="assistant",
    )

    class ThinkingAgent(ScriptedAgent):
        """Makes the refund, then asks an LLM something before finishing."""

        def generate_next_message(self, message: Any, state: int) -> Any:
            if state == 1:
                llm_utils.generate(
                    model=MINI, messages=[UserMessage(role="user", content="sum up")], max_tokens=50
                )
            return super().generate_next_message(message, state)

    monkeypatch.setattr(llm_utils, "completion", _fake_completion())
    with BenchStore(tmp_path / "bench.db") as store:
        gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
        kwargs = dict(
            num_trials=1,
            store=store,
            mode="wrapped",
            gate=gate,
            agent_model="scripted",
            make_agent=lambda env, _: ThinkingAgent(env.get_tools(), env.get_policy(), [refund]),
            make_user=lambda env, _: ScriptedUser([]),
        )
        with Ledger(store.path, Caps({"capture": 1e-9})) as broke, budget_guard(broke):
            report = run_batch("retail", [task], **kwargs)
        assert report.ran == 0 and len(report.failed) == 1
        [failed] = store.simulations("failed")
        assert failed.session_id in store.abandoned_session_ids()
        assert {w.session_id for w in store.writes()} == {failed.session_id}  # only abandoned

        with Ledger(store.path, Caps({"capture": 1.0})) as led, budget_guard(led):
            report = run_batch("retail", [task], **kwargs)
            assert report.ran == 1
            calls = led.summary()["rows"]
            again = run_batch("retail", [task], **kwargs)  # a duplicate: resumed, no calls
            assert again.ran == 0 and again.resumed == 1
            assert led.summary()["rows"] == calls
        [done] = store.simulations("done")
        assert done.session_id not in store.abandoned_session_ids()


def test_cumulative_stages_only_run_the_new_simulations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("tau2")
    from test_tau2_harness import ScriptedAgent, ScriptedUser, _task

    from hatchway import Gate
    from hatchway.bench.tau2 import DEFAULT_POLICY
    from hatchway.bench.tau2.harness import run_batch

    stage1 = [_task("retail", "13")]
    stage2 = [*stage1, _task("retail", "10")]
    with BenchStore(tmp_path / "bench.db") as store:
        gate = Gate(DEFAULT_POLICY, store=store, domain="retail", agent_model="scripted")
        kwargs = dict(
            num_trials=1,
            store=store,
            mode="wrapped",
            gate=gate,
            agent_model="scripted",
            make_agent=lambda env, _: ScriptedAgent(env.get_tools(), env.get_policy(), []),
            make_user=lambda env, _: ScriptedUser([]),
        )
        first = run_batch("retail", stage1, **kwargs)
        second = run_batch("retail", stage2, **kwargs)
        assert (first.ran, second.ran, second.resumed) == (1, 1, 1)
        assert len(store.simulations("done")) == 2
        # Nothing starts while the budget margin is not there.
        third = run_batch("retail", [_task("retail", "1")], can_start=lambda: False, **kwargs)
        assert (third.ran, third.not_started) == (0, 1)
