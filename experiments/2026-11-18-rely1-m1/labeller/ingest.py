"""Check a labeller's answers against the labeller pack, and keep them only if they all pass.

    python ingest.py SOURCE [SOURCE ...] [--call P001-S] [--require-all] [--out answers.jsonl]

SOURCE is a file of answers, a directory (every *.json and *.txt file in it is read), or "-" to
read pasted text from standard input (end with Ctrl-D, or Ctrl-Z then Enter on Windows). A
source holds one or more JSON arrays of answer objects. Code fences (```json ... ```) and text
outside the arrays are allowed, so a pasted reply works; a warning is printed for such text. A
"[" that does not start valid JSON, or a "{" outside an array, is an error (a reply cut off or
broken, or answers wrapped in an object).

Each packet file is one call: P001-A asks the agreement question (P001.A), P001-S the statement
questions (P001.S1, P001.S2, ...).

Each answer object must have exactly the fields "id", "answer" and "reason". Checked against
manifest.json (next to this file):

- unknown IDs (not in the pack, or not in --call when given);
- duplicate IDs (within a source or across sources);
- missing IDs: every ID of every call that has at least one answer; with --require-all, every
  ID of every call in the pack;
- invalid answers: "yes" / "no" / "not_sure" for statements (IDs ending .S<n>), "agreed" /
  "not_agreed" / "not_sure" for the agreement question (.A);
- a missing or empty reason; a missing or extra field; a non-object.

A reason over 20 words is not refused: the answer is kept, flagged `reason_over_20_words`, and
a warning is printed (the prompt asks for 20 at most; a model that writes 21 would otherwise
fail the same way on every fresh rerun and leave the question unanswered).

If anything fails, the problems are listed, nothing is written and the exit code is 1. If all
pass, the answers are written to --out (JSON lines, one per ID, sorted) when given, and a summary
is printed. Needs only the Python 3.9+ standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_WORDS = 20
FIELDS = {"id", "answer", "reason"}
FENCE = re.compile(r"^[ \t]*```[A-Za-z]*[ \t]*$", re.M)  # a fence marker on its own line


class RepeatedKey(ValueError):
    pass


def _no_repeats(pairs: list) -> dict:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise RepeatedKey(f"repeated field(s) {sorted({k for k in keys if keys.count(k) > 1})}")
    return dict(pairs)


def load_manifest(path: Path) -> tuple[dict, dict[str, dict], dict[str, list[str]]]:
    m = json.loads(path.read_text(encoding="utf-8"))
    ids: dict[str, dict] = {}
    by_call: dict[str, list[str]] = {}
    for c in m["calls"]:
        by_call[c["call"]] = [q["id"] for q in c["questions"]]
        for q in c["questions"]:
            ids[q["id"]] = {"call": c["call"], "kind": q["kind"]}
    return m, ids, by_call


def arrays(text: str) -> tuple[list, bool]:
    """Every top-level JSON array in the text, and whether any other text was left over.

    Raises ValueError for a "[" that does not start valid JSON, so a broken outer array cannot
    be silently replaced by a complete array nested inside it.
    """
    text = FENCE.sub(" ", text)
    dec = json.JSONDecoder(object_pairs_hook=_no_repeats)
    found, leftover, i = [], False, 0
    while i < len(text):
        if text[i] == "[":
            try:
                value, end = dec.raw_decode(text, i)
            except RepeatedKey as e:
                raise ValueError(f"an answer object has {e}") from None
            except json.JSONDecodeError as e:
                raise ValueError(f"broken JSON from character {i} ({e.msg})") from None
            if isinstance(value, list):
                found.append(value)
                i = end
                continue
        if text[i] == "{":
            raise ValueError(f"JSON outside an answer array, from character {i}")
        if not text[i].isspace():
            leftover = True
        i += 1
    return found, leftover


def _encodable(s: str) -> bool:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def calls_named(problems: list[str]) -> list[str]:
    """The calls a list of problems points at: P001-S directly, or via IDs P001.S2 / P001.A."""
    out = []
    for p in problems:
        for pid, kind in re.findall(r"\b(P\d{3})[.-]([AS])", p):
            out.append(f"{pid}-{kind}")
    return out


def read_sources(sources: list[str]) -> list[tuple[str, str]]:
    out = []
    for s in sources:
        if s == "-":
            out.append(("pasted text", sys.stdin.read()))
            continue
        p = Path(s)
        if p.is_dir():
            files = sorted(f for f in p.iterdir() if f.suffix in {".json", ".txt"} and f.is_file())
            if not files:
                out.append((str(p), ""))
            out += [(str(f), f.read_text(encoding="utf-8")) for f in files]
        elif p.is_file():
            out.append((str(p), p.read_text(encoding="utf-8")))
        else:
            raise SystemExit(f"no such file or directory: {s}")
    return out


def check(
    sources: list[tuple[str, str]],
    manifest: tuple[dict, dict[str, dict], dict[str, list[str]]],
    call: str | None = None,
    require_all: bool = False,
) -> tuple[list[str], list[str], list[dict]]:
    """Return (problems, warnings, rows). Rows are only meaningful when there are no problems."""
    m, ids, by_call = manifest
    allowed = m["allowed_answers"]
    problems: list[str] = []
    warnings: list[str] = []
    rows: list[dict] = []
    seen: Counter = Counter()
    where: dict[str, list[str]] = defaultdict(list)
    if call is not None and call not in by_call:
        return [f"--call {call}: not a call in this pack"], [], []
    for name, text in sources:
        try:
            found, leftover = arrays(text)
        except ValueError as e:
            problems.append(f"{name}: {e}")
            continue
        if not found:
            problems.append(f"{name}: no JSON array of answers found (refused, cut off or empty?)")
            continue
        if not any(found):
            problems.append(f"{name}: the JSON array(s) hold no answers")
            continue
        if leftover:
            warnings.append(f"{name}: text outside the JSON array(s) was ignored")
        for arr in found:
            for k, obj in enumerate(arr):
                tag = f"{name}: item {k + 1}"
                if not isinstance(obj, dict):
                    problems.append(f"{tag}: not an object")
                    continue
                qid = obj.get("id")
                if isinstance(qid, str):
                    tag = f"{name}: {qid}"
                missing, extra = FIELDS - set(obj), set(obj) - FIELDS
                if missing:
                    problems.append(f"{tag}: missing field(s) {sorted(missing)}")
                if extra:
                    problems.append(f"{tag}: unexpected field(s) {sorted(extra)}")
                if not isinstance(qid, str) or qid not in ids:
                    problems.append(f"{tag}: unknown ID {qid!r}")
                    continue
                if call is not None and ids[qid]["call"] != call:
                    problems.append(f"{tag}: belongs to {ids[qid]['call']}, not {call}")
                    continue
                seen[qid] += 1
                where[qid].append(name)
                kind = ids[qid]["kind"]
                ans = obj.get("answer")
                if ans not in allowed[kind]:
                    problems.append(
                        f"{tag}: invalid answer {ans!r} (allowed for {kind}: {allowed[kind]})"
                    )
                reason = obj.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    problems.append(f"{tag}: reason missing or empty")
                elif not _encodable(reason):
                    problems.append(f"{tag}: reason has characters that cannot be saved as UTF-8")
                long = isinstance(reason, str) and len(reason.split()) > MAX_WORDS
                if long:  # kept and flagged: the answer stands; the reason ran long
                    warnings.append(
                        f"{tag}: reason has {len(reason.split())} words (asked for {MAX_WORDS} "
                        "at most); kept and flagged"
                    )
                rows.append(
                    {
                        "id": qid,
                        "call": ids[qid]["call"],
                        "packet": qid.split(".")[0],
                        "kind": kind,
                        "answer": ans,
                        "reason": reason,
                        "reason_over_20_words": long,
                        "source": Path(name).name if name != "pasted text" else name,
                    }
                )
    for qid, n in sorted(seen.items()):
        if n > 1:
            problems.append(f"{qid}: duplicate ID, answered {n} times ({', '.join(where[qid])})")
    answered = {ids[q]["call"] for q in seen}
    expect = {call} if call is not None else set(by_call) if require_all else answered
    for c in sorted(expect):
        miss = [q for q in by_call[c] if q not in seen]
        if miss:
            problems.append(f"{c}: missing ID(s) {', '.join(miss)}")
    rows.sort(key=lambda r: (r["packet"], r["call"], r["id"]))
    return problems, warnings, rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sources", nargs="+", help='answer file(s), director(ies), or "-" for paste')
    ap.add_argument("--call", help="expect answers for this one call only (e.g. P001-S)")
    ap.add_argument("--require-all", action="store_true", help="every call must be answered")
    ap.add_argument("--out", help="write the checked answers here (JSON lines)")
    ap.add_argument("--manifest", default=str(HERE / "manifest.json"))
    a = ap.parse_args(argv)
    if a.call and a.require_all:
        ap.error("--call checks one call; --require-all checks the whole pack. Use one.")
    manifest = load_manifest(Path(a.manifest))
    problems, warnings, rows = check(read_sources(a.sources), manifest, a.call, a.require_all)
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    if problems:
        print(f"REFUSED: {len(problems)} problem(s); nothing was written.", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        bad = [a.call] if a.call else sorted(set(calls_named(problems)) & set(manifest[2]))
        if bad:
            print("calls to rerun:", " ".join(bad), file=sys.stderr)
        return 1
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    calls = sorted({r["call"] for r in rows})
    counts = Counter((r["kind"], r["answer"]) for r in rows)
    print(f"OK: {len(rows)} answers for {len(calls)} call(s) of {len(manifest[2])}.")
    for (kind, ans), n in sorted(counts.items()):
        print(f"  {kind:10s} {ans:11s} {n}")
    if a.out:
        print("written:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
