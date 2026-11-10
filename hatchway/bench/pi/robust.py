"""The robustness pack (`RFC-robustness.md`): R1 replication, R2 random rules, R3 audit pricing,
R4 specific certified exceptions, R5 imperfect perception. Zero spend; Phase A's code, cases and
results are reused unchanged.

    python -m hatchway.bench.pi.robust generate   # robustness/cases.jsonl.gz + manifest (τ² data)
    python -m hatchway.bench.pi.robust evaluate   # results/robustness.json, written once
    python -m hatchway.bench.pi.robust report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hatchway.bench.drb.v2.risk import cp_ucb
from hatchway.bench.pi import cases as C
from hatchway.bench.pi import evaluate as E
from hatchway.bench.pi import induce as S
from hatchway.bench.pi.worlds import BY_NAME, CANCEL, EXCHANGE, RETURN, WORLDS, World

FRESH_SEED = 20261026
RULE_SEED = 20261026
DIR = "robustness"
CASES_FILE = f"{DIR}/cases.jsonl.gz"
MANIFEST = f"{DIR}/manifest.json"
RESULT_FILE = "results/robustness.json"
CODE_FILES = ("cases.py", "worlds.py", "induce.py", "evaluate.py", "robust.py")

N_ESCALATE = 100
N_RELAX = 20
MIN_TRAIN_FAMILIES = 25
MAX_TRIGGER_SHARE = 0.25
R2_K = (1, 2, 5, 10, 20)
R3_K = (10, 20, 40)
R3_RATES = (0.02, 0.05, 0.10, 0.25, 0.50, 1.00)
R3_MIN_FAMILIES = 40
R3_TOP_LITERALS = 3
R3_CONTROL_RATE = 0.25
R4_K = (5, 10, 20)
R5_K = (5, 10, 20)
R5_RATES = (0.0, 0.02, 0.05, 0.10)
R5_RANDOM_RULES = 30
REPLICATES = 10
CERT_UCB = 0.10
ACTIONS = (RETURN, EXCHANGE, CANCEL)
NUMERIC = ("amount", "order_total", "n_items", "user_orders")
MONEY = ("amount", "order_total", "price_difference")


# --- Split -------------------------------------------------------------------------------------


def split3(family_id: str) -> str:
    h = int(hashlib.sha256(f"{FRESH_SEED}:split3:{family_id}".encode()).hexdigest()[:8], 16) % 5
    return "train" if h < 2 else ("cert" if h == 2 else "test")


def masks(p: E.Prepared) -> dict[str, np.ndarray]:
    s = np.array([split3(f) for f in p.family], dtype=object)
    return {name: s == name for name in ("train", "cert", "test")}


# --- R2 rule grammar ---------------------------------------------------------------------------


def cond_holds(cond: Mapping[str, Any], facts: Mapping[str, Any]) -> bool:
    if cond["op"] == "gt":
        return float(facts[cond["fact"]]) > cond["value"]
    if cond["op"] == "has":
        return cond["value"] in facts["products"]
    return str(facts[cond["fact"]]) == cond["value"]


def rule_world(spec: Mapping[str, Any]) -> World:
    action, conds, kind = spec["action"], spec["conds"], spec["kind"]

    def scope(c: C.Case) -> bool:
        return (action is None or c.action == action) and all(cond_holds(x, c.facts) for x in conds)

    def hidden(c: C.Case) -> str | None:
        if kind == "escalate":
            return "ASK" if c.decision == "ALLOW" and scope(c) else None
        if c.failing() == {"CONFIRMATION_MISSING": "ask"} and scope(c):
            return "ALLOW"
        return None

    return World(spec["name"], "hidden", describe_spec(spec), hidden=hidden)


def describe_spec(spec: Mapping[str, Any]) -> str:
    parts = [f"action = {spec['action']}"] if spec["action"] else []
    for x in spec["conds"]:
        op = {"gt": ">", "eq": "=", "has": "includes"}[x["op"]]
        parts.append(f"{x['fact']} {op} {x['value']}")
    verb = "escalate" if spec["kind"] == "escalate" else "allow without confirmation"
    return f"{verb} if " + " and ".join(parts)


def _round(fact: str, x: float) -> float:
    return float(round(x / 50) * 50) if fact in MONEY else float(round(x))


def _condition(
    rng: random.Random, pool: Sequence[C.Case], states: Sequence[str], action: str | None
):
    kinds = ["num", "payment", "state", "product"]
    kind = rng.choice(kinds)
    if kind == "num":
        facts = list(NUMERIC) + (["price_difference"] if action == EXCHANGE else [])
        fact = rng.choice(facts)
        values = sorted(float(c.facts[fact]) for c in pool)
        q = rng.uniform(0.6, 0.95)
        t = _round(fact, values[min(len(values) - 1, int(q * len(values)))])
        return {"fact": fact, "op": "gt", "value": t}
    if kind == "payment":
        v = rng.choice(sorted({str(c.facts["payment_source"]) for c in pool}))
        return {"fact": "payment_source", "op": "eq", "value": v}
    if kind == "state":
        return {"fact": "user_state", "op": "eq", "value": rng.choice(list(states))}
    v = rng.choice(sorted({p for c in pool for p in c.facts["products"]}))
    return {"fact": "products", "op": "has", "value": v}


def sample_rules(cases: Sequence[C.Case]) -> list[dict[str, Any]]:
    """The preregistered grammar and filter; the first N_ESCALATE and N_RELAX rules kept."""
    rng = random.Random(RULE_SEED)
    states = [s for s, _ in Counter(str(c.facts["user_state"]) for c in cases).most_common(10)]
    split = {c.family_id: split3(c.family_id) for c in cases}
    kept: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    for kind, n in (("escalate", N_ESCALATE), ("relax", N_RELAX)):
        got = attempts = 0
        while got < n and attempts < 5000:
            attempts += 1
            action = rng.choice(ACTIONS) if rng.random() < 0.7 else None
            if kind == "escalate":
                base = [c for c in cases if c.decision == "ALLOW"]
            else:
                base = [c for c in cases if c.failing() == {"CONFIRMATION_MISSING": "ask"}]
            pool = [c for c in base if action is None or c.action == action]
            if not pool:
                continue
            conds = [
                _condition(rng, pool, states, action) for _ in range(1 if rng.random() < 0.5 else 2)
            ]
            if len({(x["fact"], x["op"]) for x in conds}) < len(conds):
                continue
            spec = {
                "name": f"R2-{kind[0].upper()}{got + 1:03d}",
                "kind": kind,
                "action": action,
                "conds": conds,
            }
            w = rule_world(spec)
            trig = [c for c in pool if w.triggers(c)]
            fams = {c.family_id for c in trig if split[c.family_id] == "train"}
            ids = frozenset(c.case_id for c in trig)
            if (
                len(fams) < MIN_TRAIN_FAMILIES
                or len(trig) > MAX_TRIGGER_SHARE * len(pool)
                or ids in seen
            ):
                continue
            seen.add(ids)
            spec["trigger_cases"] = len(trig)
            spec["trigger_share"] = round(len(trig) / len(pool), 4)
            spec["train_families"] = len(fams)
            kept.append(spec)
            got += 1
    return kept


def rule_type(spec: Mapping[str, Any]) -> str:
    kinds = "+".join(sorted({"num" if x["op"] == "gt" else x["fact"] for x in spec["conds"]}))
    scope = "one action" if spec["action"] else "any action"
    return f"{spec['kind']} · {len(spec['conds'])} cond ({kinds}) · {scope}"


# --- Sweeps ------------------------------------------------------------------------------------


def _summ(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return E.summarize(runs)


def sweep_s(p: E.Prepared, m: dict[str, np.ndarray], ks: Sequence[int], tag: str) -> dict[str, Any]:
    """Arm S, clean labels, on the three-way split (train and test; certification unused)."""
    test_idx = np.flatnonzero(m["test"])
    test_cols = p.subset(test_idx.tolist())
    by_k = {}
    for k in ks:
        runs = [_run_s(p, k, r, m["train"], test_idx, test_cols, tag) for r in range(REPLICATES)]
        by_k[str(k)] = _summ(runs)
    return {"by_k": by_k, "k_star": E.k_star(by_k)}


def _run_s(
    p: E.Prepared,
    k: int,
    rep: int,
    train: np.ndarray,
    test_idx: np.ndarray,
    test_cols: S.Columns,
    tag: str,
) -> dict[str, Any]:
    rng = random.Random(f"{FRESH_SEED}:{tag}:{p.world.name}:{k}:{rep}")
    sample = E.training_sample(p, train, k, rng)
    if sample is None:
        return {"available": False}
    ix = np.array(sample, dtype=int)
    learned = S.learn(p.subset(sample), p.r0[ix], p.relaxable[ix], p.truth[ix])
    decision = learned.decide(test_cols, p.r0[test_idx], p.relaxable[test_idx])
    return {
        "available": True,
        "labelled": len(sample),
        "labelled_triggering": int(p.trigger[ix].sum()),
        "rules": [r.to_json() for r in learned.rules],
        "n_literals": learned.n_literals,
        **E.scores(p, test_idx, decision),
    }


# --- R3 audits ---------------------------------------------------------------------------------


def audited(
    p: E.Prepared, sample: list[int], rate: float, strategy: str, rng: random.Random, y: np.ndarray
) -> list[int]:
    """Positions (into `sample`) the learner sees: every escalated case plus `b` audits."""
    escalated = [j for j, i in enumerate(sample) if p.r0[i]]
    allowed = [j for j, i in enumerate(sample) if not p.r0[i]]
    b = round(rate * len(allowed))
    if strategy == "random" or b == 0:
        return sorted(escalated + rng.sample(allowed, b))
    first = rng.sample(allowed, b // 2)
    rest = [j for j in allowed if j not in set(first)]
    second: list[int] = []
    pos = [j for j in first if y[j]]
    if pos:
        cols = p.subset([sample[j] for j in allowed])
        where = {j: n for n, j in enumerate(allowed)}
        lits = S.candidate_literals(cols)
        matrix = np.column_stack([lit.mask(cols) for lit in lits])
        f_rows = np.array([where[j] for j in first])
        n = matrix[f_rows].sum(axis=0)
        k = matrix[np.array([where[j] for j in pos])].sum(axis=0)
        tail = S.log_tail_table(len(first), len(pos))
        score = np.where(k >= 1, tail[n, k], np.inf)
        top = np.argsort(score, kind="stable")[:R3_TOP_LITERALS]
        top = [t for t in top if np.isfinite(score[t])]
        if top:
            covered = matrix[:, top].any(axis=1)
            cand = [j for j in rest if covered[where[j]]]
            second = rng.sample(cand, min(b - len(first), len(cand)))
    left = [j for j in rest if j not in set(second)]
    second += rng.sample(left, min(b - len(first) - len(second), len(left)))
    return sorted(escalated + first + second)


def run_audit(
    p: E.Prepared,
    m: dict[str, np.ndarray],
    k: int,
    rate: float,
    strategy: str,
    rep: int,
    test_idx: np.ndarray,
    test_cols: S.Columns,
    shuffled: bool = False,
) -> dict[str, Any]:
    rng = random.Random(f"{FRESH_SEED}:R3:{p.world.name}:{k}:{rate}:{strategy}:{shuffled}:{rep}")
    sample = E.training_sample(p, m["train"], k, rng)
    if sample is None:
        return {"available": False}
    y = p.truth[np.array(sample)].copy()
    if shuffled:
        order = list(range(len(sample)))
        rng.shuffle(order)
        y = y[order]
    seen = audited(p, sample, rate, strategy, rng, y)
    idx = [sample[j] for j in seen]
    ix = np.array(idx, dtype=int)
    learned = S.learn(p.subset(idx), p.r0[ix], p.relaxable[ix], y[seen])
    decision = learned.decide(test_cols, p.r0[test_idx], p.relaxable[test_idx])
    return {
        "available": True,
        "labelled": len(idx),
        "labelled_triggering": int(p.trigger[ix].sum()),
        "rules": [r.to_json() for r in learned.rules],
        "n_literals": learned.n_literals,
        **E.scores(p, test_idx, decision),
    }


def needed_rate(by_rate: Mapping[str, Mapping[str, Any]]) -> float | None:
    for rate in R3_RATES:
        s = by_rate.get(str(rate), {})
        if s.get("available") and s["recovery_rate"] >= E.K_STAR_RATE:
            return rate
    return None


# --- R4 specific, certified exceptions ---------------------------------------------------------


def specialize(rule: S.Rule, cols: S.Columns, positives: np.ndarray) -> S.Rule:
    """The conjunction of every candidate literal true for all the positives the rule covers
    (tightest numeric bound each way), with the rule's own literals."""
    covered = positives & rule.mask(cols)
    if not covered.any():
        return rule
    keep: dict[tuple[str, str], S.Literal] = {}
    extra: set[S.Literal] = set(rule.literals)
    for lit in S.candidate_literals(cols):
        if not lit.mask(cols)[covered].all():
            continue
        if lit.op == "gt":
            cur = keep.get((lit.fact, "gt"))
            if cur is None or lit.value > cur.value:
                keep[(lit.fact, "gt")] = lit
        elif lit.op == "le":
            cur = keep.get((lit.fact, "le"))
            if cur is None or lit.value < cur.value:
                keep[(lit.fact, "le")] = lit
        else:
            extra.add(lit)
    lits = tuple(sorted(extra | set(keep.values())))
    return S.Rule(rule.kind, lits, rule.positives, rule.covered, rule.log_p_adjusted)


def certify(
    rule: S.Rule,
    cols: S.Columns,
    r0: np.ndarray,
    relaxable: np.ndarray,
    truth: np.ndarray,
    family: np.ndarray,
) -> tuple[bool, dict[str, Any]]:
    fires = rule.mask(cols) & r0 & relaxable
    eligible = set(family[fires].tolist())
    failing = set(family[fires & truth].tolist())
    ucb = cp_ucb(len(failing), len(eligible))
    info = {"eligible_families": len(eligible), "failing_families": len(failing), "ucb": ucb}
    return bool(eligible) and ucb <= CERT_UCB, info


def certified(
    learned: S.Learned, train_cols: S.Columns, positives: np.ndarray, cert: tuple
) -> tuple[S.Learned, list[dict[str, Any]]]:
    rules: list[S.Rule] = list(learned.escalate_rules)
    log = []
    for r in learned.allow_rules:
        spec = specialize(r, train_cols, positives)
        ok, info = certify(spec, *cert)
        log.append({"rule": spec.describe(), "certified": ok, **info})
        if ok:
            rules.append(spec)
    return S.Learned(rules, learned.n_literals), log


def fired_failures(p: E.Prepared, test_idx: np.ndarray, decision: np.ndarray) -> tuple[int, int]:
    """Test families where an exception allowed a case the starting policy escalated, and those
    among them where such a case is one the truth escalates."""
    r0 = p.r0[test_idx]
    fired = r0 & ~decision
    fam = p.family[test_idx]
    return len(set(fam[fired].tolist())), len(set(fam[fired & p.truth[test_idx]].tolist()))


def run_cert(
    p: E.Prepared,
    m: dict[str, np.ndarray],
    k: int,
    rep: int,
    test_idx: np.ndarray,
    test_cols: S.Columns,
    cert_cols: S.Columns,
    cert_idx: np.ndarray,
) -> dict[str, Any]:
    rng = random.Random(f"{FRESH_SEED}:R4:{p.world.name}:{k}:{rep}")
    sample = E.training_sample(p, m["train"], k, rng)
    if sample is None:
        return {"available": False}
    ix = np.array(sample, dtype=int)
    cols = p.subset(sample)
    y = p.truth[ix]
    learned = S.learn(cols, p.r0[ix], p.relaxable[ix], y)
    positives = p.relaxable[ix] & ~y
    cert = (cert_cols, p.r0[cert_idx], p.relaxable[cert_idx], p.truth[cert_idx], p.family[cert_idx])
    cert_learned, log = certified(learned, cols, positives, cert)
    out: dict[str, Any] = {"available": True, "certification": log}
    for arm, model in (("S", learned), ("S-cert", cert_learned)):
        decision = model.decide(test_cols, p.r0[test_idx], p.relaxable[test_idx])
        fired, failed = fired_failures(p, test_idx, decision)
        out[arm] = {
            **E.scores(p, test_idx, decision),
            "fired_families": fired,
            "fired_failing": failed,
        }
    return out


def v2_certified() -> dict[str, Any]:
    """The v2 side check with S-cert: exceptions specialized on v2's development records,
    certified on its calibration pools, evaluated on its fresh slices (descriptive)."""
    from hatchway.bench.drb.evaluate import profile_of
    from hatchway.bench.drb.v2 import run as V2
    from hatchway.bench.pi import v2check as V

    dev = V2.development_pool(V2.v1_synthetic())
    fresh = V2.load_pools(V.V2_DIR, V2.FRESH_FILE)
    cal = V2.load_pools(V.V2_DIR, V2.CAL_FILE)
    sch = V.schema(
        [*dev, *(r for rs in fresh.values() for r in rs), *(r for rs in cal.values() for r in rs)]
    )
    models: dict[str, S.Learned] = {}
    logs: dict[str, Any] = {}
    for prof in ("P1", "P2"):
        recs = [r for r in dev if profile_of(r) == prof]
        cols, r0, relaxable, truth = V._arrays(recs, sch)
        learned = S.learn(cols, r0, relaxable, truth)
        pool = cal[f"cal_{prof}"]
        ccols, cr0, crel, ctruth = V._arrays(pool, sch)
        fam = np.array([r.family_id for r in pool], dtype=object)
        models[prof], logs[prof] = certified(
            learned, cols, relaxable & ~truth, (ccols, cr0, crel, ctruth, fam)
        )
    everything = [r for s in V.SLICES for r in fresh[s]]
    slices = {
        s: V.by_profile(models, recs, sch)
        for s, recs in (*((s, fresh[s]) for s in V.SLICES), ("overall", everything))
    }
    return {"certification": logs, "slices": slices}


# --- R5 perception noise -----------------------------------------------------------------------


def noisy_facts(cases: Sequence[C.Case], rate: float) -> list[dict[str, Any]]:
    if rate == 0:
        return [dict(c.facts) for c in cases]
    cats = {f: sorted({str(c.facts[f]) for c in cases}) for f in S.CAT_FACTS}
    nums = {f: [float(c.facts[f]) for c in cases] for f in S.NUM_FACTS}
    prods = [c.facts["products"] for c in cases]
    out = []
    for c in cases:
        rng = random.Random(f"{FRESH_SEED}:noise:{rate}:{c.case_id}")
        f = dict(c.facts)
        for b in S.BOOL_FACTS:
            if rng.random() < rate:
                f[b] = not f[b]
        for cat in S.CAT_FACTS:
            if rng.random() < rate:
                f[cat] = rng.choice([v for v in cats[cat] if v != str(f[cat])] or cats[cat])
        for n in S.NUM_FACTS:
            if rng.random() < rate:
                f[n] = rng.choice(nums[n])
        if rng.random() < rate:
            f["products"] = rng.choice(prods)
        out.append(f)
    return out


class NoisyPrepared(E.Prepared):
    """True starting policy and truth; the learner sees (and is applied to) noisy facts."""

    def __init__(self, world: World, cases: Sequence[C.Case], facts: Sequence[Mapping[str, Any]]):
        super().__init__(world, cases)
        self.noisy = list(facts)

    def subset(self, idx: Sequence[int]) -> S.Columns:
        return S.Columns([self.noisy[i] for i in idx], [self.cases[i].text for i in idx])


# --- Evaluation --------------------------------------------------------------------------------


def _k_steps(k: int | None) -> int:
    grid = list(E.K_GRID)
    return grid.index(k) if k is not None else len(grid)


def r1(cases: Sequence[C.Case], phase_a: Mapping[str, Any]) -> dict[str, Any]:
    from hatchway.bench.pi import run as RUN

    worlds = E.run_all(cases)
    label, detail = RUN.outcome(worlds)
    orig = {w["world"]: w["arms"]["S"]["clean"]["k_star"] for w in phase_a["worlds"]}
    fresh = {w["world"]: w["arms"]["S"]["clean"]["k_star"] for w in worlds}
    within = {n: abs(_k_steps(fresh[n]) - _k_steps(orig[n])) <= 1 for n in orig}
    passed = detail["checks"]["A1_shuffled_control"] and detail["checks"]["A3_discriminating"]
    passed = passed and sum(within.values()) >= 11
    return {
        "passed": passed,
        "fresh_outcome": label,
        "fresh_checks": detail,
        "k_star_phase_a": orig,
        "k_star_fresh": fresh,
        "within_one_step": within,
        "worlds": worlds,
    }


def r2(cases: Sequence[C.Case], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for spec in rules:
        p = E.Prepared(rule_world(spec), cases)
        res = sweep_s(p, masks(p), R2_K, "R2")
        out[spec["name"]] = {
            **{k: v for k, v in spec.items() if k != "conds"},
            "conds": spec["conds"],
            "type": rule_type(spec),
            **res,
        }
    by_type: dict[str, dict[str, Any]] = {}
    for v in out.values():
        t = by_type.setdefault(v["type"], {"rules": 0, "k5": 0, "k10": 0, "k20": 0})
        t["rules"] += 1
        ks = v["k_star"]
        for lim in (5, 10, 20):
            t[f"k{lim}"] += ks is not None and ks <= lim
    return {"rules": out, "by_type": by_type}


def r3(cases: Sequence[C.Case], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    worlds = [
        rule_world(s)
        for s in rules
        if s["kind"] == "escalate" and s["train_families"] >= R3_MIN_FAMILIES
    ]
    worlds += [BY_NAME[n] for n in ("H1_LARGE_REFUND", "H3_REPEAT_CANCEL", "H4_UPCHARGE")]
    out: dict[str, Any] = {}
    cells = []
    control = []
    for w in worlds:
        p = E.Prepared(w, cases)
        m = masks(p)
        fams = len(set(p.family[m["train"] & p.trigger].tolist()))
        if fams < R3_MIN_FAMILIES:
            out[w.name] = {"available": False, "train_families": fams}
            continue
        test_idx = np.flatnonzero(m["test"])
        test_cols = p.subset(test_idx.tolist())
        res: dict[str, Any] = {"train_families": fams}
        for k in R3_K:
            row = {}
            for strategy in ("random", "targeted"):
                by_rate = {
                    str(rate): _summ(
                        [
                            run_audit(p, m, k, rate, strategy, r, test_idx, test_cols)
                            for r in range(REPLICATES)
                        ]
                    )
                    for rate in R3_RATES
                }
                row[strategy] = {"by_rate": by_rate, "needed_rate": needed_rate(by_rate)}
            ctrl = _summ(
                [
                    run_audit(
                        p, m, k, R3_CONTROL_RATE, "targeted", r, test_idx, test_cols, shuffled=True
                    )
                    for r in range(REPLICATES)
                ]
            )
            row["targeted_shuffled"] = ctrl
            control.append(ctrl)
            res[str(k)] = row
            cells.append((row["random"]["needed_rate"], row["targeted"]["needed_rate"]))
        out[w.name] = res
    reached = [(a, b) for a, b in cells if a is not None or b is not None]
    better = sum(1 for a, b in reached if b is not None and (a is None or b <= a / 2))
    runs = sum(c["replicates"] for c in control if c.get("available"))
    any_rule = sum(
        c["any_rule_rate"] * c["replicates"] for c in control if c.get("available")
    ) / max(runs, 1)
    passed = bool(reached) and better / len(reached) >= 0.5 and any_rule <= 0.05
    return {
        "passed": passed,
        "cells_reached": len(reached),
        "cells_targeted_at_most_half": better,
        "targeted_shuffled_any_rule_rate": any_rule,
        "worlds": out,
    }


def r4(cases: Sequence[C.Case], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    worlds = [BY_NAME["H6_SMALL_CANCEL_WAIVER"]] + [
        rule_world(s) for s in rules if s["kind"] == "relax"
    ]
    out: dict[str, Any] = {}
    pooled = {"S": [0, 0], "S-cert": [0, 0]}
    for w in worlds:
        p = E.Prepared(w, cases)
        m = masks(p)
        test_idx, cert_idx = np.flatnonzero(m["test"]), np.flatnonzero(m["cert"])
        test_cols, cert_cols = p.subset(test_idx.tolist()), p.subset(cert_idx.tolist())
        res = {}
        for k in R4_K:
            runs = [
                run_cert(p, m, k, r, test_idx, test_cols, cert_cols, cert_idx)
                for r in range(REPLICATES)
            ]
            ok = [r for r in runs if r["available"]]
            row: dict[str, Any] = {"available": bool(ok), "replicates": len(ok)}
            for arm in ("S", "S-cert"):
                if not ok:
                    continue
                fired = sum(r[arm]["fired_families"] for r in ok)
                failed = sum(r[arm]["fired_failing"] for r in ok)
                pooled[arm][0] += fired
                pooled[arm][1] += failed
                row[arm] = {
                    "catch_mean": float(
                        np.mean([r[arm]["catch"] for r in ok if r[arm]["catch"] is not None])
                    ),
                    "failing_families_mean": float(
                        np.mean([r[arm]["failing_families"] for r in ok])
                    ),
                    "false_allows_mean": float(np.mean([r[arm]["false_allows"] for r in ok])),
                    "fired_families": fired,
                    "fired_failing": failed,
                }
            if ok:
                row["certified_share"] = float(
                    np.mean([c["certified"] for r in ok for c in r["certification"]] or [0.0])
                )
                row["example_certification"] = ok[0]["certification"]
            res[str(k)] = row
        out[w.name] = {
            "description": w.description,
            "by_k": res,
            "R0": E.scores(p, test_idx, p.r0[test_idx]),
        }
    rate = {a: (v[1] / v[0] if v[0] else 0.0) for a, v in pooled.items()}
    passed = rate["S-cert"] <= CERT_UCB and rate["S"] > CERT_UCB
    return {
        "passed": passed,
        "pooled_fired": pooled,
        "pooled_failure_rate": rate,
        "worlds": out,
        "v2": v2_certified(),
    }


def r5(cases: Sequence[C.Case], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    regenerated = (
        list(WORLDS) + [rule_world(s) for s in rules if s["kind"] == "escalate"][:R5_RANDOM_RULES]
    )
    noisy = {rate: noisy_facts(cases, rate) for rate in R5_RATES}
    out: dict[str, Any] = {}
    for w in regenerated:
        res = {}
        for rate in R5_RATES:
            p = NoisyPrepared(w, cases, noisy[rate])
            res[str(rate)] = sweep_s(p, masks(p), R5_K, f"R5:{rate}")
        out[w.name] = res
    return {"worlds": out}


def code_hashes() -> dict[str, str]:
    here = Path(__file__).parent
    return {f: hashlib.sha256((here / f).read_bytes()).hexdigest() for f in CODE_FILES}


def cmd_generate(d: Path) -> dict[str, Any]:
    if (d / MANIFEST).exists():
        raise SystemExit("robustness cases already generated (written once)")
    cases = C.generate(seed=FRESH_SEED)
    sha = C.write_cases(d / CASES_FILE, cases)
    rules = sample_rules(cases)
    manifest = {
        "generator": C.GENERATOR,
        "seed": FRESH_SEED,
        "rule_seed": RULE_SEED,
        "dataset_sha256": sha,
        "cases": len(cases),
        "families": len({c.family_id for c in cases}),
        "split": dict(Counter(split3(f) for f in {c.family_id for c in cases})),
        "rules": rules,
        "code_sha256": code_hashes(),
    }
    (d / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def load(d: Path) -> tuple[list[C.Case], dict[str, Any]]:
    manifest = json.loads((d / MANIFEST).read_text())
    cases = C.read_cases(d / CASES_FILE)
    if C.dataset_sha256(cases) != manifest["dataset_sha256"]:
        raise SystemExit("the robustness cases do not match their manifest")
    return cases, manifest


def cmd_evaluate(d: Path) -> dict[str, Any]:
    if (d / RESULT_FILE).exists():
        raise SystemExit("robustness pack already evaluated once; results are written once")
    cases, manifest = load(d)
    if manifest["code_sha256"] != code_hashes():
        raise SystemExit("code changed since the robustness cases were generated")
    phase_a = json.loads((d / "results/phase-a.json").read_text())
    rules = manifest["rules"]
    result = {
        "dataset_sha256": manifest["dataset_sha256"],
        "code_sha256": code_hashes(),
        "spend_usd": 0.0,
        "external_calls": 0,
        "R1": r1(cases, phase_a),
        "R2": r2(cases, rules),
        "R3": r3(cases, rules),
        "R4": r4(cases, rules),
        "R5": r5(cases, rules),
    }
    path = d / RESULT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    from hatchway.bench.pi.run import EXPERIMENT

    ap = argparse.ArgumentParser(prog="python -m hatchway.bench.pi.robust")
    ap.add_argument("command", choices=("generate", "evaluate", "report"))
    ap.add_argument("--dir", type=Path, default=EXPERIMENT)
    a = ap.parse_args(argv)
    if a.command == "generate":
        m = cmd_generate(a.dir)
        print(m["cases"], m["families"], m["split"], len(m["rules"]), m["dataset_sha256"])
    elif a.command == "evaluate":
        r = cmd_evaluate(a.dir)
        print({k: r[k].get("passed") for k in ("R1", "R3", "R4")})
    else:
        from hatchway.bench.pi import robust_report

        print(robust_report.build(a.dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
