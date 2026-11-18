"""Cross-validation folds over train + dev, grouped by task ID (M0 decision 5). Run once.

    python experiments/2026-11-18-rely1-m0/folds.py

Thresholds are not set on the 41-action dev split alone. They are set by cross-validation over
train and dev together, with every action of one (domain, task) in one fold. The test splits are
not touched.

Assignment: tasks in a seeded random order, larger tasks first, each to the fold with the
smallest resulting share of good or bad actions (whichever is fuller), then the fewest actions.
Good / bad are the M0 truth labels; ungraded actions count only towards size. Writes
splits/folds.json and splits/folds_manifest.json (sha256). The frozen split files are not changed.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from packets import TRUTH  # noqa: E402

K = 5
SEED = 20261118
OUT = HERE / "splits/folds.json"


def truth_of(rows: list[dict]) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    for capture in {r["capture"] for r in rows}:
        t = TRUTH[capture]()
        for r in rows:
            if r["capture"] == capture:
                out[r["write_id"]] = t[r["write_id"]]["should_run"] if r["write_id"] in t else None
    return out


def counts(ids: list[str], truth: dict[str, bool | None]) -> dict[str, int]:
    c = Counter("good" if truth[w] else "bad" if truth[w] is False else "ungraded" for w in ids)
    return {"actions": len(ids), "good": c["good"], "bad": c["bad"], "ungraded": c["ungraded"]}


def main() -> None:
    if OUT.exists():
        raise SystemExit("folds are frozen; written once")
    split_rows = {n: json.loads((HERE / f"splits/{n}.json").read_text()) for n in ("train", "dev")}
    rows = split_rows["train"] + split_rows["dev"]
    truth = truth_of(rows)
    tasks: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        tasks.setdefault((r["domain"], r["task_id"]), []).append(r["write_id"])

    order = sorted(tasks)
    random.Random(SEED).shuffle(order)
    order.sort(key=lambda t: -len(tasks[t]))  # stable: ties keep the seeded order
    folds: list[list[tuple[str, str]]] = [[] for _ in range(K)]
    tally = [Counter() for _ in range(K)]
    total = Counter("good" if truth[w] else "bad" if truth[w] is False else "x" for w in truth)

    def load(i: int, t: tuple[str, str]) -> tuple[float, int, int]:
        """The fold's fuller share of good or bad actions once task t is added."""
        g = tally[i]["good"] + sum(1 for w in tasks[t] if truth[w])
        b = tally[i]["bad"] + sum(1 for w in tasks[t] if truth[w] is False)
        return (max(g / total["good"], b / total["bad"]), tally[i]["n"], i)

    for t in order:
        f = min(range(K), key=lambda i: load(i, t))
        folds[f].append(t)
        for w in tasks[t]:
            tally[f]["n"] += 1
            tally[f]["good" if truth[w] else "bad" if truth[w] is False else "ungraded"] += 1

    body = {
        "k": K,
        "seed": SEED,
        "grouping": "(domain, task_id) over train + dev",
        "folds": [
            {
                "fold": i,
                "tasks": sorted(f"{d}:{t}" for d, t in folds[i]),
                "write_ids": sorted(w for t in folds[i] for w in tasks[t]),
            }
            for i in range(K)
        ],
    }
    text = json.dumps(body, indent=1) + "\n"
    OUT.write_text(text)
    summary = {
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "train": counts([r["write_id"] for r in split_rows["train"]], truth),
        "dev": counts([r["write_id"] for r in split_rows["dev"]], truth),
        "folds": [
            {
                "fold": f["fold"],
                **counts(f["write_ids"], truth),
                "domains": dict(Counter(t.split(":")[0] for t in f["tasks"])),
                "tasks": len(f["tasks"]),
            }
            for f in body["folds"]
        ],
    }
    (HERE / "splits/folds_manifest.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
