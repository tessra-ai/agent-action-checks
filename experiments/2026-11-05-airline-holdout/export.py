"""Export the captured airline writes, blind, for the judges and the graders.

Works on a copy of the capture store (`runs/airline2/export.db`; the store writes on open). Leaves
out writes of abandoned sessions and of tools the gate policy does not know. Writes, once:

- `data/runs.jsonl`: per write, the conversation exactly as the agent had it when it proposed
  the write, ending with the proposed call (id `proposed`). Nothing else.
- `data/meta.jsonl`: per write, task, agent model, the backend's outcome and error, and the
  simulation's τ² reward. Only the analysis reads it.

    python experiments/2026-11-05-airline-holdout/export.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from hatchway.bench.store import BenchStore
from hatchway.bench.tau2.snapshot import evidence_from_store

HERE = Path(__file__).parent
SOURCE = Path("runs/airline2/airline.db")
COPY = Path("runs/airline2/export.db")


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
    if (HERE / "data/runs.jsonl").exists():
        sys.exit("data/runs.jsonl exists; exported once")
    if not COPY.exists():
        src = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
        dst = sqlite3.connect(COPY)
        src.backup(dst)
        src.close()
        dst.close()
    runs, meta = [], []
    with BenchStore(COPY) as store:
        abandoned = store.abandoned_session_ids()
        sims = {s.session_id: s for s in store.simulations("done")}
        for w in store.writes():
            if w.domain != "airline" or w.session_id in abandoned or not w.known_action:
                continue
            if w.session_id not in sims:
                continue
            ev = evidence_from_store(store, w)
            assert ev is not None, w.write_id
            proposing = {
                "role": "assistant",
                "content": ev.proposing_text,
                "tool_calls": [{"id": "proposed", "function": w.action, "arguments": dict(w.args)}],
            }
            runs.append(
                {
                    "write_id": w.write_id,
                    "action": w.action,
                    "messages": [*(turn_json(t) for t in ev.turns), proposing],
                }
            )
            out = store.outcome(w.write_id)
            sim = sims[w.session_id]
            meta.append(
                {
                    "write_id": w.write_id,
                    "action": w.action,
                    "task_id": w.task_id,
                    "agent_model": w.agent_model,
                    "session_id": w.session_id,
                    "seq": w.seq,
                    "state_hash": w.state_hash,
                    "rubric_hash": w.rubric_hash,
                    "outcome": out.outcome if out else None,
                    "backend_error": out.backend_error if out else None,
                    "reward": sim.reward,
                }
            )
    (HERE / "data").mkdir(exist_ok=True)
    for name, rows in (("runs.jsonl", runs), ("meta.jsonl", meta)):
        (HERE / "data" / name).write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        )
    print(len(runs), "airline writes exported")


if __name__ == "__main__":
    main()
