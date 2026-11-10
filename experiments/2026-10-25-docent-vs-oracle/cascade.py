"""Addendum 3B: a cheap-first cascade, Jev on every write and Docent only where Jev is unsure.

No model calls. Jev's single-question P(policy ok) comes from the pilot scores in the store
copies; Docent's verdict from `results/comparison.json`. The rule and the primary operating
point (w = 0.4) were fixed in README.md before this ran. Writes `results/cascade.json` once.

    python experiments/2026-10-25-docent-vs-oracle/cascade.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from hatchway.bench.pilot import concepts as P
from hatchway.bench.store import BenchStore
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.policy import load_policy

HERE = Path(__file__).parent
COPIES = Path("runs/docent")
ORACLE = "tau2-oracle-1:41ee37217182"
JEV = ("jev", "jev-1.14.0")
OUT = HERE / "results/cascade.json"
WIDTHS = [round(0.05 * i, 2) for i in range(11)]
PRIMARY = 0.4
JEV_COST, DOCENT_COST = 0.0003, 0.007


def rows() -> list[dict]:
    pilot = P.rubrics(load_policy(DEFAULT_POLICY))
    docent = {
        r["write_id"]: r["judge"]
        for r in json.loads((HERE / "results/comparison.json").read_text())["rows"]
    }
    out = []
    for name in ("targeted", "smoke2"):
        with BenchStore(COPIES / f"{name}.db") as store:
            for rec in store.proposed_actions(ORACLE):
                if rec.domain != "retail" or rec.deterministic_decision == "UNKNOWN":
                    continue
                s = store.get_score(rec.state_hash, pilot[rec.action][1], *JEV)
                ok = s is not None and s.status == "ok"
                out.append(
                    {
                        "write_id": rec.write_id,
                        "oracle_allows": rec.deterministic_decision == "ALLOW",
                        "docent_allows": docent[rec.write_id] == "ALLOW",
                        "jev_p": P.baseline_answers(s.question_vector)["policy_ok"] if ok else None,
                    }
                )
    return out


def run(data: list[dict], w: float) -> dict:
    routed = [r["jev_p"] is None or abs(r["jev_p"] - 0.5) <= w + 1e-9 for r in data]
    pred = [
        r["docent_allows"] if go else r["jev_p"] >= 0.5 for r, go in zip(data, routed, strict=True)
    ]
    truth = [r["oracle_allows"] for r in data]
    share = sum(routed) / len(data)
    return {
        "w": w,
        "sent_to_docent": sum(routed),
        "share_sent": round(share, 3),
        "agree": sum(p == t for p, t in zip(pred, truth, strict=True)),
        "wrongly_allowed": sum(p and not t for p, t in zip(pred, truth, strict=True)),
        "wrongly_stopped": sum(t and not p for p, t in zip(pred, truth, strict=True)),
        "n": len(data),
        "cost_per_action_usd": round(JEV_COST + share * DOCENT_COST, 5),
    }


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    data = rows()
    curve = [run(data, w) for w in WIDTHS]
    result = {
        "rule": "send to Docent if Jev has no answer or |P - 0.5| <= w; else allow iff P >= 0.5",
        "primary_w": PRIMARY,
        "costs_usd": {"jev_per_call": JEV_COST, "docent_per_action": DOCENT_COST},
        "jev_missing": sum(r["jev_p"] is None for r in data),
        "curve": curve,
        "rows": data,
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(f"{'w':>5} {'sent':>5} {'agree':>6} {'w.allow':>8} {'w.stop':>7} {'$/action':>9}")
    for c in curve:
        mark = "  <- primary" if c["w"] == PRIMARY else ""
        print(
            f"{c['w']:>5} {c['sent_to_docent']:>5} {c['agree']:>4}/{c['n']} "
            f"{c['wrongly_allowed']:>8} {c['wrongly_stopped']:>7} "
            f"{c['cost_per_action_usd']:>9}{mark}"
        )


if __name__ == "__main__":
    main()
