"""Step 1 (project venv): export the real retail writes for Docent's judge, blind.

Reads copies of the capture stores (`runs/docent/*.db`, never the originals: the store writes
on open) and writes two files:

- `runs/docent/runs.jsonl`: per write, the conversation exactly as the agent had it when it
  proposed the write (`pre_action_snapshots.messages`), plus the proposed call. No verdict,
  reason code, explanation, backend outcome or benchmark match.
- `runs/docent/truth.jsonl`: per write, the oracle's verdict and the benchmark match. Only the
  comparison step reads it.

Retail only: the 35 telecom writes stay under the decision-record benchmark seal.

    python experiments/2026-10-25-docent-vs-oracle/export_runs.py
"""

from __future__ import annotations

import json
from pathlib import Path

from hatchway.bench.drb.seal import assert_no_telecom, load_seal
from hatchway.bench.store import BenchStore
from hatchway.bench.tau2.snapshot import evidence_from_store

ORACLE = "tau2-oracle-1:41ee37217182"
OUT = Path("runs/docent")
SEAL = Path("experiments/2026-10-23-decision-record-benchmark/telecom-seal.json")


def turn_json(t) -> dict:
    out = {"role": t.role, "content": t.content}
    if t.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "function": c.name, "arguments": dict(c.arguments)} for c in t.tool_calls
        ]
    if t.tool_call_id:
        out["tool_call_id"] = t.tool_call_id
    if t.error:
        out["error"] = True
    return out


def main() -> None:
    runs, truth, ids = [], [], []
    for name in ("targeted", "smoke2"):
        store = BenchStore(OUT / f"{name}.db")
        by_id = {}
        for rec in store.proposed_actions(ORACLE):
            if rec.domain != "retail":
                continue
            by_id[rec.write_id] = rec
        for rec in by_id.values():
            write = next(w for w in store.writes(rec.session_id) if w.write_id == rec.write_id)
            ev = evidence_from_store(store, write)
            assert ev is not None, rec.write_id
            turns = [turn_json(t) for t in ev.turns]
            proposing = {
                "role": "assistant",
                "content": ev.proposing_text,
                "tool_calls": [
                    {"id": "proposed", "function": rec.action, "arguments": dict(rec.args)}
                ],
            }
            runs.append(
                {
                    "write_id": rec.write_id,
                    "store": name,
                    "action": rec.action,
                    "messages": [*turns, proposing],
                }
            )
            truth.append(
                {
                    "write_id": rec.write_id,
                    "store": name,
                    "action": rec.action,
                    "task_id": rec.task_id,
                    "agent_model": rec.agent_model,
                    "oracle": rec.deterministic_decision,
                    "reason_codes": list(rec.deterministic_reason_codes),
                    "explanation": rec.deterministic_explanation,
                    "benchmark_match": rec.benchmark_match,
                    "execution_outcome": rec.execution_outcome,
                }
            )
            ids.append(rec.write_id)
        store.close()
    assert_no_telecom(ids, load_seal(SEAL), "docent-vs-oracle export")
    for path, rows in (("runs.jsonl", runs), ("truth.jsonl", truth)):
        (OUT / path).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(len(runs), "retail writes exported")


if __name__ == "__main__":
    main()
