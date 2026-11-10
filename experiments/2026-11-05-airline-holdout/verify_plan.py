"""Verify the plan-aware claims of one set and score the check against its truths.

    python experiments/2026-11-05-airline-holdout/verify_plan.py airline1 | airline2 | retail

Reads `results/claims_<set>.jsonl`; writes `results/claims_<set>_verified.jsonl` and
`results/claims_<set>_metrics.json`. Truths: airline1, the corrected benchmark and the
adjudicated truth of the first capture; airline2, the graders and the corrected benchmark of
this capture; retail, the oracle. Catches that must stay flagged are listed per set.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
EXP = HERE.parent
sys.path.insert(0, str(HERE))
from claims_plan import domain, load, plan_verdict  # noqa: E402
from extract_plan import SETS  # noqa: E402

CATCHES = {
    "airline1": {
        "01M61PYGRX51BXSSZ4R86R0CQH": "case 14, task 25: price and certificate remainder",
        "01M61Q0HD0F0DNRS5WWVBVESGP": "case 13, task 35: second cheapest",
    },
    "airline2": {},
    "retail": {"01M5JZ4FQ7N37RJXVD6FW00S14": "task 12: the Gaming Mouse"},
}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def calls(name: str) -> dict[str, dict]:
    out = {}
    for path in SETS[name][1]:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for w, sess, seq, action, args, blob in conn.execute(
            "SELECT w.write_id, w.session_id, w.seq, w.action, w.args, b.data FROM "
            "captured_writes w JOIN pre_action_snapshots s USING (write_id) "
            "JOIN db_blobs b ON b.hash = s.agent_db_hash"
        ):
            out[w] = {
                "session": sess,
                "seq": seq,
                "call": (action, json.loads(args), json.loads(zlib.decompress(blob))),
            }
    return out


def truths(name: str, ids) -> dict[str, dict[str, bool]]:
    if name == "airline1":
        bench = {
            r["write_id"]: r
            for r in json.loads(
                (EXP / "2026-10-28-airline-veto/results/benchmark_corrected.json").read_text()
            )["rows"]
        }
        return {
            "corrected_benchmark": {w: bench[w]["corrected_run"] for w in ids if w in bench},
            "adjudicated": {
                w: bench[w]["adjudicated_run"] for w in ids if w in bench and bench[w]["graded"]
            },
        }
    if name == "airline2":
        out = {}
        g = HERE / "results/grades.jsonl"
        if g.exists():
            grade = {r["write_id"]: r for r in jsonl(g)}
            out["graders"] = {w: grade[w]["grader_run"] for w in ids if w in grade}
        b = HERE / "results/benchmark_corrected.json"
        if b.exists():
            bench = {r["write_id"]: r for r in json.loads(b.read_text())["rows"]}
            out["corrected_benchmark"] = {w: bench[w]["corrected_run"] for w in ids if w in bench}
        return out
    oracle = {r["write_id"]: r for r in jsonl(EXP / "2026-10-25-docent-vs-oracle/data/truth.jsonl")}
    return {
        "oracle": {
            w: oracle[w]["oracle"] == "ALLOW"
            for w in ids
            if w in oracle and oracle[w]["oracle"] in ("ALLOW", "ASK", "DENY")
        }
    }


def main(name: str) -> None:
    out_v = HERE / f"results/claims_{name}_verified.jsonl"
    out_m = HERE / f"results/claims_{name}_metrics.json"
    if out_v.exists() or out_m.exists():
        sys.exit("results exist; written once")
    dom = SETS[name][0]
    mod, _, _ = domain(dom)
    plan_eval = load("plan_eval", EXP / "2026-11-05-plan-level-claims/evaluate.py")
    list_match = (
        plan_eval.airline_list_match(mod) if dom == "airline" else plan_eval.retail_list_match(mod)
    )
    plan_rules = load("plan_rules", EXP / "2026-11-05-plan-level-claims/plan.py")
    extracted = {r["write_id"]: r for r in jsonl(HERE / f"results/claims_{name}.jsonl")}
    if name == "airline2":  # README, Deviations: score only the 122 exported writes, not the 6
        kept = {r["write_id"] for r in jsonl(HERE / "data/meta.jsonl")}  # from failed simulations
        extracted = {w: r for w, r in extracted.items() if w in kept}
    info = calls(name)
    sessions = defaultdict(list)
    for w, r in info.items():
        sessions[r["session"]].append((w, r["seq"], r["call"]))
    verified = {}
    for w, ex in extracted.items():
        r = info[w]
        own = r["call"]
        others = plan_rules.plan_calls(
            (w, r["seq"], own[0], own[1]), sessions[r["session"]], so_far=False
        )
        claims = [
            {**c, **plan_verdict(c, own, others, mod.verify, list_match)}
            for c in (ex["claims"] or [])
        ]
        verified[w] = {
            "write_id": w,
            "action": own[0],
            "status": ex["status"],
            "plan_size": len(others),
            "claims": claims,
            "flagged": any(c["verdict"] == "false" for c in claims),
        }
    out_v.write_text("".join(json.dumps(verified[w], sort_keys=True) + "\n" for w in extracted))
    metrics = {
        "writes": len(verified),
        "extracted_ok": sum(v["status"] == "ok" for v in verified.values()),
        "claims": sum(len(v["claims"]) for v in verified.values()),
        "verdicts": dict(Counter(c["verdict"] for v in verified.values() for c in v["claims"])),
        "scopes": dict(Counter(c.get("scope") for v in verified.values() for c in v["claims"])),
        "plan_reasons": dict(
            Counter(c.get("plan") for v in verified.values() for c in v["claims"] if c.get("plan"))
        ),
        "flagged_writes": sum(v["flagged"] for v in verified.values()),
        "catches": {
            w: {"what": what, "flagged": verified[w]["flagged"]}
            for w, what in CATCHES[name].items()
            if w in verified
        },
        "by_truth": {},
    }
    for tname, truth in truths(name, list(verified)).items():
        good = [w for w in truth if truth[w]]
        stop = [w for w in truth if not truth[w]]
        metrics["by_truth"][tname] = {
            "good_total": len(good),
            "good_flagged": sum(verified[w]["flagged"] for w in good),
            "good_flagged_ids": sorted(w for w in good if verified[w]["flagged"]),
            "stop_total": len(stop),
            "stop_flagged": sum(verified[w]["flagged"] for w in stop),
        }
    out_m.write_text(json.dumps(metrics, indent=1) + "\n")
    print(json.dumps({k: v for k, v in metrics.items() if k != "by_truth"}, indent=1))
    for t, m in metrics["by_truth"].items():
        print(
            f"{t}: good flagged {m['good_flagged']}/{m['good_total']}; stop flagged "
            f"{m['stop_flagged']}/{m['stop_total']}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SETS:
        sys.exit(__doc__)
    main(sys.argv[1])
