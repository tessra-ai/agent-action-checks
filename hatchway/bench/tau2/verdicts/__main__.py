"""Policy verdicts in a benchmark store: recompute, review queue, manual import, agreement.

    python -m hatchway.bench.tau2.verdicts runs/smoke.db                  # summary
    python -m hatchway.bench.tau2.verdicts runs/smoke.db --recompute      # new oracle version
    python -m hatchway.bench.tau2.verdicts runs/smoke.db --queue review.yaml
    python -m hatchway.bench.tau2.verdicts runs/smoke.db --import review.yaml
    python -m hatchway.bench.tau2.verdicts runs/smoke.db --report

`--recompute` appends verdicts for the current `ORACLE_VERSION` from the stored pre-action
snapshots; existing verdicts are never rewritten.

`--queue FILE` writes the review queue as YAML: every UNKNOWN verdict without an adjudication,
plus a seeded audit sample of ALLOW, ASK and DENY verdicts (`--audit-rate` of each class, at
least `--audit-min`), so the oracle's confident answers are checked too. A reviewer fills in
`decision` (and optionally `reason_codes`, `explanation`) and `reviewer`, then runs `--import`.
An imported review overrides the deterministic verdict of the same oracle version; both are
kept.

`--report` prints, per deterministic decision, how many reviewed verdicts the reviewers agreed
with: the oracle's audited error rate.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from hatchway.bench.store import BenchStore
from hatchway.bench.tau2.snapshot import evidence_from_store, verdict_record
from hatchway.bench.tau2.verdicts.base import POLICY_DECISIONS
from hatchway.bench.tau2.verdicts.registry import ORACLE_VERSION, evaluate


def recompute(store: BenchStore) -> Counter[str]:
    """Append current-version verdicts for every write with a snapshot and no such verdict."""
    counts: Counter[str] = Counter()
    for write in store.writes():
        if store.verdict(write.write_id, ORACLE_VERSION) is not None:
            continue
        evidence = evidence_from_store(store, write)
        if evidence is None:
            counts["no_snapshot"] += 1
            continue
        verdict = evaluate(evidence)
        store.record_verdict(write.write_id, verdict_record(verdict))
        counts[verdict.expected_decision] += 1
    return counts


def review_queue(
    store: BenchStore, oracle_version: str, *, audit_rate: float, audit_min: int, seed: int
) -> list[dict[str, Any]]:
    """Unadjudicated UNKNOWNs, then an audit sample of each other decision class."""
    rows = store.proposed_actions(oracle_version, require_verdicts=False)
    reviewed = {m.write_id for m in store.manual_verdicts(oracle_version) if m.adjudicated}
    pending = [r for r in rows if r.write_id not in reviewed]
    queue = [_entry(r, "unknown_queue") for r in pending if r.deterministic_decision == "UNKNOWN"]
    rng = random.Random(f"audit:{seed}:{oracle_version}")
    for decision in ("ALLOW", "ASK", "DENY"):
        pool = [r for r in pending if r.deterministic_decision == decision]
        k = min(len(pool), max(audit_min, round(audit_rate * len(pool))))
        queue += [_entry(r, "audit_sample") for r in rng.sample(pool, k)]
    return queue


def _entry(row: Any, kind: str) -> dict[str, Any]:
    return {
        "write_id": row.write_id,
        "oracle_version": row.oracle_version,
        "review_kind": kind,
        "action": row.action,
        "args": row.args,
        "task": f"{row.domain}/{row.task_id}",
        "oracle_decision": row.deterministic_decision,
        "oracle_reasons": list(row.deterministic_reason_codes),
        "oracle_explanation": row.deterministic_explanation,
        "decision": None,
        "reason_codes": [],
        "explanation": "",
        "reviewer": None,
    }


def import_reviews(store: BenchStore, path: Path) -> int:
    """Record every filled-in review in `path`. Entries without a decision are skipped."""
    entries = yaml.safe_load(path.read_text()) or []
    known = {w.write_id for w in store.writes()}
    n = 0
    for e in entries:
        if not e.get("decision"):
            continue
        if e["decision"] not in POLICY_DECISIONS:
            raise ValueError(f"{e['write_id']}: decision must be one of {POLICY_DECISIONS}")
        if not e.get("reviewer"):
            raise ValueError(f"{e['write_id']}: a review needs a reviewer")
        if e["write_id"] not in known:
            raise KeyError(f"no captured write {e['write_id']}")
        store.record_manual_verdict(
            write_id=e["write_id"],
            oracle_version=e["oracle_version"],
            expected_decision=e["decision"],
            reviewer=str(e["reviewer"]),
            review_kind=e.get("review_kind", "audit_sample"),
            reason_codes=e.get("reason_codes") or [],
            explanation=e.get("explanation") or "",
        )
        n += 1
    return n


def agreement(store: BenchStore, oracle_version: str) -> dict[str, dict[str, Any]]:
    """Per deterministic decision: reviewed count, agreed count, and the reviewers' decisions."""
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"reviewed": 0, "agreed": 0})
    for r in store.proposed_actions(oracle_version, require_verdicts=False):
        if r.manual_decision is None:
            continue
        block = out[r.deterministic_decision]
        block["reviewed"] += 1
        block["agreed"] += r.manual_decision == r.deterministic_decision
        block.setdefault("reviewer_decisions", Counter())[r.manual_decision] += 1
    return {
        k: {**v, "reviewer_decisions": dict(v.get("reviewer_decisions", {}))}
        for k, v in sorted(out.items())
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("store", type=Path)
    parser.add_argument("--oracle-version", default=ORACLE_VERSION)
    parser.add_argument("--recompute", action="store_true")
    parser.add_argument("--queue", type=Path, help="write the review queue to this YAML file")
    parser.add_argument("--audit-rate", type=float, default=0.2)
    parser.add_argument("--audit-min", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--import", dest="import_file", type=Path, help="reviewed YAML file")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    with BenchStore(args.store) as store:
        if args.recompute:
            print(f"recomputed for {ORACLE_VERSION}: {dict(recompute(store))}")
        if args.import_file:
            print(f"imported {import_reviews(store, args.import_file)} reviews")
        rows = store.proposed_actions(args.oracle_version, require_verdicts=False)
        missing = len(store.writes()) - len(rows)
        print(
            f"oracle version {args.oracle_version}: {len(rows)} proposals with verdicts"
            + (f", {missing} without" if missing else "")
        )
        print("deterministic:", dict(Counter(r.deterministic_decision for r in rows)))
        print("effective:    ", dict(Counter(r.effective_decision for r in rows)))
        unknown = sum(r.effective_decision == "UNKNOWN" for r in rows)
        if rows:
            print(f"unknown rate: {unknown / len(rows):.1%}")
        adjudicated = sum(r.effective_source == "manual_review" for r in rows)
        print(
            f"audit: {adjudicated} adjudicated reviews"
            if adjudicated
            else "audit: deterministic oracle only, unaudited (no adjudicated reviews)"
        )
        if args.queue:
            queue = review_queue(
                store,
                args.oracle_version,
                audit_rate=args.audit_rate,
                audit_min=args.audit_min,
                seed=args.seed,
            )
            args.queue.write_text(yaml.safe_dump(queue, sort_keys=False, allow_unicode=True))
            kinds = Counter(e["review_kind"] for e in queue)
            print(f"wrote {len(queue)} items to {args.queue}: {dict(kinds)}")
        if args.report:
            for decision, block in agreement(store, args.oracle_version).items():
                print(f"{decision}: {block}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
