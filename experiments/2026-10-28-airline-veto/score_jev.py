"""Jev's single question on every exported airline write, then the answers to a results file.

Scores in the export copy of the store, under the budget ledger's `scoring` cap ($2). The
question is `policy_ok` from `hatchway-airline.yaml`. Writes `results/jev.jsonl` once.

    python experiments/2026-10-28-airline-veto/score_jev.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from capture import CAPS

from hatchway.bench.budget import Ledger
from hatchway.bench.score import make_judge, score_store
from hatchway.bench.store import BenchStore
from hatchway.policy import load_policy

HERE = Path(__file__).parent
COPY = Path("runs/airline/export.db")
JEV = ("jev", "jev-1.14.0")
OUT = HERE / "results/jev.jsonl"


async def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    policy = load_policy(HERE / "hatchway-airline.yaml")
    meta = [json.loads(line) for line in (HERE / "data/meta.jsonl").read_text().splitlines()]
    ids = {m["write_id"] for m in meta}
    with Ledger(Path("runs/airline/ledger.db"), CAPS) as ledger, BenchStore(COPY) as store:
        ledger.recover()
        judge = make_judge(f"{JEV[0]}:{JEV[1]}", store)
        try:
            summary = await score_store(
                store, policy, [judge], concurrency=4, ledger=ledger, write_ids=ids
            )
        finally:
            aclose = getattr(judge, "aclose", None)
            if aclose is not None:
                await aclose()
        print(json.dumps(asdict(summary), default=str)[:800])
        print("ledger", json.dumps(ledger.summary(), default=str))
        rows = []
        for m in meta:
            s = store.get_score(m["state_hash"], m["rubric_hash"], *JEV)
            ok = s is not None and s.status == "ok"
            rows.append(
                {
                    "write_id": m["write_id"],
                    "status": s.status if s else "missing",
                    "p_yes": s.question_vector.answers["policy_ok"].p_yes if ok else None,
                }
            )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"wrote {OUT}: {sum(r['p_yes'] is not None for r in rows)} of {len(rows)} answered")


if __name__ == "__main__":
    asyncio.run(main())
