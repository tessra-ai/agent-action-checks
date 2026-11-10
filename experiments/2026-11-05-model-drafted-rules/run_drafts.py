"""Run every drafted module on the 133 airline writes, each in its own subprocess.

    python experiments/2026-11-05-model-drafted-rules/run_drafts.py

The parent never imports a draft. The child (`--child <draft.py> <out.jsonl>`) builds the same
`Context` the hand-written rules get (`rules.context_from`), calls the draft's `check` on each
write inside try/except, and writes `results/<name>.jsonl`: per write the blocks and any error.
A draft that fails to import yields a file where every write has `import_error` set and no
blocks. Written once per draft.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).parent
RULES = HERE.parent / "2026-10-28-airline-rules"
STORE = Path("runs/airline/export.db")
TIMEOUT_S = 300


def load_writes() -> list[tuple[str, str, dict, list, dict]]:
    conn = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT w.write_id, w.action, w.args, s.messages, b.data FROM captured_writes w "
        "JOIN pre_action_snapshots s USING (write_id) JOIN db_blobs b ON b.hash = s.agent_db_hash "
        "ORDER BY w.session_id, w.seq"
    ).fetchall()
    return [
        (w, a, json.loads(args), json.loads(msgs), json.loads(zlib.decompress(blob)))
        for w, a, args, msgs, blob in rows
    ]


def apply(check, writes, context_from) -> list[dict]:
    out = []
    for write_id, action, args, messages, db in writes:
        ctx = context_from(action, args, db, messages)
        row = {"write_id": write_id, "action": action, "blocks": [], "error": None}
        try:
            result = check(ctx)
            row["blocks"] = [
                {"rule": str(r), "reason": str(why)[:300]} for r, why in (result or [])
            ]
        except BaseException as exc:  # the draft's bug (or exit), recorded as no block
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        out.append(row)
    return out


def child(draft: Path, out: Path) -> None:
    sys.path.insert(0, str(RULES))
    from rules import context_from

    sys.path.remove(str(RULES))  # the draft runs without the hand-written rules importable
    sys.modules.pop("rules", None)
    writes = load_writes()
    try:
        spec = importlib.util.spec_from_file_location(f"draft_{draft.stem}", draft)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check = module.check
    except Exception as exc:
        rows = [
            {
                "write_id": w,
                "action": a,
                "blocks": [],
                "error": None,
                "import_error": f"{type(exc).__name__}: {exc}"[:300],
            }
            for w, a, *_ in writes
        ]
    else:
        rows = apply(check, writes, context_from)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def main() -> None:
    for draft in sorted((HERE / "results/drafts").glob("*.py")):
        out = HERE / f"results/{draft.stem}.jsonl"
        if out.exists():
            print(f"{out} exists; skipped")
            continue
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(HERE / "run_drafts.py"),
                    "--child",
                    str(draft),
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            sys.exit(f"{draft.stem}: child ran past {TIMEOUT_S}s and was killed")
        if proc.returncode != 0 or not out.exists():
            sys.exit(f"{draft.stem}: child failed\n{proc.stderr[-2000:]}")
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        blocked = sum(bool(r["blocks"]) for r in rows)
        errors = sum(bool(r["error"]) for r in rows)
        imp = rows[0].get("import_error") if rows else None
        print(
            f"{draft.stem}: {len(rows)} writes, {blocked} blocked, {errors} errors"
            + (f", import error: {imp}" if imp else "")
        )


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main()
