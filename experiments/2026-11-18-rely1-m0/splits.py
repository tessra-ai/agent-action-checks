"""Freeze the Rely-1 splits by task ID (README.md, "Splits"). Run once.

    python experiments/2026-11-18-rely1-m0/splits.py

Groups are (domain, τ² task ID): every action of one task, and so of one conversation, sits in
one split. Planted errors (M3) inherit the split of the action they are made from.

1. test_unseen: a random quarter of the airline task IDs (seed SEED), every action with those
   IDs in either capture. The anchor tasks are not eligible: they are known development cases.
2. test_repeat: the rest of the second airline capture (airline2), new conversations for tasks
   that also appear in train or dev. Sharing task IDs with train/dev is what this set measures.
   A second-capture task with no train or dev action is not a repeat: it goes to test_unseen.
3. dev: a quarter of the remaining task IDs per domain, anchor tasks first, the rest at random.
4. train: everything else.

Writes splits/{train,dev,test_repeat,test_unseen}.json and splits/manifest.json (sha256 of each).
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from packets import ANCHORS, CAPTURES, jsonl, meta  # noqa: E402

SEED = 20261118
OUT = HERE / "splits"


def actions() -> list[dict]:
    rows = []
    for capture, (domain, d) in CAPTURES.items():
        m = meta(capture)
        for r in jsonl(d / "data/runs.jsonl"):
            w = r["write_id"]
            rows.append(
                {
                    "write_id": w,
                    "capture": capture,
                    "domain": domain,
                    "task_id": m[w]["task_id"],
                    "session_id": m[w].get("session_id"),
                }
            )
    return rows


def quarter(n: int) -> int:
    return max(1, round(n / 4))


def assign(rows: list[dict]) -> tuple[dict[str, str], dict]:
    rng = random.Random(SEED)
    by_id = {r["write_id"]: r for r in rows}
    anchor_tasks = {(by_id[w]["domain"], by_id[w]["task_id"]) for w in ANCHORS}

    def tasks(domain: str) -> list[str]:
        return sorted({r["task_id"] for r in rows if r["domain"] == domain}, key=int)

    air = tasks("airline")
    eligible = [t for t in air if ("airline", t) not in anchor_tasks]
    unseen = sorted(rng.sample(eligible, quarter(len(air))), key=int)

    split_of_task: dict[tuple[str, str], str] = {("airline", t): "test_unseen" for t in unseen}
    dev_tasks: dict[str, list[str]] = {}
    for domain in ("airline", "retail"):
        # Tasks left for train/dev: in airline, only those seen in the first capture.
        pool = [
            t
            for t in tasks(domain)
            if (domain, t) not in split_of_task
            and (
                domain != "airline"
                or any(r["task_id"] == t and r["capture"] == "airline1" for r in rows)
            )
        ]
        forced = sorted([t for t in pool if (domain, t) in anchor_tasks], key=int)
        rest = [t for t in pool if t not in forced]
        k = max(0, quarter(len(pool)) - len(forced))
        dev = sorted(forced + rng.sample(rest, k), key=int)
        dev_tasks[domain] = dev
        for t in pool:
            split_of_task[(domain, t)] = "dev" if t in dev else "train"

    split = {}
    only_second: set[str] = set()
    for r in rows:
        key = (r["domain"], r["task_id"])
        if split_of_task.get(key) == "test_unseen":
            split[r["write_id"]] = "test_unseen"
        elif r["capture"] == "airline2" and key in split_of_task:
            split[r["write_id"]] = "test_repeat"
        elif r["capture"] == "airline2":
            # A task only in the second capture is not a repeat: no train or dev conversation.
            split[r["write_id"]] = "test_unseen"
            only_second.add(r["task_id"])
        else:
            split[r["write_id"]] = split_of_task[key]
    info = {
        "seed": SEED,
        "airline_task_ids": air,
        "anchor_tasks_not_eligible": sorted(f"{d}:{t}" for d, t in anchor_tasks),
        "unseen_task_ids": unseen,
        "unseen_task_ids_only_in_second_capture": sorted(only_second, key=int),
        "dev_task_ids": dev_tasks,
    }
    return split, info


def check(rows: list[dict], split: dict[str, str]) -> dict:
    """The M0 gate checks, recomputed from the saved assignment."""
    groups: dict[str, set] = {}
    sessions: dict[str, set] = {}
    for r in rows:
        s = split[r["write_id"]]
        groups.setdefault(s, set()).add((r["domain"], r["task_id"]))
        if r["session_id"]:
            sessions.setdefault(s, set()).add(r["session_id"])
    names = sorted(groups)
    pairs = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            pairs[f"{a}|{b}"] = sorted(f"{d}:{t}" for d, t in groups[a] & groups[b])
    session_overlap = {
        f"{a}|{b}": len(sessions.get(a, set()) & sessions.get(b, set()))
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    }

    def overlap(a: str, b: str) -> list[str]:
        """Shared task IDs of two splits, whichever order their key was built in."""
        return pairs["|".join(sorted((a, b)))]

    strict = ["train", "dev", "test_unseen"]
    strict_ok = all(
        not overlap(a, b) for i, a in enumerate(strict) for b in strict[i + 1 :]
    ) and not overlap("test_repeat", "test_unseen")
    return {
        "task_overlap": pairs,
        "session_overlap": session_overlap,
        "train_dev_unseen_disjoint_and_unseen_disjoint_from_all": strict_ok,
        "repeat_shares_tasks_only_with": sorted(
            {
                k.replace("test_repeat", "").strip("|")
                for k, v in pairs.items()
                if "test_repeat" in k and v
            }
        ),
    }


def main() -> None:
    if (OUT / "manifest.json").exists():
        raise SystemExit("splits are frozen; delete nothing, they are written once")
    rows = actions()
    split, info = assign(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in ("train", "dev", "test_repeat", "test_unseen"):
        ids = sorted(w for w, s in split.items() if s == name)
        body = (
            json.dumps(
                [
                    {k: r[k] for k in ("write_id", "capture", "domain", "task_id")}
                    for r in rows
                    if r["write_id"] in ids
                ],
                indent=1,
            )
            + "\n"
        )
        (OUT / f"{name}.json").write_text(body)
        hashes[name] = {"actions": len(ids), "sha256": hashlib.sha256(body.encode()).hexdigest()}
    manifest = {**info, "splits": hashes, "checks": check(rows, split)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
