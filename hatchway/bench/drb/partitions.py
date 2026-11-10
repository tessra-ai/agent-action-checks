"""Family-grouped, immutable partitions for the synthetic and retail records.

Synthetic, frozen before fitting:

| Partition | Content |
|---|---|
| `syn_pretrain`, `syn_promotion`, `syn_final` | P1/P2 families of in-distribution actions, 3/1/1 |
| `syn_holdout_action` | Every P1/P2 family of `HELD_OUT_ACTION` |
| `syn_holdout_domain` | Every P1/P2 family of `HELD_OUT_DOMAIN` |
| `syn_p3_adapt` | 5 held-out-profile (P3) families; the k-subsets are its first k records |
| `syn_p3_eval` | The other P3 families |
| `syn_hard` | Hard-rule records, only for the non-overridability check |

In-distribution families are split per action, label-free, by seeded shuffle (3 / 1 / 1 of 5).

Retail: whole scenario families, label-free, closest to 50 / 20 / 30 by write count:
`retail_adapt`, `retail_promotion`, `retail_holdout`. Telecom is sealed (`seal`) and is in no
partition here.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hatchway.bench.drb.schema import DecisionRecord, dataset_hash

HELD_OUT_ACTION = "issue_reimbursement"
HELD_OUT_DOMAIN = "access"
HELD_OUT_PROFILE = "P3"
P3_ADAPT_FAMILIES = 5
ADAPT_K = (0, 5, 10, 25)
SYN_SPLIT = (3, 1, 1)  # pretrain, promotion, final families per in-distribution action
RETAIL_TARGETS = {"retail_adapt": 0.5, "retail_promotion": 0.2, "retail_holdout": 0.3}
SYNTHETIC_PARTITIONS = (
    "syn_pretrain",
    "syn_promotion",
    "syn_final",
    "syn_holdout_action",
    "syn_holdout_domain",
    "syn_p3_adapt",
    "syn_p3_eval",
    "syn_hard",
)


def assign_synthetic(records: Sequence[DecisionRecord], seed: int) -> list[DecisionRecord]:
    """Each record with its synthetic partition. Reads no label."""
    families: dict[str, list[DecisionRecord]] = defaultdict(list)
    for r in records:
        families[r.family_id].append(r)
    split_of: dict[str, str] = {}
    by_action: dict[str, list[str]] = defaultdict(list)
    p3: list[str] = []
    for fam, recs in sorted(families.items()):
        r0 = recs[0]
        if fam.endswith("/hard"):
            split_of[fam] = "syn_hard"
        elif r0.org_profile.startswith(HELD_OUT_PROFILE + "@"):
            p3.append(fam)
        elif r0.domain == HELD_OUT_DOMAIN:
            split_of[fam] = "syn_holdout_domain"
        elif r0.action == HELD_OUT_ACTION:
            split_of[fam] = "syn_holdout_action"
        else:
            by_action[r0.action].append(fam)
    rng = random.Random(f"{seed}:partitions")
    for action in sorted(by_action):
        fams = sorted(by_action[action])
        rng.shuffle(fams)
        n_pre, n_pro, _ = SYN_SPLIT
        for i, fam in enumerate(fams):
            split_of[fam] = (
                "syn_pretrain"
                if i < n_pre
                else "syn_promotion"
                if i < n_pre + n_pro
                else "syn_final"
            )
    p3 = sorted(p3)
    rng.shuffle(p3)
    for i, fam in enumerate(p3):
        split_of[fam] = "syn_p3_adapt" if i < P3_ADAPT_FAMILIES else "syn_p3_eval"
    order = {f: i for i, f in enumerate(p3)}
    out = [r.with_split(split_of[r.family_id]) for r in records]
    # P3 adaptation records in their frozen order, so the k-subsets are prefixes.
    return sorted(out, key=lambda r: (r.split, order.get(r.family_id, -1), r.record_id))


def adaptation_subset(records: Sequence[DecisionRecord], k: int) -> list[DecisionRecord]:
    """The first k records of the held-out profile's adaptation partition (nested in k)."""
    pool = [r for r in records if r.split == "syn_p3_adapt"]
    return pool[:k]


def split_retail(families: Mapping[str, int], seed: int) -> dict[str, str]:
    """family -> retail partition, label-free: of 2,000 seeded shuffles, the one whose write
    shares land closest to `RETAIL_TARGETS` (every partition non-empty)."""
    fams = sorted(families)
    total = sum(families.values())
    names = list(RETAIL_TARGETS)
    n = len(fams)
    counts = [max(1, round(RETAIL_TARGETS[k] * n)) for k in names]
    while sum(counts) > n:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < n:
        counts[0] += 1
    rng = random.Random(f"{seed}:retail")
    best: tuple[float, list[str]] | None = None
    for _ in range(2000):
        order = fams[:]
        rng.shuffle(order)
        err, start = 0.0, 0
        for name, c in zip(names, counts, strict=True):
            part = order[start : start + c]
            start += c
            err += (sum(families[f] for f in part) / total - RETAIL_TARGETS[name]) ** 2
        if best is None or err < best[0] - 1e-12:
            best = (err, order)
    assert best is not None
    out, start = {}, 0
    for name, c in zip(names, counts, strict=True):
        for f in best[1][start : start + c]:
            out[f] = name
        start += c
    return out


@dataclass(frozen=True)
class Manifest:
    """What a set of records is, by partition: counts, family ids and hashes."""

    name: str
    body: dict[str, Any]


def manifest(name: str, records: Iterable[DecisionRecord], extra: Mapping[str, Any]) -> dict:
    recs = list(records)
    parts: dict[str, list[DecisionRecord]] = defaultdict(list)
    for r in recs:
        parts[r.split].append(r)
    return {
        "manifest": name,
        **extra,
        "dataset_sha256": dataset_hash(recs),
        "partitions": {
            p: {
                "records": len(rs),
                "families": sorted({r.family_id for r in rs}),
                "should_run": sum(r.should_run for r in rs),
                "should_escalate": sum(not r.should_run for r in rs),
                "hard_rule": sum(r.hard_rule is not None for r in rs),
                "sha256": dataset_hash(rs),
            }
            for p, rs in sorted(parts.items())
        },
        "records": [
            {
                "record_id": r.record_id,
                "family_id": r.family_id,
                "split": r.split,
                "record_hash": r.record_hash,
            }
            for r in sorted(recs, key=lambda r: r.record_id)
        ],
    }


def assert_family_isolation(records: Iterable[DecisionRecord]) -> None:
    seen: dict[str, str] = {}
    for r in records:
        if seen.setdefault(r.family_id, r.split) != r.split:
            raise AssertionError(f"family {r.family_id} crosses partitions")
