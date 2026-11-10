"""Addendum 5: how much of Addendum 4's change is run-to-run noise? Writes `results/control.json`
once.

    python experiments/2026-10-25-docent-vs-oracle/compare_control.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from compare_refined import agreement, jsonl, label, runs

HERE = Path(__file__).parent
OUT = HERE / "results/control.json"


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    orig = jsonl(HERE / "results/judge.jsonl")
    control = jsonl(HERE / "results/judge_control.jsonl")
    refined = json.loads((HERE / "results/refined.json").read_text())
    oracle = {w: r["oracle"] for w, r in jsonl(HERE / "data/truth.jsonl").items()}
    disagreements = {
        c["write_id"] for c in json.loads((HERE / "adjudication.json").read_text())["cases"]
    }
    a = {w: label(r) for w, r in orig.items()}
    c = {w: label(control.get(w)) for w in orig}
    rest = [w for w in orig if w not in disagreements and c[w]]
    noise = [
        {
            "write_id": w,
            "original": a[w],
            "control": c[w],
            "original_rollouts": orig[w]["rollout_labels"],
            "control_rollouts": control[w]["rollout_labels"],
            "run_or_not_changed": runs(a[w]) != runs(c[w]),
            "oracle": oracle[w],
        }
        for w in rest
        if a[w] != c[w]
    ]
    per_change = [
        {
            "write_id": ch["write_id"],
            "original": ch["original"],
            "refined": ch["refined"],
            "control": c[ch["write_id"]],
            "control_rollouts": control[ch["write_id"]]["rollout_labels"],
            "control_same_change": c[ch["write_id"]] == ch["refined"],
            "oracle": ch["oracle"],
        }
        for ch in refined["changes"]
    ]
    result = {
        "not_judged": sorted(w for w in orig if not c[w]),
        "regression_set": len(rest),
        "noise_changes": len(noise),
        "noise_changes_run_or_not": sum(n["run_or_not_changed"] for n in noise),
        "noise": noise,
        "refined_changes_checked": per_change,
        "vs_oracle": {
            "original": refined["vs_oracle"]["original"],
            "control": agreement(c, oracle),
            "refined": refined["vs_oracle"]["refined"],
        },
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(f"not judged: {len(result['not_judged'])}")
    print(
        f"control vs original on {len(rest)}: {len(noise)} changed, "
        f"{result['noise_changes_run_or_not']} run-or-not"
    )
    for n in noise:
        print("   ", n["write_id"], n["original_rollouts"], "->", n["control_rollouts"])
    print("refined changes, does the control make the same change?")
    for p in per_change:
        print(
            f"    {p['write_id']} {p['original']} -> refined {p['refined']}, "
            f"control {p['control']} {p['control_rollouts']} oracle {p['oracle']}"
        )
    for k, v in result["vs_oracle"].items():
        print(k, v)


if __name__ == "__main__":
    main()
