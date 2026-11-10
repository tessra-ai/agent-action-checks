"""M6b: the multivariate learner, on synthetic receipts with a known multi-question signal."""

import random

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression

from hatchway.bench.frozen import calibrated_predict, calibrator_predict, scalar_score
from hatchway.bench.learner import (
    MIN_ACTION_INCORRECT,
    Example,
    catch_auto,
    ece,
    fit_calibrator,
    fit_single,
    fit_threshold,
    fit_thresholds,
    fit_two_judge,
    isotonic_fit,
)
from hatchway.bench.synthetic import make_case


def examples(n: int, seed: int, group_offset: int = 0) -> list[Example]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        case = make_case(rng)
        group = f"task-{(i + group_offset) // 3}"
        out.append(Example(case.action, case.vectors, case.verdict == "ALLOW", group))
    return out


def scores_of(rows, fn):
    return [fn(e) for e in rows]


def columns(rows):
    return [e.ok for e in rows], [e.weight for e in rows], [e.action for e in rows]


# --- thresholds ------------------------------------------------------------------------------


def test_threshold_catches_target_share_including_ties():
    scores = [0.1, 0.2, 0.2, 0.3, 0.9, 0.95, 0.99]
    ok = [False, False, False, True, True, False, True]
    t = fit_threshold(scores, ok, [1.0] * 7, target=0.75)
    # 3 of 4 incorrect (0.1, 0.2, 0.2) must score below t; t sits between 0.2 and 0.3.
    assert t == pytest.approx(0.25)
    assert fit_threshold(scores, ok, [1.0] * 7, target=1.0) == pytest.approx(0.97)
    assert fit_threshold([0.5, 0.6], [True, True], [1.0, 1.0], 0.95) is None


def test_threshold_respects_ips_weights():
    scores, ok = [0.1, 0.5, 0.8], [False, False, True]
    # The 0.5 write carries most of the incorrect weight, so it must be caught.
    assert fit_threshold(scores, ok, [1.0, 9.0, 1.0], target=0.5) == pytest.approx(0.65)
    assert fit_threshold(scores, ok, [9.0, 1.0, 1.0], target=0.5) == pytest.approx(0.3)


def test_rare_actions_fall_back_to_global_threshold():
    rng = random.Random(0)
    scores, ok, actions = [], [], []
    for _ in range(200):
        bad = rng.random() < 0.2
        scores.append(rng.random() * 0.6 if bad else 0.3 + rng.random() * 0.7)
        ok.append(not bad)
        actions.append("common")
    scores += [0.1, 0.9]
    ok += [False, True]
    actions += ["rare", "rare"]
    th = fit_thresholds(scores, ok, [1.0] * len(ok), actions, 0.95)
    assert th.detail["common"]["source"] == "action"
    assert th.detail["rare"] == {
        "n_incorrect": 1,
        "source": "global",
        "threshold": th.global_threshold,
    }
    assert "rare" not in th.per_action and th.for_action("rare") == th.global_threshold
    catch, _ = catch_auto(scores, ok, [1.0] * len(ok), actions, th)
    assert catch >= 0.95
    assert MIN_ACTION_INCORRECT == 5


# --- calibration -----------------------------------------------------------------------------


@pytest.mark.parametrize("increasing", [True, False])
def test_isotonic_matches_sklearn(increasing):
    rng = np.random.default_rng(1)
    x = rng.random(400).round(2)
    p = 0.2 + 0.6 * x if increasing else 0.8 - 0.6 * x
    y = (rng.random(400) < p).astype(float)
    w = rng.random(400) + 0.5
    kx, ky = isotonic_fit(x, y, w)
    ref = IsotonicRegression(increasing=increasing, out_of_bounds="clip").fit(x, y, sample_weight=w)
    grid = np.linspace(-0.1, 1.1, 101)
    np.testing.assert_allclose(np.interp(grid, kx, ky), ref.predict(grid), atol=1e-12)


def test_calibrator_kind_depends_on_label_count():
    rows = examples(120, seed=3)
    feats = [{"q": scalar_score(e.vectors["jev"])} for e in rows]
    ok, w, _ = columns(rows)
    groups = [e.group for e in rows]
    assert fit_calibrator(feats[:49], ok[:49], w[:49], groups[:49], 0)["kind"] == "logistic"
    assert (
        fit_calibrator(feats[:50], ok[:50], w[:50], groups[:50], 0)["kind"] == "isotonic_logistic"
    )
    one_class = [i for i, o in enumerate(ok) if o][:10]
    const = fit_calibrator([feats[i] for i in one_class], [True] * 10, [1.0] * 10, ["g"] * 10, 0)
    assert const == {"kind": "constant", "p": 1.0, "n_labels": 10}


def test_zero_ips_weight_drops_a_row():
    rows = examples(40, seed=4)
    feats = [
        {"a": scalar_score(e.vectors["jev"]), "b": scalar_score(e.vectors["openai_decisions"])}
        for e in rows
    ]
    ok, w, _ = columns(rows)
    groups = [e.group for e in rows]
    w0 = [0.0] * 5 + w[5:]
    full = fit_calibrator(feats, ok, w0, groups, 0)
    dropped = fit_calibrator(feats[5:], ok[5:], w[5:], groups[5:], 0)
    probe = {"a": 0.6, "b": 0.7}
    assert calibrator_predict(full, probe) == pytest.approx(
        calibrator_predict(dropped, probe), abs=1e-4
    )


def test_ece():
    assert ece([0.9] * 10, [True] * 9 + [False]) == pytest.approx(0.0)
    assert ece([0.9] * 10, [True] * 5 + [False] * 5) == pytest.approx(0.4)
    assert ece([], []) is None


# --- M6b acceptance --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def train_test():
    return examples(600, seed=10), examples(4000, seed=11, group_offset=10**6)


def test_learner_beats_best_scalar_baseline(train_test):
    train, test = train_test
    ok_tr, w_tr, a_tr = columns(train)
    ok_te, w_te, a_te = columns(test)
    best_scalar = 0.0
    for judge in ("llm_baseline", "jev", "openai_decisions"):
        s_tr = scores_of(train, lambda e, j=judge: scalar_score(e.vectors[j]))
        th = fit_thresholds(s_tr, ok_tr, w_tr, a_tr, 0.95)
        s_te = scores_of(test, lambda e, j=judge: scalar_score(e.vectors[j]))
        best_scalar = max(best_scalar, catch_auto(s_te, ok_te, w_te, a_te, th)[1])
    model, oof = fit_single(train, "jev", seed=0)
    th = fit_thresholds(oof.tolist(), ok_tr, w_tr, a_tr, 0.95)
    p_te = scores_of(test, lambda e: calibrated_predict(model, e.action, e.vectors["jev"]))
    catch, auto = catch_auto(p_te, ok_te, w_te, a_te, th)
    assert catch >= 0.93  # the 95% train target, held out
    assert auto > best_scalar + 0.2


def test_ece_at_most_5_points_after_200_labels(train_test):
    train, test = train_test
    model, _ = fit_single(train[:200], "jev", seed=0)
    p = scores_of(test, lambda e: calibrated_predict(model, e.action, e.vectors["jev"]))
    after = ece(p, [e.ok for e in test])
    before = ece(scores_of(test, lambda e: scalar_score(e.vectors["jev"])), [e.ok for e in test])
    assert after <= 0.05
    assert after < before


def test_fits_are_deterministic(train_test):
    train, _ = train_test
    rows = train[:300]
    assert fit_single(rows, "jev", seed=5)[0] == fit_single(rows, "jev", seed=5)[0]
    m1, s1 = fit_two_judge(rows, ("jev", "openai_decisions"), seed=5, target=0.95)
    m2, s2 = fit_two_judge(rows, ("jev", "openai_decisions"), seed=5, target=0.95)
    assert m1 == m2
    np.testing.assert_array_equal(s1, s2)


def test_two_judge_routes_disagreement(train_test):
    train, _ = train_test
    model, eff = fit_two_judge(train[:300], ("jev", "openai_decisions"), seed=0, target=0.95)
    assert set(model["combiner"]["features"]) == {"p:jev", "p:openai_decisions", "disagreement"}
    limit = model["disagreement_max"]
    if limit is not None:
        assert (eff == -1.0).any()
