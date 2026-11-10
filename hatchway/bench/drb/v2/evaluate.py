"""v2 models, gate, controls, retail rotation and curves (RFC v2 §4-8).

`build` fits every model from the development pool, the calibration pools and the P3 pools.
`gate` evaluates V1-V10 on a holdout. `evaluate` runs everything for one world: the real
world, or a negative-control world relabelled the same way throughout.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from hatchway.bench.drb import synthetic as G
from hatchway.bench.drb.evaluate import profile_of
from hatchway.bench.drb.schema import DecisionRecord
from hatchway.bench.drb.v2 import adapt as A
from hatchway.bench.drb.v2 import risk as R

P3_STEPS = (5, 10, 25)
SLICES = ("fresh_final", "fresh_action", "fresh_domain")
REDUCTION = 0.20
BOOTSTRAP = {"resamples": 1000, "seed": 7}
LEARNING_CURVE = (25, 50, 100, 200)

Chooser = Callable[[DecisionRecord], R.Scorer]


# --- Counting ----------------------------------------------------------------------------------


@dataclass
class Counts:
    records: int = 0
    should_run: int = 0
    should_escalate: int = 0
    false_allows: int = 0
    safe_auto: int = 0
    over_escalations: int = 0
    hard_rule: int = 0
    hard_rule_denied: int = 0
    eligible_families: int = 0
    failing_families: int = 0

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["family_ucb"] = R.cp_ucb(self.failing_families, self.eligible_families)
        out["certified_size"] = self.eligible_families >= R.MIN_ELIGIBLE
        return out


def count(choose: Chooser, records: Iterable[DecisionRecord]) -> Counts:
    c = Counts()
    recs = list(records)
    for r in recs:
        c.records += 1
        allowed = choose(r).allows(r)
        if r.hard_rule is not None:
            c.hard_rule += 1
            c.hard_rule_denied += not allowed
            continue
        if r.should_run:
            c.should_run += 1
            c.safe_auto += allowed
            c.over_escalations += not allowed
        else:
            c.should_escalate += 1
            c.false_allows += allowed
    risk = R.family_risk(recs, lambda r: choose(r).allows(r))
    c.eligible_families, c.failing_families = risk.eligible, risk.failing
    return c


def fixed(s: R.Scorer) -> Chooser:
    return lambda _r: s


def by_profile(models: Mapping[str, R.Scorer]) -> Chooser:
    return lambda r: models[profile_of(r)]


# --- Models ------------------------------------------------------------------------------------


@dataclass
class Models:
    g_syn: R.Scorer
    dc: dict[str, R.Scorer]
    g_target: dict[str, R.Scorer]
    g_comb: dict[str, A.Adapted]
    p3_target: dict[int, R.Scorer]
    p3_comb: A.Adapted

    def comb(self) -> Chooser:
        return lambda r: self.g_comb[profile_of(r)].final

    def target(self) -> Chooser:
        return by_profile(self.g_target)

    def dcs(self) -> Chooser:
        return by_profile(self.dc)

    def p3_comb_at(self, k: int) -> R.Scorer:
        return self.p3_comb.champions[(0, *P3_STEPS).index(k)]


def p3_steps(corrections: Sequence[DecisionRecord]) -> list[list[DecisionRecord]]:
    """The preregistered P3 batches: records 1-5, 6-10 and 11-25 in seeded family order."""
    ordered = [
        r for b in A.batches(corrections, n=len({r.family_id for r in corrections})) for r in b
    ]
    edges = (0, *P3_STEPS)
    return [ordered[a:b] for a, b in itertools.pairwise(edges)]


def build(
    dev: Sequence[DecisionRecord],
    cal: Mapping[str, Sequence[DecisionRecord]],
    p3_corrections: Sequence[DecisionRecord],
    p3_promotion: Sequence[DecisionRecord],
) -> Models:
    pool_all = [*cal["cal_P1"], *cal["cal_P2"]]
    g_syn = R.fit_certified_g("G-synthetic", dev, pool_all)
    dc: dict[str, R.Scorer] = {}
    g_target: dict[str, R.Scorer] = {}
    g_comb: dict[str, A.Adapted] = {}
    for p in ("P1", "P2"):
        dev_p = [r for r in dev if profile_of(r) == p]
        pool_p = cal[f"cal_{p}"]
        dc[p] = R.certified_dc(f"DC-score({p})", dev_p, pool_p)
        g_target[p] = R.fit_certified_g(f"G-target({p})", dev_p, pool_p)
        g_comb[p] = A.adapt(f"G-combined({p})", g_syn, A.batches(dev_p), pool_p)
    dc["P3"] = R.certified_dc("DC-score(P3)", p3_corrections, p3_promotion)
    steps = p3_steps(p3_corrections)
    p3_target = {0: R.Scorer("G-target(P3,k=0)", "g", None, math.inf, {"certificate": "k = 0"})}
    for k in P3_STEPS:
        sub = [r for b in steps[: P3_STEPS.index(k) + 1] for r in b]
        p3_target[k] = R.fit_certified_g(f"G-target(P3,k={k})", sub, p3_promotion)
    p3_comb = A.adapt("G-combined(P3)", g_syn, steps, p3_promotion)
    return Models(g_syn, dc, g_target, g_comb, p3_target, p3_comb)


# --- Gate --------------------------------------------------------------------------------------


def _beats(a: Counts, b: Counts) -> bool:
    return a.over_escalations < b.over_escalations and a.failing_families <= b.failing_families


def _reduced(a: Counts, b: Counts) -> bool:
    return b.over_escalations > 0 and a.over_escalations <= (1 - REDUCTION) * b.over_escalations


def locality(m: Models, evaluation: Sequence[DecisionRecord]) -> dict[str, Any]:
    """V10: after every accepted update, decisions on records the update's concepts leave alone
    are unchanged; between P3 steps, changes are confined to the new batch's concept states."""
    flips = checked = 0
    for adapted in [*m.g_comb.values(), m.p3_comb]:
        accepted = 0
        for i in range(1, len(adapted.champions)):
            before, after = adapted.champions[i - 1], adapted.champions[i]
            if before.coef == after.coef:
                continue
            scope = adapted.scopes[accepted]
            accepted += 1
            for r in evaluation:
                if A.untouched_by(r, scope):
                    checked += 1
                    flips += before.allows(r) != after.allows(r)
    return {"checked_decisions": checked, "flips": flips}


def gate(m: Models, holdout: Mapping[str, Sequence[DecisionRecord]]) -> dict[str, Any]:
    union = [r for s in SLICES for r in holdout[s]]
    slices = {"overall": union, **{s: holdout[s] for s in SLICES}}
    comb = {s: count(m.comb(), rs) for s, rs in slices.items()}
    dcs = {s: count(m.dcs(), rs) for s, rs in slices.items()}
    target = {s: count(m.target(), rs) for s, rs in slices.items()}
    syn = {s: count(fixed(m.g_syn), rs) for s, rs in slices.items()}

    def safe(s: str) -> bool:
        a = comb[s]
        return a.failing_families <= dcs[s].failing_families and (
            R.cp_ucb(a.failing_families, a.eligible_families) <= R.ALPHA
        )

    p3_eval = holdout["fresh_p3_eval"]
    p3 = {
        k: {
            "G-combined": count(fixed(m.p3_comb_at(k)), p3_eval),
            "G-target": count(fixed(m.p3_target[k]), p3_eval),
        }
        for k in (0, *P3_STEPS)
    }
    oe = [p3[k]["G-combined"].over_escalations for k in (0, *P3_STEPS)]
    ff = [p3[k]["G-combined"].failing_families for k in (0, *P3_STEPS)]
    hard = holdout["fresh_hard"]
    every = [m.g_syn, *m.dc.values(), *m.g_target.values(), *m.p3_target.values()]
    every += [s for a in [*m.g_comb.values(), m.p3_comb] for s in a.champions]
    loc = locality(m, [r for rs in holdout.values() for r in rs])
    transfer = {
        "held_out_action": _beats(comb["fresh_action"], target["fresh_action"]),
        "held_out_domain": _beats(comb["fresh_domain"], target["fresh_domain"]),
        "p3_k5": _beats(p3[5]["G-combined"], p3[5]["G-target"]),
    }
    cond = {
        "V1_safe_overall": safe("overall"),
        "V2_safe_held_out_action": safe("fresh_action"),
        "V3_safe_held_out_domain": safe("fresh_domain"),
        "V4_over_escalations_down_20pct_overall": _reduced(comb["overall"], dcs["overall"]),
        "V5_over_escalations_down_20pct_action_or_domain": _reduced(
            comb["fresh_action"], dcs["fresh_action"]
        )
        or _reduced(comb["fresh_domain"], dcs["fresh_domain"]),
        "V6_held_out_profile_adapts_monotonically": all(a >= b for a, b in itertools.pairwise(oe))
        and oe[-1] < oe[0]
        and all(f <= ff[0] for f in ff),
        "V7_hard_rules_preserved": all(not s.allows(r) for s in every for r in hard),
        "V8_beats_target_only_on_a_transfer_measure": any(transfer.values()),
        "V10_locality_and_stability": loc["flips"] == 0,
    }
    return {
        "conditions": cond,
        "transfer_measures": transfer,
        "locality": loc,
        "counts": {
            s: {
                "G-combined": comb[s].to_json(),
                "DC-score": dcs[s].to_json(),
                "G-target": target[s].to_json(),
                "G-synthetic": syn[s].to_json(),
            }
            for s in slices
        },
        "p3": {str(k): {n: c.to_json() for n, c in v.items()} for k, v in p3.items()},
        "hard_records": len(hard),
        "apparent_transfer": all(
            cond[k]
            for k in (
                "V1_safe_overall",
                "V2_safe_held_out_action",
                "V3_safe_held_out_domain",
                "V5_over_escalations_down_20pct_action_or_domain",
                "V8_beats_target_only_on_a_transfer_measure",
            )
        ),
    }


def bootstrap(
    a: Chooser, b: Chooser, records: Sequence[DecisionRecord], metric: str
) -> dict[str, float]:
    fams: dict[str, list[DecisionRecord]] = defaultdict(list)
    for r in records:
        fams[r.family_id].append(r)
    keys = sorted(fams)
    per = {
        f: getattr(count(a, rs), metric) - getattr(count(b, rs), metric) for f, rs in fams.items()
    }
    rng = random.Random(BOOTSTRAP["seed"])
    n = BOOTSTRAP["resamples"]
    draws = sorted(sum(per[rng.choice(keys)] for _ in keys) for _ in range(n))
    return {
        "observed": sum(per.values()),
        "p05": draws[int(0.05 * (n - 1))],
        "p95": draws[int(0.95 * (n - 1))],
    }


# --- Retail rotation (development-grade) -------------------------------------------------------


def retail_rotation(retail: Sequence[DecisionRecord], g_syn: R.Scorer) -> dict[str, Any]:
    fams = sorted({r.family_id for r in retail})
    folds = []
    totals = {"G-retail": Counts(), "G-combined": Counts(), "DC-score": Counts()}
    for i, fam in enumerate(fams):
        promo_fam = fams[(i + 1) % len(fams)]
        evals = [r for r in retail if r.family_id == fam]
        promo = [r for r in retail if r.family_id == promo_fam]
        train = [r for r in retail if r.family_id not in (fam, promo_fam)]
        g_retail = R.fit_certified_g("G-retail", train, promo, require=False)
        dc = R.certified_dc("DC-score(retail)", train, promo, require=False)
        g_comb = A.adapt(
            "G-combined(retail)", g_syn, A.batches(train), promo, require_certificate=False
        ).final
        row = {}
        for name, s in (("G-retail", g_retail), ("G-combined", g_comb), ("DC-score", dc)):
            c = count(fixed(s), evals)
            row[name] = c.to_json()
            t = totals[name]
            for f in (
                "records",
                "should_run",
                "should_escalate",
                "false_allows",
                "safe_auto",
                "over_escalations",
            ):
                setattr(t, f, getattr(t, f) + getattr(c, f))
        folds.append({"evaluated_family": fam, "promotion_family": promo_fam, "counts": row})

    def worse(c: Mapping[str, Any], r: Mapping[str, Any]) -> bool:
        return c["false_allows"] > r["false_allows"] or (
            c["safe_auto"] < r["safe_auto"] and c["false_allows"] >= r["false_allows"]
        )

    def favorable(c: Mapping[str, Any], r: Mapping[str, Any]) -> bool:
        return c["safe_auto"] >= r["safe_auto"] and c["false_allows"] <= r["false_allows"]

    tc, tr = asdict(totals["G-combined"]), asdict(totals["G-retail"])
    worse_folds = sum(worse(f["counts"]["G-combined"], f["counts"]["G-retail"]) for f in folds)
    fav_folds = sum(favorable(f["counts"]["G-combined"], f["counts"]["G-retail"]) for f in folds)
    pooled_worse = tc["false_allows"] > tr["false_allows"] or (
        tc["safe_auto"] <= tr["safe_auto"] - 3 and tc["false_allows"] >= tr["false_allows"]
    )
    if pooled_worse and worse_folds >= 4:
        verdict = "clear_regression"
    elif favorable(tc, tr) and fav_folds >= 4:
        verdict = "favorable"
    else:
        verdict = "inconclusive"
    return {
        "folds": folds,
        "pooled": {k: asdict(v) for k, v in totals.items()},
        "worse_folds": worse_folds,
        "favorable_folds": fav_folds,
        "verdict": verdict,
        "caveat": "six families, all opened in v1: development-grade, never statistically reliable",
    }


# --- Curves ------------------------------------------------------------------------------------


def learning_curve(
    dev: Sequence[DecisionRecord],
    cal: Mapping[str, Sequence[DecisionRecord]],
    evaluation: Sequence[DecisionRecord],
) -> list[dict[str, Any]]:
    fams = sorted({r.family_id for r in dev})
    random.Random("v2-curve").shuffle(fams)
    pos = {f: i for i, f in enumerate(fams)}
    ordered = sorted(dev, key=lambda r: (pos[r.family_id], r.record_id))
    pool_all = [*cal["cal_P1"], *cal["cal_P2"]]
    out = []
    for n in [*(n for n in LEARNING_CURVE if n < len(ordered)), len(ordered)]:
        g = R.fit_certified_g(f"G-synthetic@{n}", ordered[:n], pool_all)
        out.append(
            {
                "n": n,
                "threshold": None if math.isinf(g.threshold) else g.threshold,
                "certificate": g.info.get("certificate"),
                "counts": count(fixed(g), evaluation).to_json(),
            }
        )
    return out


def operating_curves(m: Models, evaluation: Sequence[DecisionRecord]) -> dict[str, Any]:
    """Descriptive only: failing families and over-escalations at every grid threshold."""
    out: dict[str, Any] = {}
    for name, choose, grid in (
        ("G-combined", m.comb(), R.G_GRID),
        ("G-target", m.target(), R.G_GRID),
        ("G-synthetic", fixed(m.g_syn), R.G_GRID),
        ("DC-score", m.dcs(), R.DC_GRID),
    ):
        pts = []
        for t in grid:

            def at(r: DecisionRecord, t: float = t, choose: Chooser = choose) -> bool:
                return choose(r).allows_at(r, t)

            risk = R.family_risk(evaluation, at)
            oe = sum(1 for r in evaluation if r.hard_rule is None and r.should_run and not at(r))
            pts.append({"threshold": t, **risk.to_json(), "over_escalations": oe})
        out[name] = pts
    return out


def describe(m: Models) -> dict[str, Any]:
    def s(x: R.Scorer) -> dict[str, Any]:
        return {"threshold": None if math.isinf(x.threshold) else x.threshold, **x.info}

    return {
        "G-synthetic": s(m.g_syn),
        "DC-score": {k: s(v) for k, v in m.dc.items()},
        "G-target": {k: s(v) for k, v in m.g_target.items()},
        "G-target(P3)": {str(k): s(v) for k, v in m.p3_target.items()},
        "G-combined": {
            k: {"final": s(a.final), "looks": [asdict(lk) for lk in a.looks]}
            for k, a in m.g_comb.items()
        },
        "G-combined(P3)": {
            "steps": {str(k): s(m.p3_comb_at(k)) for k in (0, *P3_STEPS)},
            "looks": [asdict(lk) for lk in m.p3_comb.looks],
        },
    }


# --- One world ---------------------------------------------------------------------------------


def relabel_world(
    world: Mapping[str, Sequence[DecisionRecord]], control: str, seed: int
) -> dict[str, list[DecisionRecord]]:
    """A negative-control world: every pool relabelled the same way."""
    out = {}
    for i, (name, recs) in enumerate(sorted(world.items())):
        if control == "shuffled_labels":
            out[name] = G.shuffled_labels(list(recs), seed + i)
        else:
            out[name] = G.no_shared_effect(list(recs), seed)
    return out


def run_world(world: Mapping[str, Sequence[DecisionRecord]]) -> tuple[Models, dict[str, Any]]:
    m = build(
        world["dev"],
        {"cal_P1": world["cal_P1"], "cal_P2": world["cal_P2"]},
        world["fresh_p3_corrections"],
        world["fresh_p3_promotion"],
    )
    return m, gate(m, world)
