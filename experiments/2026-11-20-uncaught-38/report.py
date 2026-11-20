"""Builds the table for Report.md from neither_38.json and types.json. EXPLORATORY, MODEL-READ."""

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
d = {x["pid"]: x for x in json.loads((HERE / "neither_38.json").read_text())}
t = json.loads((HERE / "types.json").read_text())
assert set(t["actions"]) == set(d), set(d) ^ set(t["actions"])
undeclared = {ty for ty, _ in t["actions"].values()} - set(t["types"])
if undeclared:
    raise SystemExit(f"undeclared types in types.json: {sorted(undeclared)}")
STOP = ("deny", "ask")


def stops(label):
    if label is None:
        raise SystemExit("a rubric judge result is missing")
    return label in STOP


rows = defaultdict(list)
for pid, (ty, _why) in t["actions"].items():
    rows[ty].append(pid)
out = []
for ty, name in t["types"].items():
    ps = rows.get(ty, [])
    if not ps:
        continue
    air = [p for p in ps if d[p]["domain"] == "airline"]
    ret = [p for p in ps if d[p]["domain"] == "retail"]
    blocked = [p for p in air if d[p]["rules_16"]["blocks"]]
    rule_names = sorted({b["rule"] for p in air for b in d[p]["rules_16"]["blocks"]})
    j_both = sum(
        stops(d[p]["rubric_judge"]["run_1"]) and stops(d[p]["rubric_judge"]["run_2"]) for p in air
    )
    j_one = sum(
        (stops(d[p]["rubric_judge"]["run_1"])) != (stops(d[p]["rubric_judge"]["run_2"]))
        for p in air
    )
    r_stop = sum(stops(d[p]["rubric_judge"]["original"]) for p in ret)
    r_stop_ref = sum(stops(d[p]["rubric_judge"]["refined"]) for p in ret)
    out.append(
        {
            "type": ty,
            "name": name,
            "n": len(ps),
            "pids": ps,
            "airline": len(air),
            "retail": len(ret),
            "rules_block": f"{len(blocked)} of {len(air)}"
            if air
            else "n/a (retail: no hand-written rules)",
            "rules": rule_names,
            "judge_airline_both_runs_stop": f"{j_both} of {len(air)}" if air else None,
            "judge_airline_one_run_stops": j_one if air else None,
            "judge_retail_stop": f"{r_stop} of {len(ret)} (refined rubric {r_stop_ref})"
            if ret
            else None,
            "examples": [t["actions"][p][1] for p in ps[:2]],
            "agreement_split": [p for p in ps if d[p]["agreement"] != "both agreed"],
        }
    )
(HERE / "table.json").write_text(json.dumps(out, indent=1) + "\n")
for r in out:
    print(
        r["n"],
        r["type"],
        r["rules_block"],
        r["rules"],
        r["judge_airline_both_runs_stop"],
        r["judge_airline_one_run_stops"],
        r["judge_retail_stop"],
        r["agreement_split"],
    )
