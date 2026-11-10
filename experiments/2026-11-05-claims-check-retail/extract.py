"""Extract the agent's claims about each of the 73 retail writes (gpt-4.1-mini, structured output).

    python experiments/2026-11-05-claims-check-retail/extract.py   # once

Same extractor, model, temperature, output limit and spend meter as the airline claims check
(`experiments/2026-10-28-claims-check/extract.py`); only the instructions and schema are the
retail ones. Hard cap $1 (stop at $0.95, worst case reserved per call, probe first). Writes
`results/extracted.jsonl`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

from openai import AsyncOpenAI

from hatchway.judges.llm_baseline import PRICES

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from claims_retail import INSTRUCTIONS, SCHEMA, render  # noqa: E402

RUNS = HERE.parent / "2026-10-25-docent-vs-oracle/data/runs.jsonl"
STORES = {"targeted": Path("runs/targeted.db"), "smoke2": Path("runs/smoke2.db")}
OUT = HERE / "results/extracted.jsonl"
MODEL = "gpt-4.1-mini-2025-04-14"
PRICE = PRICES[MODEL]
CAP_USD, STOP_USD = 1.0, 0.95
MAX_OUTPUT = 2000
spent = {"usd": 0.0, "reserved": 0.0, "calls": 0, "refused": 0}


def worst_case(prompt: str) -> float:
    return len(prompt) / 3 * PRICE.input + MAX_OUTPUT * PRICE.output


def load_rows() -> list[dict]:
    """The 73 writes in runs.jsonl order, each with its proposing text from its store."""
    runs = [json.loads(line) for line in RUNS.read_text().splitlines() if line.strip()]
    text = {}
    for path in STORES.values():
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for w, t in conn.execute("SELECT write_id, proposing_text FROM pre_action_snapshots"):
            text[w] = t or ""
    rows = []
    for r in runs:
        (call,) = [c for c in r["messages"][-1]["tool_calls"] if c["id"] == "proposed"]
        rows.append(
            {
                "write_id": r["write_id"],
                "action": r["action"],
                "args": call["arguments"],
                "messages": r["messages"][:-1],
                "proposing_text": text.get(r["write_id"], ""),
            }
        )
    return rows


async def extract(client: AsyncOpenAI, sem: asyncio.Semaphore, row: dict) -> dict:
    prompt = render(row["messages"], row["action"], row["args"], row["proposing_text"])
    async with sem:
        bound = worst_case(INSTRUCTIONS + prompt)
        if spent["usd"] + spent["reserved"] + bound > STOP_USD:
            spent["refused"] += 1
            return {"write_id": row["write_id"], "status": "not_scheduled", "claims": None}
        spent["reserved"] += bound
        try:
            resp = await client.chat.completions.create(
                model=MODEL,
                temperature=0,
                max_tokens=MAX_OUTPUT,
                messages=[
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "claims", "strict": True, "schema": SCHEMA},
                },
            )
        except Exception as exc:  # recorded, never retried silently
            spent["reserved"] -= bound
            return {"write_id": row["write_id"], "status": f"error: {exc!r}"[:300], "claims": None}
        spent["reserved"] -= bound
        u = resp.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        spent["usd"] += (
            (u.prompt_tokens - cached) * PRICE.input
            + cached * PRICE.cached_input
            + u.completion_tokens * PRICE.output
        )
        spent["calls"] += 1
        claims = json.loads(resp.choices[0].message.content or '{"claims": []}')["claims"]
        return {"write_id": row["write_id"], "status": "ok", "claims": claims}


async def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT} exists; written once")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")
    rows = load_rows()
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(8)
    probe = await extract(client, sem, rows[0])
    print(f"probe: {probe['status']}, {spent['calls']} call, ${spent['usd']:.4f}")
    if probe["status"] != "ok" or spent["usd"] <= 0:
        sys.exit("the probe failed or was not metered; not starting")
    rest = await asyncio.gather(*(extract(client, sem, r) for r in rows[1:]))
    out = [probe, *rest]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in out))
    print(
        f"wrote {OUT}: {sum(r['status'] == 'ok' for r in out)} of {len(out)} ok; "
        f"spend ${spent['usd']:.3f} over {spent['calls']} calls; refused {spent['refused']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
