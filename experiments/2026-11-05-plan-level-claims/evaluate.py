"""Re-verify every extracted claim at plan level, both variants, both domains (README.md).

python experiments/2026-11-05-plan-level-claims/evaluate.py   # once
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
AIR = HERE.parent / "2026-10-28-claims-check"
VETO = HERE.parent / "2026-10-28-airline-veto"
RET = HERE.parent / "2026-11-05-claims-check-retail"
ORACLE = HERE.parent / "2026-10-25-docent-vs-oracle"
sys.path.insert(0, str(HERE))
from plan import plan_calls, plan_verdict  # noqa: E402

OUT = HERE / "results/metrics.json"
CATCHES = {
    "airline": {
        "01M61PYGRX51BXSSZ4R86R0CQH": "case 14, task 25: price and certificate remainder",
        "01M61Q0HD0F0DNRS5WWVBVESGP": "case 13, task 35: second cheapest",
    },
    "retail": {"01M5JZ4FQ7N37RJXVD6FW00S14": "task 12: the Gaming Mouse"},
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def store_rows(path: Path) -> dict[str, dict]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = {}
    for w, sess, seq, action, args, blob in conn.execute(
        "SELECT w.write_id, w.session_id, w.seq, w.action, w.args, b.data FROM captured_writes w "
        "JOIN pre_action_snapshots s USING (write_id) JOIN db_blobs b ON b.hash = s.agent_db_hash"
    ):
        out[w] = {
            "session": sess,
            "seq": seq,
            "action": action,
            "args": json.loads(args),
            "db": json.loads(zlib.decompress(blob)),
        }
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def airline_list_match(air):
    def match(claim, own, union):
        kind = claim.get("kind")
        if kind == "flights":
            said = {(f["flight_number"], f.get("date")) for f in claim.get("flights") or []}
            pairs = {tuple(x) for x in union}
            return (
                bool(said)
                and {n for n, _ in said} == {n for n, _ in pairs}
                and all(d is None or (n, d) in pairs for n, d in said)
            )
        if kind == "payment_method":
            action, args, db = own
            pid = air.resolve_payment(claim.get("payment"), air.user_of(action, args, db))
            return pid is not None and pid in union
        return None

    return match


def retail_list_match(ret):
    def match(claim, own, union):
        kind = claim.get("kind")
        if kind == "items":
            if claim.get("item_ids"):
                return sorted(claim["item_ids"]) == sorted(union)
            if claim.get("item_names"):
                return sorted(_norm(n) for n in claim["item_names"]) == sorted(union)
            return False
        if kind == "payment_method":
            action, args, db = own
            pid = ret.resolve_payment(
                claim.get("payment"), ret.user_of(action, args, db), ret.order_of(args, db)
            )
            return pid is not None and pid in union
        return None

    return match


def run_domain(name, rows, verified, verify, list_match, variants):
    sessions = defaultdict(list)
    for w, r in rows.items():
        sessions[r["session"]].append((w, r["seq"], (r["action"], r["args"], r["db"])))
    out = {}
    for variant, so_far in variants.items():
        res = {}
        for w, v in verified.items():
            r = rows[w]
            own = (r["action"], r["args"], r["db"])
            others = plan_calls(
                (w, r["seq"], r["action"], r["args"]), sessions[r["session"]], so_far
            )
            claims = [
                {**c, **plan_verdict(c, own, others, verify, list_match)} for c in v["claims"]
            ]
            res[w] = {
                "write_id": w,
                "action": r["action"],
                "plan_size": len(others),
                "own_target": r["args"].get("reservation_id") or r["args"].get("order_id") or "",
                "claims": claims,
                "flagged_before": v["flagged"],
                "flagged": any(c["verdict"] == "false" for c in claims),
            }
        (HERE / "results").mkdir(exist_ok=True)
        (HERE / f"results/{name}_{variant}.jsonl").write_text(
            "".join(json.dumps(res[w], sort_keys=True) + "\n" for w in verified)
        )
        out[variant] = res
    return out


def summarize(res, truths, catches, prior_class):
    out = {}
    for tname, truth in truths.items():
        good = [w for w in truth if truth[w]]
        stop = [w for w in truth if not truth[w]]
        removed = [w for w in good if res[w]["flagged_before"] and not res[w]["flagged"]]
        out[tname] = {
            "good_total": len(good),
            "good_flagged_before": sum(res[w]["flagged_before"] for w in good),
            "good_flagged_after": sum(res[w]["flagged"] for w in good),
            "good_flags_removed": {w: prior_class.get(w) for w in removed},
            "stop_total": len(stop),
            "stop_flagged_before": sum(res[w]["flagged_before"] for w in stop),
            "stop_flagged_after": sum(res[w]["flagged"] for w in stop),
            "stop_flags_removed": [
                w for w in stop if res[w]["flagged_before"] and not res[w]["flagged"]
            ],
        }
    out["catches"] = {
        w: {"what": what, "before": res[w]["flagged_before"], "after": res[w]["flagged"]}
        for w, what in catches.items()
    }
    out["plan_reasons"] = dict(
        Counter(c["plan"] for v in res.values() for c in v["claims"] if c.get("plan"))
    )
    out["flagged_before"] = sum(v["flagged_before"] for v in res.values())
    out["flagged_after"] = sum(v["flagged"] for v in res.values())
    return out


def main() -> None:
    if OUT.exists():
        sys.exit("results exist; written once")
    variants = {"plan_all": False, "plan_so_far": True}
    air = load("air_claims", AIR / "claims.py")
    ret = load("ret_claims", RET / "claims_retail.py")

    # airline
    rows = store_rows(Path("runs/airline/export.db"))
    verified = {r["write_id"]: r for r in jsonl(AIR / "results/verified.jsonl")}
    bench = {
        r["write_id"]: r
        for r in json.loads((VETO / "results/benchmark_corrected.json").read_text())["rows"]
    }
    air_truths = {
        "corrected_benchmark": {w: bench[w]["corrected_run"] for w in verified},
        "adjudicated": {w: bench[w]["adjudicated_run"] for w in verified if bench[w]["graded"]},
    }
    # the task 11 real misstatement: the refund quoted at $1,444
    for w, v in verified.items():
        if any(c["kind"] == "refund" and c.get("amount") == 1444 for c in v["claims"]):
            CATCHES["airline"][w] = "task 11: refund quoted at $1,444, the call refunds $5,244"
    air_res = run_domain("airline", rows, verified, air.verify, airline_list_match(air), variants)
    air_prior = {w: f"task {bench[w]['task_id']}" for w in verified}

    # retail
    rows = {**store_rows(Path("runs/targeted.db")), **store_rows(Path("runs/smoke2.db"))}
    verified = {r["write_id"]: r for r in jsonl(RET / "results/verified.jsonl")}
    oracle = {r["write_id"]: r for r in jsonl(ORACLE / "data/truth.jsonl")}
    ret_truths = {
        "oracle": {
            w: oracle[w]["oracle"] == "ALLOW"
            for w in verified
            if oracle[w]["oracle"] in ("ALLOW", "ASK", "DENY")
        }
    }
    flags = json.loads((RET / "review/flags.json").read_text())
    ret_prior = {f["write_id"]: f["classification"] for f in flags}
    ret_res = run_domain("retail", rows, verified, ret.verify, retail_list_match(ret), variants)

    metrics = {
        "airline": {
            v: summarize(air_res[v], air_truths, CATCHES["airline"], air_prior) for v in variants
        },
        "retail": {
            v: summarize(ret_res[v], ret_truths, CATCHES["retail"], ret_prior) for v in variants
        },
    }
    OUT.write_text(json.dumps(metrics, indent=1) + "\n")
    for dom in metrics:
        for v in variants:
            m = metrics[dom][v]
            for t, s in m.items():
                if isinstance(s, dict) and "good_total" in s:
                    print(
                        f"{dom} {v} {t}: good flagged {s['good_flagged_before']}->"
                        f"{s['good_flagged_after']} of {s['good_total']}; stop flagged "
                        f"{s['stop_flagged_before']}->{s['stop_flagged_after']} "
                        f"of {s['stop_total']}"
                    )
            kept = [(c["what"][:20], c["before"], c["after"]) for c in m["catches"].values()]
            print(f"  catches: {kept}")
            print(f"  reasons: {m['plan_reasons']}")


if __name__ == "__main__":
    main()
