"""Per-action table for the closing write-up (train and dev only; the test splits are not read).

    python experiments/2026-11-20-closing-writeup/actions.py   # -> results/actions.json

The one step that reads the git-ignored M0 packets (rebuilt by M0's packets.py; the M1 label set
was built on packets sha256 bd411422..., checked here). Everything else in this folder reads
committed files only, so numbers.py can rebuild numbers.json from the repository.

Per action: pack ID, write ID, domain, task, split, fold, ruling (bad / good / ungraded) and its
source, the labellers' agreement answers and consensus, each asked statement's answers and
consensus with its text, the agent model and the backend outcome (accepted or rejected) from the
capture metadata. No conversation text other than the asked statements' own sentences.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
M1 = EXP / "2026-11-18-rely1-m1"
sys.path.insert(0, str(M1))
import kev_pilot as K  # noqa: E402


def jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


WRITE_ID = re.compile(r'"write_id":\s*"([0-9A-Z]{26})"')


def in_scope(p: Path, scope: set[str]) -> list[dict]:
    """Capture metadata rows for train and dev actions only. The capture files also hold the
    sealed test actions; their lines are skipped before decoding, so no test outcome is read."""
    out = []
    for line in p.read_text().splitlines():
        m = WRITE_ID.search(line)
        if m and m.group(1) in scope:
            out.append(json.loads(line))
    return out


def main() -> None:
    want = json.loads((M1 / "results/summary.json").read_text())["packets_sha256"]
    got = hashlib.sha256((K.M0 / "runs/packets.jsonl").read_bytes()).hexdigest()
    if got != want:
        raise SystemExit("M0 packets differ from the ones the M1 labels were built on")
    act = K.load()
    a = {r["id"]: r for r in jsonl(M1 / "results/labels_a.jsonl")}
    b = {r["id"]: r for r in jsonl(M1 / "results/labels_b.jsonl")}
    scope = {v["write_id"] for v in json.loads((M1 / "results/pack_key.json").read_text()).values()}
    meta = {}
    for r in in_scope(EXP / "2026-10-28-airline-veto/data/meta.jsonl", scope):
        meta[r["write_id"]] = {"agent_model": r["agent_model"], "backend": r["outcome"]}
    for r in in_scope(EXP / "2026-10-25-docent-vs-oracle/data/truth.jsonl", scope):
        meta[r["write_id"]] = {"agent_model": r["agent_model"], "backend": r["execution_outcome"]}
    out = {}
    for pid, x in sorted(act.items()):
        t = x["packet"]["meta"]["truth"]
        m = meta[x["write_id"]]
        out[pid] = {
            "write_id": x["write_id"],
            "domain": x["packet"]["domain"],
            "task": x["task"],
            "split": x["split"],
            "fold": x["fold"],
            "ruling": x["ruling"],
            "ruling_source": None if t is None else t["source"],
            "action_tool": x["packet"]["proposed_action"]["tool"],
            "agent_model": m["agent_model"],
            "backend": m["backend"],
            "agreement": {
                "A": a[f"{pid}.A"]["answer"],
                "B": b[f"{pid}.A"]["answer"],
                "consensus": x["agree"],
            },
            "statements": {
                q: {
                    "A": a[q]["answer"],
                    "B": b[q]["answer"],
                    "consensus": s["label"],
                    "turn": s["unit"]["turn"],
                    "text": s["unit"]["text"],
                }
                for q, s in x["stmts"].items()
            },
        }
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results/actions.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(len(out), "actions ->", HERE / "results/actions.json")


if __name__ == "__main__":
    main()
