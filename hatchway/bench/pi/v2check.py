"""Descriptive side check: was the model type part of the decision-record benchmark v2 failure?

Each v2 organization's judgment is one crisp rule over two concepts (`profiles.json`), which a
logistic score with a threshold fits poorly. Here arm S starts from DC-score at threshold 1.0
(escalate unless every applicable concept is satisfied) and learns rules from the same records
v2 fitted on:

- P1 and P2: S fitted on that profile's v1 in-distribution development records, evaluated on
  the v2 fresh final, held-out-action and held-out-domain slices;
- P3: S fitted on the first k fresh P3 corrections (v2's preregistered order), evaluated on the
  fresh P3 evaluation set.

Facts are each concept's state (`not_applicable` when it does not apply), the action and the
domain. Hard-rule records always escalate and are never relaxed. The fresh holdout was already
used by v2, so these numbers are descriptive only and cannot change v2's outcome.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hatchway.bench.drb.evaluate import profile_of
from hatchway.bench.drb.schema import DecisionRecord
from hatchway.bench.drb.v2 import run as V2
from hatchway.bench.drb.v2.evaluate import p3_steps
from hatchway.bench.drb.v2.risk import cp_ucb, dc_score
from hatchway.bench.pi import induce as S

V2_DIR = Path(__file__).parents[3] / "experiments/2026-10-23-decision-record-benchmark-v2"
SLICES = ("fresh_final", "fresh_action", "fresh_domain")


def schema(records: Sequence[DecisionRecord]) -> S.Schema:
    concepts = sorted({c for r in records for c in r.concepts})
    return S.Schema(bools=(), cats=("action", "domain", *concepts), nums=())


def facts(r: DecisionRecord) -> dict[str, Any]:
    return {
        "action": r.action,
        "domain": r.domain,
        **{c: (v.state if v.applicable else "not_applicable") for c, v in r.concepts.items()},
    }


def _arrays(records: Sequence[DecisionRecord], sch: S.Schema):
    cols = S.Columns([facts(r) for r in records], None, sch)
    r0 = np.array([r.hard_rule is not None or dc_score(r) < 1.0 for r in records], dtype=bool)
    relaxable = np.array([r.hard_rule is None for r in records], dtype=bool) & r0
    truth = np.array([not r.should_run for r in records], dtype=bool)
    return cols, r0, relaxable, truth


def fit(records: Sequence[DecisionRecord], sch: S.Schema) -> S.Learned:
    cols, r0, relaxable, truth = _arrays(records, sch)
    return S.learn(cols, r0, relaxable, truth)


def decisions(
    learned: S.Learned | None, records: Sequence[DecisionRecord], sch: S.Schema
) -> tuple[np.ndarray, np.ndarray]:
    """(escalate, truth escalate) for each record; `learned=None` is the starting policy."""
    cols, r0, relaxable, truth = _arrays(records, sch)
    return (r0 if learned is None else learned.decide(cols, r0, relaxable)), truth


def counts(
    records: Sequence[DecisionRecord], decision: np.ndarray, truth: np.ndarray
) -> dict[str, Any]:
    """Counts over a whole slice: a family with records under both profiles counts once."""
    family = np.array([r.family_id for r in records], dtype=object)
    eligible = set(family[truth].tolist())
    failing = set(family[truth & ~decision].tolist())
    return {
        "eligible_families": len(eligible),
        "failing_families": len(failing),
        "family_ucb": cp_ucb(len(failing), len(eligible)),
        "false_allows": int((truth & ~decision).sum()),
        "should_escalate": int(truth.sum()),
        "safe_auto": int((~truth & ~decision).sum()),
        "over_escalations": int((~truth & decision).sum()),
        "should_run": int((~truth).sum()),
    }


def by_profile(
    models: dict[str, S.Learned] | None, records: Sequence[DecisionRecord], sch: S.Schema
) -> dict[str, Any]:
    """Each record decided by its profile's model (or the starting policy), counted together."""
    ordered: list[DecisionRecord] = []
    dec, tru = [], []
    for p in ("P1", "P2"):
        recs = [r for r in records if profile_of(r) == p]
        d, t = decisions(None if models is None else models[p], recs, sch)
        ordered += recs
        dec.append(d)
        tru.append(t)
    return counts(ordered, np.concatenate(dec), np.concatenate(tru))


def run() -> dict[str, Any]:
    dev = V2.development_pool(V2.v1_synthetic())
    fresh = V2.load_pools(V2_DIR, V2.FRESH_FILE)
    sch = schema([*dev, *(r for rs in fresh.values() for r in rs)])
    v2 = json.loads((V2_DIR / "results/v2.json").read_text())
    models = {p: fit([r for r in dev if profile_of(r) == p], sch) for p in ("P1", "P2")}
    out: dict[str, Any] = {
        "rules": {p: [r.to_json() for r in m.rules] for p, m in models.items()},
        "slices": {},
    }
    everything = [r for s in SLICES for r in fresh[s]]
    for s, recs in (*((s, fresh[s]) for s in SLICES), ("overall", everything)):
        row = {
            "S": by_profile(models, recs, sch),
            "DC-score@1.0 (start)": by_profile(None, recs, sch),
        }
        for name in ("DC-score", "G-combined", "G-target"):
            row[f"v2 {name}"] = v2["gate"]["counts"][s][name]
        out["slices"][s] = row
    steps = p3_steps(fresh["fresh_p3_corrections"])
    seen: list[DecisionRecord] = []
    evaluation = fresh["fresh_p3_eval"]
    p3: dict[str, Any] = {
        "0": {"S": counts(evaluation, *decisions(None, evaluation, sch)), "rules": []}
    }
    for k, batch in zip((5, 10, 25), steps, strict=True):
        seen += batch
        m = fit(seen, sch)
        p3[str(k)] = {
            "S": counts(evaluation, *decisions(m, evaluation, sch)),
            "rules": [r.to_json() for r in m.rules],
        }
    for k, row in p3.items():
        for name in ("G-combined", "G-target"):
            row[f"v2 {name}"] = v2["gate"]["p3"][k][name]
    out["p3"] = p3
    return out
