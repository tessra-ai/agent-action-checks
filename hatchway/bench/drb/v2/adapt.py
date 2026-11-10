"""Bounded, anchored, local, cumulative adaptation with challenger promotion (RFC v2 §3).

A batch of corrections may move only the `not_satisfied` and `unknown` indicator weights of the
concepts it exhibits in those states. Everything else is fixed: the intercept, the `satisfied`
indicators and the signed-confidence terms. So a record whose corrected concepts are satisfied or
not applicable keeps its exact score.

- **Anchoring.** The update minimizes the batch's balanced log-loss plus
  (`LAMBDA_ADAPT` / 2)·||w - w_champion||^2.
- **Bounds.** Each free weight moves at most `DELTA` from the champion per batch and at most
  `CUMULATIVE` from the pretrained weights (L-BFGS-B, exact under the box).
- **Promotion.** A challenger is promoted only on the organization's untouched promotion pool,
  at the champion's carried threshold.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from hatchway.bench.drb import model as M
from hatchway.bench.drb.schema import CONCEPTS, DecisionRecord
from hatchway.bench.drb.v2.risk import ALPHA, Scorer, family_risk

LAMBDA_ADAPT = 10.0
DELTA = 1.0
CUMULATIVE = 3.0
N_BATCHES = 5
BATCH_SEED = 0
_INDEX = {name: i for i, name in enumerate(M.FEATURE_NAMES)}


def exhibited(batch: Sequence[DecisionRecord]) -> set[str]:
    """Concepts some batch record has applicable and not satisfied or unknown."""
    return {
        c
        for r in batch
        for c in CONCEPTS
        if r.concepts[c].applicable and r.concepts[c].state in ("not_satisfied", "unknown")
    }


def free_indices(batch: Sequence[DecisionRecord]) -> list[int]:
    return sorted(
        _INDEX[f"{c}:{state}"] for c in exhibited(batch) for state in ("not_satisfied", "unknown")
    )


def untouched_by(rec: DecisionRecord, concepts: set[str]) -> bool:
    """True if an update scoped to `concepts` cannot change this record's score."""
    return all(
        not rec.concepts[c].applicable or rec.concepts[c].state == "satisfied" for c in concepts
    )


def update(
    champion: M.Coefficients, pretrained: M.Coefficients, batch: Sequence[DecisionRecord]
) -> M.Coefficients:
    soft = [r for r in batch if r.hard_rule is None]
    free = free_indices(soft)
    if not soft or not free:
        return champion
    x = np.stack([M.features(r) for r in soft])
    y = np.asarray([1.0 if r.should_run else 0.0 for r in soft])
    n, n_pos = len(y), y.sum()
    sw = np.where(y == 1, n / (2 * n_pos), n / (2 * (n - n_pos))) if 0 < n_pos < n else np.ones(n)
    w0 = np.asarray(champion.w)
    wp = np.asarray(pretrained.w)
    base = x @ w0 + champion.b

    def objective(v: np.ndarray) -> tuple[float, np.ndarray]:
        dw = v - w0[free]
        z = base + x[:, free] @ dw
        p = expit(z)
        eps = 1e-12
        loss = -np.sum(sw * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
        loss += 0.5 * LAMBDA_ADAPT * float(dw @ dw)
        grad = x[:, free].T @ (sw * (p - y)) + LAMBDA_ADAPT * dw
        return float(loss), grad

    bounds = [
        (max(w0[i] - DELTA, wp[i] - CUMULATIVE), min(w0[i] + DELTA, wp[i] + CUMULATIVE))
        for i in free
    ]
    res = minimize(objective, w0[free], jac=True, method="L-BFGS-B", bounds=bounds)
    w = w0.copy()
    w[free] = np.clip(res.x, [b[0] for b in bounds], [b[1] for b in bounds])
    return M.Coefficients(tuple(float(v) for v in w), champion.b)


def batches(records: Sequence[DecisionRecord], n: int = N_BATCHES) -> list[list[DecisionRecord]]:
    """`n` consecutive batches in a seeded family order."""
    soft = [r for r in records if r.hard_rule is None]
    fams = sorted({r.family_id for r in soft})
    random.Random(BATCH_SEED).shuffle(fams)
    pos = {f: i for i, f in enumerate(fams)}
    ordered = sorted(soft, key=lambda r: (pos[r.family_id], r.record_id))
    size = -(-len(ordered) // n) if ordered else 0
    return [ordered[i : i + size] for i in range(0, len(ordered), size)] if size else []


@dataclass
class Look:
    batch: int
    records: int
    free_concepts: list[str]
    promoted: bool
    reason: str
    champion_pool: dict[str, Any]
    challenger_pool: dict[str, Any]


@dataclass
class Adapted:
    champions: list[Scorer]  # the champion after each batch (index 0 = before any)
    looks: list[Look] = field(default_factory=list)
    scopes: list[set[str]] = field(default_factory=list)  # concepts each accepted update touched

    @property
    def final(self) -> Scorer:
        return self.champions[-1]


def pool_stats(s: Scorer, pool: Sequence[DecisionRecord]) -> dict[str, Any]:
    risk = family_risk(pool, s.allows)
    oe = sum(1 for r in pool if r.hard_rule is None and r.should_run and not s.allows(r))
    return {**risk.to_json(), "over_escalations": oe}


def adapt(
    name: str,
    pretrained: Scorer,
    steps: Sequence[Sequence[DecisionRecord]],
    pool: Sequence[DecisionRecord],
    *,
    require_certificate: bool = True,
) -> Adapted:
    """Cumulative adaptation from `pretrained` through `steps`; promotion judged on `pool`."""
    champ = Scorer(name, "g", pretrained.coef, pretrained.threshold, dict(pretrained.info))
    out = Adapted([champ])
    if pretrained.coef is None:
        return out
    for b, batch in enumerate(steps, start=1):
        coef = update(champ.coef, pretrained.coef, batch)  # type: ignore[arg-type]
        chal = Scorer(name, "g", coef, champ.threshold, dict(champ.info))
        cs, hs = pool_stats(champ, pool), pool_stats(chal, pool)
        if hs["failing_families"] > cs["failing_families"]:
            ok, why = False, "more failing families on the promotion pool"
        elif hs["over_escalations"] >= cs["over_escalations"]:
            ok, why = False, "no fewer over-escalations on the promotion pool"
        elif require_certificate and hs["ucb"] > ALPHA:
            ok, why = False, f"promotion-pool UCB {hs['ucb']:.3f} > {ALPHA}"
        else:
            ok, why = True, "promoted"
        scope = exhibited([r for r in batch if r.hard_rule is None])
        out.looks.append(Look(b, len(batch), sorted(scope), ok, why, cs, hs))
        if ok:
            champ = chal
            out.scopes.append(scope)
        out.champions.append(champ)
    return out
