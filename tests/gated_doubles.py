"""Test helpers for the gated pass: fake judges, and real frozen arms built in code."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from hatchway.bench.frozen import FrozenArm
from hatchway.judges.base import (
    Answer,
    ChoiceAnswer,
    Question,
    QuestionType,
    QuestionVector,
    ScoreAnswer,
    YesNoAnswer,
)
from hatchway.judges.runner import JudgeResult
from hatchway.policy import Policy


def frozen_arm(
    policy: Policy, judges: Sequence, *, threshold: float | None = 0.5, arm: str = "E"
) -> FrozenArm:
    """A real `FrozenArm` with a `scalar_mean` model on the first judge's yes/no answers.

    It requires every given judge. `threshold=0.0` allows every write that every judge scored;
    `threshold=1.1` asks on every write."""
    return FrozenArm(
        arm=arm,
        judges=tuple((j.name, j.model_id) for j in judges),
        rubric_hashes={name: a.rubric_hash for name, a in policy.actions.items() if a.questions},
        model={"type": "scalar_mean", "judge": judges[0].name},
        global_threshold=threshold,
    )


class FakeJudge:
    """Answers every yes/no question with `p_yes` and reports `cost_usd` per call.

    `p_yes_by_action` overrides `p_yes` for states whose proposed call is that action.
    `delay_s` sleeps before answering; `error` is raised instead of answering."""

    def __init__(
        self,
        name: str = "fake",
        model_id: str = "fake-1",
        *,
        p_yes: float = 0.9,
        p_yes_by_action: Mapping[str, float] | None = None,
        cost_usd: float | None = 0.001,
        delay_s: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.name, self.model_id = name, model_id
        self.p_yes, self.p_yes_by_action = p_yes, dict(p_yes_by_action or {})
        self.cost_usd, self.delay_s, self.error = cost_usd, delay_s, error
        self.calls = 0

    async def score_with_cost(self, state_text: str, questions: Sequence[Question]) -> JudgeResult:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        proposed = state_text.rsplit("## Proposed action\n", 1)[-1]
        p_yes = next(
            (p for a, p in self.p_yes_by_action.items() if proposed.startswith(f"{a}(")),
            self.p_yes,
        )
        answers: dict[str, Answer] = {}
        for q in questions:
            if q.type is QuestionType.YES_NO:
                answers[q.name] = YesNoAnswer(p_yes=p_yes)
            elif q.type is QuestionType.SCORE:
                answers[q.name] = ScoreAnswer(value=p_yes)
            else:
                options = q.options or ()
                answers[q.name] = ChoiceAnswer(probs={o: 1 / len(options) for o in options})
        vector = QuestionVector(judge=self.name, model_id=self.model_id, answers=answers)
        return JudgeResult(vector, cost_usd=self.cost_usd)

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
        return (await self.score_with_cost(state_text, questions)).vector
