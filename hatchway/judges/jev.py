"""TypeSafe Jev judge (System One API, `POST /v1/systemone`).

Shapes follow https://docs.typesafe.ai/api/system-one (checked 2026-10-20): `yes_no` maps to a
`noul` question, `choice` to `choice` and `score` to `score`. Questions are a map keyed by name
and answers come back under the same names. Choice options are sent with `null` descriptions
(interpreted by name alone). Score questions use the Decisions judge's `SCORE_LEVELS` as the
ordered `criteria`; the returned score (the probability-weighted level index) is divided by the
top index to land in [0, 1]. Any response that does not fit these shapes is a non-retryable
`JudgeError`, which the runner stores as `status='error'`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from hatchway.judges._http import (
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
from hatchway.judges.openai_decisions import SCORE_LEVELS
from hatchway.judges.runner import JudgeError, JudgeResult

TYPESAFE_BASE_URL = "https://api.typesafe.ai/v1"

# Pinned rather than `jev-latest`, so benchmark rows keyed by model id do not drift.
DEFAULT_MODEL = "jev-1.14.0"

# Jev bills input tokens only ($0.042 per million); output tokens are free.
USD_PER_INPUT_TOKEN = {"jev-1.14.0": 0.042 / 1_000_000, "jev-1.13.0": 0.042 / 1_000_000}

_API_TYPE = {
    QuestionType.YES_NO: "noul",
    QuestionType.CHOICE: "choice",
    QuestionType.SCORE: "score",
}


def build_request(model: str, state_text: str, questions: Sequence[Question]) -> dict[str, Any]:
    """Render the `/v1/systemone` request body for one proposed action."""
    return {
        "model": model,
        "state": state_text,
        "questions": {q.name: _question(q) for q in questions},
    }


def _question(q: Question) -> dict[str, Any]:
    body: dict[str, Any] = {"type": _API_TYPE[q.type]}
    if q.type is QuestionType.YES_NO:
        body["instructions"] = f"Is this statement true of the proposed action? {q.text}"
    elif q.type is QuestionType.CHOICE:
        body["instructions"] = q.text or f"Which {q.name} best describes the proposed action?"
        body["criteria"] = {option: None for option in q.options or ()}
    else:
        body["instructions"] = f"How true is this statement of the proposed action? {q.text}"
        body["criteria"] = [f"{label}: {d}" for label, d in SCORE_LEVELS]
    return body


def parse_response(
    body: dict[str, Any], questions: Sequence[Question], *, judge: str, model_id: str
) -> QuestionVector:
    """Turn a `/v1/systemone` response into a QuestionVector, or raise JudgeError."""
    raw = body.get("answers")
    if not isinstance(raw, dict):
        raise malformed("no answers object")
    remaining = dict(raw)
    answers: dict[str, Answer] = {}
    for q in questions:
        item = remaining.pop(q.name, None)
        if not isinstance(item, dict):
            raise malformed(f"no answer for {q.name}")
        if item.get("type") != _API_TYPE[q.type]:
            raise malformed(f"{q.name}: expected {_API_TYPE[q.type]}, got {item.get('type')!r}")
        try:
            answers[q.name] = _answer(q, item)
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            raise malformed(f"{q.name}: {short_error(exc)}") from None
    if remaining:
        raise malformed(f"unexpected answers: {', '.join(sorted(remaining))}")
    return QuestionVector(judge=judge, model_id=model_id, answers=answers)


def _answer(q: Question, item: dict[str, Any]) -> Answer:
    if q.type is QuestionType.YES_NO:
        return YesNoAnswer(p_yes=finite_number(item["noul"]))
    if q.type is QuestionType.CHOICE:
        raw = item["probabilities"]
        if not isinstance(raw, dict) or set(raw) != set(q.options or ()):
            raise ValueError("choice probabilities do not match the options")
        return ChoiceAnswer(probs={option: finite_number(p) for option, p in raw.items()})
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


class JevJudge:
    name = "jev"

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = TYPESAFE_BASE_URL,
    ) -> None:
        self.model_id = model_id
        self._api_key = api_key or api_key_from_env("TYPESAFE_API_KEY")
        self._client = client or httpx.AsyncClient(timeout=None)
        self._url = f"{base_url.rstrip('/')}/systemone"

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
