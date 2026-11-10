"""Judge adapters, request mapping and the retry runner.

Request bodies are checked against the documented `/v1/decisions` shapes. Response parsing is
tested only against responses recorded from real API calls (tests/fixtures/judges/); fake
judges below exercise the runner, not any API.
"""

import asyncio
import random
from collections.abc import Sequence

import pytest

from hatchway.bench import BenchStore, ScoreRecord
from hatchway.judges import (
    ChoiceAnswer,
    Judge,
    Question,
    QuestionType,
    QuestionVector,
    ScoreAnswer,
    YesNoAnswer,
    jev,
    llm_baseline,
    openai_decisions,
)
from hatchway.judges.oracle import OracleJudge
from hatchway.judges.runner import JudgeError, JudgeResult, RetryPolicy, score_with_retry
from hatchway.state import state_hash

YES_NO = Question(name="policy_ok", type=QuestionType.YES_NO, text="This refund follows policy.")
CHOICE = Question(name="risk", type=QuestionType.CHOICE, options=("low", "medium", "high"))
SCORE = Question(name="fit", type=QuestionType.SCORE, text="This matches the request.")
QUESTIONS = (YES_NO, CHOICE, SCORE)
STATE = "## Proposed action\nrefund_order({})\n"


def _vector(judge: str = "fake", model_id: str = "fake-1", **overrides) -> QuestionVector:
    answers = {
        "policy_ok": YesNoAnswer(p_yes=0.8),
        "risk": ChoiceAnswer(probs={"low": 0.7, "medium": 0.2, "high": 0.1}),
        "fit": ScoreAnswer(value=0.75),
    } | overrides
    return QuestionVector(judge=judge, model_id=model_id, answers=answers)


class ScriptedJudge:
    """Plays back a script of results or exceptions, one per call."""

    name = "fake"
    model_id = "fake-1"

    def __init__(self, *script: object, delay_s: float = 0.0) -> None:
        self.script = list(script)
        self.calls = 0
        self.delay_s = delay_s

    async def score_with_cost(self, state_text: str, questions: Sequence[Question]) -> JudgeResult:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item  # type: ignore[return-value]

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
        return (await self.score_with_cost(state_text, questions)).vector


def _run(judge: Judge, policy: RetryPolicy | None = None) -> tuple[ScoreRecord, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    record = asyncio.run(
        score_with_retry(
            judge,
            STATE,
            QUESTIONS,
            state_hash="s" * 64,
            rubric_hash="r" * 64,
            policy=policy or RetryPolicy(max_attempts=3, base_delay_s=1.0),
            sleep=fake_sleep,
            rng=random.Random(0),
        )
    )
    return record, sleeps


# --- Request mapping: each question type maps to the documented API shape -------------------


def test_decisions_request_maps_each_question_type() -> None:
    body = openai_decisions.build_request("gpt-6-luna", STATE, QUESTIONS)
    assert body["model"] == "gpt-6-luna"
    assert body["input"] == STATE
    predicate, choice, score = body["questions"]
    assert predicate["type"] == "predicate"
    assert predicate["name"] == "policy_ok"
    assert "This refund follows policy." in predicate["instructions"]
    assert set(predicate) == {"type", "name", "instructions"}
    assert choice["type"] == "choice"
    assert choice["choices"] == [{"value": "low"}, {"value": "medium"}, {"value": "high"}]
    assert set(choice) == {"type", "name", "instructions", "choices"}
    assert score["type"] == "score"
    assert [level["label"] for level in score["levels"]] == [
        label for label, _ in openai_decisions.SCORE_LEVELS
    ]
    assert set(score) == {"type", "name", "instructions", "levels"}


def test_llm_baseline_request_asks_for_one_token_with_logprobs() -> None:
    for q in QUESTIONS:
        body = llm_baseline.build_request("chat-model", STATE, q)
        assert body["max_completion_tokens"] == 1
        assert body["logprobs"] is True
        assert body["messages"][-1]["content"].startswith(STATE)
    choice_prompt = llm_baseline.build_request("m", STATE, CHOICE)["messages"][-1]["content"]
    assert "1. low\n2. medium\n3. high" in choice_prompt


def test_llm_baseline_rejects_choice_with_too_many_options() -> None:
    q = Question(name="x", type=QuestionType.CHOICE, options=tuple("abcdefghij"))
    with pytest.raises(JudgeError) as info:
        llm_baseline.build_request("m", STATE, q)
    assert not info.value.retryable


def test_adapters_require_a_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        openai_decisions.OpenAIDecisionsJudge()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm_baseline.LLMBaselineJudge(model_id="m")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        jev.JevJudge()


# --- Runner: retries, latency, cost and error rows ------------------------------------------


def test_success_on_first_attempt() -> None:
    judge = ScriptedJudge(JudgeResult(_vector(), cost_usd=0.002))
    record, sleeps = _run(judge)
    assert record.status == "ok"
    assert record.question_vector == _vector()
    assert record.attempts == 1
    assert record.cost_usd == pytest.approx(0.002)
    assert record.first_attempt_latency_ms is not None
    assert record.latency_ms is not None
    assert record.latency_ms >= record.first_attempt_latency_ms
    assert sleeps == []


def test_retryable_errors_are_retried_with_backoff_and_cost_summed() -> None:
    judge = ScriptedJudge(
        JudgeError("HTTP 429", retryable=True),
        JudgeError("HTTP 500", retryable=True, cost_usd=0.001),
        JudgeResult(_vector(), cost_usd=0.002),
    )
    record, sleeps = _run(judge)
    assert record.status == "ok"
    assert record.attempts == 3
    assert record.cost_usd == pytest.approx(0.003)
    assert len(sleeps) == 2
    assert 0 <= sleeps[0] <= 1.0
    assert 0 <= sleeps[1] <= 2.0


def test_exhausted_retries_store_an_error_row_not_a_score() -> None:
    judge = ScriptedJudge(*(JudgeError("HTTP 503", retryable=True) for _ in range(3)))
    record, sleeps = _run(judge)
    assert record.status == "error"
    assert record.question_vector is None
    assert record.attempts == 3
    assert record.error == "HTTP 503"
    assert len(sleeps) == 2


def test_non_retryable_error_stops_immediately() -> None:
    judge = ScriptedJudge(JudgeError("refusal for policy_ok", retryable=False, cost_usd=0.001))
    record, sleeps = _run(judge)
    assert (record.status, record.attempts, sleeps) == ("error", 1, [])
    assert record.error == "refusal for policy_ok"
    assert record.cost_usd == pytest.approx(0.001)


def test_answers_that_do_not_match_the_questions_are_an_error() -> None:
    wrong_type = _vector(fit=YesNoAnswer(p_yes=0.5))
    judge = ScriptedJudge(JudgeResult(wrong_type))
    record, _ = _run(judge)
    assert record.status == "error"
    assert record.error is not None and record.error.startswith("malformed answers")
    assert judge.calls == 1


def test_answers_from_the_wrong_model_are_an_error() -> None:
    record, _ = _run(ScriptedJudge(JudgeResult(_vector(model_id="other"))))
    assert record.status == "error"


def test_timeouts_are_retried_and_first_attempt_latency_recorded() -> None:
    judge = ScriptedJudge(JudgeResult(_vector()), JudgeResult(_vector()), delay_s=0.2)
    policy = RetryPolicy(max_attempts=2, timeout_s=0.05, base_delay_s=0.0)
    record, _ = _run(judge, policy)
    assert record.status == "error"
    assert record.attempts == 2
    assert record.error == "timed out after 0.05s"
    assert record.first_attempt_latency_ms is not None
    assert record.first_attempt_latency_ms >= 50


def test_judge_with_plain_score_method_works() -> None:
    class Plain:
        name = "fake"
        model_id = "fake-1"

        async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
            return _vector()

    record, _ = _run(Plain())
    assert record.status == "ok"
    assert record.cost_usd is None


def test_error_rows_round_trip_through_the_store(tmp_path) -> None:
    record, _ = _run(ScriptedJudge(JudgeError("HTTP 400", retryable=False)))
    with BenchStore(tmp_path / "bench.db") as store:
        assert store.put_score(record)
        assert store.get_score(*record.key) == record


# --- Oracle ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdict", "p_ok"), [("ALLOW", 1.0), ("ASK", 0.0), ("DENY", 0.0), ("UNKNOWN", 0.5)]
)
def test_oracle_answers_from_policy_verdicts(verdict: str, p_ok: float) -> None:
    judge = OracleJudge({state_hash(STATE): verdict})  # type: ignore[dict-item]
    record, _ = _run(judge)
    assert record.status == "ok"
    vector = record.question_vector
    assert vector is not None
    assert vector.answers["policy_ok"] == YesNoAnswer(p_yes=p_ok)
    assert vector.answers["fit"] == ScoreAnswer(value=p_ok)
    assert vector.answers["risk"] == ChoiceAnswer(
        probs={"low": 1 / 3, "medium": 1 / 3, "high": 1 / 3}
    )


def test_oracle_without_a_verdict_is_an_error() -> None:
    record, _ = _run(OracleJudge({}))
    assert (record.status, record.attempts) == ("error", 1)


def test_adapters_satisfy_the_judge_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-real")
    assert isinstance(OracleJudge({}), Judge)
    assert isinstance(openai_decisions.OpenAIDecisionsJudge(), Judge)
    assert isinstance(llm_baseline.LLMBaselineJudge(model_id="m"), Judge)
    assert isinstance(jev.JevJudge(), Judge)
