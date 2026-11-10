"""Oracle judge: answers from policy verdicts. For tests and benchmark upper bounds only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from hatchway.bench.store import PolicyDecision
from hatchway.judges.base import (
    Answer,
    ChoiceAnswer,
    Question,
    QuestionType,
    QuestionVector,
    ScoreAnswer,
    YesNoAnswer,
)
from hatchway.judges.runner import JudgeError
from hatchway.state import state_hash

_P_OK: Mapping[PolicyDecision, float] = {"ALLOW": 1.0, "ASK": 0.0, "DENY": 0.0, "UNKNOWN": 0.5}


class OracleJudge:
    """Looks up each state's policy verdict by `state_hash`.

    Yes/no and score questions get 1.0 for `ALLOW`, 0.0 for `ASK` or `DENY` and 0.5 for
    `UNKNOWN`: the oracle treats every rubric statement as "this write may execute". Choice
    questions carry no direction, so they get a uniform distribution.
    """

    def __init__(
        self,
        labels: Mapping[str, PolicyDecision],
        *,
        name: str = "oracle",
        model_id: str = "verdicts",
    ) -> None:
        self.name = name
        self.model_id = model_id
        self._labels = dict(labels)

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
        label = self._labels.get(state_hash(state_text))
        if label is None:
            raise JudgeError("no policy verdict for this state", retryable=False)
        p_ok = _P_OK[label]
        answers: dict[str, Answer] = {}
        for q in questions:
            if q.type is QuestionType.YES_NO:
                answers[q.name] = YesNoAnswer(p_yes=p_ok)
            elif q.type is QuestionType.SCORE:
                answers[q.name] = ScoreAnswer(value=p_ok)
            else:
                options = q.options or ()
                answers[q.name] = ChoiceAnswer(probs={o: 1 / len(options) for o in options})
        return QuestionVector(judge=self.name, model_id=self.model_id, answers=answers)
