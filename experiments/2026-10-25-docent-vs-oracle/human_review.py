"""Addendum 3A: compare the human review with both graders. Writes `results/human_review.json` once.

python experiments/2026-10-25-docent-vs-oracle/human_review.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "results/human_review.json"


def runs(label: str) -> bool:
    return label.upper() == "ALLOW"


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    key = json.loads((HERE / "review/key.json").read_text())["cases"]
    answers = json.loads((HERE / "review/answers.json").read_text())["answers"]
    adj = {
        c["write_id"]: c["class"]
        for c in json.loads((HERE / "adjudication.json").read_text())["cases"]
    }
    rows = []
    for k in key:
        h = answers[k["case"]]["decision"].upper()
        rows.append(
            {
                **k,
                "human": h,
                "human_exact_oracle": h == k["oracle"],
                "human_exact_docent": h == k["docent"],
                "human_run_matches_oracle": runs(h) == runs(k["oracle"]),
                "human_run_matches_docent": runs(h) == runs(k["docent"]),
                "claude_provisional": adj.get(k["write_id"]),
            }
        )
    dis = [r for r in rows if r["role"] == "disagreement"]
    split = [r for r in dis if runs(r["oracle"]) != runs(r["docent"])]
    result = {
        "controls_human_matches_both_exactly": sum(
            r["human_exact_oracle"] for r in rows if r["role"] == "control"
        ),
        "run_vs_stop_disagreements": len(split),
        "human_sides_with_docent": sum(r["human_run_matches_docent"] for r in split),
        "human_sides_with_oracle": sum(r["human_run_matches_oracle"] for r in split),
        "severity_disagreements": len(dis) - len(split),
        "human_exact_docent_on_severity": sum(
            r["human_exact_docent"] for r in dis if r not in split
        ),
        "human_exact_oracle_on_severity": sum(
            r["human_exact_oracle"] for r in dis if r not in split
        ),
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    for r in rows:
        print(
            f"{r['case']} {r['role']:12s} oracle {r['oracle']:7s} docent {r['docent']:5s} "
            f"human {r['human']:7s} claude {r['claude_provisional']}"
        )
    print({k: v for k, v in result.items() if k != "rows"})


if __name__ == "__main__":
    main()
