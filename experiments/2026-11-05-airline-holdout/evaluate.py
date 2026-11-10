"""Every arm against both truths on the held-out capture (README.md, Metrics). No model calls.

    python experiments/2026-11-05-airline-holdout/evaluate.py   # once

Arms: Jev alone, each Docent run alone, the veto gate (both runs), the retail cascade; the
hand-written rules (blocks only, with and without the inferred duplicate-seat rule); the Claude
draft; the plan-aware claims check; and the stacks rules + Docent and rules + claims + Docent.
Truths: the blind graders (graded writes) and the corrected τ² benchmark (all writes).
Writes `results/metrics.json`.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from analyze import jsonl, upper95  # noqa: E402

OUT = HERE / "results/metrics.json"


def score(run: dict[str, bool], truth: dict[str, bool]) -> dict:
    ran = [w for w in truth if run.get(w)]
    wrong = [w for w in ran if not truth[w]]
    good = [w for w in truth if truth[w]]
    return {
        "ran": len(ran),
        "wrong": len(wrong),
        "wrong_rate_upper95": upper95(len(wrong), len(ran)) if ran else None,
        "good_sent_back": sum(not run.get(w) for w in good),
        "good_total": len(good),
        "wrong_write_ids": sorted(wrong),
    }


def main() -> None:
    if OUT.exists():
        sys.exit("results exist; written once")
    gate = {r["write_id"]: r for r in json.loads((HERE / "results/gate.json").read_text())["rows"]}
    ids = sorted(gate)
    grade = {r["write_id"]: r for r in jsonl(HERE / "results/grades.jsonl")}
    bench = {
        r["write_id"]: r
        for r in json.loads((HERE / "results/benchmark_corrected.json").read_text())["rows"]
    }
    hand = {r["write_id"]: r for r in jsonl(HERE / "results/rules_hand.jsonl")}
    claude = {r["write_id"]: r for r in jsonl(HERE / "results/rules_claude.jsonl")}
    claims = {r["write_id"]: r for r in jsonl(HERE / "results/claims_airline2_verified.jsonl")}
    truths = {
        "graders": {w: grade[w]["grader_run"] for w in ids if w in grade},
        "corrected_benchmark": {w: bench[w]["corrected_run"] for w in ids},
    }
    arms: dict[str, dict[str, bool]] = {
        "jev": {w: gate[w]["jev_run"] for w in ids},
        "hand_rules": {w: not hand[w]["with_duplicate"]["blocks"] for w in ids},
        "hand_rules_no_duplicate": {w: not hand[w]["without_duplicate"]["blocks"] for w in ids},
        "claude_rules": {w: not claude[w]["blocks"] for w in ids},
        "claims": {w: not claims[w]["flagged"] for w in ids},
    }
    for k in (1, 2):
        arms[f"docent_{k}"] = {w: gate[w][f"docent_{k}_run"] for w in ids}
        arms[f"gate_{k}"] = {w: gate[w][f"gate_{k}_run"] for w in ids}
        arms[f"cascade_{k}"] = {w: gate[w][f"cascade_{k}_run"] for w in ids}
        for rules in ("hand_rules", "claude_rules"):
            arms[f"{rules}_docent_{k}"] = {
                w: arms[rules][w] and gate[w][f"docent_{k}_run"] for w in ids
            }
            arms[f"{rules}_claims_docent_{k}"] = {
                w: arms[rules][w] and arms["claims"][w] and gate[w][f"docent_{k}_run"] for w in ids
            }
    metrics = {t: {a: score(arms[a], truth) for a in arms} for t, truth in truths.items()}
    graded = [w for w in ids if w in grade]
    result = {
        "writes": len(ids),
        "graded": len(graded),
        "truth_agreement_on_graded": sum(
            truths["graders"][w] == truths["corrected_benchmark"][w] for w in graded
        ),
        "truth_disagreements": [
            {
                "write_id": w,
                "task": bench[w]["task_id"],
                "action": bench[w]["action"],
                "class": bench[w]["class"],
                "corrected_run": bench[w]["corrected_run"],
                "grader_labels": grade[w]["labels"],
            }
            for w in graded
            if truths["graders"][w] != truths["corrected_benchmark"][w]
        ],
        "benchmark_classes": dict(Counter(bench[w]["class"] for w in ids)),
        "metrics": metrics,
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(
        f"writes {len(ids)}, graded {len(graded)}, truths agree on "
        f"{result['truth_agreement_on_graded']} of {len(graded)}"
    )
    for t in truths:
        print(t)
        for a, m in metrics[t].items():
            print(
                f"  {a:30s} ran {m['ran']:3d} wrong {m['wrong']:2d} "
                f"(ub {m['wrong_rate_upper95']}) good sent back "
                f"{m['good_sent_back']:2d}/{m['good_total']}"
            )


if __name__ == "__main__":
    main()
