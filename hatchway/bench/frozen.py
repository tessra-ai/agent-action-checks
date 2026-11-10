"""Frozen replay arms: the fitted policy each arm B-F hands to the live gated pass (M7).

A `FrozenArm` is plain JSON: the judges it needs, the rubric hashes it was fit on, its model
parameters and its thresholds. Nothing is pickled, and evaluating an arm needs only the standard
library, so the live gate does not import scikit-learn.

Model types (the `model` object in the file):

- `scalar_mean` (arms B, C, D): `p_ok` is the mean of the judge's `yes_no` `p_yes` and `score`
  values, restricted to the core questions when the rubric has them; see `scalar_score`.
- `calibrated` (arm E): one judge's question vector through a fitted `Calibrator`, per action
  when the action had enough labels, else the global (`"*"`) one.
- `two_judge` (arm F): a `calibrated` model per judge, then a logistic combiner over both
  calibrated probabilities and their disagreement `|p_a - p_b|`. Writes whose disagreement
  exceeds `disagreement_max` go to `ASK` whatever their `p_ok`.

A calibrator maps a feature dict (see `vector_features`) to a probability: each feature is
optionally passed through a piecewise-linear isotonic map, transformed (`logit` or `identity`),
standardized, and combined by logistic regression. `kind='constant'` returns a fixed `p`.

Thresholds: `ALLOW` if `p_ok >= threshold(action)`. An action without its own threshold uses the
global one. A threshold that could not be fit (no incorrect training writes) is stored as `null`
and loads as +inf, so the arm fails closed and asks for everything.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from hatchway.judges.base import ChoiceAnswer, QuestionVector, ScoreAnswer, YesNoAnswer

FORMAT = "hatchway.frozen_arm"
FORMAT_VERSION = 1
LOGIT_EPS = 1e-3
# The out-of-the-box questions a do-it-yourself team would ask; arms B-D average only these.
CORE_QUESTIONS = frozenset({"policy_ok", "matches_request"})


def vector_features(vector: QuestionVector) -> dict[str, float]:
    """One feature per yes_no / score question (its `p_yes` or value) and per choice option
    (`"question=option"`)."""
    features: dict[str, float] = {}
    for name, answer in vector.answers.items():
        if isinstance(answer, YesNoAnswer):
            features[name] = answer.p_yes
        elif isinstance(answer, ScoreAnswer):
            features[name] = answer.value
        else:
            assert isinstance(answer, ChoiceAnswer)
            for option, p in answer.probs.items():
                features[f"{name}={option}"] = p
    return features


def scalar_score(vector: QuestionVector) -> float:
    """The fixed scalar of arms B-D: the mean of the `yes_no` `p_yes` and `score` values.

    When the rubric has the core questions (`CORE_QUESTIONS`), only those are averaged: the
    per-rule questions are the multivariate signal arms E and F are tested on, and folding them
    into the fixed scalar would hand part of it to the baselines. Choice answers (τ²'s `risk`)
    are left out: they rate the cost of a mistake, not whether the action is correct, and have
    no direction without a fitted model.
    """
    answers = vector.answers
    if any(name in answers for name in CORE_QUESTIONS):
        answers = {name: a for name, a in answers.items() if name in CORE_QUESTIONS}
    values = [
        a.p_yes if isinstance(a, YesNoAnswer) else a.value
        for a in answers.values()
        if isinstance(a, YesNoAnswer | ScoreAnswer)
    ]
    if not values:
        raise ValueError(f"{vector.judge}: no yes_no or score answers to average")
    return math.fsum(values) / len(values)


def logit(p: float) -> float:
    p = min(max(p, LOGIT_EPS), 1.0 - LOGIT_EPS)
    return math.log(p / (1.0 - p))


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Piecewise-linear interpolation, clipped at both ends (as numpy.interp)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def calibrator_predict(cal: Mapping[str, Any], features: Mapping[str, float]) -> float:
    if cal["kind"] == "constant":
        return float(cal["p"])
    z = float(cal["intercept"])
    isotonic = cal.get("isotonic")
    for i, name in enumerate(cal["features"]):
        x = features.get(name, cal["fill"][i])
        if isotonic is not None:
            x = interp(x, isotonic[i]["x"], isotonic[i]["y"])
        if cal["transforms"][i] == "logit":
            x = logit(x)
        z += cal["coef"][i] * (x - cal["mean"][i]) / cal["scale"][i]
    return sigmoid(z)


def calibrated_predict(model: Mapping[str, Any], action: str, vector: QuestionVector) -> float:
    cal = model["models"].get(action, model["models"]["*"])
    return calibrator_predict(cal, vector_features(vector))


def two_judge_parts(
    model: Mapping[str, Any], action: str, vectors: Mapping[str, QuestionVector]
) -> tuple[float, float]:
    """(p_ok, disagreement) for a `two_judge` model."""
    a, b = model["judge_order"]
    p_a = calibrated_predict(model["judges"][a], action, vectors[a])
    p_b = calibrated_predict(model["judges"][b], action, vectors[b])
    dis = abs(p_a - p_b)
    p = calibrator_predict(model["combiner"], {f"p:{a}": p_a, f"p:{b}": p_b, "disagreement": dis})
    return p, dis


@dataclass
class FrozenArm:
    arm: str
    judges: tuple[tuple[str, str], ...]
    rubric_hashes: dict[str, str]
    model: dict[str, Any]
    global_threshold: float | None
    action_thresholds: dict[str, float | None] = field(default_factory=dict)
    catch_target: float = 0.95
    info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> FrozenArm:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FrozenArm:
        if data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"not a {FORMAT} v{FORMAT_VERSION} file")
        thresholds = data["thresholds"]
        return cls(
            arm=data["arm"],
            judges=tuple((j, m) for j, m in data["judges"]),
            rubric_hashes=dict(data["rubric_hashes"]),
            model=dict(data["model"]),
            global_threshold=thresholds["global"],
            action_thresholds=dict(thresholds["per_action"]),
            catch_target=data["catch_target"],
            info=dict(data.get("info", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "arm": self.arm,
            "judges": [list(j) for j in self.judges],
            "rubric_hashes": dict(sorted(self.rubric_hashes.items())),
            "catch_target": self.catch_target,
            "thresholds": {
                "global": self.global_threshold,
                "per_action": dict(sorted(self.action_thresholds.items())),
            },
            "model": self.model,
            "info": self.info,
        }

    def p_ok(self, action: str, vectors: Mapping[str, QuestionVector]) -> float:
        """Calibrated P(write is correct). Raises KeyError if a required judge is missing."""
        kind = self.model["type"]
        if kind == "scalar_mean":
            return scalar_score(vectors[self.model["judge"]])
        if kind == "calibrated":
            return calibrated_predict(self.model, action, vectors[self.model["judge"]])
        if kind == "two_judge":
            return two_judge_parts(self.model, action, vectors)[0]
        raise ValueError(f"unknown model type {kind!r}")

    def threshold(self, action: str) -> float:
        t = self.action_thresholds.get(action, self.global_threshold)
        return math.inf if t is None else t

    def has_judges(self, vectors: Mapping[str, QuestionVector]) -> bool:
        """True if every required judge answered, with the model id the arm was fit on."""
        return all(
            name in vectors and vectors[name].model_id == model_id for name, model_id in self.judges
        )

    def decide(self, action: str, vectors: Mapping[str, QuestionVector]) -> Literal["ALLOW", "ASK"]:
        if not self.has_judges(vectors):
            return "ASK"
        if self.model["type"] == "two_judge":
            p, dis = two_judge_parts(self.model, action, vectors)
            limit = self.model.get("disagreement_max")
            if limit is not None and dis > limit:
                return "ASK"
        else:
            p = self.p_ok(action, vectors)
        return "ALLOW" if p >= self.threshold(action) else "ASK"
