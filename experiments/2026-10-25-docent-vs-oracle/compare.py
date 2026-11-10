"""Step 3 (project venv): compare Docent's judge with the oracle; metrics as preregistered in
README.md. Writes `results/comparison.json` once.

    python experiments/2026-10-25-docent-vs-oracle/compare.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
TRUTH = Path("runs/docent/truth.jsonl")
JUDGE = HERE / "results/judge.jsonl"
OUT = HERE / "results/comparison.json"
LABELS = ("ALLOW", "ASK", "DENY", "UNKNOWN")


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    truth = {r["write_id"]: r for r in map(json.loads, TRUTH.read_text().splitlines())}
    judge = {r["write_id"]: r for r in map(json.loads, JUDGE.read_text().splitlines())}
    assert set(truth) == set(judge), "write ids differ"
    rows = []
    for wid, t in truth.items():
        j = judge[wid]
        rows.append(
            {
                "write_id": wid,
                "store": t["store"],
                "action": t["action"],
                "task_id": t["task_id"],
                "agent_model": t["agent_model"],
                "oracle": t["oracle"],
                "judge": (j["label"] or "missing").upper(),
                "rollouts": [str(x).upper() for x in j["rollout_labels"]],
                "benchmark_match": t["benchmark_match"],
                "execution_outcome": t["execution_outcome"],
                "oracle_reasons": t["reason_codes"],
                "oracle_explanation": t["explanation"],
                "judge_explanation": j["explanation"],
            }
        )
    scored = [r for r in rows if r["oracle"] != "UNKNOWN"]
    o = [r["oracle"] for r in scored]
    g = [r["judge"] for r in scored]
    confusion = {
        a: {b: sum(1 for r in scored if r["oracle"] == a and r["judge"] == b) for b in LABELS}
        for a in LABELS[:3]
    }
    allow_o = [x == "ALLOW" for x in o]
    allow_g = [x == "ALLOW" for x in g]
    false_allows = [r for r in scored if r["oracle"] != "ALLOW" and r["judge"] == "ALLOW"]
    over_esc = [r for r in scored if r["oracle"] == "ALLOW" and r["judge"] != "ALLOW"]
    by_action = {}
    for act in sorted({r["action"] for r in scored}):
        rs = [r for r in scored if r["action"] == act]
        by_action[act] = {
            "n": len(rs),
            "agree_4class": sum(r["oracle"] == r["judge"] for r in rs),
            "agree_binary": sum((r["oracle"] == "ALLOW") == (r["judge"] == "ALLOW") for r in rs),
            "judge_false_allows": sum(r["oracle"] != "ALLOW" and r["judge"] == "ALLOW" for r in rs),
            "judge_over_escalations": sum(
                r["oracle"] == "ALLOW" and r["judge"] != "ALLOW" for r in rs
            ),
        }
    unanimous = sum(len(set(r["rollouts"])) == 1 for r in rows)
    claim = [
        r
        for r in rows
        if r["store"] == "smoke2" and r["benchmark_match"] == "MATCH" and r["oracle"] != "ALLOW"
    ]
    result = {
        "n_writes": len(rows),
        "n_scored": len(scored),
        "oracle_unknown": [
            {k: r[k] for k in ("write_id", "action", "judge", "rollouts")}
            for r in rows
            if r["oracle"] == "UNKNOWN"
        ],
        "agreement_4class": sum(a == b for a, b in zip(o, g, strict=True)),
        "kappa_4class": kappa(o, g),
        "agreement_binary": sum(a == b for a, b in zip(allow_o, allow_g, strict=True)),
        "kappa_binary": kappa([str(x) for x in allow_o], [str(x) for x in allow_g]),
        "oracle_counts": dict(Counter(o)),
        "judge_counts": dict(Counter(g)),
        "confusion_oracle_rows_judge_cols": confusion,
        "judge_false_allows": len(false_allows),
        "oracle_escalates": sum(x != "ALLOW" for x in o),
        "judge_over_escalations": len(over_esc),
        "oracle_allows": sum(x == "ALLOW" for x in o),
        "by_action": by_action,
        "rollouts_unanimous": unanimous,
        "claim_writes": [
            {
                k: r[k]
                for k in (
                    "write_id",
                    "action",
                    "oracle",
                    "judge",
                    "rollouts",
                    "oracle_reasons",
                    "judge_explanation",
                )
            }
            for r in claim
        ],
        "disagreements": [r for r in rows if r["oracle"] != r["judge"]],
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("rows", "disagreements", "claim_writes")},
            indent=1,
        )
    )
    print(
        "claim writes:",
        [(c["action"], c["oracle"], c["judge"], c["rollouts"]) for c in result["claim_writes"]],
    )


if __name__ == "__main__":
    main()
