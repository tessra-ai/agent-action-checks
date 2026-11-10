"""Run the hand-written rules and the Claude draft on the held-out writes (no model calls).

    python experiments/2026-11-05-airline-holdout/rules_holdout.py

Writes `results/rules_hand.jsonl` (the 16 rules of `experiments/2026-10-28-airline-rules`, with
and without the inferred duplicate-seat rule) and `results/rules_claude.jsonl` (the complete
Claude Sonnet 5.5 draft of `experiments/2026-11-05-model-drafted-rules`, run in a subprocess
like every draft), both from the pre-action snapshots of `runs/airline2/export.db`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
EXP = HERE.parent
sys.path.insert(0, str(EXP / "2026-10-28-airline-rules"))
from rules import check, context_from, to_json  # noqa: E402

STORE = Path("runs/airline2/export.db")
DRAFT = EXP / "2026-11-05-model-drafted-rules/results/drafts/claude_sonnet55_b.py"


def main() -> None:
    out_h, out_c = HERE / "results/rules_hand.jsonl", HERE / "results/rules_claude.jsonl"
    if out_h.exists() or out_c.exists():
        sys.exit("results exist; written once")
    sys.path.insert(0, str(EXP / "2026-11-05-model-drafted-rules"))
    import run_drafts

    run_drafts.STORE = STORE
    writes = run_drafts.load_writes()
    rows = []
    for write_id, action, args, messages, db in writes:
        ctx = context_from(action, args, db, messages)
        rows.append(
            {
                "write_id": write_id,
                "action": action,
                "with_duplicate": to_json(check(ctx)),
                "without_duplicate": to_json(check(ctx, duplicate_rule=False)),
            }
        )
    out_h.parent.mkdir(exist_ok=True)
    out_h.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    blocked = sum(bool(r["with_duplicate"]["blocks"]) for r in rows)
    print(f"hand-written: {len(rows)} writes, {blocked} blocked")
    env = {"HATCH_RULES_STORE": str(STORE)}
    proc = subprocess.run(
        [sys.executable, "-I", str(HERE / "rules_holdout.py"), "--child", str(DRAFT), str(out_c)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env={**__import__("os").environ, **env},
    )
    if proc.returncode != 0 or not out_c.exists():
        sys.exit(f"child failed\n{proc.stderr[-2000:]}")
    rows = [json.loads(line) for line in out_c.read_text().splitlines()]
    print(
        f"claude draft: {len(rows)} writes, {sum(bool(r['blocks']) for r in rows)} blocked, "
        f"{sum(bool(r['error']) for r in rows)} errors"
    )


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        sys.path.insert(0, str(EXP / "2026-11-05-model-drafted-rules"))
        import run_drafts

        run_drafts.STORE = Path(__import__("os").environ["HATCH_RULES_STORE"])
        run_drafts.child(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main()
