"""Judge protocol and the typed rubric questions and answers judges exchange."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]

# Choice probabilities from decision APIs are rounded; accept small drift from 1.0.
CHOICE_SUM_TOLERANCE = 1e-3


class QuestionType(StrEnum):
    YES_NO = "yes_no"
    CHOICE = "choice"
    SCORE = "score"


class Question(BaseModel):
    """One typed rubric question asked about a proposed action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    type: QuestionType
    text: str | None = None
    options: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Question:
        if self.type is QuestionType.CHOICE:
            if not self.options or len(self.options) < 2:
                raise ValueError("choice questions need at least two options")
            if len(set(self.options)) != len(self.options):
                raise ValueError("choice options must be unique")
        else:
            if self.options is not None:
                raise ValueError(f"{self.type.value} questions do not take options")
            if not self.text:
                raise ValueError(f"{self.type.value} questions need text")
        return self


class YesNoAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["yes_no"] = "yes_no"
    p_yes: Probability


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["choice"] = "choice"
    probs: dict[str, Probability]

    @model_validator(mode="after")
    def _check_sum(self) -> ChoiceAnswer:
        total = math.fsum(self.probs.values())
        if abs(total - 1.0) > CHOICE_SUM_TOLERANCE:
            raise ValueError(f"choice probabilities sum to {total:.4f}, not 1")
        return self


class ScoreAnswer(BaseModel):
    """A score normalized to [0, 1] by the judge adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["score"] = "score"
    value: Probability


Answer = Annotated[YesNoAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


class QuestionVector(BaseModel):
    """One judge's answers to every rubric question for one proposed action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    judge: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    answers: dict[str, Answer]

    def check_against(self, questions: Sequence[Question]) -> None:
        """Raise ValueError unless the answers match the questions one to one."""
        problems: list[str] = []
        expected: Mapping[str, Question] = {q.name: q for q in questions}
        missing = sorted(expected.keys() - self.answers.keys())
        extra = sorted(self.answers.keys() - expected.keys())
        if missing:
            problems.append(f"missing answers: {', '.join(missing)}")
        if extra:
            problems.append(f"unexpected answers: {', '.join(extra)}")
        for name in sorted(expected.keys() & self.answers.keys()):
            question, answer = expected[name], self.answers[name]
            if answer.type != question.type.value:
                problems.append(f"{name}: expected {question.type.value}, got {answer.type}")
            elif isinstance(answer, ChoiceAnswer) and set(answer.probs) != set(
                question.options or ()
            ):
                problems.append(f"{name}: choice keys do not match options")
        if problems:
            raise ValueError("; ".join(problems))


@runtime_checkable
class Judge(Protocol):
    """Scores a proposed action against typed rubric questions.

    Adapters call one external model per `score` call and return its raw per-question answers.
    Timeouts, retries and error handling belong to the caller.
    """

    name: str
    model_id: str

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector: ...
