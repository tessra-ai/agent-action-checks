"""Consolidate labeller B (Gemini app, manual route) once every batch is complete. Run once.

    python experiments/2026-11-18-rely1-m1/labeller/finish_b.py

Runs the package's ingest.py with --require-all on runs/gemini_package/answers/ and writes,
committed: `results/labels_b.jsonl` (one row per question ID), `results/labels_b_model_log.txt`
(Prithvi's model log: model as shown in the picker, date, notes per batch and fill),
`results/labels_b_summary.json` (counts, fills, set-aside replies, hashes).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

M1 = Path(__file__).resolve().parents[1]
PKG = M1 / "runs/gemini_package"
OUT = M1 / "results/labels_b.jsonl"
LOG = M1 / "results/labels_b_model_log.txt"
SUMMARY = M1 / "results/labels_b_summary.json"


def main() -> int:
    checked = PKG / "checked_answers.jsonl"
    p = subprocess.run(
        [sys.executable, str(PKG / "ingest.py"), str(PKG / "answers"), "--require-all",
         "--out", str(checked)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if p.returncode:
        print(p.stdout[-2000:])
        raise SystemExit("labeller B is not complete")
    rows = [json.loads(x) for x in checked.read_text().splitlines()]
    manifest = json.loads((PKG / "manifest.json").read_text())
    expected = {q["id"] for c in manifest["calls"] for q in c["questions"]}
    if {r["id"] for r in rows} != expected or len(rows) != len(expected):
        raise SystemExit("labeller B must answer every pack ID exactly once")
    for name in ("prompt.txt", "manifest.json"):
        if (PKG / name).read_bytes() != (M1 / "runs/labeller_pack" / name).read_bytes():
            raise SystemExit(f"the Gemini package {name} differs from the pack's")
    with OUT.open("w") as f:
        for r in sorted(rows, key=lambda r: r["id"]):
            f.write(json.dumps({k: v for k, v in r.items() if k != "call"}) + "\n")
    shutil.copyfile(PKG / "model_log.txt", LOG)
    fills = json.loads((PKG / "fills.json").read_text())["fills"]
    summary = {
        "labeller": "B",
        "route": "Gemini app, manual (Prithvi); one chat per batch or fill file",
        "model_per_log_row": {  # as Prithvi recorded it, "(confirm)" kept where unconfirmed
            ln.split("|")[0].strip(): ln.split("|")[1].strip()
            for ln in LOG.read_text().splitlines()[1:]
        },
        "dates": sorted({ln.split("|")[2].strip() for ln in LOG.read_text().splitlines()[1:]}),
        "answers": len(rows),
        "answer_counts": {
            f"{k}:{a}": n
            for (k, a), n in sorted(Counter((r["kind"], r["answer"]) for r in rows).items())
        },
        "reasons_over_20_words": sum(1 for r in rows if r.get("reason_over_20_words")),
        "batches": 13,
        "fills": {f["fill"]: f["calls"] for f in fills},
        "answers_from_fills": sum(1 for r in rows if r["source"].startswith("answers_F")),
        "app_cut_off": "The app skipped the last 1-3 packets of every batch over ~120k tokens; "
        "those packets were re-asked, whole and unchanged, in fill files (Prithvi, 2026-11-19).",
        "set_aside": (M1 / "runs/gemini_discarded/README.txt").read_text().splitlines(),
        "prompt_sha256": hashlib.sha256((PKG / "prompt.txt").read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256((PKG / "manifest.json").read_bytes()).hexdigest(),
    }
    SUMMARY.write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: summary[k] for k in ("answers", "answer_counts", "fills")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
