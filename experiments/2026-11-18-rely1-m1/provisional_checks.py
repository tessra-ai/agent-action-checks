"""Provisional checks on the model labels, before any manual review (Prithvi, 2026-11-20).

    python experiments/2026-11-18-rely1-m1/provisional_checks.py

PROVISIONAL AND MODEL-LABELLED: the "truth" here is the two labellers' consensus, not a person's
label. Both labellers yes = contradiction; both not_agreed = no agreement. Train and dev only (the
pack holds nothing else). Labeller A: Codex, gpt-6.2-sol, reasoning high; B: Gemini app, 4 Neon,
thinking High. Writes results/provisional_checks.json.

1. Coverage, for actions ruled bad and ruled good (and ungraded, apart): how many have a both-yes
   statement in an action both labellers call agreed ("flag"); no agreement by both; both (a
   both-yes statement on an action both call not agreed); neither; and, apart, a both-yes
   statement where the labellers split on agreement.
   Only label-set statements were labelled (380 sampled of all agent sentences), so a "neither"
   action may still hold an unlabelled contradiction.
2. Every both-yes statement in an action ruled good, with the quote and the rulings.
3. The certificate-balance statement (P112.S4, an anchor): what each labeller said.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
R = HERE / "results"
M0 = HERE.parent / "2026-11-18-rely1-m0"
sys.path.insert(0, str(HERE))
from build import rulings as load_rulings  # noqa: E402


def jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def main() -> None:
    a = {r["id"]: r for r in jsonl(R / "labels_a.jsonl")}
    b = {r["id"]: r for r in jsonl(R / "labels_b.jsonl")}
    key = json.loads((R / "pack_key.json").read_text())
    packets = {p["write_id"]: p for p in jsonl(M0 / "runs/packets.jsonl")}
    rows = {r["unit_key"]: r for r in jsonl(R / "label_set.jsonl")}
    rul = load_rulings()
    train = {r["write_id"] for r in json.loads((M0 / "splits/train.json").read_text())}

    coverage: dict[str, dict[str, Counter]] = {}
    good_flags = []
    for pid, v in key.items():
        w = v["write_id"]
        p = packets[w]
        t = p["meta"]["truth"]
        ruled = "ungraded" if t is None else ("good" if t["should_run"] else "bad")
        split = "train" if w in train else "dev"
        ag_a, ag_b = a[f"{pid}.A"]["answer"], b[f"{pid}.A"]["answer"]

        def both(x: str, ag_a: str = ag_a, ag_b: str = ag_b) -> bool:
            return ag_a == ag_b == x

        s_ids = [q for q in v["questions"] if ".S" in q]
        both_yes = [q for q in s_ids if a[q]["answer"] == b[q]["answer"] == "yes"]
        # "flag": a both-yes statement on an action both call agreed; "both": a both-yes statement
        # on an action both call not agreed; "flag, agreement split": a both-yes statement where
        # the labellers disagree on agreement.
        no_agree = both("not_agreed")
        if both_yes and both("agreed"):
            cat = "flag (both-yes, agreed)"
        elif both_yes and no_agree:
            cat = "both (both-yes and no agreement)"
        elif both_yes:
            cat = "both-yes, agreement split"
        elif no_agree:
            cat = "no agreement only"
        else:
            cat = "neither"
        for s in (split, "train+dev"):
            coverage.setdefault(ruled, {}).setdefault(s, Counter())[cat] += 1
        if ruled == "good":
            for q in both_yes:
                r = rows[v["questions"][q]]
                good_flags.append(
                    {
                        "id": q,
                        "write_id": w,
                        "task": f"{p['domain']} {p['meta']['task_id']}",
                        "split": split,
                        "turn": r["unit"]["turn"],
                        "quote": " ".join(filter(None, [r["unit"]["lead_in"], r["unit"]["text"]])),
                        "action_agreed_by": "both" if both("agreed") else "not both",
                        "ruling": {"should_run": t["should_run"], "source": t["source"]},
                        "rulings": [
                            {"who": x["who"], "decision": x["decision"], "reason": x.get("reason")}
                            for x in rul.get(w, [])
                        ],
                        "A": a[q]["reason"],
                        "B": b[q]["reason"],
                    }
                )
    q = "P112.S4"
    w = key["P112"]["write_id"]
    r = rows[key["P112"]["questions"][q]]
    out = {
        "status": "PROVISIONAL, MODEL-LABELLED: consensus of labeller A and labeller B; no "
        "person has reviewed these labels. Train and dev only.",
        "coverage": {
            k: {s: dict(c) | {"n": sum(c.values())} for s, c in v.items()}
            for k, v in coverage.items()
        },
        "both_yes_in_good_actions": good_flags,
        "certificate_balance_P112_S4": {
            "write_id": w,
            "sentence": r["unit"]["text"],
            "turn": r["unit"]["turn"],
            "prefill": r["prefill"],
            "A": a[q],
            "B": b[q],
            "ruling": packets[w]["meta"]["truth"],
            "rulings": [
                {"who": x["who"], "decision": x["decision"], "reason": x.get("reason")}
                for x in rul.get(w, [])
            ],
        },
    }
    (R / "provisional_checks.json").write_text(json.dumps(out, indent=1) + "\n")
    for k, v in out["coverage"].items():
        print(k, v["train+dev"])
    print(len(good_flags), "both-yes statements in good actions")


if __name__ == "__main__":
    main()
