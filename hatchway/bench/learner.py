"""Multivariate risk models and 95%-catch thresholds for replay arms E and F (M6b).

Calibration is over the full question vector, not one scalar: recalibrating a scalar is
monotonic and cannot reorder writes, so it cannot ask less at the same catch rate. Each
`Calibrator` (see `hatchway.bench.frozen`) is fit on one set of labeled examples:

- below `ISOTONIC_MIN_LABELS` (50) labels: L2 logistic regression on the logit of each feature;
- at 50 or more: per-feature isotonic regression (weighted pool-adjacent-violators, direction
  from the sign of the feature's correlation with the label), then an L2 logistic combiner
  over the logit of the isotonic outputs. The combiner is trained on out-of-fold isotonic
  outputs (folds grouped by task), so it does not learn from isotonic maps that saw the same
  rows;
- with a single label class: a constant.

Arm E fits one calibrator per action that has at least `ISOTONIC_MIN_LABELS` labels with at
least `MIN_CLASS_LABELS` of each class, plus a global one over all actions for the rest.

Arm F fits arm E's model for each of two judges, then a logistic combiner over both calibrated
probabilities and their disagreement `|p_a - p_b|`, trained on out-of-fold sub-model
predictions. Writes whose disagreement exceeds `disagreement_max` go to `ASK`; the limit is
chosen on train among high quantiles of the disagreement (or none) to maximize the train auto
rate at the catch target.

Thresholds for E and F are fit on out-of-fold train predictions: in-sample predictions of a
fitted model are overconfident and would set thresholds that miss the target on new tasks.

Every fit takes IPS weights (`Example.weight`; all 1.0 on week 1 benchmark data) and a seed, and
is deterministic for a given seed.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from hatchway.bench.frozen import (
    calibrated_predict,
    calibrator_predict,
    logit,
    vector_features,
)
from hatchway.judges.base import QuestionVector

ISOTONIC_MIN_LABELS = 50
MIN_CLASS_LABELS = 5
# An action with fewer incorrect training writes than this uses the arm's global threshold.
MIN_ACTION_INCORRECT = 5
CV_FOLDS = 5
L2_C = 1.0
DISAGREEMENT_QUANTILES = (0.80, 0.90, 0.95, 0.99)


@dataclass(frozen=True)
class Example:
    """One labeled training write. `ok` is True for a correct write."""

    action: str
    vectors: Mapping[str, QuestionVector]
    ok: bool
    group: str
    weight: float = 1.0


# --- thresholds ------------------------------------------------------------------------------


def fit_threshold(
    scores: Sequence[float], ok: Sequence[bool], weights: Sequence[float], target: float
) -> float | None:
    """The lowest threshold t with `score < t` for at least `target` of the incorrect weight.

    t is placed midway between the last incorrect score that must be caught and the next higher
    score, so ties are caught too. Returns None when there are no incorrect writes.
    """
    incorrect = sorted((s, w) for s, o, w in zip(scores, ok, weights, strict=True) if not o)
    total = math.fsum(w for _, w in incorrect)
    if total <= 0:
        return None
    need = target * total
    cum = 0.0
    edge = incorrect[-1][0]
    for s, w in incorrect:
        cum += w
        if cum >= need - 1e-9:
            edge = s
            break
    above = [s for s in scores if s > edge]
    return (edge + min(above)) / 2 if above else math.nextafter(edge, math.inf)


@dataclass
class Thresholds:
    global_threshold: float | None
    per_action: dict[str, float]  # only actions with their own threshold
    detail: dict[str, dict[str, Any]]  # every action: n_incorrect, source, threshold

    def for_action(self, action: str) -> float:
        t = self.per_action.get(action, self.global_threshold)
        return math.inf if t is None else t


def fit_thresholds(
    scores: Sequence[float],
    ok: Sequence[bool],
    weights: Sequence[float],
    actions: Sequence[str],
    target: float,
) -> Thresholds:
    """A global threshold plus one per action with at least `MIN_ACTION_INCORRECT` incorrect
    writes; the others fall back to the global one."""
    global_t = fit_threshold(scores, ok, weights, target)
    per_action: dict[str, float] = {}
    detail: dict[str, dict[str, Any]] = {}
    for action in sorted(set(actions)):
        idx = [i for i, a in enumerate(actions) if a == action]
        n_incorrect = sum(1 for i in idx if not ok[i])
        t = None
        if n_incorrect >= MIN_ACTION_INCORRECT:
            t = fit_threshold(
                [scores[i] for i in idx], [ok[i] for i in idx], [weights[i] for i in idx], target
            )
        if t is not None:
            per_action[action] = t
            detail[action] = {"n_incorrect": n_incorrect, "source": "action", "threshold": t}
        else:
            source = "global" if global_t is not None else "insufficient data"
            detail[action] = {"n_incorrect": n_incorrect, "source": source, "threshold": global_t}
    return Thresholds(global_t, per_action, detail)


def catch_auto(
    scores: Sequence[float],
    ok: Sequence[bool],
    weights: Sequence[float],
    actions: Sequence[str],
    thresholds: Thresholds,
) -> tuple[float | None, float | None]:
    """Weighted (catch rate, auto rate) of `thresholds` on these rows."""
    caught = incorrect = allowed = correct = 0.0
    for s, o, w, a in zip(scores, ok, weights, actions, strict=True):
        allow = s >= thresholds.for_action(a)
        if o:
            correct += w
            allowed += w * allow
        else:
            incorrect += w
            caught += w * (not allow)
    return (caught / incorrect if incorrect else None, allowed / correct if correct else None)


# --- calibration -----------------------------------------------------------------------------


def ece(
    p: Sequence[float], ok: Sequence[bool], weights: Sequence[float] | None = None, bins: int = 10
) -> float | None:
    """Expected calibration error with equal-width bins."""
    if not len(p):
        return None
    w = np.ones(len(p)) if weights is None else np.asarray(weights, dtype=float)
    pa, ya = np.asarray(p, dtype=float), np.asarray(ok, dtype=float)
    idx = np.minimum((pa * bins).astype(int), bins - 1)
    total, err = w.sum(), 0.0
    for b in range(bins):
        m = idx == b
        if w[m].sum() > 0:
            err += (
                abs(np.average(pa[m], weights=w[m]) - np.average(ya[m], weights=w[m])) * w[m].sum()
            )
    return float(err / total)


def group_folds(groups: Sequence[str], seed: int, k: int = CV_FOLDS) -> list[int] | None:
    """A fold id per row; rows of one group share a fold. None with fewer than two groups."""
    unique = sorted(set(groups))
    if len(unique) < 2:
        return None
    random.Random(seed).shuffle(unique)
    k = min(k, len(unique))
    fold_of = {g: i % k for i, g in enumerate(unique)}
    return [fold_of[g] for g in groups]


def _weighted_mean_std(x: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    mean = float(np.average(x, weights=w))
    std = float(np.sqrt(np.average((x - mean) ** 2, weights=w)))
    return mean, (std if std > 1e-9 else 1.0)


def _constant(y: np.ndarray, w: np.ndarray) -> dict[str, Any]:
    p = float(np.average(y, weights=w)) if len(y) and w.sum() > 0 else 0.5
    return {"kind": "constant", "p": p, "n_labels": len(y)}


def isotonic_fit(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Weighted isotonic regression (pool adjacent violators) of y on x.

    The direction follows the sign of the weighted correlation (increasing on a tie). Returns
    the knots (distinct x, fitted y) of a map that is linear between knots and flat outside.
    """
    ux, inverse = np.unique(x, return_inverse=True)
    wsum = np.bincount(inverse, weights=w, minlength=len(ux))
    ysum = np.bincount(inverse, weights=w * y, minlength=len(ux))
    keep = wsum > 0
    ux, wsum, ysum = ux[keep], wsum[keep], ysum[keep]
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    sign = 1.0 if float(np.sum(w * (x - xm) * (y - ym))) >= 0 else -1.0
    # Stack of blocks: [weighted sum of sign*y, weight, number of knots].
    blocks: list[list[float]] = []
    for v, wt in zip(sign * ysum / wsum, wsum, strict=True):
        blocks.append([v * wt, wt, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, wt2, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += wt2
            blocks[-1][2] += n
    fitted = np.repeat([sign * s / wt for s, wt, _ in blocks], [int(n) for _, _, n in blocks])
    return ux, np.clip(fitted, 0.0, 1.0)


def fit_calibrator(
    features: Sequence[Mapping[str, float]],
    ok: Sequence[bool],
    weights: Sequence[float],
    groups: Sequence[str],
    seed: int,
    *,
    transforms: Mapping[str, str] | None = None,
    isotonic: bool | None = None,
) -> dict[str, Any]:
    """Fit one calibrator (see the module docstring). `transforms` overrides the default
    `logit` per feature; `isotonic` forces or disables the isotonic stage."""
    y = np.asarray(ok, dtype=float)
    w = np.asarray(weights, dtype=float)
    if len(set(ok)) < 2:
        return _constant(y, w)
    names = sorted({name for f in features for name in f})
    fill = []
    for name in names:
        present = [(f[name], wi) for f, wi in zip(features, w, strict=True) if name in f]
        fill.append(float(np.average([v for v, _ in present], weights=[x for _, x in present])))
    x = np.array([[f.get(n, fill[j]) for j, n in enumerate(names)] for f in features], dtype=float)
    use_isotonic = len(y) >= ISOTONIC_MIN_LABELS if isotonic is None else isotonic
    cal: dict[str, Any] = {"kind": "isotonic_logistic" if use_isotonic else "logistic"}
    if use_isotonic:
        folds = group_folds(groups, seed)
        stage = np.empty_like(x)
        maps = []
        for j in range(len(names)):
            knots_x, knots_y = isotonic_fit(x[:, j], y, w)
            if folds is None:
                stage[:, j] = np.interp(x[:, j], knots_x, knots_y)
            else:
                fa = np.asarray(folds)
                for k in sorted(set(folds)):
                    test = fa == k
                    kx, ky = isotonic_fit(x[~test, j], y[~test], w[~test])
                    stage[test, j] = np.interp(x[test, j], kx, ky)
            maps.append({"x": knots_x.tolist(), "y": knots_y.tolist()})
        cal["isotonic"] = maps
        x = stage
    kinds = [(transforms or {}).get(n, "logit") for n in names]
    z = np.column_stack(
        [np.vectorize(logit)(x[:, j]) if t == "logit" else x[:, j] for j, t in enumerate(kinds)]
    )
    stats = [_weighted_mean_std(z[:, j], w) for j in range(len(names))]
    mean = np.array([m for m, _ in stats])
    scale = np.array([s for _, s in stats])
    lr = LogisticRegression(C=L2_C, max_iter=1000)
    lr.fit((z - mean) / scale, y, sample_weight=w)
    cal.update(
        features=names,
        fill=fill,
        transforms=kinds,
        mean=mean.tolist(),
        scale=scale.tolist(),
        coef=lr.coef_[0].tolist(),
        intercept=float(lr.intercept_[0]),
        n_labels=len(y),
    )
    return cal


def fit_judge_model(examples: Sequence[Example], judge: str, seed: int) -> dict[str, Any]:
    """Arm E's model for one judge: per-action calibrators where the action has enough labels
    of both classes, and a global (`"*"`) calibrator."""

    def fit(rows: Sequence[Example]) -> dict[str, Any]:
        return fit_calibrator(
            [vector_features(e.vectors[judge]) for e in rows],
            [e.ok for e in rows],
            [e.weight for e in rows],
            [e.group for e in rows],
            seed,
        )

    models = {"*": fit(examples)}
    for action in sorted({e.action for e in examples}):
        rows = [e for e in examples if e.action == action]
        n_ok = sum(e.ok for e in rows)
        if len(rows) >= ISOTONIC_MIN_LABELS and min(n_ok, len(rows) - n_ok) >= MIN_CLASS_LABELS:
            models[action] = fit(rows)
    return {"type": "calibrated", "judge": judge, "models": models}


def out_of_fold(
    examples: Sequence[Example],
    fit: Callable[[Sequence[Example]], Any],
    predict: Callable[[Any, Example], float],
    seed: int,
) -> np.ndarray:
    """Predictions for each example from a model fit on the other task folds (in-sample when
    there are fewer than two tasks)."""
    folds = group_folds([e.group for e in examples], seed)
    if folds is None:
        model = fit(examples)
        return np.array([predict(model, e) for e in examples])
    out = np.empty(len(examples))
    for k in sorted(set(folds)):
        train = [e for e, f in zip(examples, folds, strict=True) if f != k]
        model = fit(train)
        for i, f in enumerate(folds):
            if f == k:
                out[i] = predict(model, examples[i])
    return out


def fit_single(
    examples: Sequence[Example], judge: str, seed: int
) -> tuple[dict[str, Any], np.ndarray]:
    """Arm E for one judge: (model, out-of-fold train predictions)."""
    oof = out_of_fold(
        examples,
        lambda rows: fit_judge_model(rows, judge, seed),
        lambda model, e: calibrated_predict(model, e.action, e.vectors[judge]),
        seed,
    )
    return fit_judge_model(examples, judge, seed), oof


_COMBINER_TRANSFORMS = {"disagreement": "identity"}


def _combiner_features(a: str, b: str, p_a: float, p_b: float) -> dict[str, float]:
    return {f"p:{a}": p_a, f"p:{b}": p_b, "disagreement": abs(p_a - p_b)}


def fit_two_judge(
    examples: Sequence[Example], judges: tuple[str, str], seed: int, target: float
) -> tuple[dict[str, Any], np.ndarray]:
    """Arm F: (model, out-of-fold effective train scores). A write routed to ASK by the
    disagreement limit scores -1, below any threshold."""
    a, b = judges
    _, oof_a = fit_single(examples, a, seed)
    _, oof_b = fit_single(examples, b, seed)
    feats = [_combiner_features(a, b, pa, pb) for pa, pb in zip(oof_a, oof_b, strict=True)]
    ok = [e.ok for e in examples]
    w = [e.weight for e in examples]
    groups = [e.group for e in examples]

    def fit_comb(idx: Sequence[int]) -> dict[str, Any]:
        return fit_calibrator(
            [feats[i] for i in idx],
            [ok[i] for i in idx],
            [w[i] for i in idx],
            [groups[i] for i in idx],
            seed,
            transforms=_COMBINER_TRANSFORMS,
            isotonic=False,
        )

    combiner = fit_comb(range(len(examples)))
    folds = group_folds(groups, seed)
    oof = np.empty(len(examples))
    if folds is None:
        oof[:] = [calibrator_predict(combiner, f) for f in feats]
    else:
        for k in sorted(set(folds)):
            model = fit_comb([i for i, f in enumerate(folds) if f != k])
            for i, f in enumerate(folds):
                if f == k:
                    oof[i] = calibrator_predict(model, feats[i])

    dis = np.abs(oof_a - oof_b)
    actions = [e.action for e in examples]
    candidates: list[float | None] = [None]
    if len(dis):
        candidates += sorted({float(np.quantile(dis, q)) for q in DISAGREEMENT_QUANTILES})[::-1]
    best: tuple[float, float | None, np.ndarray] | None = None
    for limit in candidates:
        eff = oof if limit is None else np.where(dis > limit, -1.0, oof)
        thresholds = fit_thresholds(eff.tolist(), ok, w, actions, target)
        auto = catch_auto(eff.tolist(), ok, w, actions, thresholds)[1] or 0.0
        if best is None or auto > best[0] + 1e-12:
            best = (auto, limit, eff)
    assert best is not None
    model = {
        "type": "two_judge",
        "judge_order": [a, b],
        "judges": {j: fit_judge_model(examples, j, seed) for j in (a, b)},
        "combiner": combiner,
        "disagreement_max": best[1],
    }
    return model, best[2]
