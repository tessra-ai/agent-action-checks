"""The Phase A sweep: arms S and S-text in every world, over k, conditions and replicates.

For one run (world, condition, k, replicate):

1. **Training decisions.** k triggering cases, each from a different training family, plus
   `BACKGROUND` non-triggering cases from training families, all labelled with the world's
   truth (escalate or allow).
2. **Condition.**
   - `clean`: labels as they are.
   - `noise10` / `noise20`: each label flipped with probability 0.10 / 0.20 (inconsistent
     approvers).
   - `selection`: only what a live gate would get labelled: every case the starting policy
     escalates (a human answers it) plus an `AUDIT_RATE` random audit of the cases it allows.
   - `shuffled`: labels permuted across the training cases (a negative control: no rule should
     be accepted).
3. **Learn** from the starting policy and the labelled cases.
4. **Evaluate** on every case of every test family (families never cross the split):
   - catch rate: decisions equal to the truth on triggering cases;
   - false invention: decisions changed from the starting policy's correct one on
     non-triggering cases;
   - recovered: catch ≥ 0.95 and false invention ≤ 0.01;
   - safety: false allows and failing families (a family fails when any case the truth
     escalates is allowed), with the one-sided 95% Clopper-Pearson bound on family risk.

k = 0 is the zero-decision baseline (only background cases). A k the training split cannot
supply (fewer triggering families than k) is reported as unavailable.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hatchway.bench.drb.v2.risk import cp_ucb
from hatchway.bench.pi import induce as S
from hatchway.bench.pi.cases import SEED, Case
from hatchway.bench.pi.worlds import WORLDS, World, escalates

BACKGROUND = 300
AUDIT_RATE = 0.10
K_GRID = (0, 1, 2, 5, 10, 20)
CONDITIONS = ("clean", "noise10", "noise20", "selection", "shuffled")
REPLICATES = 20
ARMS = ("S", "S-text")
RECOVERY_CATCH = 0.95
RECOVERY_FALSE_INVENTION = 0.01
K_STAR_RATE = 0.8


def is_train(family_id: str, seed: int = SEED) -> bool:
    """The family split: half the families train, half test, by hash."""
    return int(hashlib.sha256(f"{seed}:split:{family_id}".encode()).hexdigest()[:8], 16) % 2 == 0


class Prepared:
    """A world's cases with the starting policy and the truth as arrays."""

    def __init__(self, world: World, cases: Sequence[Case]):
        self.world = world
        self.cases = list(cases)
        self.cols = S.Columns([c.facts for c in self.cases], [c.text for c in self.cases])
        self.r0 = np.array([escalates(world.r0(c)) for c in self.cases], dtype=bool)
        self.relaxable = np.array([world.r0_relaxable(c) for c in self.cases], dtype=bool)
        self.truth = np.array([escalates(world.truth(c)) for c in self.cases], dtype=bool)
        self.trigger = self.r0 != self.truth
        self.family = np.array([c.family_id for c in self.cases], dtype=object)

    def subset(self, idx: Sequence[int]) -> S.Columns:
        return S.Columns([self.cases[i].facts for i in idx], [self.cases[i].text for i in idx])


def safety(family: np.ndarray, truth: np.ndarray, decision: np.ndarray) -> dict[str, Any]:
    false_allow = truth & ~decision
    eligible = set(family[truth].tolist())
    failing = set(family[false_allow].tolist())
    return {
        "false_allows": int(false_allow.sum()),
        "should_escalate": int(truth.sum()),
        "over_escalations": int((~truth & decision).sum()),
        "should_allow": int((~truth).sum()),
        "eligible_families": len(eligible),
        "failing_families": len(failing),
        "family_ucb": cp_ucb(len(failing), len(eligible)),
    }


def scores(p: Prepared, idx: np.ndarray, decision: np.ndarray) -> dict[str, Any]:
    trig = p.trigger[idx]
    truth = p.truth[idx]
    hits = decision == truth
    catch = float(hits[trig].mean()) if trig.any() else None
    invention = float((~hits[~trig]).mean()) if (~trig).any() else None
    return {
        "catch": catch,
        "false_invention": invention,
        "triggering": int(trig.sum()),
        "non_triggering": int((~trig).sum()),
        "recovered": catch is not None
        and invention is not None
        and catch >= RECOVERY_CATCH
        and invention <= RECOVERY_FALSE_INVENTION,
        **safety(p.family[idx], truth, decision),
    }


def training_sample(p: Prepared, train: np.ndarray, k: int, rng: random.Random) -> list[int] | None:
    trig_by_family: dict[str, list[int]] = {}
    for i in np.flatnonzero(train & p.trigger):
        trig_by_family.setdefault(p.family[i], []).append(int(i))
    families = sorted(trig_by_family)
    if len(families) < k:
        return None
    rng.shuffle(families)
    chosen = [rng.choice(trig_by_family[f]) for f in families[:k]]
    background = [int(i) for i in np.flatnonzero(train & ~p.trigger)]
    chosen += rng.sample(background, min(BACKGROUND, len(background)))
    return sorted(chosen)


def apply_condition(
    p: Prepared, idx: list[int], condition: str, rng: random.Random
) -> tuple[list[int], np.ndarray]:
    """The labelled training cases and their labels (True: escalate) under a condition."""
    y = p.truth[idx].copy()
    if condition.startswith("noise"):
        q = int(condition[5:]) / 100
        flips = np.array([rng.random() < q for _ in idx], dtype=bool)
        y ^= flips
    elif condition == "shuffled":
        order = list(range(len(idx)))
        rng.shuffle(order)
        y = y[order]
    elif condition == "selection":
        keep = [j for j, i in enumerate(idx) if p.r0[i] or rng.random() < AUDIT_RATE]
        return [idx[j] for j in keep], y[keep]
    return idx, y


def run_one(
    p: Prepared,
    arm: str,
    condition: str,
    k: int,
    replicate: int,
    train: np.ndarray,
    test_idx: np.ndarray,
    test_cols: S.Columns,
) -> dict[str, Any]:
    rng = random.Random(f"{SEED}:{p.world.name}:{condition}:{k}:{replicate}")
    sample = training_sample(p, train, k, rng)
    if sample is None:
        return {"available": False}
    idx, y = apply_condition(p, sample, condition, rng)
    cols = p.subset(idx)
    ix = np.array(idx, dtype=int)
    learned = S.learn(cols, p.r0[ix], p.relaxable[ix], y, text=arm == "S-text")
    decision = learned.decide(test_cols, p.r0[test_idx], p.relaxable[test_idx])
    return {
        "available": True,
        "labelled": len(idx),
        "labelled_triggering": int(p.trigger[ix].sum()),
        "rules": [r.to_json() for r in learned.rules],
        "n_literals": learned.n_literals,
        **scores(p, test_idx, decision),
    }


def summarize(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ok = [r for r in runs if r.get("available")]
    if not ok:
        return {"available": False}

    def mean(key: str) -> float | None:
        vals = [r[key] for r in ok if r[key] is not None]
        return float(np.mean(vals)) if vals else None

    return {
        "available": True,
        "replicates": len(ok),
        "recovery_rate": float(np.mean([r["recovered"] for r in ok])),
        "catch_mean": mean("catch"),
        "catch_median": float(np.median([r["catch"] for r in ok if r["catch"] is not None])),
        "false_invention_mean": mean("false_invention"),
        "any_rule_rate": float(np.mean([bool(r["rules"]) for r in ok])),
        "rules_mean": float(np.mean([len(r["rules"]) for r in ok])),
        "labelled_triggering_mean": float(np.mean([r["labelled_triggering"] for r in ok])),
        "failing_families_mean": float(np.mean([r["failing_families"] for r in ok])),
        "false_allows_mean": float(np.mean([r["false_allows"] for r in ok])),
        "over_escalations_mean": float(np.mean([r["over_escalations"] for r in ok])),
        "example_rules": ok[0]["rules"],
    }


def k_star(by_k: Mapping[str, Mapping[str, Any]]) -> int | None:
    """The smallest k whose recovery rate reaches `K_STAR_RATE`, or None."""
    for k in K_GRID:
        s = by_k.get(str(k), {})
        if s.get("available") and s["recovery_rate"] >= K_STAR_RATE:
            return k
    return None


def baselines(p: Prepared, test_idx: np.ndarray) -> dict[str, Any]:
    return {
        "R0": scores(p, test_idx, p.r0[test_idx]),
        "ceiling": scores(p, test_idx, p.truth[test_idx]),
    }


def run_world(
    world: World,
    cases: Sequence[Case],
    arms: Sequence[str] = ARMS,
    conditions: Sequence[str] = CONDITIONS,
    k_grid: Sequence[int] = K_GRID,
    replicates: int = REPLICATES,
) -> dict[str, Any]:
    p = Prepared(world, cases)
    train = np.array([is_train(f) for f in p.family], dtype=bool)
    test_idx = np.flatnonzero(~train)
    test_cols = p.subset(test_idx.tolist())
    out: dict[str, Any] = {
        "world": world.name,
        "kind": world.kind,
        "description": world.description,
        "raw_signal": world.raw_signal,
        "train_triggering_families": len(set(p.family[train & p.trigger].tolist())),
        "test": {
            "families": len(set(p.family[test_idx].tolist())),
            "cases": len(test_idx),
            "triggering": int(p.trigger[test_idx].sum()),
        },
        "baselines": baselines(p, test_idx),
        "arms": {},
    }
    for arm in arms:
        by_cond: dict[str, Any] = {}
        for condition in conditions:
            by_k: dict[str, Any] = {}
            for k in k_grid:
                runs = [
                    run_one(p, arm, condition, k, r, train, test_idx, test_cols)
                    for r in range(replicates)
                ]
                by_k[str(k)] = summarize(runs)
            by_cond[condition] = {"by_k": by_k, "k_star": k_star(by_k)}
        out["arms"][arm] = by_cond
    return out


def run_all(cases: Sequence[Case], **kw: Any) -> list[dict[str, Any]]:
    return [run_world(w, cases, **kw) for w in WORLDS]
