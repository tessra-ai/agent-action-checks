"""Check the Gemini app's replies, batch by batch, and keep them only if everything passes.

    python ingest.py answers/                # every reply saved as a file in answers/
    python ingest.py answers/answers_01.txt  # one saved reply
    python ingest.py -                       # paste a reply, then Ctrl-D (Ctrl-Z, Enter on Windows)

A reply may be the downloaded/copied text as it is: code fences and text around the JSON are
fine. Name each saved reply after its batch (answers_01.txt, answers_03a.txt, ...) so problems
that cannot be tied to IDs (an unreadable reply) still point at a batch.

For every batch with at least one answer, every ID of that batch must be answered (add
--require-all to demand every batch). It reports, per batch: complete; incomplete (which IDs are
missing); invalid answers; or not started. Then it says exactly which batch to redo. An
incomplete batch is also written out split in two (redo/batch_NNa.txt and redo/batch_NNb.txt):
run those in two new chats, delete the old reply for that batch, and save the two new replies.

Writes the checked answers (--out, default checked_answers.jsonl) only when nothing fails.
Needs Python 3.9+ and the files next to it: ingest_core.py, manifest.json, batches.json.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

HEADER = """BATCH {n} of {total}: {kind} questions only.

This file holds {k} packets. Treat each packet as a separate task: apply the instructions to it,
using only that packet's own text. Answer every question ID in every packet ({ids} IDs in all).
Return ONE JSON array holding all {ids} answers, and nothing else.
"""
SECTION = re.compile(r"===== PACKET (\S+) =====\n.*?\n===== END OF PACKET \1 =====\n", re.S)


def section(call: str, text: str) -> str:
    return f"===== PACKET {call} =====\n{text.rstrip()}\n===== END OF PACKET {call} =====\n"


def batch_text(n: str, total: int, calls: list[dict], texts: dict[str, str]) -> str:
    kind = "agreement" if calls[0]["call"].endswith("-A") else "statement"
    ids = sum(len(c["questions"]) for c in calls)
    head = HEADER.format(n=n, total=total, kind=kind, k=len(calls), ids=ids)
    body = "\n".join(section(c["call"], texts[c["call"]]) for c in calls)
    return f"{head}\n{body}\n===== END OF BATCH {n}: {len(calls)} packets, {ids} IDs =====\n"


def _core():
    spec = importlib.util.spec_from_file_location("ingest_core", HERE / "ingest_core.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def split(batch: dict, total: int, manifest: dict, here: Path) -> list[str]:
    """Write the batch's packets, unchanged, as two half batches under redo/."""
    text = (here / batch["file"]).read_text(encoding="utf-8")
    blocks = {m.group(1): m.group(0) for m in SECTION.finditer(text)}
    by_call = {c["call"]: c for c in manifest["calls"]}
    calls = [by_call[c] for c in batch["calls"]]
    if len(calls) < 2:
        return []
    half = (len(calls) + 1) // 2
    out = []
    (here / "redo").mkdir(exist_ok=True)
    for suffix, part in (("a", calls[:half]), ("b", calls[half:])):
        texts = {}
        for c in part:
            body = blocks[c["call"]]
            texts[c["call"]] = body.split("\n", 1)[1].rsplit("\n===== END OF PACKET", 1)[0]
        name = f"batch_{batch['batch']}{suffix}.txt"
        (here / "redo" / name).write_text(
            batch_text(batch["batch"] + suffix, total, part, texts), encoding="utf-8"
        )
        out.append(f"redo/{name}")
    return out


NAME = re.compile(r"answers_(\d{2})([ab]?)\b")


def half_ids(batch: dict, manifest: dict) -> dict[str, list[str]]:
    """The IDs of a batch and of its two halves, split exactly as `split` writes them."""
    by_call = {c["call"]: c for c in manifest["calls"]}
    calls = batch["calls"]
    k = (len(calls) + 1) // 2
    ids = lambda cs: [q["id"] for c in cs for q in by_call[c]["questions"]]  # noqa: E731
    return {"": batch["ids"], "a": ids(calls[:k]), "b": ids(calls[k:])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check Gemini replies against the batches.")
    ap.add_argument("sources", nargs="+", help='saved replies (files or folders), or "-" to paste')
    ap.add_argument("--require-all", action="store_true", help="every batch must be answered")
    ap.add_argument("--out", default=str(HERE / "checked_answers.jsonl"))
    a = ap.parse_args(argv)
    core = _core()
    manifest = core.load_manifest(HERE / "manifest.json")
    batches = json.loads((HERE / "batches.json").read_text())["batches"]
    total = len(batches)
    batch_of = {i: b["batch"] for b in batches for i in b["ids"]}
    by_batch = {b["batch"]: b for b in batches}

    sources = core.read_sources(a.sources)
    problems, warnings, rows = core.check(sources, manifest)
    answered = defaultdict(set)
    part_of: dict[str, tuple[str, str]] = {}  # id -> (batch, half) of the file it came from
    halves_used: dict[str, set[str]] = defaultdict(set)
    misnamed: dict[str, set[str]] = defaultdict(set)  # file -> batches its IDs belong to
    for r in rows:
        answered[batch_of[r["id"]]].add(r["id"])
        m = NAME.search(r["source"])
        if not m:
            continue
        n, h = m.group(1), m.group(2)
        halves_used[n].add(h)
        if n not in by_batch or r["id"] not in half_ids(by_batch[n], manifest[0])[h]:
            misnamed[r["source"]].add(batch_of[r["id"]])
        else:
            part_of[r["id"]] = (n, h)

    bad_batches: dict[str, list[str]] = defaultdict(list)
    loose: list[str] = []
    for p in problems:
        ids = [i for i in re.findall(r"\bP\d{3}\.(?:S\d+|A)\b", p) if i in batch_of]
        if ids:
            bad_batches[batch_of[ids[0]]].append(p)
        elif "missing ID(s)" not in p:  # missing IDs are recomputed per batch below
            loose.append(p)
    for w in warnings:
        print("note:", w)

    unreadable_parts = {(m.group(1), m.group(2)) for p in loose if (m := NAME.search(p))}
    unreadable = {n for n, _ in unreadable_parts}
    for n, h in unreadable_parts:
        if h:
            halves_used[n].add(h)
    # Each batch is answered by one reply, or by exactly one reply per half: never pieced
    # together from several incomplete chats.
    sources_of: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        sources_of[batch_of[r["id"]]].add(r["source"])

    print()
    redo: list[str] = []
    for b in batches:
        n, ids = b["batch"], b["ids"]
        got = answered.get(n, set())
        names = sorted(sources_of.get(n, set()))
        part_names = {NAME.search(s).group(2) if NAME.search(s) else None for s in names}
        if len(names) > 1 and not (len(names) <= 2 and part_names <= {"a", "b"}):
            print(f"batch {n}: answers come from {len(names)} replies: {', '.join(names)}")
            redo.append(
                f"Batch {n} is pieced together from several replies ({', '.join(names)}). Keep "
                f"one complete reply (answers_{n}.txt) or one per half (answers_{n}a.txt and "
                f"answers_{n}b.txt); delete the rest."
            )
            continue
        if not got and not bad_batches.get(n) and n in unreadable:
            print(f"batch {n}: its reply could not be read (see below)")
            continue
        if not got and not bad_batches.get(n):
            status = "not started" if not a.require_all else "NOT ANSWERED"
            print(f"batch {n}: {status}")
            if a.require_all:
                redo.append(f"Run batch_{n}.txt.")
            continue
        missing = [i for i in ids if i not in got]
        if "" in halves_used.get(n, set()) and halves_used[n] - {""}:
            # A batch is answered either by its own reply or by its two halves, never a mix.
            print(f"batch {n}: MIXED, answers_{n}.txt and half replies are both present")
            redo.append(
                f"Batch {n} has both answers_{n}.txt and half replies (answers_{n}a/b.txt). Keep "
                f"one set: delete answers_{n}.txt if you redid it in halves."
            )
            continue
        used = halves_used.get(n, set()) - {""}
        if used and (missing or bad_batches.get(n)):
            # The batch was redone in halves: point at the half (or halves) still wrong.
            parts = half_ids(b, manifest[0])
            split(by_batch[n], total, manifest[0], HERE)
            bad_ids = {i for p in bad_batches.get(n, []) for i in re.findall(r"P\d{3}\.\w+", p)}
            for h in ("a", "b"):
                miss_h = [i for i in parts[h] if i not in got]
                if miss_h or bad_ids & set(parts[h]):
                    what = f"{len(miss_h)} IDs missing" if miss_h else "invalid answers"
                    print(f"batch {n}{h}: {what}")
                    for p in bad_batches.get(n, [])[:5]:
                        if any(i in p for i in parts[h]):
                            print("   -", p)
                    redo.append(
                        f"Redo redo/batch_{n}{h}.txt in a new chat and replace answers_{n}{h}.txt."
                    )
            continue
        if missing:
            shown = ", ".join(missing[:12]) + (" ..." if len(missing) > 12 else "")
            print(f"batch {n}: INCOMPLETE, {len(missing)} of {len(ids)} IDs missing: {shown}")
            halves = split(by_batch[n], total, manifest[0], HERE)
            if halves:
                redo.append(
                    f"Batch {n} is incomplete. Delete your saved reply for batch {n}, then run "
                    f"{halves[0]} and {halves[1]}, each in a new chat, and save the two replies "
                    f"as answers_{n}a.txt and answers_{n}b.txt."
                )
            else:
                redo.append(f"Redo batch_{n}.txt in a new chat and replace its saved reply.")
        elif bad_batches.get(n):
            print(f"batch {n}: INVALID ANSWERS")
            for p in bad_batches[n][:8]:
                print("   -", p)
            redo.append(f"Redo batch_{n}.txt in a new chat and replace its saved reply.")
        else:
            print(f"batch {n}: complete ({len(ids)} IDs)")
    for p in loose:
        name = re.match(r"(.*?):", p)
        hint = re.search(r"answers_(\d{2})([ab]?)", p)
        print("PROBLEM:", p)
        cut = "broken JSON" in p or "no JSON array" in p
        if hint and cut and not hint.group(2) and hint.group(1) in by_batch:
            # A reply cut off or unreadable: offer the batch in two smaller halves.
            n = hint.group(1)
            halves = split(by_batch[n], total, manifest[0], HERE)
            if halves:
                redo.append(
                    f"The reply for batch {n} could not be read (cut off?). Delete it, then run "
                    f"{halves[0]} and {halves[1]}, each in a new chat, and save the two replies "
                    f"as answers_{n}a.txt and answers_{n}b.txt."
                )
                continue
        if hint and hint.group(2) and hint.group(1) in by_batch:
            n, h = hint.group(1), hint.group(2)
            split(by_batch[n], total, manifest[0], HERE)
            redo.append(f"Redo redo/batch_{n}{h}.txt in a new chat and replace answers_{n}{h}.txt.")
            continue
        redo.append(
            f"Redo batch {hint.group(1) + hint.group(2)} in a new chat and replace its saved reply."
            if hint
            else f"Could not read {name.group(1) if name else 'a reply'}; redo the batch it was "
            "for in a new chat."
        )

    for f, holds in sorted(misnamed.items()):
        print(f"PROBLEM: {f} holds answers for batch {', '.join(sorted(holds))}, not its name")
        redo.append(
            f"{f} is saved under the wrong batch name: it holds answers for batch "
            f"{', '.join(sorted(holds))}. Rename it to match, or delete it, then check again."
        )

    print()
    if redo or problems:
        print("NOT SAVED. To fix:")
        for r in dict.fromkeys(redo):
            print("  *", r)
        return 1
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({**r, "batch": batch_of[r["id"]]}, ensure_ascii=False) + "\n")
    done = sum(1 for b in batches if answered.get(b["batch"]))
    print(f"ALL GOOD: {len(rows)} answers from {done} of {total} batches saved to {a.out}")
    if done < total:
        print("(Batches not started yet are listed above.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
