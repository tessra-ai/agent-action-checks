"""Capture the airline conversations (agents gpt-4.1 / mini / nano, user gpt-4.1-mini).

Hard cap: every agent and user call reserves its maximum cost in the budget ledger first
(`capture` $4); no new simulation starts with less than $0.30 left. Resumable: a rerun skips
finished simulations. The store and τ² results live under `runs/airline2/` (git-ignored).

    python experiments/2026-11-05-airline-holdout/capture.py
"""

from __future__ import annotations

import json
from pathlib import Path

from hatchway.bench.budget import Caps, Ledger
from hatchway.bench.store import BenchStore
from hatchway.bench.tau2.config import load_run_config
from hatchway.bench.tau2.harness import run_config

HERE = Path(__file__).parent
RUNS = Path("runs/airline2")
CAPS = Caps({"capture": 4.0, "scoring": 2.0}, total=6.0)


def main() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    config = load_run_config(HERE / "airline2.yaml")
    with BenchStore(RUNS / "airline.db") as store, Ledger(RUNS / "ledger.db", CAPS) as ledger:
        print("recovered reservations:", ledger.recover())
        summary = run_config(
            config,
            store,
            RUNS / "tau2",
            policy=HERE / "hatchway-airline.yaml",
            ledger=ledger,
            start_margin_usd=0.30,
        )
    (RUNS / "capture-summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: summary[k] for k in ("spent_usd_this_run", "ledger")}, default=str))


if __name__ == "__main__":
    main()
