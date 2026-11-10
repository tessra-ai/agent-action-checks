"""Pilot data: label-free candidates, the three-way family split, the sealed holdout, and rows.

**Candidates** are the writes of completed simulations (done, with a reward) in the pilot's
stores, for write actions that have a pilot rubric. They carry no label and no score: only what
is needed to group and split them (scenario family, domain, action, order).

**Scenario families** are `tau2.families.scenario_family` ids. They are not qualified by store,
so a scenario captured in two stores stays on one side of the split.

**The split** assigns whole families, per domain, to three disjoint datasets: `revealed`
(fitting, thresholds, corrections), `promotion` (accepting or rejecting challengers) and
`holdout` (one final evaluation). It reads no label: of `SPLIT_DRAWS` seeded shuffles, the one
whose write shares land closest to `SPLIT_TARGETS` in every domain is kept.

**The holdout is sealed**: the split file stores only salted hashes of its family ids. `rows()`
refuses the holdout scope unless called by the final evaluation, and every other scope drops
holdout families before any verdict or score is read.
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hatchway.bench.pilot.arms import Row
from hatchway.bench.pilot.concepts import baseline_answers, concept_vector
from hatchway.bench.store import BenchStore
from hatchway.policy import Policy

Scope = Literal["revealed", "promotion", "holdout"]
SPLITS: tuple[Scope, ...] = ("revealed", "promotion", "holdout")
SPLIT_TARGETS = {"revealed": 0.5, "promotion": 0.2, "holdout": 0.3}
SPLIT_DRAWS = 2000
HOLDOUT_SALT = "pilot-holdout:"


class HoldoutSealed(RuntimeError):
    """A command other than the final evaluation tried to read the holdout."""


@dataclass(frozen=True)
class Candidate:
    write_id: str
    store: str
    session_id: str
    seq: int
    ts: str
    domain: str
    task_id: str
    action: str
    family: str
    state_hash: str


def tau2_family(domain: str, task_id: str) -> str:
    from tau2.run import get_tasks

    from hatchway.bench.tau2.families import scenario_family

    [task] = get_tasks(domain, task_ids=[task_id])
    return scenario_family(domain, task)


def candidates(
    stores: Mapping[str, Path],
    actions: Iterable[str],
    family_of: Callable[[str, str], str] = tau2_family,
) -> list[Candidate]:
    """Writes of completed simulations for the given actions, in (store, ts, session, seq)
    order. `stores` maps a short store name to its path."""
    wanted = set(actions)
    families: dict[tuple[str, str], str] = {}
    out = []
    for name, path in stores.items():
        with BenchStore(path) as store:
            done = {s.session_id for s in store.simulations("done") if s.reward is not None}
            for w in store.writes():
                if w.session_id not in done or w.action not in wanted:
                    continue
                key = (w.domain or "", w.task_id or "")
                if key not in families:
                    families[key] = family_of(*key)
                out.append(
                    Candidate(
                        w.write_id,
                        name,
                        w.session_id,
                        w.seq,
                        w.ts,
                        key[0],
                        key[1],
                        w.action,
                        families[key],
                        w.state_hash,
                    )
                )
    return sorted(out, key=lambda c: (c.store, c.ts, c.session_id, c.seq))


def candidates_digest(cands: Sequence[Candidate]) -> str:
    """sha256 of the candidates' identities: what the pilot is defined over."""
    lines = sorted(f"{c.store}\t{c.write_id}\t{c.state_hash}\t{c.family}" for c in cands)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def family_hash(family: str) -> str:
    return hashlib.sha256((HOLDOUT_SALT + family).encode()).hexdigest()


# --- The split -----------------------------------------------------------------------------------


def _counts(n: int) -> dict[Scope, int]:
    """Families per dataset for a domain with n families: largest remainders on the targets,
    with every dataset non-empty once there are at least three families."""
    raw = {s: SPLIT_TARGETS[s] * n for s in SPLITS}
    counts = {s: int(raw[s]) for s in SPLITS}
    for s in sorted(SPLITS, key=lambda s: raw[s] - counts[s], reverse=True):
        if sum(counts.values()) >= n:
            break
        counts[s] += 1
    if n >= 3:
        for s in SPLITS:
            if counts[s] == 0:
                donor = max(SPLITS, key=lambda d: counts[d])
                counts[donor] -= 1
                counts[s] = 1
    return counts


def freeze_split(cands: Sequence[Candidate], seed: int) -> dict[str, Any]:
    """The label-free three-way split (see the module docstring)."""
    sizes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in cands:
        sizes[c.domain][c.family] += 1
    rng = random.Random(seed)
    assignment: dict[str, Scope] = {}
    detail = {}
    for domain in sorted(sizes):
        fams = sorted(sizes[domain])
        total = sum(sizes[domain].values())
        counts = _counts(len(fams))
        best: tuple[float, list[str]] | None = None
        for _ in range(SPLIT_DRAWS):
            order = fams[:]
            rng.shuffle(order)
            err = 0.0
            start = 0
            for s in SPLITS:
                part = order[start : start + counts[s]]
                start += counts[s]
                err += (sum(sizes[domain][f] for f in part) / total - SPLIT_TARGETS[s]) ** 2
            if best is None or err < best[0] - 1e-12:
                best = (err, order)
        assert best is not None
        start = 0
        shares = {}
        for s in SPLITS:
            part = best[1][start : start + counts[s]]
            start += counts[s]
            for f in part:
                assignment[f] = s
            shares[s] = {
                "families": len(part),
                "writes": sum(sizes[domain][f] for f in part),
            }
        detail[domain] = {"families": len(fams), "writes": total, "datasets": shares}
    holdout = sorted(family_hash(f) for f, s in assignment.items() if s == "holdout")
    return {
        "seed": seed,
        "targets": SPLIT_TARGETS,
        "draws": SPLIT_DRAWS,
        "rule": "label-free; per domain, whole families; closest write shares to the targets",
        "revealed": sorted(f for f, s in assignment.items() if s == "revealed"),
        "promotion": sorted(f for f, s in assignment.items() if s == "promotion"),
        "holdout": {"family_sha256": holdout, "salt": HOLDOUT_SALT},
        "by_domain": detail,
    }


def scope_of(family: str, split: Mapping[str, Any]) -> Scope | None:
    if family_hash(family) in set(split["holdout"]["family_sha256"]):
        return "holdout"
    if family in split["revealed"]:
        return "revealed"
    if family in split["promotion"]:
        return "promotion"
    return None


def in_scope(
    cands: Sequence[Candidate], split: Mapping[str, Any], scope: Scope, *, final_eval: bool = False
) -> list[Candidate]:
    """The candidates of one dataset. The holdout only for the final evaluation; a family in
    two datasets, or in none, is an error."""
    if scope == "holdout" and not final_eval:
        raise HoldoutSealed("the holdout is read only by final-eval")
    overlap = set(split["revealed"]) & set(split["promotion"])
    if overlap:
        raise ValueError(f"families in two datasets: {sorted(overlap)}")
    out = []
    for c in cands:
        s = scope_of(c.family, split)
        if s is None:
            raise ValueError(f"family {c.family!r} is in no dataset; the split is stale")
        if c.family in split["revealed"] and s == "holdout":
            raise ValueError(f"family {c.family!r} is revealed and held out")
        if s == scope:
            out.append(c)
    return out


# --- Rows -----------------------------------------------------------------------------------------


def label_of(decision: str | None) -> int | None:
    if decision == "ALLOW":
        return 1
    if decision in ("ASK", "DENY"):
        return 0
    return None


def rows(
    cands: Sequence[Candidate],
    stores: Mapping[str, Path],
    policy: Policy,
    oracle_version: str,
    rubric_hashes: Mapping[str, str],
    judges: Mapping[str, str],
) -> tuple[list[Row], dict[str, dict[str, Any]]]:
    """Rows for already-scoped candidates (see `in_scope`), with verdicts at `oracle_version`
    and each judge's pilot-rubric answers. Also returns per-write call facts (cost, latency,
    status) by judge, for the cost and latency report."""
    by_store: dict[str, list[Candidate]] = defaultdict(list)
    for c in cands:
        by_store[c.store].append(c)
    out: list[Row] = []
    calls: dict[str, dict[str, Any]] = {}
    for name, group in by_store.items():
        with BenchStore(stores[name]) as store:
            if store.manual_verdicts(oracle_version):
                raise ValueError(f"{name}: manual verdicts exist; the pilot is oracle-only")
            for c in group:
                verdict = store.verdict(c.write_id, oracle_version)
                concepts = {}
                baseline = {}
                facts = {}
                for judge, model_id in judges.items():
                    rec = store.get_score(c.state_hash, rubric_hashes[c.action], judge, model_id)
                    facts[judge] = (
                        None
                        if rec is None
                        else {
                            "status": rec.status,
                            "cost_usd": rec.cost_usd,
                            "latency_ms": rec.latency_ms,
                            "attempts": rec.attempts,
                        }
                    )
                    if rec is not None and rec.status == "ok" and rec.question_vector is not None:
                        concepts[judge] = concept_vector(rec.question_vector)
                        baseline[judge] = dict(baseline_answers(rec.question_vector))
                meta = policy.actions[c.action].metadata
                assert meta is not None
                out.append(
                    Row(
                        write_id=c.write_id,
                        family=c.family,
                        domain=c.domain,
                        action=c.action,
                        order=(c.store, c.ts, c.session_id, c.seq),
                        label=label_of(verdict.expected_decision if verdict else None),
                        verdict=verdict.expected_decision if verdict else None,
                        impact=meta.impact,
                        reversible=meta.reversible,
                        concepts=concepts,
                        baseline=baseline,
                        reason_codes=tuple(verdict.reason_codes) if verdict else (),
                    )
                )
                calls[c.write_id] = facts
    return sorted(out, key=lambda r: r.order), calls
