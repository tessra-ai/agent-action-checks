"""The 38 'neither' bad actions (provisional_checks.py's category), with everything on record.
EXPLORATORY, MODEL-READ. Train and dev only."""

import hashlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
M1 = HERE.parent / "2026-11-18-rely1-m1"
M0 = HERE.parent / "2026-11-18-rely1-m0"
# git-ignored M0 packets: this checkout's, or RELY_PACKETS (a worktree reads the main checkout's)
PACKETS = Path(os.environ.get("RELY_PACKETS", M0 / "runs/packets.jsonl"))


def jsonl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


EXP = HERE.parent


# train + dev write IDs (the M1 pack): evidence for any other action, held-out test included, is
# dropped as each file is read, never kept
WRITE_ID = re.compile(r'"write_id":\s*"([0-9A-Z]{26})"')
SCOPE = {v["write_id"] for v in json.loads((M1 / "results/pack_key.json").read_text()).values()}


def in_scope_lines(path):
    """JSONL records whose write ID is in scope; other lines are skipped before decoding."""
    for line in Path(path).read_text().splitlines():
        m = WRITE_ID.search(line)
        if m and m.group(1) in SCOPE:
            yield json.loads(line)


def by_write(path):
    return {r["write_id"]: r for r in in_scope_lines(path) if r["write_id"] in SCOPE}


def rulings_in_scope():
    """build.rulings() restricted to the scope: grader lines are skipped before decoding; the
    review files are small JSON documents of cases, kept only for in-scope cases."""
    out = {}
    d = EXP / "2026-10-28-airline-veto"
    for g in in_scope_lines(d / "results/grades.jsonl"):
        for label, reason in zip(g["labels"], g["reasons"], strict=False):
            out.setdefault(g["write_id"], []).append(
                {"who": "grader", "decision": label, "reason": reason}
            )
    # the person's reviews and corrections (build.rulings' other sources), case by case
    for exp, files in (
        (
            "2026-10-28-airline-veto",
            (("answers", "Prithvi (blind review)"), ("corrections", "Prithvi (correction)")),
        ),
        ("2026-10-25-docent-vs-oracle", (("answers", "Prithvi (review)"),)),
    ):
        d = EXP / exp
        key = {
            k["case"]: k["write_id"]
            for k in json.loads((d / "review/key.json").read_text())["cases"]
        }
        for name, who in files:
            doc = json.loads((d / f"review/{name}.json").read_text())
            items = (
                [(c, a["decision"], a["reason"]) for c, a in doc["answers"].items()]
                if name == "answers"
                else [(c["case"], c["corrected"], c["reason"]) for c in doc["corrections"]]
            )
            for case, decision, reason in items:
                if key[case] in SCOPE:
                    out.setdefault(key[case], []).append(
                        {"who": who, "decision": decision, "reason": reason}
                    )
    return out


def stop(label):
    return None if label is None else label != "run"


def main():
    rules = by_write(EXP / "2026-10-28-airline-rules/results/rules.jsonl")
    d1 = by_write(EXP / "2026-10-28-airline-veto/results/docent_1.jsonl")
    d2 = by_write(EXP / "2026-10-28-airline-veto/results/docent_2.jsonl")
    rj = by_write(EXP / "2026-10-25-docent-vs-oracle/results/judge.jsonl")
    rjr = by_write(EXP / "2026-10-25-docent-vs-oracle/results/judge_refined.jsonl")
    oracle = by_write(EXP / "2026-10-25-docent-vs-oracle/data/truth.jsonl")
    R = M1 / "results"
    a = {r["id"]: r for r in jsonl(R / "labels_a.jsonl")}
    b = {r["id"]: r for r in jsonl(R / "labels_b.jsonl")}
    key = json.loads((R / "pack_key.json").read_text())
    want = json.loads((M1 / "results/summary.json").read_text())["packets_sha256"]
    if hashlib.sha256(PACKETS.read_bytes()).hexdigest() != want:
        raise SystemExit("M0 packets differ from the ones the M1 labels were built on")
    packets = {p["write_id"]: p for p in jsonl(PACKETS)}
    train = {r["write_id"] for r in json.loads((M0 / "splits/train.json").read_text())}
    rul = rulings_in_scope()
    out = []
    for pid, v in key.items():
        w = v["write_id"]
        p = packets[w]
        t = p["meta"]["truth"]
        if t is None or t["should_run"]:
            continue
        s = [q for q in v["questions"] if ".S" in q]
        if any(a[q]["answer"] == b[q]["answer"] == "yes" for q in s):
            continue
        ag_a, ag_b = a[f"{pid}.A"]["answer"], b[f"{pid}.A"]["answer"]
        if ag_a == ag_b == "not_agreed":
            continue
        out.append(
            {
                "pid": pid,
                "write_id": w,
                "capture": p["capture"],
                "domain": p["domain"],
                "task_id": p["meta"]["task_id"],
                "split": "train" if w in train else "dev",
                "truth_source": t["source"],
                "action": {
                    "tool": p["proposed_action"]["tool"],
                    "arguments": p["proposed_action"]["arguments"],
                },
                "rulings": rul.get(w, []),
                "labellers": {"A": a[f"{pid}.A"], "B": b[f"{pid}.A"]},
                "statements_asked": len(s),
                "rules_16": (
                    {
                        "blocks": rules[w]["with_duplicate"]["blocks"],
                        "needs": rules[w]["with_duplicate"]["needs"],
                    }
                    if w in rules
                    else None
                ),
                "rubric_judge": (
                    {
                        "run_1": d1[w]["label"] if w in d1 else None,
                        "run_2": d2[w]["label"] if w in d2 else None,
                        "explanation_1": d1[w]["explanation"] if w in d1 else None,
                    }
                    if p["domain"] == "airline"
                    else {
                        "original": rj[w]["label"] if w in rj else None,
                        "refined": rjr[w]["label"] if w in rjr else None,
                        "explanation": rj[w]["explanation"] if w in rj else None,
                    }
                ),
                "oracle": (
                    {
                        k: oracle[w][k]
                        for k in ("oracle", "reason_codes", "explanation", "execution_outcome")
                    }
                    if w in oracle
                    else None
                ),
                "agreement": "both agreed"
                if ag_a == ag_b == "agreed"
                else f"split (A {ag_a}, B {ag_b})",
            }
        )
    print(len(out), "actions")
    (HERE / "neither_38.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
