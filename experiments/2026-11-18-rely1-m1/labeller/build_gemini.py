"""Labeller B, manual route: the package Prithvi runs in the Gemini app (Prithvi, 2026-11-19).

    python experiments/2026-11-18-rely1-m1/labeller/build_gemini.py

Writes `runs/gemini_package/` (git-ignored):
- `prompt.txt`: the labeller pack's prompt, unchanged;
- `batch_01.txt` ...: whole calls of the pack, unchanged, between "===== PACKET <call> =====" and
  "===== END OF PACKET <call> =====" lines, under a short batch header (the only added text, the
  same in every batch: the file holds several packets, answer every ID, one JSON array).
  A batch holds only agreement calls or only statement calls, so which actions have statement
  questions cannot hint at agreement (as in the pack). batch_01 is a test batch: the statement
  calls of the first 10 actions that have them. Each batch is kept under ~150k tokens,
  estimated as characters / 3.2 (a conservative ratio; no tokenizer for the app is available
  offline);
- `batches.json`: the calls and IDs in each batch;
- `ingest.py` (+ `ingest_core.py`, `manifest.json`): checks the replies batch by batch;
- `HOWTO.txt`: one page.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
M1 = HERE.parent
PACK = M1 / "runs/labeller_pack"
OUT = M1 / "runs/gemini_package"
SUMMARY = M1 / "results/gemini_package.json"
CHARS_PER_TOKEN = 3.2
MAX_TOKENS = 150_000
TEST_ACTIONS = 10

sys.path.insert(0, str(HERE))
from gemini_ingest import batch_text, section  # noqa: E402


def pack_batches(calls: list[dict], texts: dict[str, str], budget: int) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for c in calls:
        n = len(texts[c["call"]]) + 200
        if cur and size + n > budget:
            out.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += n
    if cur:
        out.append(cur)
    return out


def balance(calls: list[dict], texts: dict[str, str], budget: int) -> list[list[dict]]:
    """Fewest batches under the budget, then even sizes (greedy on a lowered budget)."""
    k = len(pack_batches(calls, texts, budget))
    total = sum(len(texts[c["call"]]) + 200 for c in calls)
    lo = total // k
    for b in range(lo, budget + 1, 2000):
        got = pack_batches(calls, texts, b)
        if len(got) == k:
            return got
    return pack_batches(calls, texts, budget)


def main() -> None:
    m = json.loads((PACK / "manifest.json").read_text())
    calls = m["calls"]
    texts = {c["call"]: (PACK / c["file"]).read_text(encoding="utf-8") for c in calls}
    prompt = (PACK / "prompt.txt").read_text(encoding="utf-8")
    budget = int(MAX_TOKENS * CHARS_PER_TOKEN) - len(prompt) - 2000
    s_calls = [c for c in calls if c["call"].endswith("-S")]
    a_calls = [c for c in calls if c["call"].endswith("-A")]
    test, s_rest = s_calls[:TEST_ACTIONS], s_calls[TEST_ACTIONS:]
    groups = [test, *balance(s_rest, texts, budget), *balance(a_calls, texts, budget)]
    # Never touch what the operator owns (answers/, model_log.txt, redo/): only generated files
    # are (re)written, and a batch file that would change is refused once answers exist.
    OUT.mkdir(parents=True, exist_ok=True)
    has_answers = any((OUT / "answers").glob("*")) if (OUT / "answers").exists() else False
    total = len(groups)
    old_prompt = OUT / "prompt.txt"
    if has_answers and old_prompt.exists() and old_prompt.read_text(encoding="utf-8") != prompt:
        raise SystemExit("prompt.txt would change, but answers exist; not rebuilding")
    index, bodies = [], {}
    for i, g in enumerate(groups, 1):
        n = f"{i:02d}"
        body = batch_text(n, total, g, texts)
        if len(body) + len(prompt) > MAX_TOKENS * CHARS_PER_TOKEN:
            raise SystemExit(f"batch {n} is over budget")
        for c in g:  # the packet text is carried unchanged
            assert section(c["call"], texts[c["call"]]) in body
        f = OUT / f"batch_{n}.txt"
        if has_answers and f.exists() and f.read_text(encoding="utf-8") != body:
            raise SystemExit(f"{f.name} would change, but answers exist; not rebuilding")
        bodies[f] = body
        index.append(
            {
                "batch": n,
                "file": f.name,
                "kind": "agreement" if g[0]["call"].endswith("-A") else "statement",
                "test": i == 1,
                "calls": [c["call"] for c in g],
                "ids": [q["id"] for c in g for q in c["questions"]],
                "chars": len(body),
                "est_tokens_with_prompt": round((len(body) + len(prompt)) / CHARS_PER_TOKEN),
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )
    covered = [c for b in index for c in b["calls"]]
    if sorted(covered) != sorted(c["call"] for c in calls) or len(set(covered)) != len(covered):
        raise SystemExit("batches must cover every call exactly once")
    # Every check has passed; only now is anything written.
    for f, body in bodies.items():
        f.write_text(body, encoding="utf-8")
    (OUT / "batches.json").write_text(json.dumps({"batches": index}, indent=1) + "\n")
    shutil.copyfile(PACK / "prompt.txt", OUT / "prompt.txt")
    shutil.copyfile(PACK / "manifest.json", OUT / "manifest.json")
    shutil.copyfile(PACK / "ingest.py", OUT / "ingest_core.py")
    shutil.copyfile(HERE / "gemini_ingest.py", OUT / "ingest.py")
    shutil.copyfile(HERE / "gemini_howto.txt", OUT / "HOWTO.txt")
    (OUT / "answers").mkdir(exist_ok=True)
    if not (OUT / "model_log.txt").exists():
        (OUT / "model_log.txt").write_text(
            "batch | model name exactly as shown in the picker | date | notes\n"
            + "".join(f"{b['batch']} |  |  | \n" for b in index)
        )
    SUMMARY.write_text(
        json.dumps(
            {
                "pack_manifest_sha256": hashlib.sha256(
                    (PACK / "manifest.json").read_bytes()
                ).hexdigest(),
                "prompt_sha256": hashlib.sha256((PACK / "prompt.txt").read_bytes()).hexdigest(),
                "chars_per_token_estimate": CHARS_PER_TOKEN,
                "batches": [{k: v for k, v in b.items() if k != "ids"} for b in index],
            },
            indent=1,
        )
        + "\n"
    )
    for b in index:
        print(
            b["batch"], b["kind"], len(b["calls"]), "calls", len(b["ids"]), "IDs",
            f"~{b['est_tokens_with_prompt'] // 1000}k tokens",
        )  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
