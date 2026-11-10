"""Judge adapters against responses recorded from the real APIs.

Every fixture in tests/fixtures/judges/ is a real call made by scripts/record_judge_fixtures.py.
An httpx MockTransport plays it back: the adapter must send exactly the recorded request body
and gets the recorded status and response. Malformed-response cases serve a real response to a
request it does not answer.
"""

import asyncio
import json
import math
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from hatchway.bench import ScoreRecord
from hatchway.judges import (
    ChoiceAnswer,
    Question,
    QuestionType,
    ScoreAnswer,
    YesNoAnswer,
    jev,
    llm_baseline,
    openai_decisions,
)
from hatchway.judges.runner import RetryPolicy, score_with_retry

FIXTURES = Path(__file__).parent / "fixtures" / "judges"

# Must match scripts/record_judge_fixtures.py.
STATE = (
    "## Context: conversation\n"
    "Customer: I was charged twice for order #W123. Please refund the duplicate $20 charge.\n\n"
    "## Earlier writes in this session\n(none)\n\n"
    '## Proposed action\nrefund_order({"amount":20,"method":"card","order_id":"W123"})\n'
)
YES_NO = Question(name="policy_ok", type=QuestionType.YES_NO, text="This refund follows policy.")
CHOICE = Question(name="risk", type=QuestionType.CHOICE, options=("low", "medium", "high"))
SCORE = Question(
    name="matches_request",
    type=QuestionType.SCORE,
    text="This action matches what the customer asked for.",
)
QUESTIONS = (YES_NO, CHOICE, SCORE)
BY_TYPE = {q.type.value: q for q in QUESTIONS}

LLM_MODEL = "gpt-4.1-mini-2025-04-14"  # the model the llm_baseline fixtures were recorded with
LLM_PRICES = llm_baseline.PRICES[LLM_MODEL]
# The LLM baseline fixtures were recorded on a state with a long policy section (the τ² retail
# policy), so their prompts are long enough to be cached.
LLM_STATE = (FIXTURES / "llm_baseline_state.txt").read_text()
TOP = len(openai_decisions.SCORE_LEVELS) - 1


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _replay(*names: str) -> httpx.AsyncClient:
    """A client that answers each request with the fixture recorded for that exact request."""
    fixtures = [_fixture(n) for n in names]

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        for f in fixtures:
            if request.url.path.endswith(f["path"]) and sent == f["request"]:
                return httpx.Response(f["status"], json=f["response"])
        raise AssertionError(f"no recorded response for {request.url.path} {sent}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serve(name: str) -> httpx.AsyncClient:
    """A client that answers every request with one recorded response, whatever was asked."""
    f = _fixture(name)
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(f["status"], json=f["response"]))
    )


def _decisions(client: httpx.AsyncClient) -> openai_decisions.OpenAIDecisionsJudge:
    return openai_decisions.OpenAIDecisionsJudge(api_key="test-key-not-real", client=client)


def _jev(client: httpx.AsyncClient) -> jev.JevJudge:
    return jev.JevJudge(api_key="test-key-not-real", client=client)


def _llm(client: httpx.AsyncClient, model_id: str = LLM_MODEL) -> llm_baseline.LLMBaselineJudge:
    return llm_baseline.LLMBaselineJudge(
        model_id=model_id,
        usd_per_input_token=LLM_PRICES.input,
        usd_per_output_token=LLM_PRICES.output,
        usd_per_cached_input_token=LLM_PRICES.cached_input,
        api_key="test-key-not-real",
        client=client,
    )


def _run(judge: Any, questions: Sequence[Question], state: str = STATE) -> ScoreRecord:
    async def no_sleep(_: float) -> None:
        return None

    return asyncio.run(
        score_with_retry(
            judge,
            state,
            questions,
            state_hash="s" * 64,
            rubric_hash="r" * 64,
            policy=RetryPolicy(max_attempts=3),
            sleep=no_sleep,
            rng=random.Random(0),
        )
    )


# --- OpenAI Decisions ------------------------------------------------------------------------


def test_decisions_all_question_types_from_one_recorded_call() -> None:
    f = _fixture("decisions_all_types")
    record = _run(_decisions(_replay("decisions_all_types")), QUESTIONS)
    assert record.status == "ok"
    assert record.attempts == 1
    raw = {a["name"]: a for a in f["response"]["answers"]}
    answers = record.question_vector.answers  # type: ignore[union-attr]
    assert answers["policy_ok"] == YesNoAnswer(p_yes=raw["policy_ok"]["probability"])
    assert answers["risk"] == ChoiceAnswer(
        probs={p["value"]: p["probability"] for p in raw["risk"]["probabilities"]}
    )
    assert answers["matches_request"] == ScoreAnswer(value=raw["matches_request"]["score"] / TOP)
    # Decisions bills input tokens only; cached and output tokens are free.
    tokens = f["response"]["usage"]["input_tokens"]
    assert record.cost_usd == pytest.approx(tokens * 0.10 / 1_000_000)


@pytest.mark.parametrize("qtype", ["yes_no", "choice", "score"])
def test_decisions_each_question_type(qtype: str) -> None:
    q = BY_TYPE[qtype]
    record = _run(_decisions(_replay(f"decisions_{qtype}")), [q])
    assert record.status == "ok"
    assert record.question_vector.answers[q.name].type == qtype  # type: ignore[union-attr]
    assert record.cost_usd is not None and record.cost_usd > 0


def test_decisions_unauthorized_is_a_non_retried_error_row() -> None:
    record = _run(_decisions(_replay("decisions_error_unauthorized")), QUESTIONS)
    assert (record.status, record.attempts, record.question_vector) == ("error", 1, None)
    assert record.error == "HTTP 401 (invalid_request_error)"
    assert record.cost_usd is None


def test_decisions_response_missing_answers_is_malformed() -> None:
    record = _run(_decisions(_serve("decisions_yes_no")), QUESTIONS)
    assert (record.status, record.attempts) == ("error", 1)
    assert record.error == "malformed response: no answer for risk"
    # The call was still billed.
    tokens = _fixture("decisions_yes_no")["response"]["usage"]["input_tokens"]
    assert record.cost_usd == pytest.approx(tokens * 0.10 / 1_000_000)


def test_decisions_answer_of_the_wrong_type_is_malformed() -> None:
    as_yes_no = Question(name="risk", type=QuestionType.YES_NO, text="Low risk.")
    record = _run(_decisions(_serve("decisions_choice")), [as_yes_no])
    assert record.status == "error"
    assert record.error == "malformed response: risk: expected predicate, got 'choice'"


def test_decisions_choice_values_that_do_not_match_the_options_are_malformed() -> None:
    other = Question(name="risk", type=QuestionType.CHOICE, options=("low", "high"))
    record = _run(_decisions(_serve("decisions_choice")), [other])
    assert record.status == "error"
    assert record.error == "malformed response: risk: choice values do not match the options"


# --- TypeSafe Jev ----------------------------------------------------------------------------


def test_jev_all_question_types_from_one_recorded_call() -> None:
    f = _fixture("jev_all_types")
    record = _run(_jev(_replay("jev_all_types")), QUESTIONS)
    assert record.status == "ok"
    assert record.model_id == jev.DEFAULT_MODEL == f["response"]["model"]
    raw = f["response"]["answers"]
    answers = record.question_vector.answers  # type: ignore[union-attr]
    assert answers["policy_ok"] == YesNoAnswer(p_yes=raw["policy_ok"]["noul"])
    assert answers["risk"] == ChoiceAnswer(probs=raw["risk"]["probabilities"])
    assert answers["matches_request"] == ScoreAnswer(value=raw["matches_request"]["score"] / TOP)
    # Jev bills input tokens only; the response reports output tokens, which are free.
    usage = f["response"]["usage"]
    assert usage["output_tokens"] > 0
    assert record.cost_usd == pytest.approx(usage["input_tokens"] * 0.042 / 1_000_000)


def test_jev_request_maps_each_question_type() -> None:
    body = jev.build_request(jev.DEFAULT_MODEL, STATE, QUESTIONS)
    assert body["state"] == STATE
    noul, choice, score = (body["questions"][q.name] for q in QUESTIONS)
    assert noul["type"] == "noul" and "criteria" not in noul
    assert choice == {
        "type": "choice",
        "instructions": "Which risk best describes the proposed action?",
        "criteria": {"low": None, "medium": None, "high": None},
    }
    assert score["type"] == "score"
    assert len(score["criteria"]) == len(openai_decisions.SCORE_LEVELS)
    # The score levels the API echoes back as `legend` are the ones we sent, in order.
    legend = _fixture("jev_score")["response"]["answers"]["matches_request"]["legend"]
    assert [legend[str(i)] for i in range(len(legend))] == score["criteria"]


@pytest.mark.parametrize("qtype", ["yes_no", "choice", "score"])
def test_jev_each_question_type(qtype: str) -> None:
    q = BY_TYPE[qtype]
    record = _run(_jev(_replay(f"jev_{qtype}")), [q])
    assert record.status == "ok"
    assert record.question_vector.answers[q.name].type == qtype  # type: ignore[union-attr]
    assert record.cost_usd is not None and record.cost_usd > 0


@pytest.mark.parametrize(
    ("fixture", "model_id", "questions", "error"),
    [
        ("jev_error_unauthorized", jev.DEFAULT_MODEL, QUESTIONS, "HTTP 401 (authentication_error)"),
        ("jev_error_unknown_model", "no-such-model", QUESTIONS, "HTTP 400 (api_usage_error)"),
    ],
)
def test_jev_api_errors_are_non_retried_error_rows(
    fixture: str, model_id: str, questions: Sequence[Question], error: str
) -> None:
    judge = jev.JevJudge(model_id=model_id, api_key="test-key-not-real", client=_replay(fixture))
    record = _run(judge, questions)
    assert (record.status, record.attempts, record.error) == ("error", 1, error)
    assert record.cost_usd is None


def test_jev_validation_error_is_a_non_retried_error_row() -> None:
    record = _run(_jev(_serve("jev_error_validation")), [SCORE])
    assert (record.status, record.attempts, record.error) == ("error", 1, "HTTP 422 (too_short)")


def test_jev_response_missing_answers_is_malformed() -> None:
    record = _run(_jev(_serve("jev_yes_no")), QUESTIONS)
    assert (record.status, record.attempts) == ("error", 1)
    assert record.error == "malformed response: no answer for risk"
    tokens = _fixture("jev_yes_no")["response"]["usage"]["input_tokens"]
    assert record.cost_usd == pytest.approx(tokens * 0.042 / 1_000_000)


def test_jev_answer_of_the_wrong_type_is_malformed() -> None:
    as_score = Question(name="policy_ok", type=QuestionType.SCORE, text="Follows policy.")
    record = _run(_jev(_serve("jev_yes_no")), [as_score])
    assert record.status == "error"
    assert record.error == "malformed response: policy_ok: expected score, got 'noul'"


def test_jev_choice_probabilities_that_do_not_match_the_options_are_malformed() -> None:
    other = Question(name="risk", type=QuestionType.CHOICE, options=("low", "high"))
    record = _run(_jev(_serve("jev_choice")), [other])
    assert record.status == "error"
    assert record.error == "malformed response: risk: choice probabilities do not match the options"


# --- LLM baseline ----------------------------------------------------------------------------


def test_llm_baseline_all_question_types_from_recorded_calls() -> None:
    client = _replay("llm_baseline_yes_no", "llm_baseline_choice", "llm_baseline_score")
    record = _run(_llm(client), QUESTIONS, LLM_STATE)
    assert record.status == "ok"
    answers = record.question_vector.answers  # type: ignore[union-attr]
    for q in QUESTIONS:
        f = _fixture(f"llm_baseline_{q.type.value}")
        assert answers[q.name] == llm_baseline.parse_answer(q, f["response"])
    # The recorded top tokens favour yes, low risk and a full match.
    assert answers["policy_ok"].p_yes > 0.9  # type: ignore[union-attr]
    risk = answers["risk"].probs  # type: ignore[union-attr]
    assert max(risk, key=risk.__getitem__) == "low"
    assert answers["matches_request"].value > 0.9  # type: ignore[union-attr]
    # One call per question, each billed for its prompt and one completion token.
    expected = 0.0
    for q in QUESTIONS:
        usage = _fixture(f"llm_baseline_{q.type.value}")["response"]["usage"]
        assert usage["completion_tokens"] == 1
        cached = usage["prompt_tokens_details"]["cached_tokens"]
        expected += (
            (usage["prompt_tokens"] - cached) * LLM_PRICES.input
            + cached * LLM_PRICES.cached_input
            + LLM_PRICES.output
        )
    assert record.cost_usd == pytest.approx(expected)


def test_llm_baseline_repeat_call_is_served_from_the_prompt_cache_at_the_cached_rate() -> None:
    first = _fixture("llm_baseline_yes_no")
    repeat = _fixture("llm_baseline_yes_no_repeat")
    assert repeat["request"] == first["request"]
    usage = repeat["response"]["usage"]
    cached = usage["prompt_tokens_details"]["cached_tokens"]
    assert cached > 1024 and cached < usage["prompt_tokens"]
    record = _run(_llm(_serve("llm_baseline_yes_no_repeat")), [YES_NO], LLM_STATE)
    assert record.status == "ok"
    assert record.cost_usd == pytest.approx(
        (usage["prompt_tokens"] - cached) * LLM_PRICES.input
        + cached * LLM_PRICES.cached_input
        + usage["completion_tokens"] * LLM_PRICES.output
    )
    first_usage = first["response"]["usage"]
    full_price = first_usage["prompt_tokens"] * LLM_PRICES.input + LLM_PRICES.output
    assert record.cost_usd < full_price / 2


def test_llm_baseline_prompt_puts_the_shared_policy_first_and_the_question_last() -> None:
    body = _fixture("llm_baseline_yes_no")["request"]
    assert body == llm_baseline.build_request(LLM_MODEL, LLM_STATE, YES_NO)
    prompt = body["messages"][1]["content"]
    policy_at = prompt.index("## Context: policy\n")
    conversation_at = prompt.index("## Context: conversation\n")
    question_at = prompt.index("## Question\n")
    assert policy_at == 0 < conversation_at < prompt.index("## Proposed action") < question_at
    # Every write's prompt starts with the same bytes up to its conversation.
    other_state = LLM_STATE.replace("water bottle", "desk lamp")
    other = llm_baseline.build_request(LLM_MODEL, other_state, CHOICE)["messages"][1]["content"]
    assert other[:conversation_at] == prompt[:conversation_at]
    assert llm_baseline.prompt_cache_key(other_state) == body["prompt_cache_key"]


def test_llm_baseline_yes_no_merges_case_variants_of_the_answer_token() -> None:
    body = _fixture("llm_baseline_yes_no")["response"]
    top = body["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    p_yes = sum(math.exp(t["logprob"]) for t in top if t["token"].strip().lower() == "yes")
    p_no = sum(math.exp(t["logprob"]) for t in top if t["token"].strip().lower() == "no")
    answer = llm_baseline.parse_answer(YES_NO, body)
    assert answer == YesNoAnswer(p_yes=p_yes / (p_yes + p_no))


def test_llm_baseline_model_without_logprobs_is_a_non_retried_error_row() -> None:
    client = _replay("llm_baseline_error_no_logprobs")
    record = _run(_llm(client, "gpt-5-mini"), [YES_NO], LLM_STATE)
    assert (record.status, record.attempts) == ("error", 1)
    assert record.error == "HTTP 403 (invalid_request_error)"


def test_llm_baseline_response_without_a_valid_answer_token_is_malformed() -> None:
    # The choice question's recorded reply is a digit: no yes/no mass for a yes_no question.
    record = _run(_llm(_serve("llm_baseline_choice")), [YES_NO])
    assert (record.status, record.attempts) == ("error", 1)
    assert record.error == "malformed response: policy_ok: no valid answer token"
    usage = _fixture("llm_baseline_choice")["response"]["usage"]
    assert usage["prompt_tokens_details"]["cached_tokens"] == 0
    assert record.cost_usd == pytest.approx(
        usage["prompt_tokens"] * LLM_PRICES.input + usage["completion_tokens"] * LLM_PRICES.output
    )


def test_llm_baseline_one_failed_question_fails_the_whole_call() -> None:
    # Every question gets the choice reply: a digit, unusable for the yes_no question only.
    record = _run(_llm(_serve("llm_baseline_choice")), QUESTIONS)
    assert record.status == "error"
    assert record.question_vector is None
    assert record.error == "malformed response: policy_ok: no valid answer token"
    bodies = json.loads(record.raw_response or "")
    assert set(bodies) == {q.name for q in QUESTIONS} and all(bodies.values())


def test_every_fixture_is_a_real_recording_without_secrets() -> None:
    for path in FIXTURES.glob("*.json"):
        f = json.loads(path.read_text())
        assert set(f) == {"path", "request", "response", "status"}, path.name
        text = path.read_text().lower()
        assert "authorization" not in text and "bearer" not in text, path.name
        if f["status"] != 200:
            # Error bodies keep the type and code only; messages can echo the key.
            response = json.dumps(f["response"]).lower()
            assert "message" not in response and "msg" not in response, path.name
