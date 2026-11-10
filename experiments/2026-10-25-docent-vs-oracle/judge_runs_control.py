"""Addendum 5 (separate venv with `docent==0.1.88`): rerun Docent's judge with the original,
unchanged rubric, as a noise control for Addendum 4.

Hard spend cap: token usage is counted on every OpenAI call (Responses API, which Docent uses,
and Chat Completions), and no new call starts once the total reaches `STOP_USD`. A one-write
probe runs first; the script stops unless the meter counted it. Writes
`results/judge_control.jsonl` once.

    <docent-venv>/bin/python experiments/2026-10-25-docent-vs-oracle/judge_runs_control.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from docent._llm_util.llm_svc import BaseLLMService
from docent.judges.runner import run_rubric
from docent.judges.types import DEFAULT_JUDGE_MODEL, Rubric
from judge_runs import (
    MAX_NEW_TOKENS,
    OUTPUT_SCHEMA,
    PRICE_IN,
    PRICE_OUT,
    ROLLOUTS,
    RUBRIC_TEXT,
    agent_run,
)
from openai.resources.chat.completions import AsyncCompletions
from openai.resources.responses import AsyncResponses

HERE = Path(__file__).parent
RUNS = HERE / "data/runs.jsonl"
OUT = HERE / "results/judge_control.jsonl"
CAP_USD, STOP_USD = 1.0, 0.90
WORST_CALL_USD = 30000 * PRICE_IN + MAX_NEW_TOKENS * PRICE_OUT

spent = {"usd": 0.0, "calls": 0, "refused": 0}


def _charge(out: object, stream: bool) -> None:
    usage = None if stream else getattr(out, "usage", None)
    if usage is None:
        spent["usd"] += WORST_CALL_USD
    else:
        tokens_in = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0)
        tokens_out = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0)
        spent["usd"] += tokens_in * PRICE_IN + tokens_out * PRICE_OUT
    spent["calls"] += 1


def _metered(original):  # wraps an SDK create method
    async def create(self, *args, **kwargs):
        if spent["usd"] >= STOP_USD:
            spent["refused"] += 1
            raise RuntimeError(f"spend cap reached (${spent['usd']:.3f}); no new calls")
        out = await original(self, *args, **kwargs)
        _charge(out, bool(kwargs.get("stream")))
        return out

    return create


def rubric() -> Rubric:
    return Rubric(
        rubric_text=RUBRIC_TEXT,
        output_schema=OUTPUT_SCHEMA,
        judge_model=DEFAULT_JUDGE_MODEL,
        n_rollouts_per_input=ROLLOUTS,
        judge_variant="majority",
    )


async def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; the judge runs once")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")
    AsyncResponses.create = _metered(AsyncResponses.create)
    AsyncCompletions.create = _metered(AsyncCompletions.create)
    rows = [json.loads(line) for line in RUNS.read_text().splitlines() if line.strip()]
    runs = [agent_run(i, r) for i, r in enumerate(rows)]
    svc = BaseLLMService(max_concurrency=8)

    await run_rubric(runs[:1], rubric(), svc, max_new_tokens=MAX_NEW_TOKENS, timeout=180.0)
    print(f"probe: {spent['calls']} calls metered, ${spent['usd']:.4f}")
    if spent["calls"] < ROLLOUTS or spent["usd"] <= 0:
        sys.exit("the meter did not count the probe; not starting")

    results = await run_rubric(runs, rubric(), svc, max_new_tokens=MAX_NEW_TOKENS, timeout=180.0)
    by_run = {r.agent_run_id: r for r in results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for run, row in zip(runs, rows, strict=True):
            res = by_run.get(run.id)
            meta = (res.result_metadata or {}) if res else {}
            rollouts = meta.get("final_results") or []
            f.write(
                json.dumps(
                    {
                        "write_id": row["write_id"],
                        "run_name": run.name,
                        "result_type": res.result_type.value if res else "missing",
                        "label": (res.output or {}).get("label") if res else None,
                        "explanation": (res.output or {}).get("explanation") if res else None,
                        "rollout_labels": [r.get("label") for r in rollouts],
                    },
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
    print(f"wrote {OUT}; spend ${spent['usd']:.3f} over {spent['calls']} calls (probe included)")
    print(f"calls refused by the cap: {spent['refused']}")


if __name__ == "__main__":
    asyncio.run(main())
