"""FrozenArm: the JSON contract the live gated pass (M7) loads."""

import json
import math

import pytest

from hatchway.bench.frozen import FrozenArm, calibrator_predict, interp, scalar_score
from hatchway.judges import ChoiceAnswer, QuestionVector, YesNoAnswer

CANCEL = "cancel_pending_order"
RETURN = "return_delivered_order_items"


def vector(
    judge: str, policy: float, match: float, high: float = 0.2, model: str = "m"
) -> QuestionVector:
    return QuestionVector(
        judge=judge,
        model_id=model,
        answers={
            "policy_ok": YesNoAnswer(p_yes=policy),
            "matches_request": YesNoAnswer(p_yes=match),
            "risk": ChoiceAnswer(probs={"low": 0.8 - high, "medium": 0.2, "high": high}),
        },
    )


def scalar_arm(**kw) -> FrozenArm:
    return FrozenArm(
        arm="C",
        judges=(("jev", "m"),),
        rubric_hashes={CANCEL: "r1"},
        model={"type": "scalar_mean", "judge": "jev"},
        global_threshold=kw.get("global_threshold", 0.6),
        action_thresholds=kw.get("action_thresholds", {CANCEL: 0.8}),
    )


def logistic(features: list[str], coef: list[float], intercept: float = 0.0) -> dict:
    n = len(features)
    return {
        "kind": "logistic",
        "features": features,
        "fill": [0.5] * n,
        "transforms": ["identity"] * n,
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "coef": coef,
        "intercept": intercept,
    }


def two_judge_arm(disagreement_max: float | None) -> FrozenArm:
    def judge_model(name: str) -> dict:
        return {
            "type": "calibrated",
            "judge": name,
            "models": {"*": logistic(["policy_ok"], [8.0], -4.0)},
        }

    return FrozenArm(
        arm="F",
        judges=(("jev", "m"), ("openai_decisions", "m")),
        rubric_hashes={CANCEL: "r1"},
        model={
            "type": "two_judge",
            "judge_order": ["jev", "openai_decisions"],
            "judges": {
                "jev": judge_model("jev"),
                "openai_decisions": judge_model("openai_decisions"),
            },
            "combiner": logistic(["p:jev", "p:openai_decisions"], [3.0, 3.0], -3.0),
            "disagreement_max": disagreement_max,
        },
        global_threshold=0.5,
    )


def test_scalar_is_mean_of_yes_no_answers():
    assert scalar_score(vector("jev", 0.9, 0.5, high=0.6)) == pytest.approx(0.7)


def test_scalar_ignores_per_rule_questions_when_core_questions_exist():
    v = vector("jev", 0.9, 0.5)
    with_rules = v.model_copy(
        update={"answers": {**v.answers, "status_ok": YesNoAnswer(p_yes=0.0)}}
    )
    assert scalar_score(with_rules) == pytest.approx(0.7)
    rules_only = QuestionVector(
        judge="jev",
        model_id="m",
        answers={"status_ok": YesNoAnswer(p_yes=0.2), "confirmed": YesNoAnswer(p_yes=0.6)},
    )
    assert scalar_score(rules_only) == pytest.approx(0.4)


def test_thresholds_per_action_with_global_fallback():
    arm = scalar_arm()
    assert arm.threshold(CANCEL) == 0.8
    assert arm.threshold("never_seen") == 0.6
    v = {"jev": vector("jev", 0.7, 0.7)}
    assert arm.decide(CANCEL, v) == "ASK"
    assert arm.decide("never_seen", v) == "ALLOW"


def test_unfit_threshold_fails_closed():
    arm = scalar_arm(global_threshold=None, action_thresholds={})
    assert arm.threshold(CANCEL) == math.inf
    assert arm.decide(CANCEL, {"jev": vector("jev", 1.0, 1.0)}) == "ASK"


def test_missing_judge_or_other_model_asks():
    arm = scalar_arm()
    assert arm.decide(CANCEL, {}) == "ASK"
    assert arm.decide(CANCEL, {"jev": vector("jev", 1.0, 1.0, model="other")}) == "ASK"
    with pytest.raises(KeyError):
        arm.p_ok(CANCEL, {})


def test_disagreement_routed_to_ask():
    agree = {
        "jev": vector("jev", 0.95, 0.9),
        "openai_decisions": vector("openai_decisions", 0.95, 0.9),
    }
    split = {
        "jev": vector("jev", 0.95, 0.9),
        "openai_decisions": vector("openai_decisions", 0.3, 0.9),
    }
    routed = two_judge_arm(disagreement_max=0.5)
    assert routed.decide(CANCEL, agree) == "ALLOW"
    # Without routing, the high Jev score alone is enough to allow.
    assert two_judge_arm(disagreement_max=None).p_ok(CANCEL, split) >= 0.5
    assert two_judge_arm(disagreement_max=None).decide(CANCEL, split) == "ALLOW"
    assert routed.decide(CANCEL, split) == "ASK"


@pytest.mark.parametrize("make", [scalar_arm, lambda: two_judge_arm(0.4)])
def test_save_load_round_trip_is_plain_json(tmp_path, make):
    arm = make()
    path = tmp_path / "arm.json"
    arm.save(path)
    data = json.loads(path.read_text())
    assert data["format"] == "hatchway.frozen_arm"
    assert data["arm"] == arm.arm
    loaded = FrozenArm.load(path)
    assert loaded == arm
    assert loaded.judges == arm.judges
    v = {"jev": vector("jev", 0.9, 0.8), "openai_decisions": vector("openai_decisions", 0.6, 0.8)}
    for action in (CANCEL, RETURN):
        assert loaded.p_ok(action, v) == arm.p_ok(action, v)
        assert loaded.decide(action, v) == arm.decide(action, v)


def test_rejects_other_files(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"arm": "B"}')
    with pytest.raises(ValueError, match="frozen_arm"):
        FrozenArm.load(path)


def test_isotonic_stage_interpolates_and_clips():
    xs, ys = [0.2, 0.5, 0.8], [0.1, 0.4, 0.9]
    assert interp(0.0, xs, ys) == 0.1
    assert interp(1.0, xs, ys) == 0.9
    assert interp(0.35, xs, ys) == pytest.approx(0.25)
    cal = {**logistic(["q"], [1.0]), "kind": "isotonic_logistic", "isotonic": [{"x": xs, "y": ys}]}
    # identity transform, coef 1: sigmoid(isotonic(x))
    assert calibrator_predict(cal, {"q": 0.35}) == pytest.approx(1 / (1 + math.exp(-0.25)))
    # A missing feature uses the stored fill value.
    assert calibrator_predict(cal, {}) == calibrator_predict(cal, {"q": 0.5})
