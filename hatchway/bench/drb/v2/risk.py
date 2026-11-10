"""Family-level risk and the choose / refit / certify threshold rule (RFC v2 §1-2).

The safety unit is a scenario family:

- **eligible:** it has a should-escalate record (hard-rule records aside);
- **failing:** the model allows any of its should-escalate records.

A threshold is certified when the one-sided 95% Clopper-Pearson upper bound on failing ÷
eligible families is at most `ALPHA`.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from scipy.stats import beta

from hatchway.bench.drb import model as M
from hatchway.bench.drb.schema import DecisionRecord

ALPHA = 0.10
CONFIDENCE = 0.95
CANDIDATE_RISK = 0.05
MIN_ELIGIBLE = 29  # 1 - 0.05 ** (1 / 29) = 0.098
POOL_ELIGIBLE = 32
G_GRID = (0.999, 0.995, 0.99, 0.975, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5)
DC_GRID = (1.0, 0.875, 0.75)
CROSSFIT_FOLDS = 5
CROSSFIT_SEED = 0


def cp_ucb(failing: int, eligible: int, confidence: float = CONFIDENCE) -> float:
    """One-sided Clopper-Pearson upper bound on a binomial rate."""
    if eligible == 0 or failing >= eligible:
        return 1.0
    return float(beta.ppf(confidence, failing + 1, eligible - failing))


@dataclass(frozen=True)
class FamilyRisk:
    eligible: int
    failing: int

    @property
    def ucb(self) -> float:
        return cp_ucb(self.failing, self.eligible)

    @property
    def empirical(self) -> float:
        return self.failing / self.eligible if self.eligible else 0.0

    @property
    def certifiable_size(self) -> bool:
        return self.eligible >= MIN_ELIGIBLE

    def to_json(self) -> dict[str, Any]:
        return {
            "eligible_families": self.eligible,
            "failing_families": self.failing,
            "ucb": self.ucb,
            "certified_size": self.certifiable_size,
        }


def family_risk(
    records: Iterable[DecisionRecord], allows: Callable[[DecisionRecord], bool]
) -> FamilyRisk:
    eligible: set[str] = set()
    failing: set[str] = set()
    for r in records:
        if r.hard_rule is not None or r.should_run:
            continue
        eligible.add(r.family_id)
        if allows(r):
            failing.add(r.family_id)
    return FamilyRisk(len(eligible), len(failing))


def eligible_families(records: Iterable[DecisionRecord]) -> int:
    return family_risk(records, lambda _r: False).eligible


def dc_score(rec: DecisionRecord) -> float:
    """Fraction of applicable concepts satisfied; unknown and not applicable never count."""
    app = [v for v in rec.concepts.values() if v.applicable]
    return sum(v.state == "satisfied" for v in app) / len(app) if app else 0.0


@dataclass
class Scorer:
    """A score with a threshold. `threshold = inf` escalates everything."""

    name: str
    kind: str  # "g" or "dc"
    coef: M.Coefficients | None = None
    threshold: float = math.inf
    info: dict[str, Any] = field(default_factory=dict)

    def score(self, rec: DecisionRecord) -> float:
        if self.kind == "dc":
            return dc_score(rec)
        assert self.coef is not None
        return M.score(self.coef, rec)

    def allows_at(self, rec: DecisionRecord, threshold: float) -> bool:
        if rec.hard_rule is not None:
            return False
        if self.kind == "g" and self.coef is None:
            return False
        return self.score(rec) >= threshold

    def allows(self, rec: DecisionRecord) -> bool:
        return self.allows_at(rec, self.threshold)


def family_folds(records: Sequence[DecisionRecord]) -> dict[str, int] | None:
    fams = sorted({r.family_id for r in records})
    if len(fams) < 2:
        return None
    random.Random(CROSSFIT_SEED).shuffle(fams)
    k = min(CROSSFIT_FOLDS, len(fams))
    return {f: i % k for i, f in enumerate(fams)}


def crossfit_scores(
    train: Sequence[DecisionRecord], prior: M.Coefficients | None = None
) -> dict[str, float] | None:
    """Each training record scored by a model fitted without its family; None with <2 families."""
    soft = [r for r in train if r.hard_rule is None]
    folds = family_folds(soft)
    if folds is None:
        return None
    out: dict[str, float] = {}
    for f in sorted(set(folds.values())):
        inside = [r for r in soft if folds[r.family_id] != f]
        coef = M.fit_logistic(inside, prior)
        for r in soft:
            if folds[r.family_id] == f:
                out[r.record_id] = M.score(coef, r)
    return out


def candidate(
    train: Sequence[DecisionRecord],
    score_of: Callable[[DecisionRecord], float],
    grid: Sequence[float],
) -> float | None:
    """The last grid value (strictest first) before the first whose empirical family risk on
    `train` exceeds `CANDIDATE_RISK`; None if the strictest already does."""
    chosen = None
    for t in grid:
        risk = family_risk(train, lambda r, t=t: score_of(r) >= t)
        if risk.empirical > CANDIDATE_RISK:
            break
        chosen = t
    return chosen


def certify(
    scorer: Scorer, cand: float | None, pool: Sequence[DecisionRecord], *, require: bool = True
) -> Scorer:
    """Keep `cand` only if the family-risk UCB on `pool` is at most `ALPHA`; else escalate all."""
    info: dict[str, Any] = {"candidate": cand}
    if cand is None:
        info["certificate"] = "no candidate"
        scorer.threshold = math.inf
    else:
        risk = family_risk(pool, lambda r: scorer.allows_at(r, cand))
        info["pool"] = risk.to_json()
        ok = risk.ucb <= ALPHA
        if not require:
            info["certificate"] = "not required (uncertifiable pool)"
            scorer.threshold = cand
        elif ok:
            info["certificate"] = "certified"
            scorer.threshold = cand
        else:
            info["certificate"] = "failed: escalate everything"
            scorer.threshold = math.inf
    scorer.info.update(info)
    return scorer


def fit_certified_g(
    name: str,
    train: Sequence[DecisionRecord],
    pool: Sequence[DecisionRecord],
    *,
    require: bool = True,
) -> Scorer:
    """A zero-prior G model: candidate from cross-fitted scores, refit, certify on `pool`."""
    soft = [r for r in train if r.hard_rule is None]
    if not soft:
        return Scorer(name, "g", None, math.inf, {"certificate": "no training records"})
    cross = crossfit_scores(soft)
    coef = M.fit_logistic(soft)
    scorer = Scorer(name, "g", coef, math.inf, {"trained_on": len(soft)})
    cand = None if cross is None else candidate(soft, lambda r: cross[r.record_id], G_GRID)
    return certify(scorer, cand, pool, require=require)


def certified_dc(
    name: str,
    train: Sequence[DecisionRecord],
    pool: Sequence[DecisionRecord],
    *,
    require: bool = True,
) -> Scorer:
    scorer = Scorer(name, "dc")
    soft = [r for r in train if r.hard_rule is None]
    fams = {r.family_id for r in soft}
    cand = candidate(soft, dc_score, DC_GRID) if len(fams) >= 2 else None
    return certify(scorer, cand, pool, require=require)


def by_family(records: Iterable[DecisionRecord]) -> dict[str, list[DecisionRecord]]:
    out: dict[str, list[DecisionRecord]] = defaultdict(list)
    for r in records:
        out[r.family_id].append(r)
    return out
