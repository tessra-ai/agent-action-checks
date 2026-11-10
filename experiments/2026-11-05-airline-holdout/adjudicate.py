"""Every arm against the adjudicated held-out truth (Report.md, "The person's review").

    python experiments/2026-11-05-airline-holdout/adjudicate.py   # once

Adjudicated truth: the blind graders' majority, replaced by the person's first-capture rulings
on the two held-out writes that repeat those cases (`review/consistency.json`, "applied") and by
the person's blind review of 18 writes (`review/answers.json`, with `review/corrections.json`
applied). Same arms as `evaluate.py`. Writes `results/adjudicated.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from evaluate import jsonl, score  # noqa: E402

OUT = HERE / "results/adjudicated.json"


def truth() -> tuple[dict[str, bool], dict[str, str]]:
    key = json.loads((HERE / "grading/key.json").read_text())
    key = key.get("cases", key)
    c2w = {k["case"]: k["write_id"] for k in key} if isinstance(key, list) else dict(key)
    grade = {c2w[g["case"]]: g for g in jsonl(HERE / "results/grades.jsonl")}
    t = {w: g["grader_run"] for w, g in grade.items()}
    src = dict.fromkeys(t, "graders")
    for a in json.loads((HERE / "review/consistency.json").read_text())["applied"]:
        t[a["write_id"]] = a["ruling"] == "allow"
        src[a["write_id"]] = "first-capture ruling"
    rkey = {k["case"]: k for k in json.loads((HERE / "review/key.json").read_text())["cases"]}
    answers = json.loads((HERE / "review/answers.json").read_text())["answers"]
    decided = {c: a["decision"] for c, a in answers.items()}
    for c in json.loads((HERE / "review/corrections.json").read_text())["corrections"]:
        decided[c["case"]] = c["corrected"]
    for c, d in decided.items():
        t[rkey[c]["write_id"]] = d == "allow"
        src[rkey[c]["write_id"]] = "person's review"
    return t, src


def main() -> None:
    if OUT.exists():
        sys.exit("results exist; written once")
    t, src = truth()
    gate = {r["write_id"]: r for r in json.loads((HERE / "results/gate.json").read_text())["rows"]}
    ids = sorted(gate)
    hand = {r["write_id"]: r for r in jsonl(HERE / "results/rules_hand.jsonl")}
    claude = {r["write_id"]: r for r in jsonl(HERE / "results/rules_claude.jsonl")}
    claims = {r["write_id"]: r for r in jsonl(HERE / "results/claims_airline2_verified.jsonl")}
    arms: dict[str, dict[str, bool]] = {
        "jev": {w: gate[w]["jev_run"] for w in ids},
        "hand_rules": {w: not hand[w]["with_duplicate"]["blocks"] for w in ids},
        "claude_rules": {w: not claude[w]["blocks"] for w in ids},
        "claims": {w: not claims[w]["flagged"] for w in ids},
    }
    for k in (1, 2):
        arms[f"docent_{k}"] = {w: gate[w][f"docent_{k}_run"] for w in ids}
        arms[f"gate_{k}"] = {w: gate[w][f"gate_{k}_run"] for w in ids}
        for rules in ("hand_rules", "claude_rules"):
            arms[f"{rules}_docent_{k}"] = {
                w: arms[rules][w] and gate[w][f"docent_{k}_run"] for w in ids
            }
            arms[f"{rules}_claims_docent_{k}"] = {
                w: arms[rules][w] and arms["claims"][w] and gate[w][f"docent_{k}_run"] for w in ids
            }
    metrics = {a: score(arms[a], t) for a in arms}
    changed = [w for w in t if src[w] != "graders"]
    result = {
        "truth": "graders, replaced by the person's first-capture rulings (2) and review (18)",
        "writes_in_truth": len(t),
        "should_run": sum(t.values()),
        "sources": {s: sum(1 for w in t if src[w] == s) for s in set(src.values())},
        "person_set": len(changed),
        "metrics": metrics,
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(f"writes {len(t)}, should run {sum(t.values())}, set by the person {len(changed)}")
    for a, m in metrics.items():
        print(
            f"  {a:30s} ran {m['ran']:3d} wrong {m['wrong']:2d} (ub {m['wrong_rate_upper95']}) "
            f"good sent back {m['good_sent_back']:2d}/{m['good_total']}"
        )


if __name__ == "__main__":
    main()
