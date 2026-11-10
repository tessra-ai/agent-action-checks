"""Re-score the configurations under the adjudicated truth (post hoc, after unblinding).

    python experiments/2026-10-28-airline-veto/adjudicate.py

Truth: the graders' majority, replaced by the person's answers after `review/corrections.json`
(later entries override earlier ones for the same case). Writes `results/metrics_adjudicated.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from analyze import CONFIGS, jsonl, upper95

HERE = Path(__file__).parent


def adjudicated_truth() -> dict[str, bool]:
    grade = {g["write_id"]: g for g in jsonl(HERE / "results/grades.jsonl")}
    key = {
        k["case"]: k["write_id"]
        for k in json.loads((HERE / "review/key.json").read_text())["cases"]
    }
    answers = json.loads((HERE / "review/answers.json").read_text())["answers"]
    fixes = json.loads((HERE / "review/corrections.json").read_text())["corrections"]
    final = {c: a["decision"] for c, a in answers.items()} | {
        f["case"]: f["corrected"] for f in fixes
    }
    truth = {w: g["grader_run"] for w, g in grade.items()}
    truth |= {key[c]: d == "allow" for c, d in final.items()}
    return truth


def main() -> None:
    gate = json.loads((HERE / "results/gate.json").read_text())["rows"]
    key = {
        k["write_id"]: k["case"]
        for k in json.loads((HERE / "review/key.json").read_text())["cases"]
    }
    truth = adjudicated_truth()
    out = {}
    for cfg in CONFIGS:
        ran = [r["write_id"] for r in gate if r[f"{cfg}_run"]]
        wrong = [w for w in ran if not truth[w]]
        out[cfg] = {
            "ran": len(ran),
            "wrong": len(wrong),
            "wrong_rate_upper95": upper95(len(wrong), len(ran)),
            "wrong_cases": sorted(key[w] for w in wrong if w in key),
            "wrong_unreviewed": sum(w not in key for w in wrong),
        }
    good = [w for w in truth if truth[w]]
    for k in (1, 2):
        out[f"gate_{k}"]["good_sent_back"] = sum(
            not next(r for r in gate if r["write_id"] == w)[f"gate_{k}_run"] for w in good
        )
        out[f"gate_{k}"]["good_graded"] = len(good)
    result = {
        "truth": "graders' majority, replaced by the person's answers after the corrections in "
        "review/corrections.json (post hoc, after unblinding)",
        "metrics": out,
    }
    (HERE / "results/metrics_adjudicated.json").write_text(json.dumps(result, indent=1) + "\n")
    for cfg, m in out.items():
        print(cfg, {k: v for k, v in m.items() if k != "wrong_cases"}, m["wrong_cases"])


if __name__ == "__main__":
    main()
