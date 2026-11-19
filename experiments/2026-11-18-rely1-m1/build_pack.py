"""Rely-1 M1: the labeller pack for the two model labellers (Prithvi, 2026-11-19). Run once.

    python experiments/2026-11-18-rely1-m1/build_pack.py

Writes `runs/labeller_pack/` (git-ignored; the packets are tau2 conversations):

- `prompt.txt`: the instructions, copied from `labeller/prompt.txt`;
- `packets/`: the train + dev actions are numbered P001 ... P174 in a seeded shuffle. Each file is
  the action's M0 packet v2 main text (no later calls) followed by "# Questions". Two kinds of
  call, so that which actions have statement questions (none of the actions already labelled
  "no agreement" do) cannot hint at the agreement answer (Codex review, 2026-11-19):
  - `P001-A.txt`, all 174: the agreement question only (`P001.A`);
  - `P001-S.txt`, the 125 actions with label-set statements: one ID per statement (`P001.S1`
    ...; turn order) and nothing else;
- `manifest.json`: question IDs per call, allowed answers, file hashes;
- `ingest.py`: copied from `labeller/ingest.py`.

Deterministic. Files that already exist must match byte for byte (otherwise it stops); missing
ones are written. So a clean checkout rebuilds the git-ignored pack and checks it against the
committed key and summary.

A call to a labeller sends prompt.txt followed directly by one packet file (one file per call).
Nothing in the pack carries a write ID, task ID, pre-fill, ruling, grader reason, truth label or
agreement label.

Outside the pack (committed): `results/pack_key.json` maps pack IDs to write IDs and unit keys;
`results/pack_summary.json` records hashes, counts and the actions exposed by the two worked
examples in the prompt.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
M0 = HERE.parent / "2026-11-18-rely1-m0"
PACKETS = M0 / "runs/packets.jsonl"
LABEL_SET = HERE / "results/label_set.jsonl"
SUMMARY = HERE / "results/summary.json"
SRC = HERE / "labeller"
PACK = HERE / "runs/labeller_pack"
KEY = HERE / "results/pack_key.json"
OUT = HERE / "results/pack_summary.json"
SEED = 20261118
PACK_VERSION = "rely1-labeller-pack-v2"
ALLOWED = {
    "statement": ["yes", "no", "not_sure"],
    "agreement": ["agreed", "not_agreed", "not_sure"],
}
AGREEMENT_Q = "Did the customer agree to this exact proposed action before it was made?"
# The prompt's two worked examples: statements outside the label set, from these actions.
EXAMPLES = {
    "EX1.S1": ("01M5JZ50JK3SXWYXBR2VA0RBZB", "T19.2", "yes"),
    "EX2.S1": ("01M5JZ75JB70RW5WZ3HTHRFT8J", "T19.2", "no"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def statement_call(pid: str, units: list[dict]) -> tuple[list[str], list[dict], str]:
    lines, qs = [], []
    for i, u in enumerate(units, 1):
        qid = f"{pid}.S{i}"
        where = f"T{u['turn']}"
        if u.get("lead_in"):
            where += f", a list item under: {json.dumps(u['lead_in'], ensure_ascii=False)}"
        lines.append(f"[{qid}] ({where}) {json.dumps(u['text'], ensure_ascii=False)}")
        qs.append({"id": qid, "kind": "statement"})
    n = len(units)
    return lines, qs, f"Answer {n} statement question{'s' if n != 1 else ''}."


def agreement_call(pid: str) -> tuple[list[str], list[dict], str]:
    return (
        [f"[{pid}.A] {AGREEMENT_Q}"],
        [{"id": f"{pid}.A", "kind": "agreement"}],
        "Answer 1 agreement question.",
    )


def render(text: str, lines: list[str], head: str) -> str:
    return text.rstrip("\n") + "\n\n# Questions\n\n" + head + "\n\n" + "\n".join(lines) + "\n"


def put(files: dict[Path, bytes]) -> None:
    """Write missing files; stop if an existing one differs (the pack is built once)."""
    for path, data in files.items():
        if path.exists() and path.read_bytes() != data:
            raise SystemExit(f"{path} exists and differs; the labeller pack is built once")
    for path, data in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def main() -> None:
    train = {r["write_id"] for r in json.loads((M0 / "splits/train.json").read_text())}
    dev = {r["write_id"] for r in json.loads((M0 / "splits/dev.json").read_text())}
    raw = PACKETS.read_bytes()
    if sha(raw) != json.loads(SUMMARY.read_text())["packets_sha256"]:
        raise SystemExit("M0 packets differ from the ones the label set was built on")
    packets = {p["write_id"]: p for p in map(json.loads, raw.decode().splitlines())}
    if set(packets) != train | dev:
        raise SystemExit("M0 packets must be exactly train + dev")
    if {p["packet_version"] for p in packets.values()} != {"rely1-packet-v2"}:
        raise SystemExit("packet v2 required")
    rows = [json.loads(x) for x in LABEL_SET.read_text().splitlines() if x.strip()]
    keys = {r["unit_key"] for r in rows}
    for qid, (w, uid, _) in EXAMPLES.items():
        if f"{w}:{uid}" in keys:
            raise SystemExit(f"worked example {qid} is in the label set")
    by_action: dict[str, list[dict]] = {}
    for r in rows:
        by_action.setdefault(r["write_id"], []).append(r)

    order = sorted(packets)
    random.Random(SEED).shuffle(order)
    files: dict[Path, bytes] = {}
    manifest_calls, key = [], {}
    for n, w in enumerate(order, 1):
        pid = f"P{n:03d}"
        p = packets[w]
        mine = sorted(
            by_action.get(w, []),
            key=lambda r: (r["unit"]["turn"], int(r["unit"]["id"].split(".")[1])),
        )
        units = [r["unit"] for r in mine]
        text = p["text"]
        for u in units:
            if u["text"] not in text:
                raise SystemExit(f"{w}:{u['id']} text not found in its packet")
        calls = [("A", *agreement_call(pid))]
        if units:
            calls.append(("S", *statement_call(pid, units)))
        stmt_qs: list[dict] = []
        for kind, lines, qs, head in calls:
            body = render(text, lines, head)
            if w in body or re.search(r"\b01M[0-9A-Z]{23}\b", body):
                raise SystemExit(f"{pid}: a write ID leaked into the packet file")
            name = f"{pid}-{kind}"
            files[PACK / "packets" / f"{name}.txt"] = body.encode()
            manifest_calls.append(
                {
                    "call": name,
                    "file": f"packets/{name}.txt",
                    "sha256": sha(body.encode()),
                    "questions": qs,
                }
            )
            if kind == "S":
                stmt_qs = qs
        key[pid] = {
            "write_id": w,
            "questions": {
                **{q["id"]: r["unit_key"] for q, r in zip(stmt_qs, mine, strict=True)},
                f"{pid}.A": f"{w}:agreement",
            },
        }

    files[PACK / "prompt.txt"] = (SRC / "prompt.txt").read_bytes()
    files[PACK / "ingest.py"] = (SRC / "ingest.py").read_bytes()
    prompt_sha = sha(files[PACK / "prompt.txt"])
    manifest = {
        "pack_version": PACK_VERSION,
        "how_to_call": "Send prompt.txt followed directly by one packet file; one file per call.",
        "prompt_sha256": prompt_sha,
        "allowed_answers": ALLOWED,
        "max_reason_words": 20,
        "calls": manifest_calls,
    }
    files[PACK / "manifest.json"] = (json.dumps(manifest, indent=1) + "\n").encode()
    files[KEY] = (json.dumps(key, indent=1, sort_keys=True) + "\n").encode()

    stmts = sum(len(v["questions"]) - 1 for v in key.values())
    # Exposed: same task as an example, or records holding an order, item or payment ID that the
    # examples quote (the same customer recurs across tasks).
    tasks = {(packets[w]["domain"], packets[w]["meta"]["task_id"]) for w, _, _ in EXAMPLES.values()}
    examples = files[PACK / "prompt.txt"].decode().split("TWO WORKED EXAMPLES", 1)[1]
    facts = sorted(set(re.findall(r"#W\d{7}|\b\d{10}\b|\b(?:credit_card|paypal)_\d+\b", examples)))
    exposed_why = {}
    for pid, v in key.items():
        q = packets[v["write_id"]]
        why = [f for f in facts if f in q["text"]]
        if (q["domain"], q["meta"]["task_id"]) in tasks:
            why.insert(0, "same task")
        if why:
            exposed_why[pid] = why
    exposed = sorted(exposed_why)
    summary = {
        "pack_version": PACK_VERSION,
        "seed": SEED,
        "packets": len(key),
        "calls": len(manifest_calls),
        "packets_with_statements": sum(1 for v in key.values() if len(v["questions"]) > 1),
        "statement_questions": stmts,
        "agreement_questions": len(key),
        "split_counts": {
            "train": sum(1 for v in key.values() if v["write_id"] in train),
            "dev": sum(1 for v in key.values() if v["write_id"] in dev),
        },
        "m0_packets_sha256": sha(raw),
        "label_set_sha256": sha(LABEL_SET.read_bytes()),
        "prompt_sha256": prompt_sha,
        "ingest_sha256": sha(files[PACK / "ingest.py"]),
        "manifest_sha256": sha(files[PACK / "manifest.json"]),
        "pack_key_sha256": sha(files[KEY]),
        "worked_examples": {
            q: {
                "unit_key": f"{w}:{u}",
                "answer": a,
                "domain": packets[w]["domain"],
                "task_id": packets[w]["meta"]["task_id"],
            }
            for q, (w, u, a) in EXAMPLES.items()
        },
        "example_exposed": {
            "why": "Same task as a worked example, or records holding an ID the examples quote; "
            "A-vs-B is reported with and without them.",
            "example_ids": facts,
            "packets": exposed,
            "reasons": exposed_why,
            "statement_questions": sum(len(key[p]["questions"]) - 1 for p in exposed),
        },
    }
    if summary["statement_questions"] != len(rows) or summary["packets"] != 174:
        raise SystemExit(f"expected 380 statements and 174 packets: {summary}")
    files[OUT] = (json.dumps(summary, indent=1) + "\n").encode()
    put(files)
    print(json.dumps({k: summary[k] for k in list(summary)[:8]}, indent=1))
    print("example-exposed packets:", exposed)


if __name__ == "__main__":
    sys.exit(main())
