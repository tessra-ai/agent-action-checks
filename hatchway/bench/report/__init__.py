"""Internal, read-only benchmark viewer: a static HTML report over the benchmark store and τ²
results, for drilling from the overview into simulations, tasks and single writes.

    python -m hatchway.bench.report runs/m4.db --results runs/m4 --out report/

This is an inspection tool for the week 1 benchmark, not the product dashboard (SPEC.md, "Not
in v0"). It serves nothing and makes no network requests: open `report/index.html` from disk.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from hatchway.bench.report.labels import SCORE_SPREAD_THRESHOLD
from hatchway.bench.report.load import Bench, load
from hatchway.bench.report.render import write_report
from hatchway.bench.tau2 import DEFAULT_POLICY

__all__ = ["Bench", "build_report", "load", "main", "write_report"]


def build_report(
    store: str | Path,
    out: str | Path,
    results: Iterable[str | Path] = (),
    policy: str | Path | None = DEFAULT_POLICY,
    *,
    replay: str | Path | None = None,
    oracle_version: str | None = None,
    spread_threshold: float = SCORE_SPREAD_THRESHOLD,
) -> Path:
    """Write the report for `store` into `out`; returns the index page's path. `replay` is M6's
    output directory, for each arm's decision on every write."""
    bench = load(store, results, policy, oracle_version=oracle_version, replay=replay)
    return write_report(bench, out, spread_threshold=spread_threshold)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hatchway.bench.report", description=__doc__.splitlines()[0]
    )
    parser.add_argument("store", type=Path, help="benchmark SQLite file")
    parser.add_argument(
        "--results",
        nargs="*",
        type=Path,
        default=[],
        help="τ² results JSON files, or directories holding them (the harness --out)",
    )
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--policy", type=Path, default=DEFAULT_POLICY, help="policy file, for question text"
    )
    parser.add_argument(
        "--replay", type=Path, help="M6 replay output directory (its frozen_*.json arms)"
    )
    parser.add_argument(
        "--oracle-version", help="policy verdicts to show (default: the current oracle's)"
    )
    parser.add_argument(
        "--spread-threshold",
        type=float,
        default=SCORE_SPREAD_THRESHOLD,
        help="flag actions whose judges' policy scores differ by more than this "
        f"(default {SCORE_SPREAD_THRESHOLD})",
    )
    args = parser.parse_args(argv)
    if not args.store.is_file():
        parser.error(f"no such store: {args.store}")
    index = build_report(
        args.store,
        args.out,
        args.results,
        args.policy,
        replay=args.replay,
        oracle_version=args.oracle_version,
        spread_threshold=args.spread_threshold,
    )
    print(index)
    return 0


if __name__ == "__main__":
    sys.exit(main())
