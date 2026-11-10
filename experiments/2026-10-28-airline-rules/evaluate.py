"""Compare the gates of README.md against the three truths, and audit every rule block.

    python experiments/2026-10-28-airline-rules/evaluate.py   # once

Writes `results/gates.json`.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
VETO = HERE.parent / "2026-10-28-airline-veto"
sys.path.insert(0, str(VETO))
from analyze import jsonl, upper95  # noqa: E402

OUT = HERE / "results/gates.json"
YES = 0.5


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    rules = {r["write_id"]: r for r in jsonl(HERE / "results/rules.jsonl")}
    facts = {r["write_id"]: r for r in jsonl(HERE / "results/facts.jsonl")}
    gate = {r["write_id"]: r for r in json.loads((VETO / "results/gate.json").read_text())["rows"]}
    bench = {
        r["write_id"]: r
        for r in json.loads((VETO / "results/benchmark_corrected.json").read_text())["rows"]
    }
    ids = sorted(rules)

    def facts_ok(w: str) -> bool:
        p = facts[w]["p_yes"]
        if facts[w]["status"] != "ok" or (p.get("confirmed") or 0) < YES:
            return False
        if rules[w]["action"] == "book_reservation" and (p.get("insurance_asked") or 0) < YES:
            return False
        needs = rules[w]["with_duplicate"]["needs"]
        return not ("reason_covered" in needs and (p.get("reason_covered") or 0) < YES)

    def rules_ok(w: str, dup: bool = True) -> bool:
        r = rules[w]["with_duplicate" if dup else "without_duplicate"]
        return not r["blocks"] and not r["needs"]

    def rules_facts_ok(w: str, dup: bool = True) -> bool:
        r = rules[w]["with_duplicate" if dup else "without_duplicate"]
        return not r["blocks"] and facts_ok(w)

    gates = {
        "rules": lambda w: rules_ok(w),
        "rules_no_duplicate": lambda w: rules_ok(w, dup=False),
        "rules_facts": lambda w: rules_facts_ok(w),
        "rules_facts_no_duplicate": lambda w: rules_facts_ok(w, dup=False),
    }
    for k in (1, 2):
        gates[f"old_{k}"] = lambda w, k=k: gate[w][f"gate_{k}_run"]
        gates[f"docent_{k}"] = lambda w, k=k: gate[w][f"docent_{k}_run"]
        gates[f"rules_docent_{k}"] = lambda w, k=k: rules_ok(w) and gate[w][f"docent_{k}_run"]
        gates[f"rules_facts_docent_{k}"] = lambda w, k=k: (
            rules_facts_ok(w) and gate[w][f"docent_{k}_run"]
        )
        gates[f"rules_old_{k}"] = lambda w, k=k: rules_facts_ok(w) and gate[w][f"gate_{k}_run"]
    gates["jev_policy_ok"] = lambda w: gate[w]["jev_run"]

    truths = {
        "corrected_benchmark": {w: bench[w]["corrected_run"] for w in ids},
        "adjudicated": {w: bench[w]["adjudicated_run"] for w in ids if bench[w]["graded"]},
        "graders": {w: bench[w]["grader_run"] for w in ids if bench[w]["graded"]},
    }
    metrics = {}
    for tname, truth in truths.items():
        metrics[tname] = {}
        good = [w for w in truth if truth[w]]
        for gname, run in gates.items():
            ran = [w for w in truth if run(w)]
            wrong = [w for w in ran if not truth[w]]
            metrics[tname][gname] = {
                "ran": len(ran),
                "wrong": len(wrong),
                "wrong_rate_upper95": upper95(len(wrong), len(ran)),
                "good_sent_back": sum(not run(w) for w in good),
                "good_total": len(good),
                "wrong_write_ids": wrong,
            }

    per_rule = {}
    fired = Counter(b["rule"] for w in ids for b in rules[w]["with_duplicate"]["blocks"])
    for rule in sorted(fired):
        hits = [
            w for w in ids if any(b["rule"] == rule for b in rules[w]["with_duplicate"]["blocks"])
        ]
        per_rule[rule] = {
            "fires": len(hits),
            "only_rule": sum(len(rules[w]["with_duplicate"]["blocks"]) == 1 for w in hits),
            "false_blocks": {
                t: [w for w in hits if truth.get(w) is True] for t, truth in truths.items()
            },
        }
    caught = {}
    for t in ("corrected_benchmark", "adjudicated"):
        old_wrong = sorted(
            set(metrics[t]["old_1"]["wrong_write_ids"])
            | set(metrics[t]["old_2"]["wrong_write_ids"])
        )
        caught[t] = {
            w: {
                "task": bench[w]["task_id"],
                "action": bench[w]["action"],
                "rules": [b["rule"] for b in rules[w]["with_duplicate"]["blocks"]],
                "needs": rules[w]["with_duplicate"]["needs"],
                "facts": facts[w]["p_yes"],
            }
            for w in old_wrong
        }
    blocks = [
        {
            "write_id": w,
            "task": bench[w]["task_id"],
            "action": rules[w]["action"],
            "blocks": rules[w]["with_duplicate"]["blocks"],
            "corrected_benchmark": truths["corrected_benchmark"][w],
            "adjudicated": truths["adjudicated"].get(w),
            "graders": truths["graders"].get(w),
            "grader_labels": bench[w]["grader_labels"],
        }
        for w in ids
        if rules[w]["with_duplicate"]["blocks"]
    ]
    fact_counts = {
        q: Counter(
            "yes" if (facts[w]["p_yes"].get(q) or 0) >= YES else "no"
            for w in ids
            if q in facts[w]["p_yes"]
        )
        for q in ("confirmed", "insurance_asked", "reason_covered")
    }
    result = {
        "metrics": metrics,
        "per_rule": per_rule,
        "old_gate_wrong_runs": caught,
        "fact_counts": fact_counts,
        "blocks": blocks,
    }
    OUT.write_text(json.dumps(result, indent=1, default=dict) + "\n")
    for t in truths:
        print(f"== {t}")
        for g, m in metrics[t].items():
            print(
                f"  {g:26s} ran {m['ran']:3d} wrong {m['wrong']:3d} "
                f"upper95 {m['wrong_rate_upper95']} "
                f"sent back {m['good_sent_back']}/{m['good_total']}"
            )


if __name__ == "__main__":
    main()
