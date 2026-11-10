"""Plan-aware claims extraction on one set (gpt-4.1-mini, structured output).

    python experiments/2026-11-05-airline-holdout/extract_plan.py airline1 | airline2 | retail

Same extractor, model, temperature, output limit and spend meter as the earlier claims checks;
the schema and instructions are the domain's plus `scope` and `target` (`claims_plan.py`).
Hard cap $1 per set (stop at $0.95, worst case reserved per call, probe first). Writes
`results/claims_<set>.jsonl` once.
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
from claims_plan import domain  # noqa: E402

SETS = {
    "airline1": ("airline", [Path("runs/airline/export.db")]),
    "airline2": ("airline", [Path("runs/airline2/export.db")]),
    "retail": ("retail", [Path("runs/targeted.db"), Path("runs/smoke2.db")]),
}
RETAIL_RUNS = HERE.parent / "2026-10-25-docent-vs-oracle/data/runs.jsonl"
MODEL = "gpt-4.1-mini-2025-04-14"
PRICE = PRICES[MODEL]
CAP_USD, STOP_USD = 1.0, 0.95
MAX_OUTPUT = 2500
spent = {"usd": 0.0, "reserved": 0.0, "calls": 0, "refused": 0}


def load_rows(name: str) -> list[dict]:
    """The set's writes with their pre-action messages and proposing text, from the stores."""
    _, stores = SETS[name]
    rows = []
    for path in stores:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for w, a, g, m, t, s, q in conn.execute(
            "SELECT w.write_id, w.action, w.args, s.messages, s.proposing_text, w.session_id, "
            "w.seq FROM captured_writes w JOIN pre_action_snapshots s USING (write_id) "
            "ORDER BY w.session_id, w.seq"
        ):
            rows.append(
                {
                    "write_id": w,
                    "action": a,
                    "args": json.loads(g),
                    "messages": json.loads(m),
                    "proposing_text": t or "",
                    "session": s,
                    "seq": q,
                }
            )
    if name == "retail":  # only the 73 writes of the retail experiment
        keep = {json.loads(line)["write_id"] for line in RETAIL_RUNS.read_text().splitlines()}
        rows = [r for r in rows if r["write_id"] in keep]
    return rows


def worst_case(prompt: str) -> float:
    return len(prompt) / 3 * PRICE.input + MAX_OUTPUT * PRICE.output


async def extract(client, sem, row, instructions, schema, render) -> dict:
    prompt = render(row["messages"], row["action"], row["args"], row["proposing_text"])
    async with sem:
        bound = worst_case(instructions + prompt)
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
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "claims", "strict": True, "schema": schema},
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
        try:
            claims = json.loads(resp.choices[0].message.content or '{"claims": []}')["claims"]
        except json.JSONDecodeError as exc:  # the output limit cut the JSON: no claims, recorded
            status = f"error: truncated ({exc})"[:300]
            return {"write_id": row["write_id"], "status": status, "claims": None}
        return {"write_id": row["write_id"], "status": "ok", "claims": claims}


async def main(name: str) -> None:
    out = HERE / f"results/claims_{name}.jsonl"
    if out.exists():
        sys.exit(f"{out} exists; written once")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")
    mod, schema, instructions = domain(SETS[name][0])
    rows = load_rows(name)
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(8)
    probe = await extract(client, sem, rows[0], instructions, schema, mod.render)
    print(f"probe: {probe['status']}, {spent['calls']} call, ${spent['usd']:.4f}")
    if probe["status"] != "ok" or spent["usd"] <= 0:
        sys.exit("the probe failed or was not metered; not starting")
    rest = await asyncio.gather(
        *(extract(client, sem, r, instructions, schema, mod.render) for r in rows[1:])
    )
    res = [probe, *rest]
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in res))
    print(
        f"wrote {out}: {sum(r['status'] == 'ok' for r in res)} of {len(res)} ok; "
        f"spend ${spent['usd']:.3f} over {spent['calls']} calls; refused {spent['refused']}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SETS:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
