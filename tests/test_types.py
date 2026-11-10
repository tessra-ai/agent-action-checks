import asyncio
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from hatchway import Decision, Result
from hatchway.judges import (
    ChoiceAnswer,
    Judge,
    Question,
    QuestionType,
    QuestionVector,
    ScoreAnswer,
    YesNoAnswer,
)

QUESTIONS = [
    Question(name="policy_ok", type=QuestionType.YES_NO, text="Follows the refund policy."),
    Question(name="risk", type=QuestionType.CHOICE, options=("low", "medium", "high")),
    Question(name="confidence", type=QuestionType.SCORE, text="How sure is the agent?"),
]

VECTOR = QuestionVector(
    judge="jev",
    model_id="jev-1",
    answers={
        "policy_ok": YesNoAnswer(p_yes=0.92),
        "risk": ChoiceAnswer(probs={"low": 0.7, "medium": 0.2, "high": 0.1}),
        "confidence": ScoreAnswer(value=0.4),
    },
)


def test_every_question_type_round_trips_through_json() -> None:
    restored = QuestionVector.model_validate_json(VECTOR.model_dump_json())

    assert restored == VECTOR
    assert isinstance(restored.answers["policy_ok"], YesNoAnswer)
    assert isinstance(restored.answers["risk"], ChoiceAnswer)
    assert isinstance(restored.answers["confidence"], ScoreAnswer)
    restored.check_against(QUESTIONS)


def test_questions_round_trip_through_json() -> None:
    for question in QUESTIONS:
        assert Question.model_validate_json(question.model_dump_json()) == question


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "yes_no", "p_yes": 1.2},
        {"type": "yes_no", "p_yes": float("nan")},
        {"type": "score", "value": -0.1},
        {"type": "choice", "probs": {"low": 0.5, "high": 0.1}},
        {"type": "maybe", "p_yes": 0.5},
    ],
)
def test_malformed_answers_are_rejected(answer: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        QuestionVector.model_validate({"judge": "jev", "model_id": "m", "answers": {"q": answer}})


def test_choice_probabilities_tolerate_rounding() -> None:
    ChoiceAnswer(probs={"low": 0.3333, "medium": 0.3333, "high": 0.3333})


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({"policy_ok": YesNoAnswer(p_yes=0.5)}, "missing answers: confidence, risk"),
        (
            {**VECTOR.answers, "extra": YesNoAnswer(p_yes=0.5)},
            "unexpected answers: extra",
        ),
        (
            {**VECTOR.answers, "policy_ok": ScoreAnswer(value=0.5)},
            "policy_ok: expected yes_no, got score",
        ),
        (
            {**VECTOR.answers, "risk": ChoiceAnswer(probs={"low": 0.5, "high": 0.5})},
            "risk: choice keys do not match options",
        ),
    ],
)
def test_check_against_reports_mismatches(answers: dict[str, object], message: str) -> None:
    vector = QuestionVector(judge="jev", model_id="m", answers=answers)
    with pytest.raises(ValueError, match=message):
        vector.check_against(QUESTIONS)


class FakeJudge:
    name = "fake"
    model_id = "fake-1"

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
        return QuestionVector(
            judge=self.name,
            model_id=self.model_id,
            answers={q.name: YesNoAnswer(p_yes=0.5) for q in questions},
        )


def test_a_simple_class_satisfies_the_judge_protocol() -> None:
    judge = FakeJudge()
    assert isinstance(judge, Judge)
    yes_no = [q for q in QUESTIONS if q.type is QuestionType.YES_NO]
    vector = asyncio.run(judge.score("state", yes_no))
    vector.check_against(yes_no)


def test_decision_round_trips_and_is_bounded() -> None:
    decision = Decision(result=Result.ASK, reason="policy_ok below threshold", p_ok=0.4)
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    assert decision.result == "ASK"
    with pytest.raises(ValidationError):
        Decision(result=Result.ALLOW, reason="", p_ok=1.5)
    with pytest.raises(ValidationError):
        Decision(result="MAYBE", reason="")
