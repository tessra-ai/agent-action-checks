"""OpenAI Decisions API judge (`POST /v1/decisions`, public beta).

Shapes follow https://developers.openai.com/api/docs/guides/decisions (checked 2026-10-20):
`yes_no` maps to a `predicate` question, `choice` to `choice` and `score` to `score`. A score
question needs ordered levels, which `Question` does not carry, so every score question uses
`SCORE_LEVELS`; the returned score (a probability-weighted level index) is divided by the top
index to land in [0, 1]. A `refusal` answer or any response that does not fit these shapes is
a non-retryable `JudgeError`, which the runner stores as `status='error'`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from hatchway.judges._http import (
    OPENAI_BASE_URL,
    api_key_from_env,
    dump_body,
    finite_number,
    malformed,
    post_json,
    short_error,
)
from hatchway.judges.base import (
    Answer,
    ChoiceAnswer,
    Question,
    QuestionType,
    QuestionVector,
    ScoreAnswer,
    YesNoAnswer,
)
from hatchway.judges.runner import JudgeError, JudgeResult

DEFAULT_MODEL = "gpt-6-luna"

# gpt-6-luna on /v1/decisions bills input tokens only.
USD_PER_INPUT_TOKEN = {"gpt-6-luna": 0.10 / 1_000_000}

# Ordered lowest to highest: how strongly the action meets the question's statement.
SCORE_LEVELS: tuple[tuple[str, str], ...] = (
    ("Not at all", "The statement is clearly false for this action."),
    ("Slightly", "The statement is mostly false for this action."),
    ("Partly", "The statement is about as true as it is false for this action."),
    ("Mostly", "The statement is mostly true for this action."),
    ("Fully", "The statement is clearly true for this action."),
)

_API_TYPE = {
    QuestionType.YES_NO: "predicate",
    QuestionType.CHOICE: "choice",
    QuestionType.SCORE: "score",
}


def build_request(model: str, state_text: str, questions: Sequence[Question]) -> dict[str, Any]:
    """Render the `/v1/decisions` request body for one proposed action."""
    return {
        "model": model,
        "input": state_text,
        "questions": [_question(q) for q in questions],
    }


def _question(q: Question) -> dict[str, Any]:
    body: dict[str, Any] = {"type": _API_TYPE[q.type], "name": q.name}
    if q.type is QuestionType.YES_NO:
        body["instructions"] = f"Is this statement true of the proposed action? {q.text}"
    elif q.type is QuestionType.CHOICE:
        body["instructions"] = q.text or f"Which {q.name} best describes the proposed action?"
        body["choices"] = [{"value": option} for option in q.options or ()]
    else:
        body["instructions"] = f"How true is this statement of the proposed action? {q.text}"
        body["levels"] = [{"label": label, "description": d} for label, d in SCORE_LEVELS]
    return body


def parse_response(
    body: dict[str, Any], questions: Sequence[Question], *, judge: str, model_id: str
) -> QuestionVector:
    """Turn a `/v1/decisions` response into a QuestionVector, or raise JudgeError."""
    raw = body.get("answers")
    if not isinstance(raw, list):
        raise malformed("no answers array")
    by_name: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise malformed("answer without a name")
        if item["name"] in by_name:
            raise malformed(f"duplicate answer for {item['name']}")
        by_name[item["name"]] = item
    answers: dict[str, Answer] = {}
    for q in questions:
        item = by_name.pop(q.name, None)
        if item is None:
            raise malformed(f"no answer for {q.name}")
        if item.get("type") == "refusal":
            raise JudgeError(f"refusal for {q.name}", retryable=False)
        if item.get("type") != _API_TYPE[q.type]:
            raise malformed(f"{q.name}: expected {_API_TYPE[q.type]}, got {item.get('type')!r}")
        try:
            answers[q.name] = _answer(q, item)
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            raise malformed(f"{q.name}: {short_error(exc)}") from None
    if by_name:
        raise malformed(f"unexpected answers: {', '.join(sorted(by_name))}")
    return QuestionVector(judge=judge, model_id=model_id, answers=answers)


def _answer(q: Question, item: dict[str, Any]) -> Answer:
    if q.type is QuestionType.YES_NO:
        return YesNoAnswer(p_yes=finite_number(item["probability"]))
    if q.type is QuestionType.CHOICE:
        probs: dict[str, float] = {}
        for entry in item["probabilities"]:
            value = entry["value"]
            if not isinstance(value, str) or value in probs:
                raise ValueError(f"bad or duplicate choice value {value!r}")
            probs[value] = finite_number(entry["probability"])
        if set(probs) != set(q.options or ()):
            raise ValueError("choice values do not match the options")
        return ChoiceAnswer(probs=probs)
    top = len(SCORE_LEVELS) - 1
    score = finite_number(item["score"])
    if not 0 <= score <= top:
        raise ValueError(f"score {score} outside 0..{top}")
    return ScoreAnswer(value=score / top)


def cost_usd(body: dict[str, Any], model: str) -> float | None:
    """Cost from `usage.input_tokens`, or None when usage or the model's price is unknown."""
    usage = body.get("usage")
    rate = USD_PER_INPUT_TOKEN.get(model)
    if not isinstance(usage, dict) or rate is None:
        return None
    tokens = usage.get("input_tokens")
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        return None
    return tokens * rate


class OpenAIDecisionsJudge:
    name = "openai_decisions"

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = OPENAI_BASE_URL,
    ) -> None:
        self.model_id = model_id
        self._api_key = api_key or api_key_from_env("OPENAI_API_KEY")
        self._client = client or httpx.AsyncClient(timeout=None)
        self._url = f"{base_url.rstrip('/')}/decisions"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
        return (await self.score_with_cost(state_text, questions)).vector

    async def score_with_cost(self, state_text: str, questions: Sequence[Question]) -> JudgeResult:
        body = await post_json(
            self._client,
            self._url,
            self._api_key,
            build_request(self.model_id, state_text, questions),
        )
        cost, raw = cost_usd(body, self.model_id), dump_body(body)
        try:
            vector = parse_response(body, questions, judge=self.name, model_id=self.model_id)
        except JudgeError as exc:
            exc.cost_usd, exc.raw_response = cost, raw
            raise
        return JudgeResult(vector, cost, raw)
