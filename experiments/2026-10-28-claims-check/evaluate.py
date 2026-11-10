"""Verify every extracted claim and compare the gates with and without the claims check.

    python experiments/2026-10-28-claims-check/evaluate.py   # once

Writes `results/verified.jsonl` (every claim with its verdict) and `results/gates.json`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).parent
VETO = HERE.parent / "2026-10-28-airline-veto"
RULES = HERE.parent / "2026-10-28-airline-rules"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(VETO))
from analyze import jsonl, upper95  # noqa: E402
from claims import verify  # noqa: E402

STORE = Path("runs/airline/export.db")
VERIFIED = HERE / "results/verified.jsonl"
OUT = HERE / "results/gates.json"
YES = 0.5


def main() -> None:
    if OUT.exists() or VERIFIED.exists():
        sys.exit("results exist; written once")
    extracted = {r["write_id"]: r for r in jsonl(HERE / "results/extracted.jsonl")}
    conn = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    verified = {}
    for w, action, args, blob in conn.execute(
        "SELECT w.write_id, w.action, w.args, b.data FROM captured_writes w "
        "JOIN pre_action_snapshots s USING (write_id) JOIN db_blobs b ON b.hash = s.agent_db_hash"
    ):
        db, args = json.loads(zlib.decompress(blob)), json.loads(args)
        ex = extracted[w]
        checked = [{**c, **verify(c, action, args, db)} for c in (ex["claims"] or [])]
        verified[w] = {
            "write_id": w,
            "action": action,
            "status": ex["status"],
            "claims": checked,
            "flagged": any(c["verdict"] == "false" for c in checked),
        }
    VERIFIED.write_text(
        "".join(json.dumps(verified[w], sort_keys=True) + "\n" for w in sorted(verified))
    )

    rules = {r["write_id"]: r for r in jsonl(RULES / "results/rules.jsonl")}
    facts = {r["write_id"]: r for r in jsonl(RULES / "results/facts.jsonl")}
    gate = {r["write_id"]: r for r in json.loads((VETO / "results/gate.json").read_text())["rows"]}
    bench = {
        r["write_id"]: r
        for r in json.loads((VETO / "results/benchmark_corrected.json").read_text())["rows"]
    }
    ids = sorted(verified)

    def claims_ok(w: str) -> bool:
        return verified[w]["status"] == "ok" and not verified[w]["flagged"]

    def rules_ok(w: str) -> bool:
        r = rules[w]["with_duplicate"]
        return not r["blocks"] and not r["needs"]

    def facts_ok(w: str) -> bool:
        p, r = facts[w]["p_yes"], rules[w]["with_duplicate"]
        if (p.get("confirmed") or 0) < YES:
            return False
        if rules[w]["action"] == "book_reservation" and (p.get("insurance_asked") or 0) < YES:
            return False
        return not ("reason_covered" in r["needs"] and (p.get("reason_covered") or 0) < YES)

    gates = {"claims": claims_ok}
    for k in (1, 2):
        gates[f"old_{k}"] = lambda w, k=k: gate[w][f"gate_{k}_run"]
        gates[f"old_claims_{k}"] = lambda w, k=k: gate[w][f"gate_{k}_run"] and claims_ok(w)
        gates[f"rules_docent_{k}"] = lambda w, k=k: rules_ok(w) and gate[w][f"docent_{k}_run"]
        gates[f"rules_claims_docent_{k}"] = lambda w, k=k: (
            rules_ok(w) and claims_ok(w) and gate[w][f"docent_{k}_run"]
        )
        gates[f"rules_facts_claims_docent_{k}"] = lambda w, k=k: (
            rules_ok(w) and facts_ok(w) and claims_ok(w) and gate[w][f"docent_{k}_run"]
        )
    truths = {
        "corrected_benchmark": {w: bench[w]["corrected_run"] for w in ids},
        "adjudicated": {w: bench[w]["adjudicated_run"] for w in ids if bench[w]["graded"]},
        "graders": {w: bench[w]["grader_run"] for w in ids if bench[w]["graded"]},
    }
    metrics = {}
    for t, truth in truths.items():
        good = [w for w in truth if truth[w]]
        metrics[t] = {}
        for g, run in gates.items():
            ran = [w for w in truth if run(w)]
            wrong = [w for w in ran if not truth[w]]
            metrics[t][g] = {
                "ran": len(ran),
                "wrong": len(wrong),
                "wrong_rate_upper95": upper95(len(wrong), len(ran)),
                "good_sent_back": sum(not run(w) for w in good),
                "good_total": len(good),
                "wrong_write_ids": wrong,
            }
    bench_truth = truths["corrected_benchmark"]
    old_wrong = sorted(
        {w for k in (1, 2) for w in ids if gate[w][f"gate_{k}_run"] and not bench_truth[w]}
    )
    gate_failures = {
        w: {
            "task": bench[w]["task_id"],
            "action": bench[w]["action"],
            "person_case": bench[w]["person_case"],
            "flagged": verified[w]["flagged"],
            "false_claims": [c for c in verified[w]["claims"] if c["verdict"] == "false"],
            "claims": verified[w]["claims"],
        }
        for w in old_wrong
    }
    false_flags = {
        t: [
            {
                "write_id": w,
                "task": bench[w]["task_id"],
                "action": bench[w]["action"],
                "false_claims": [c for c in verified[w]["claims"] if c["verdict"] == "false"],
            }
            for w in truth
            if truth[w] and verified[w]["flagged"]
        ]
        for t, truth in truths.items()
    }
    counts = {
        v: sum(c["verdict"] == v for r in verified.values() for c in r["claims"])
        for v in ("true", "false", "unverifiable")
    }
    result = {
        "extraction": {
            "ok": sum(r["status"] == "ok" for r in verified.values()),
            "writes": len(verified),
            "claims": sum(len(r["claims"]) for r in verified.values()),
            "verdicts": counts,
            "flagged_writes": sum(r["flagged"] for r in verified.values()),
        },
        "metrics": metrics,
        "gate_failures": gate_failures,
        "false_flags": false_flags,
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["extraction"]))
    for t in truths:
        print(f"== {t}")
        for g, m in metrics[t].items():
            print(
                f"  {g:30s} ran {m['ran']:3d} wrong {m['wrong']:3d} "
                f"upper95 {m['wrong_rate_upper95']} "
                f"sent back {m['good_sent_back']}/{m['good_total']}"
            )


if __name__ == "__main__":
    main()
