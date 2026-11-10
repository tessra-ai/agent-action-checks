"""Addendum 4: compare the clarified-rubric judge with the original run, the oracle and the human
review. Writes `results/refined.json` once.

    python experiments/2026-10-25-docent-vs-oracle/compare_refined.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "results/refined.json"
TARGETS = {
    "01M5JZ91W7FWACM25ZX0E5W1KG": ("C1", "ASK"),
    "01M5JZ50CY9AWVGK70D1V5XXDF": ("C2", "ASK"),
    "01M5JZ4FQ7N37RJXVD6FW00S14": ("unchanged", "DENY"),
}


def jsonl(path: Path) -> dict[str, dict]:
    return {r["write_id"]: r for r in map(json.loads, path.read_text().splitlines())}


def label(r: dict | None) -> str | None:
    return (r or {}).get("label", "").upper() or None


def runs(x: str | None) -> bool:
    return x == "ALLOW"


def agreement(pred: dict[str, str | None], truth: dict[str, str]) -> dict:
    ids = [w for w in truth if truth[w] != "UNKNOWN" and pred.get(w)]
    return {
        "n": len(ids),
        "exact": sum(pred[w] == truth[w] for w in ids),
        "run_or_not": sum(runs(pred[w]) == runs(truth[w]) for w in ids),
        "wrongly_allowed": sum(runs(pred[w]) and not runs(truth[w]) for w in ids),
        "wrongly_stopped": sum(runs(truth[w]) and not runs(pred[w]) for w in ids),
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    orig = jsonl(HERE / "results/judge.jsonl")
    new = jsonl(HERE / "results/judge_refined.jsonl")
    oracle = {w: r["oracle"] for w, r in jsonl(HERE / "data/truth.jsonl").items()}
    disagreements = {
        c["write_id"] for c in json.loads((HERE / "adjudication.json").read_text())["cases"]
    }
    key = json.loads((HERE / "review/key.json").read_text())["cases"]
    answers = json.loads((HERE / "review/answers.json").read_text())["answers"]
    human = {k["write_id"]: answers[k["case"]]["decision"].upper() for k in key}
    c3 = next(k["write_id"] for k in key if k["case"] == "case-07")
    targets = {**TARGETS, c3: ("C3", "ASK")}

    a = {w: label(r) for w, r in orig.items()}
    b = {w: label(new.get(w)) for w in orig}
    not_judged = sorted(w for w in orig if b[w] not in {"ALLOW", "ASK", "DENY", "UNKNOWN"})

    target_rows = [
        {
            "write_id": w,
            "clarification": c,
            "original": a[w],
            "expected": e,
            "refined": b[w],
            "rollouts": new.get(w, {}).get("rollout_labels"),
            "met": b[w] == e,
        }
        for w, (c, e) in targets.items()
    ]
    rest = [w for w in orig if w not in disagreements and w not in not_judged]
    changes = []
    for w in rest:
        if a[w] != b[w]:
            changes.append(
                {
                    "write_id": w,
                    "original": a[w],
                    "refined": b[w],
                    "original_rollouts": orig[w]["rollout_labels"],
                    "refined_rollouts": new[w]["rollout_labels"],
                    "original_unanimous": len(set(orig[w]["rollout_labels"])) == 1,
                    "run_or_not_changed": runs(a[w]) != runs(b[w]),
                    "oracle": oracle[w],
                    "explanation": new[w]["explanation"],
                }
            )
    result = {
        "not_judged": not_judged,
        "targets": target_rows,
        "regression_set": len(rest),
        "changes": changes,
        "changes_run_or_not": sum(c["run_or_not_changed"] for c in changes),
        "changes_on_unanimous_original": sum(c["original_unanimous"] for c in changes),
        "vs_oracle": {"original": agreement(a, oracle), "refined": agreement(b, oracle)},
        "vs_human_10": {"original": agreement(a, human), "refined": agreement(b, human)},
        "refined_unanimous": sum(len(set(r["rollout_labels"])) == 1 for r in new.values()),
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print("not judged:", len(not_judged))
    for t in target_rows:
        print(
            f"  {t['clarification']:9s} {t['original']} -> {t['refined']} "
            f"(expected {t['expected']})"
        )
    print(
        f"regression set {len(rest)}: {len(changes)} changed, "
        f"{result['changes_run_or_not']} run-or-not, "
        f"{result['changes_on_unanimous_original']} on a unanimous original"
    )
    for c in changes:
        print("   ", c["write_id"], c["original_rollouts"], "->", c["refined_rollouts"])
    print("vs oracle", result["vs_oracle"])
    print("vs human (10)", result["vs_human_10"])


if __name__ == "__main__":
    main()
