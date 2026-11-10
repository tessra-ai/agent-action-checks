"""Synthetic rows for verifying the pilot's code, never for evidence.

`planted_rows` draws writes whose correct decision is set by shared concepts (identity, consent,
ownership, prerequisites) the same way for every action, read through a noisy judge: an analysis
that measures transfer should find it here. With `effect=False` the labels ignore the concepts,
and it must not. Every row is marked `synthetic`; the empirical report refuses such rows.
"""

from __future__ import annotations

import random

from hatchway.bench.pilot.arms import PRIMARY_JUDGE, Row
from hatchway.bench.pilot.concepts import CONCEPTS, REASON_CONCEPTS, ConceptAssessment

ACTIONS = {
    "a_return": ("retail", "financial", "partly"),
    "a_exchange": ("retail", "financial", "partly"),
    "a_cancel": ("retail", "financial", "no"),
    "t_roaming": ("telecom", "service", "yes"),
    "t_refuel": ("telecom", "financial", "no"),
}
DECISIVE = (
    "actor_identified",
    "consent_obtained",
    "ownership_authority",
    "prerequisites_satisfied",
)
_CODE = {c: next(code for code, k in REASON_CONCEPTS.items() if k == c) for c in DECISIVE}


def _judge(met: bool, rng: random.Random, noise: float) -> ConceptAssessment:
    p = rng.uniform(0.75, 1.0) if met else rng.uniform(0.0, 0.25)
    if rng.random() < noise:
        p = 1.0 - p
    return ConceptAssessment("", 0.95, p, rng.uniform(0.5, 1.0))


def planted_rows(
    n: int, seed: int, *, effect: bool = True, noise: float = 0.05, judge: str = PRIMARY_JUDGE
) -> list[Row]:
    rng = random.Random(seed)
    names = sorted(ACTIONS)
    rows = []
    for i in range(n):
        action = names[i % len(names)]
        domain, impact, reversible = ACTIONS[action]
        failed = {c for c in DECISIVE if rng.random() < 0.15}
        label = 0 if failed else 1
        if not effect:
            label = int(rng.random() < 0.6)
            failed = set()
        concepts = {}
        for c in CONCEPTS:
            a = _judge(c not in failed, rng, noise) if c in DECISIVE else _judge(True, rng, 0.3)
            concepts[c] = ConceptAssessment(c, a.applicable, a.assessment, a.confidence)
        rows.append(
            Row(
                write_id=f"syn{seed}-{i}",
                family=f"syn-family-{i // 3}",
                domain=domain,
                action=action,
                order=(i,),
                label=label,
                verdict="ALLOW" if label else "DENY",
                impact=impact,
                reversible=reversible,
                concepts={judge: concepts},
                baseline={judge: {"policy_ok": rng.random(), "matches_request": rng.random()}},
                reason_codes=tuple(sorted(_CODE[c] for c in failed)),
                synthetic=True,
            )
        )
    return rows
