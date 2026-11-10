"""Jev's narrow fact questions (`facts.yaml`) on every captured airline write.

    python experiments/2026-10-28-airline-rules/score_facts.py   # once

Scores in a fresh copy of the veto experiment's export store (`runs/airline/rules.db`), under a
separate budget ledger (`runs/airline/rules-ledger.db`, `scoring` cap $0.50). Writes
`results/facts.jsonl` once: per write, P(yes) for each of its questions.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from hatchway.bench.budget import Caps, Ledger
from hatchway.bench.score import make_judge, score_store
from hatchway.bench.store import BenchStore
from hatchway.policy import Kind, load_policy

HERE = Path(__file__).parent
SOURCE = Path("runs/airline/export.db")
COPY = Path("runs/airline/rules.db")
LEDGER = Path("runs/airline/rules-ledger.db")
CAPS = Caps({"scoring": 0.5}, total=0.5)
JEV = ("jev", "jev-1.14.0")
OUT = HERE / "results/facts.jsonl"


def copy_store() -> None:
    if COPY.exists():
        return
    src = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    dst = sqlite3.connect(COPY)
    src.backup(dst)
    dst.close()
    src.close()


async def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    copy_store()
    policy = load_policy(HERE / "facts.yaml")
    rubrics = {
        name: (list(spec.questions.values()), spec.rubric_hash)
        for name, spec in policy.actions.items()
        if spec.kind is Kind.WRITE
    }
    meta = [
        json.loads(line)
        for line in (HERE.parent / "2026-10-28-airline-veto/data/meta.jsonl")
        .read_text()
        .splitlines()
    ]
    ids = {m["write_id"] for m in meta}
    with Ledger(LEDGER, CAPS) as ledger, BenchStore(COPY) as store:
        ledger.recover()
        judge = make_judge(f"{JEV[0]}:{JEV[1]}", store)
        try:
            summary = await score_store(
                store,
                policy,
                [judge],
                concurrency=4,
                ledger=ledger,
                rubrics=rubrics,
                write_ids=ids,
            )
        finally:
            aclose = getattr(judge, "aclose", None)
            if aclose is not None:
                await aclose()
        print(json.dumps(asdict(summary), default=str)[:800])
        print("ledger", json.dumps(ledger.summary(), default=str))
        rows = []
        for m in meta:
            questions, rubric_hash = rubrics[m["action"]]
            s = store.get_score(m["state_hash"], rubric_hash, *JEV)
            ok = s is not None and s.status == "ok"
            rows.append(
                {
                    "write_id": m["write_id"],
                    "status": s.status if s else "missing",
                    "p_yes": {
                        q.name: (s.question_vector.answers[q.name].p_yes if ok else None)
                        for q in questions
                    },
                }
            )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"wrote {OUT}: {sum(r['status'] == 'ok' for r in rows)} of {len(rows)} answered")


if __name__ == "__main__":
    asyncio.run(main())
