"""Phase 0 development, internal gate, controls and the telecom evaluation.

**Counting.** The binary question is "run automatically or escalate". Hard-rule records always
end DENY and are counted apart. For the other records:

- **false allow:** the model runs a record that should escalate;
- **safe automatic run:** it runs a record that should run;
- **over-escalation:** it escalates a record that should run.

Every count travels with its denominator.

**G-combined is a procedure:** pretrain on the pooled synthetic pretraining partition, then adapt
on the target organization's own records.

- For a synthetic record labelled by profile P (P1 or P2), the target's records are P's records
  in the pretraining partition. Its internal analogue of G-retail, *G-target(P)*, fits those
  records alone.
- For the held-out profile P3, the target's records are the first k of its adaptation partition.
- For retail, the target's records are the retail adaptation partition.

**The gate** (`GATE`, frozen in the RFC) is evaluated once, by `develop`, on the synthetic final
holdout, the held-out action and the held-out domain.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hatchway.bench.drb import model as M
from hatchway.bench.drb.partitions import ADAPT_K, adaptation_subset
from hatchway.bench.drb.schema import DecisionRecord

GATE = {
    "slices": ["syn_final", "syn_holdout_action", "syn_holdout_domain"],
    "over_escalation_reduction": 0.20,
    "min_class": 10,
    "adapt_k": [5, 10, 25],
    "transfer_measures": ["syn_holdout_action", "syn_holdout_domain", "p3_k5"],
    "bootstrap": {"resamples": 1000, "interval": 0.90, "seed": 7},
    "controls": ["shuffled_labels", "no_shared_effect"],
}
SYN_CURVE = (25, 50, 100, 200)
RETAIL_CURVE = (0, 5, 10, 25)

Chooser = Callable[[DecisionRecord], M.Model]


@dataclass
class Counts:
    records: int = 0
    should_run: int = 0
    should_escalate: int = 0
    false_allows: int = 0
    safe_auto: int = 0
    over_escalations: int = 0
    escalations: int = 0
    hard_rule: int = 0
    hard_rule_denied: int = 0
    unknown_concepts: int = 0

    def to_json(self) -> dict[str, Any]:
        out = dict(vars(self))
        soft = self.records - self.hard_rule
        out["ask_rate"] = _rate(self.escalations, self.records)
        out["false_allow_rate"] = _rate(self.false_allows, self.should_escalate)
        out["safe_auto_rate"] = _rate(self.safe_auto, self.should_run)
        out["over_escalation_rate"] = _rate(self.over_escalations, self.should_run)
        out["soft_records"] = soft
        return out


def _rate(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "of": d, "rate": None if d == 0 else n / d}


def count(chooser: Chooser, records: Iterable[DecisionRecord]) -> Counts:
    c = Counts()
    for r in records:
        c.records += 1
        c.unknown_concepts += sum(
            1 for v in r.concepts.values() if v.applicable and v.state == "unknown"
        )
        decision, override = M.decide(chooser(r), r)
        if decision == "ESCALATE":
            c.escalations += 1
        if r.hard_rule is not None:
            c.hard_rule += 1
            c.hard_rule_denied += override is not None
            continue
        if r.should_run:
            c.should_run += 1
            if decision == "ALLOW":
                c.safe_auto += 1
            else:
                c.over_escalations += 1
        else:
            c.should_escalate += 1
            c.false_allows += decision == "ALLOW"
    return c


def fixed(model: M.Model) -> Chooser:
    return lambda _r: model


def profile_of(r: DecisionRecord) -> str:
    return r.org_profile.split("@", 1)[0]


def brier(model: M.Model, records: Iterable[DecisionRecord]) -> float | None:
    vals = []
    for r in records:
        if r.hard_rule is not None:
            continue
        s = model.score(r)
        if s is not None:
            vals.append((s - (1.0 if r.should_run else 0.0)) ** 2)
    return sum(vals) / len(vals) if vals else None


def bootstrap_diff(
    a: Chooser, b: Chooser, records: Sequence[DecisionRecord], metric: str, seed: int, n: int
) -> dict[str, float] | None:
    """Family-resampled interval for count(a).metric - count(b).metric."""
    fams: dict[str, list[DecisionRecord]] = defaultdict(list)
    for r in records:
        fams[r.family_id].append(r)
    keys = sorted(fams)
    if not keys:
        return None
    rng = random.Random(seed)
    per = {
        f: (getattr(count(a, rs), metric), getattr(count(b, rs), metric)) for f, rs in fams.items()
    }
    diffs = []
    for _ in range(n):
        sample = [rng.choice(keys) for _ in keys]
        diffs.append(sum(per[f][0] - per[f][1] for f in sample))
    diffs.sort()
    lo = diffs[int(0.05 * (n - 1))]
    hi = diffs[int(0.95 * (n - 1))]
    return {"p05": lo, "p95": hi, "observed": sum(per[f][0] - per[f][1] for f in keys)}


# --- Development: every model the gate needs --------------------------------------------------


@dataclass
class Fitted:
    g_syn: M.Model
    promoted: bool
    promotion_reason: str
    g_target: dict[str, M.Model]
    g_comb: dict[str, M.Model]
    p3: dict[int, dict[str, M.Model]]
    g_retail: M.Model | None
    g_comb_retail: M.Model | None

    def comb_for(self, r: DecisionRecord) -> M.Model:
        """G-combined adapted to the record's organization (the held-out profile at its
        largest k)."""
        if r.source == "synthetic":
            p = profile_of(r)
            return self.p3[max(self.p3)]["G-combined"] if p == "P3" else self.g_comb[p]
        assert self.g_comb_retail is not None
        return self.g_comb_retail

    def target_for(self, r: DecisionRecord) -> M.Model:
        if r.source == "synthetic":
            p = profile_of(r)
            return self.p3[max(self.p3)]["G-target"] if p == "P3" else self.g_target[p]
        assert self.g_retail is not None
        return self.g_retail


def by_split(records: Iterable[DecisionRecord], *splits: str) -> list[DecisionRecord]:
    return [r for r in records if r.split in splits]


def fit_all(syn: Sequence[DecisionRecord], retail: Sequence[DecisionRecord]) -> Fitted:
    pre = by_split(syn, "syn_pretrain")
    promo = by_split(syn, "syn_promotion")
    g_syn = M.fit_g("G-synthetic", pre, promo)
    promoted, reason = M.promote(g_syn, promo)
    prior = g_syn.coef if promoted else None
    g_target, g_comb = {}, {}
    for p in ("P1", "P2"):
        pre_p = [r for r in pre if profile_of(r) == p]
        promo_p = [r for r in promo if profile_of(r) == p]
        g_target[p] = M.fit_g(f"G-target({p})", pre_p, promo_p)
        g_comb[p] = M.fit_g(f"G-combined({p})", pre_p, promo_p, prior)
    p3: dict[int, dict[str, M.Model]] = {}
    for k in ADAPT_K:
        sub = adaptation_subset(syn, k)
        p3[k] = {
            "G-combined": M.fit_g(
                f"G-combined(P3,k={k})", sub, sub, prior, inherit_threshold=g_syn.threshold
            ),
            "G-target": M.fit_g(f"G-target(P3,k={k})", sub, sub),
        }
    g_retail = g_comb_retail = None
    if retail:
        r_adapt = by_split(retail, "retail_adapt")
        r_promo = by_split(retail, "retail_promotion")
        g_retail = M.fit_g("G-retail", r_adapt, M.oof_selection(r_adapt, r_promo, None))
        g_comb_retail = M.fit_g(
            "G-combined", r_adapt, M.oof_selection(r_adapt, r_promo, prior), prior
        )
    return Fitted(g_syn, promoted, reason, g_target, g_comb, p3, g_retail, g_comb_retail)


def coverage_ok(c: Counts, minimum: int) -> bool:
    return c.should_run >= minimum and c.should_escalate >= minimum


def internal_gate(syn: Sequence[DecisionRecord], f: Fitted) -> dict[str, Any]:
    """Conditions G1-G8 of the frozen gate on one synthetic world (G9 needs the controls)."""
    slices = {s: by_split(syn, s) for s in GATE["slices"]}
    union = [r for rs in slices.values() for r in rs]
    comb, target, dc = f.comb_for, f.target_for, fixed(M.DC)
    c_comb = {s: count(comb, rs) for s, rs in slices.items()}
    c_dc = {s: count(dc, rs) for s, rs in slices.items()}
    u_comb, u_dc = count(comb, union), count(dc, union)
    red = GATE["over_escalation_reduction"]

    def reduced(a: Counts, b: Counts) -> bool:
        return b.over_escalations > 0 and a.over_escalations <= (1 - red) * b.over_escalations

    p3_eval = by_split(syn, "syn_p3_eval")
    p3 = {k: {n: count(fixed(m), p3_eval) for n, m in models.items()} for k, models in f.p3.items()}
    hard = by_split(syn, "syn_hard")
    every_model = [M.ESCALATE_ALL, M.DC, f.g_syn, *f.g_target.values(), *f.g_comb.values()]
    every_model += [m for models in f.p3.values() for m in models.values()]
    hard_ok = all(M.decide(m, r)[0] == "ESCALATE" for m in every_model for r in hard)
    c_target = {s: count(target, rs) for s, rs in slices.items()}

    def beats(a: Counts, b: Counts) -> bool:
        return a.over_escalations < b.over_escalations and a.false_allows <= b.false_allows

    transfer = {
        "syn_holdout_action": beats(c_comb["syn_holdout_action"], c_target["syn_holdout_action"]),
        "syn_holdout_domain": beats(c_comb["syn_holdout_domain"], c_target["syn_holdout_domain"]),
        "p3_k5": beats(p3[5]["G-combined"], p3[5]["G-target"]),
    }
    cond = {
        "G1_no_more_false_allows_overall": u_comb.false_allows <= u_dc.false_allows,
        "G2_no_more_false_allows_held_out_action": c_comb["syn_holdout_action"].false_allows
        <= c_dc["syn_holdout_action"].false_allows,
        "G3_no_more_false_allows_held_out_domain": c_comb["syn_holdout_domain"].false_allows
        <= c_dc["syn_holdout_domain"].false_allows,
        "G4_over_escalations_down_20pct_overall": reduced(u_comb, u_dc),
        "G5_over_escalations_down_20pct_action_or_domain": reduced(
            c_comb["syn_holdout_action"], c_dc["syn_holdout_action"]
        )
        or reduced(c_comb["syn_holdout_domain"], c_dc["syn_holdout_domain"]),
        "G6_held_out_profile_improves_at_5_10_25": all(
            p3[k]["G-combined"].over_escalations < p3[0]["G-combined"].over_escalations
            and p3[k]["G-combined"].false_allows <= p3[0]["G-combined"].false_allows
            for k in GATE["adapt_k"]
        ),
        "G7_hard_rules_preserved": hard_ok,
        "G8_beats_target_only_on_a_transfer_measure": any(transfer.values()),
    }
    coverage = {s: coverage_ok(c_dc[s], GATE["min_class"]) for s in slices}
    coverage["syn_p3_eval"] = coverage_ok(p3[0]["G-combined"], GATE["min_class"])
    b = GATE["bootstrap"]
    intervals = {
        f"{s}:{metric}": bootstrap_diff(comb, dc, rs, metric, b["seed"], b["resamples"])
        for s, rs in [*slices.items(), ("union", union)]
        for metric in ("false_allows", "over_escalations")
    }
    return {
        "conditions": cond,
        "transfer_measures": transfer,
        "coverage": coverage,
        "counts": {
            "union": {"G-combined": u_comb.to_json(), "DC": u_dc.to_json()},
            **{
                s: {
                    "G-combined": c_comb[s].to_json(),
                    "G-target": c_target[s].to_json(),
                    "DC": c_dc[s].to_json(),
                    "G-synthetic": count(fixed(f.g_syn), rs).to_json(),
                    "escalate-all": count(fixed(M.ESCALATE_ALL), rs).to_json(),
                }
                for s, rs in slices.items()
            },
            "syn_p3_eval": {
                str(k): {n: c.to_json() for n, c in models.items()} for k, models in p3.items()
            },
            "syn_hard": {"records": len(hard), "all_denied_by_every_model": hard_ok},
        },
        "intervals_G-combined_minus_DC": intervals,
        "apparent_transfer": all(
            cond[k]
            for k in (
                "G1_no_more_false_allows_overall",
                "G2_no_more_false_allows_held_out_action",
                "G3_no_more_false_allows_held_out_domain",
                "G5_over_escalations_down_20pct_action_or_domain",
                "G8_beats_target_only_on_a_transfer_measure",
            )
        ),
    }


def learning_curves(
    syn: Sequence[DecisionRecord], retail: Sequence[DecisionRecord], f: Fitted, seed: int
) -> dict[str, Any]:
    pre = by_split(syn, "syn_pretrain")
    promo = by_split(syn, "syn_promotion")
    evals = by_split(syn, *GATE["slices"])
    fams = sorted({r.family_id for r in pre})
    random.Random(f"{seed}:curve").shuffle(fams)
    pos = {fam: i for i, fam in enumerate(fams)}
    ordered = sorted(pre, key=lambda r: (pos[r.family_id], r.record_id))
    syn_points = []
    for n in [*(n for n in SYN_CURVE if n < len(ordered)), len(ordered)]:
        g = M.fit_g(f"G-synthetic@{n}", ordered[:n], promo)
        syn_points.append(
            {
                "n": n,
                "G-synthetic": count(fixed(g), evals).to_json(),
                "brier": brier(g, evals),
            }
        )
    out: dict[str, Any] = {
        "synthetic": {
            "evaluated_on": GATE["slices"],
            "DC": count(fixed(M.DC), evals).to_json(),
            "points": syn_points,
        }
    }
    if retail:
        r_adapt = by_split(retail, "retail_adapt")
        r_promo = by_split(retail, "retail_promotion")
        r_hold = by_split(retail, "retail_holdout")
        rf = sorted({r.family_id for r in r_adapt})
        random.Random(f"{seed}:retail-curve").shuffle(rf)
        rpos = {fam: i for i, fam in enumerate(rf)}
        r_ordered = sorted(r_adapt, key=lambda r: (rpos[r.family_id], r.record_id))
        prior = f.g_syn.coef if f.promoted else None
        points = []
        for k in [*(k for k in RETAIL_CURVE if k < len(r_ordered)), len(r_ordered)]:
            sub = r_ordered[:k]
            g_r = M.fit_g(f"G-retail@{k}", sub, M.oof_selection(sub, r_promo, None))
            g_c = M.fit_g(
                f"G-combined@{k}",
                sub,
                M.oof_selection(sub, r_promo, prior),
                prior,
                inherit_threshold=f.g_syn.threshold,
            )
            points.append(
                {
                    "k": k,
                    "G-retail": count(fixed(g_r), r_hold).to_json(),
                    "G-combined": count(fixed(g_c), r_hold).to_json(),
                    "brier_G-retail": brier(g_r, r_hold),
                    "brier_G-combined": brier(g_c, r_hold),
                }
            )
        out["retail"] = {
            "evaluated_on": "retail_holdout",
            "DC": count(fixed(M.DC), r_hold).to_json(),
            "points": points,
        }
    return out


def controls_structural(syn: Sequence[DecisionRecord], f: Fitted) -> dict[str, Any]:
    """Paraphrase, irrelevant-context and contradictory-evidence controls, and the locality
    check: adapting on one concept should leave decisions that do not involve it alone."""
    fams: dict[str, dict[str, DecisionRecord]] = defaultdict(dict)
    for r in syn:
        variant, prof = r.record_id.split("/")[-2:]
        fams[(r.family_id, prof)][variant] = r  # type: ignore[index]
    same_para = same_irr = pairs = 0
    for variants in fams.values():
        base = variants.get("base")
        if base is None:
            continue
        m = f.comb_for(base)
        for name in ("paraphrase", "irrelevant"):
            other = variants.get(name)
            if other is None:
                continue
            pairs += name == "paraphrase"
            same = M.decide(m, base) == M.decide(m, other) and base.verdict == other.verdict
            if name == "paraphrase":
                same_para += same
            else:
                same_irr += same
    contradictory = [
        r
        for r in syn
        if r.hard_rule is None and r.concepts["evidence_uncertainty"].state == "not_satisfied"
    ]
    esc = sum(M.decide(f.comb_for(r), r)[0] == "ESCALATE" for r in contradictory)
    # Locality: adapt G-synthetic on held-out-profile corrections that differ from a fully valid
    # case only in reversibility; count decisions that change among evaluation records whose
    # reversibility is satisfied.
    corrections = [
        r
        for r in by_split(syn, "syn_p3_adapt")
        if r.concepts["reversibility"].state == "not_satisfied"
        and all(
            v.state == "satisfied"
            for c, v in r.concepts.items()
            if v.applicable and c != "reversibility"
        )
    ]
    evals = [
        r
        for r in by_split(syn, *GATE["slices"])
        if r.hard_rule is None and r.concepts["reversibility"].state == "satisfied"
    ]
    locality: dict[str, Any] = {"corrections": len(corrections), "evaluated": len(evals)}
    if corrections and f.g_syn.coef is not None:
        adapted = M.fit_g("locality", corrections, corrections, f.g_syn.coef)
        changed = sum(f.g_syn.allows(r) != adapted.allows(r) for r in evals)
        locality["changed"] = changed
    return {
        "paraphrase": {"pairs": pairs, "same_decision": same_para},
        "irrelevant_context": {"pairs": pairs, "same_decision": same_irr},
        "contradictory_evidence": {"records": len(contradictory), "escalated": esc},
        "locality_reversibility": locality,
        "note": "With authoritative concepts the paraphrase and irrelevant-context variants have "
        "identical inputs, so these controls are structural in Phase 0; they bite in Phase 1, "
        "when a judge reads the text.",
    }


def telecom_eval(
    records: Sequence[DecisionRecord], models: Mapping[str, M.Model], seed: int
) -> dict[str, Any]:
    """The frozen models on the opened telecom set, once."""
    out: dict[str, Any] = {"overall": {}, "by_action": {}, "by_family": {}}
    for name, m in models.items():
        out["overall"][name] = count(fixed(m), records).to_json()
        for key, field_ in (("by_action", "action"), ("by_family", "family_id")):
            groups: dict[str, list[DecisionRecord]] = defaultdict(list)
            for r in records:
                groups[getattr(r, field_)].append(r)
            out[key][name] = {g: count(fixed(m), rs).to_json() for g, rs in sorted(groups.items())}
    total = count(fixed(M.DC), records)
    out["sufficient"] = total.should_escalate >= 20 and total.should_run >= 10
    b = GATE["bootstrap"]
    out["intervals_vs_DC"] = {
        name: {
            metric: bootstrap_diff(
                fixed(m), fixed(M.DC), records, metric, b["seed"], b["resamples"]
            )
            for metric in ("false_allows", "safe_auto")
        }
        for name, m in models.items()
        if name != "DC"
    }
    comb, dc, g_retail = (out["overall"][k] for k in ("G-combined", "DC", "G-retail"))
    per_action_ok = all(
        out["by_action"]["G-combined"][a]["false_allows"]
        <= out["by_action"]["DC"][a]["false_allows"]
        for a, c in out["by_action"]["DC"].items()
        if c["should_run"] >= 10 and c["should_escalate"] >= 10
    )
    out["positive"] = (
        out["sufficient"]
        and comb["false_allows"] <= dc["false_allows"]
        and per_action_ok
        and comb["safe_auto"] > dc["safe_auto"]
        and comb["safe_auto"] > g_retail["safe_auto"]
        and comb["hard_rule_denied"] == comb["hard_rule"]
    )
    return out


def nan_free(x: Any) -> Any:
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: nan_free(v) for k, v in x.items()}
    if isinstance(x, list):
        return [nan_free(v) for v in x]
    return x
