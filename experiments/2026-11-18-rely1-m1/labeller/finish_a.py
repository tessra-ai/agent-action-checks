"""Consolidate labeller A once every call has an accepted answer. Run once, after run_codex.py.

    python labeller/finish_a.py --run labeller_a_high --name labels_a   (from the M1 folder)

Labeller A from 2026-11-19/20 is the reasoning run (runs/labeller_a_high, effort high) written as
labels_a; the first, no-reasoning run (runs/labeller_a) is kept as labels_a_noreasoning.

Checks all answers with the pack's ingest (--require-all) and writes, committed:
- `results/labels_a.jsonl`: one row per question ID (answer, reason, flags);
- `results/labels_a_summary.json`: model, CLI version, reasoning effort, run dates, calls and
  attempts per day, outcomes, tokens, reasons over 20 words.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

M1 = Path(__file__).resolve().parents[1]
PACK = M1 / "runs/labeller_pack"
RUN = M1 / "runs/labeller_a_high"
OUT = M1 / "results/labels_a.jsonl"
SUMMARY = M1 / "results/labels_a_summary.json"


def main() -> int:
    import argparse

    global RUN, OUT, SUMMARY
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="labeller_a_high")
    ap.add_argument("--name", default="labels_a")
    a = ap.parse_args()
    RUN = M1 / "runs" / a.run
    OUT = M1 / "results" / f"{a.name}.jsonl"
    SUMMARY = M1 / "results" / f"{a.name}_summary.json"
    spec = importlib.util.spec_from_file_location("pack_ingest", PACK / "ingest.py")
    ingest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingest)
    manifest = ingest.load_manifest(PACK / "manifest.json")
    # The answers must belong to this exact pack: the run's fingerprint and every packet.
    fp = {
        "manifest_sha256": hashlib.sha256((PACK / "manifest.json").read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256((PACK / "prompt.txt").read_bytes()).hexdigest(),
    }
    if json.loads((RUN / "pack_fingerprint.json").read_text()) != fp:
        raise SystemExit("the pack differs from the one labeller A ran on")
    for c in manifest[0]["calls"]:
        if hashlib.sha256((PACK / c["file"]).read_bytes()).hexdigest() != c["sha256"]:
            raise SystemExit(f"{c['file']} does not match the manifest")
    sources = ingest.read_sources([str(RUN / "answers")])
    problems, _, rows = ingest.check(sources, manifest, require_all=True)
    if problems:
        print("\n".join(problems[:20]))
        raise SystemExit(f"{len(problems)} problems; labeller A is not complete")
    log = [json.loads(x) for x in (RUN / "log.jsonl").read_text().splitlines()]
    # One accepted attempt per call: the last "ok", which wrote the saved reply.
    ok = list({r["call"]: r for r in log if r["outcome"] == "ok"}.values())
    if {r["call"] for r in ok} != {c["call"] for c in manifest[0]["calls"]}:
        raise SystemExit("the log's accepted attempts do not cover exactly the pack's calls")
    models = {r["model"] for r in ok}
    if len(models) != 1:
        raise SystemExit(f"accepted answers must come from one model: {models}")
    with OUT.open("w") as f:
        for r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if k != "source"}) + "\n")
    summary = {
        "labeller": "A",
        "tool": sorted({r["cli"] for r in log}),
        "model": models.pop(),
        "reasoning_effort": sorted({str(r["reasoning_effort"]) for r in ok}),
        "sign_in": "ChatGPT (codex login status); no API key in the environment",
        "dates": sorted({r["date"] for r in log}),
        "calls_accepted_per_day": dict(sorted(Counter(r["date"] for r in ok).items())),
        "attempts_per_day": dict(sorted(Counter(r["date"] for r in log).items())),
        "outcomes": dict(Counter(r["outcome"] for r in log)),
        "calls": len(ok),
        "tokens_used_total": sum(r.get("tokens_used") or 0 for r in log),
        "answers": len(rows),
        "answer_counts": {
            f"{k}:{a}": n
            for (k, a), n in sorted(Counter((r["kind"], r["answer"]) for r in rows).items())
        },
        "reasons_over_20_words": sum(1 for r in rows if r.get("reason_over_20_words")),
        "run_folder": f"runs/{RUN.name}",
    }
    SUMMARY.write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
