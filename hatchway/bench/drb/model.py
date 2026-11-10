"""Phase 0 models, all on the same authoritative concept inputs, frozen in `MODEL_SPEC`.

- **Hard rules run first.** A record whose `hard_rule` is set is DENY, and no model output
  changes that (`decide`).
- **Escalate-all.** The safety floor: every other record escalates.
- **DC.** ALLOW only when every applicable concept except `reversibility` is satisfied; unknown
  counts as not satisfied.
- **G family.** The G1 family: L2-regularized logistic regression, balanced class weights, solved
  by Newton's method.
  - Features (`features`), per applicable concept: `satisfied`, `not_satisfied`, `unknown`, and
    `confidence * (satisfied - not_satisfied)`. An inapplicable concept contributes zeros.
  - No action, domain, family or organization identity enters, and nothing else from the
    record.
  - Adaptation is the same fit with the L2 prior centered on the pretrained coefficients, at
    strength `lambda_adapt`. That prior strength is the frozen weighting between the pretrained
    evidence and the target organization's records.
- **Threshold rule (`select_threshold`).** On the selection set, the highest-scoring cut with
  zero false allows that lets the most should-run records through; ties go to the higher cut. No
  admissible cut means the model escalates everything.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.special import expit

from hatchway.bench.drb.schema import CONCEPTS, DecisionRecord, canonical, sha256_text

FEATURE_NAMES = tuple(
    f"{c}:{part}"
    for c in CONCEPTS
    for part in ("satisfied", "not_satisfied", "unknown", "signed_confidence")
)
DC_CONCEPTS = tuple(c for c in CONCEPTS if c != "reversibility")

MODEL_SPEC: dict[str, Any] = {
    "version": "drb-model-1",
    "family": "G1 (L2 logistic regression)",
    "features": list(FEATURE_NAMES),
    "feature_rules": [
        "per applicable concept: satisfied, not_satisfied and unknown indicators, and "
        "confidence x (satisfied - not_satisfied)",
        "an inapplicable concept contributes zeros; it is never read as satisfied",
        "no action, domain, family, organization, verdict, reason code, backend result, task "
        "outcome or trace result",
    ],
    "preprocessing": "none: the features are bounded indicators (no standardization)",
    "solver": "Newton's method, 50 iterations at most, tolerance 1e-10",
    "regularization": {"lambda": 1.0, "lambda_intercept": 0.001},
    "class_weights": "balanced when both classes are present, else uniform",
    "calibration": "none: the logistic output is the score",
    "pretraining": "fit on the synthetic pretraining partition, prior centered at 0",
    "adaptation": "fit on the target organization's records, prior centered at the pretrained "
    "coefficients",
    "lambda_adapt": 1.0,
    "threshold_rule": "on the selection set, the cut with zero false allows that lets through "
    "the most should-run records; ties go to the higher cut; none admissible means escalate "
    "everything",
    "selection_sets": {
        "G-synthetic": "synthetic promotion partition",
        "G-target(P) / G-combined(P), P in P1, P2": "synthetic promotion records of profile P",
        "held-out profile at k": "the k adaptation records themselves (k = 0 keeps the "
        "pretrained threshold; G-target escalates everything at k = 0)",
        "G-retail / G-combined (retail)": "family-grouped out-of-fold scores on retail "
        "adaptation (up to 5 folds, seed 0) plus scores on retail promotion",
    },
    "promotion_rule": "G-synthetic seeds G-combined only if, on synthetic promotion, it has no "
    "more false allows than DC and lets at least one should-run record through; otherwise "
    "G-combined starts from a zero prior",
    "dc_rule": "ALLOW iff every applicable concept except reversibility is satisfied (unknown "
    "counts as not satisfied)",
    "hard_rules": "applied before every model; never overridden",
    "seed": 0,
}


def spec_hash() -> str:
    return sha256_text(canonical(MODEL_SPEC))


def features(rec: DecisionRecord) -> np.ndarray:
    x = []
    for c in CONCEPTS:
        v = rec.concepts[c]
        if not v.applicable:
            x += [0.0, 0.0, 0.0, 0.0]
            continue
        sat, nsat, unk = v.state == "satisfied", v.state == "not_satisfied", v.state == "unknown"
        x += [float(sat), float(nsat), float(unk), v.confidence * (float(sat) - float(nsat))]
    return np.asarray(x, dtype=float)


def dc_allows(rec: DecisionRecord) -> bool:
    return all(
        rec.concepts[c].state == "satisfied" for c in DC_CONCEPTS if rec.concepts[c].applicable
    )


# --- The logistic fit --------------------------------------------------------------------------


@dataclass(frozen=True)
class Coefficients:
    w: tuple[float, ...]
    b: float

    @staticmethod
    def zero() -> Coefficients:
        return Coefficients(tuple(0.0 for _ in FEATURE_NAMES), 0.0)


def fit_logistic(
    records: Sequence[DecisionRecord], prior: Coefficients | None = None
) -> Coefficients:
    """L2 logistic regression with the penalty centered on `prior` (zero when None)."""
    prior = prior or Coefficients.zero()
    if not records:
        return prior
    x = np.stack([features(r) for r in records])
    y = np.asarray([1.0 if r.should_run else 0.0 for r in records])
    n_pos, n = y.sum(), len(y)
    balanced = 0 < n_pos < n
    sw = np.where(y == 1, n / (2 * n_pos), n / (2 * (n - n_pos))) if balanced else np.ones(n)
    xa = np.hstack([x, np.ones((n, 1))])
    mu = np.asarray([*prior.w, prior.b])
    reg = np.full(len(mu), MODEL_SPEC["regularization"]["lambda"])
    reg[-1] = MODEL_SPEC["regularization"]["lambda_intercept"]
    theta = mu.copy()
    for _ in range(50):
        p = expit(xa @ theta)
        grad = xa.T @ (sw * (p - y)) + reg * (theta - mu)
        hess = (xa * (sw * p * (1 - p))[:, None]).T @ xa + np.diag(reg)
        step = np.linalg.solve(hess, grad)
        theta -= step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    return Coefficients(tuple(float(v) for v in theta[:-1]), float(theta[-1]))


def score(coef: Coefficients, rec: DecisionRecord) -> float:
    z = float(np.dot(features(rec), np.asarray(coef.w))) + coef.b
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def select_threshold(scored: Sequence[tuple[float, bool]]) -> float:
    """The frozen threshold rule over (score, should_run) pairs."""
    best_t, best_auto = math.inf, 0
    for t in sorted({s for s, _ in scored}, reverse=True):
        fa = sum(1 for s, run in scored if s >= t and not run)
        if fa:
            break  # lower cuts only add false allows
        auto = sum(1 for s, run in scored if s >= t and run)
        if auto > best_auto:
            best_t, best_auto = t, auto
    return best_t


# --- Fitted models -----------------------------------------------------------------------------


@dataclass
class Model:
    """A decision rule: `kind` is escalate_all, dc or g."""

    name: str
    kind: str
    coef: Coefficients | None = None
    threshold: float = math.inf
    trained_on: tuple[str, ...] = ()
    info: dict[str, Any] = field(default_factory=dict)

    def score(self, rec: DecisionRecord) -> float | None:
        if self.kind == "g" and self.coef is not None:
            return score(self.coef, rec)
        if self.kind == "dc":
            return 1.0 if dc_allows(rec) else 0.0
        return None

    def allows(self, rec: DecisionRecord) -> bool:
        """The learned (or fixed) recommendation, before hard rules."""
        if self.kind == "dc":
            return dc_allows(rec)
        s = self.score(rec)
        return s is not None and s >= self.threshold

    @property
    def version(self) -> str:
        body = {
            "spec": spec_hash(),
            "name": self.name,
            "coef": None if self.coef is None else [list(self.coef.w), self.coef.b],
            "threshold": None if math.isinf(self.threshold) else self.threshold,
            "trained_on": sorted(self.trained_on),
        }
        return f"{self.name}:{sha256_text(canonical(body))[:16]}"


ESCALATE_ALL = Model("escalate-all", "escalate_all")
DC = Model("DC", "dc")


def decide(model: Model, rec: DecisionRecord) -> tuple[str, str | None]:
    """(ALLOW / ESCALATE, override). A hard rule is DENY whatever the model says."""
    if rec.hard_rule is not None:
        return "ESCALATE", f"hard_rule:{rec.hard_rule}"
    return ("ALLOW" if model.allows(rec) else "ESCALATE"), None


def fit_g(
    name: str,
    train: Sequence[DecisionRecord],
    selection: Sequence[DecisionRecord] | Callable[[Coefficients], list[tuple[float, bool]]],
    prior: Coefficients | None = None,
    *,
    inherit_threshold: float | None = None,
) -> Model:
    """A G model: fitted on `train` (prior-centered), thresholded on `selection` (records, or a
    function of the fitted coefficients that returns (score, should_run) pairs). With no
    training records, the prior is the model and `inherit_threshold` its threshold."""
    soft = [r for r in train if r.hard_rule is None]
    coef = fit_logistic(soft, prior)
    if not soft and inherit_threshold is not None:
        t = inherit_threshold
    elif callable(selection):
        t = select_threshold(selection(coef))
    else:
        t = select_threshold(
            [(score(coef, r), r.should_run) for r in selection if r.hard_rule is None]
        )
    if not soft and prior is None:
        t = math.inf
    return Model(name, "g", coef, t, tuple(r.record_id for r in soft))


def oof_selection(
    train: Sequence[DecisionRecord],
    extra: Sequence[DecisionRecord],
    prior: Coefficients | None,
    seed: int = 0,
) -> Callable[[Coefficients], list[tuple[float, bool]]]:
    """Selection pairs: family-grouped out-of-fold scores on `train` and the full model's
    scores on `extra`."""

    def pairs(full: Coefficients) -> list[tuple[float, bool]]:
        soft = [r for r in train if r.hard_rule is None]
        fams = sorted({r.family_id for r in soft})
        out = [(score(full, r), r.should_run) for r in extra if r.hard_rule is None]
        if len(fams) < 2:
            return out + [(score(full, r), r.should_run) for r in soft]
        random.Random(seed).shuffle(fams)
        k = min(5, len(fams))
        fold = {f: i % k for i, f in enumerate(fams)}
        for f in range(k):
            inside = [r for r in soft if fold[r.family_id] != f]
            sub = fit_logistic(inside, prior)
            out += [(score(sub, r), r.should_run) for r in soft if fold[r.family_id] == f]
        return out

    return pairs


def promote(g_syn: Model, promotion: Sequence[DecisionRecord]) -> tuple[bool, str]:
    """The frozen promotion rule for G-synthetic as G-combined's starting point."""
    soft = [r for r in promotion if r.hard_rule is None]
    fa_g = sum(1 for r in soft if not r.should_run and g_syn.allows(r))
    fa_dc = sum(1 for r in soft if not r.should_run and dc_allows(r))
    auto = sum(1 for r in soft if r.should_run and g_syn.allows(r))
    if fa_g > fa_dc:
        return False, f"more false allows than DC on promotion ({fa_g} > {fa_dc})"
    if auto == 0:
        return False, "lets no should-run record through on promotion"
    return True, f"false allows {fa_g} <= DC's {fa_dc}; {auto} should-run records allowed"
