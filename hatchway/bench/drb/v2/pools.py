"""v2 synthetic pools (RFC v2 §5), drawn with the unchanged `drb-synthetic-1` family generator.

A pool adds families deterministically, cycling its actions and profiles, until it has
`POOL_ELIGIBLE` eligible families (families with a should-escalate record). In P1/P2 evaluation
pools every fifth family is crossed (rendered under P1 and P2). Family ids are prefixed
`v2/<pool>/`, so they never collide with v1 families.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from hatchway.bench.drb import synthetic as G
from hatchway.bench.drb.partitions import HELD_OUT_ACTION, HELD_OUT_DOMAIN
from hatchway.bench.drb.schema import DecisionRecord
from hatchway.bench.drb.v2.risk import POOL_ELIGIBLE, eligible_families

CALIBRATION_SEED = 20261024
ALLOWED_P = 0.8
CROSS_EVERY = 5
P3_CORRECTION_FAMILIES = 5
MAX_FAMILIES = 400


def in_distribution() -> list[tuple[str, str, dict[str, Any]]]:
    return [(d, a, s) for d, a, s in G.actions() if d != HELD_OUT_DOMAIN and a != HELD_OUT_ACTION]


def held_out_action() -> list[tuple[str, str, dict[str, Any]]]:
    return [(d, a, s) for d, a, s in G.actions() if a == HELD_OUT_ACTION]


def held_out_domain() -> list[tuple[str, str, dict[str, Any]]]:
    return [(d, a, s) for d, a, s in G.actions() if d == HELD_OUT_DOMAIN]


def draw(
    name: str,
    seed: int,
    actions: Sequence[tuple[str, str, dict[str, Any]]],
    profiles: Sequence[str],
    *,
    min_eligible: int | None = POOL_ELIGIBLE,
    n_families: int | None = None,
    cross: bool = False,
) -> list[DecisionRecord]:
    """Families until `min_eligible` eligible families (or exactly `n_families`)."""
    rng = random.Random(f"{seed}:{name}")
    out: list[DecisionRecord] = []
    for i in range(MAX_FAMILIES):
        if n_families is not None and i >= n_families:
            break
        if n_families is None and eligible_families(out) >= (min_eligible or 0):
            break
        domain, action, spec = actions[i % len(actions)]
        if cross and i % CROSS_EVERY == CROSS_EVERY - 1:
            profs: tuple[str, ...] = ("P1", "P2")
        else:
            profs = (profiles[(i // len(actions)) % len(profiles)],)
        out += G.family_records(
            rng,
            domain,
            action,
            spec,
            f"v2/{name}/{domain}/{action}/f{i}",
            profs,
            allowed=rng.random() < ALLOWED_P,
            seed=seed,
        )
    else:
        raise RuntimeError(f"{name}: no {min_eligible} eligible families in {MAX_FAMILIES}")
    return [r.with_split(name) for r in out]


def hard(name: str, seed: int) -> list[DecisionRecord]:
    rng = random.Random(f"{seed}:{name}")
    out = []
    for domain, action, spec in G.actions():
        base = G._base(rng, spec, ("P1",), allowed=True)
        for p in ("P1", "P2"):
            out.append(
                G._record(
                    domain=domain,
                    action=action,
                    spec=spec,
                    family=f"v2/{name}/{domain}/{action}/hard",
                    variant="prohibited",
                    latent={**base, "prohibited": True},
                    profile_id=p,
                    render_variant=0,
                    seed=seed,
                ).with_split(name)
            )
    return out


def calibration_pools(seed: int = CALIBRATION_SEED) -> dict[str, list[DecisionRecord]]:
    ind = in_distribution()
    return {
        "cal_P1": draw("cal_P1", seed, ind, ("P1",)),
        "cal_P2": draw("cal_P2", seed, ind, ("P2",)),
    }


def fresh_pools(seed: int) -> dict[str, list[DecisionRecord]]:
    ind = in_distribution()
    return {
        "fresh_final": draw("fresh_final", seed, ind, ("P1", "P2"), cross=True),
        "fresh_action": draw("fresh_action", seed, held_out_action(), ("P1", "P2"), cross=True),
        "fresh_domain": draw("fresh_domain", seed, held_out_domain(), ("P1", "P2"), cross=True),
        "fresh_p3_corrections": draw(
            "fresh_p3_corrections", seed, ind, ("P3",), n_families=P3_CORRECTION_FAMILIES
        ),
        "fresh_p3_promotion": draw("fresh_p3_promotion", seed, ind, ("P3",)),
        "fresh_p3_eval": draw("fresh_p3_eval", seed, ind, ("P3",)),
        "fresh_hard": hard("fresh_hard", seed),
    }
