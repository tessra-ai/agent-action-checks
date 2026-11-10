"""Run the frozen rules on every captured airline write, from its pre-action snapshot.

    python experiments/2026-10-28-airline-rules/rules_run.py   # once

Reads the veto experiment's export copy read-only (`runs/airline/export.db`) and writes
`results/rules.jsonl`: per write, the blocks (rule and reason) and the facts it needs, with and
without the inferred `DUPLICATE_SEAT` rule.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rules import check, context_from, to_json  # noqa: E402

STORE = Path("runs/airline/export.db")
OUT = HERE / "results/rules.jsonl"


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    conn = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT w.write_id, w.action, w.args, s.messages, b.data FROM captured_writes w "
        "JOIN pre_action_snapshots s USING (write_id) JOIN db_blobs b ON b.hash = s.agent_db_hash "
        "ORDER BY w.session_id, w.seq"
    ).fetchall()
    out = []
    for write_id, action, args, messages, blob in rows:
        db = json.loads(zlib.decompress(blob))
        ctx = context_from(action, json.loads(args), db, json.loads(messages))
        out.append(
            {
                "write_id": write_id,
                "action": action,
                "typed_user_ids": sorted(ctx.typed_user_ids),
                "with_duplicate": to_json(check(ctx)),
                "without_duplicate": to_json(check(ctx, duplicate_rule=False)),
            }
        )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in out))
    blocked = sum(bool(r["with_duplicate"]["blocks"]) for r in out)
    print(f"wrote {OUT}: {len(out)} writes, {blocked} blocked by at least one rule")


if __name__ == "__main__":
    main()
