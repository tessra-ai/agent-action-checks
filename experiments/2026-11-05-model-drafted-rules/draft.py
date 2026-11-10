"""Draft airline rules from the policy with a model, three times (once per draft).

    python experiments/2026-11-05-model-drafted-rules/draft.py

Same metered client as the claims checks: worst case reserved per call, hard cap $1, stop at
$0.95. Saves each reply's module verbatim to `results/drafts/<name>.py` and the usage to
`results/drafts.jsonl`. Written once; a second run refuses.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from hatchway.judges.llm_baseline import PRICES

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from brief import INSTRUCTIONS, brief, extract_code  # noqa: E402

OUT_DIR = HERE / "results/drafts"
META = HERE / "results/drafts.jsonl"
DRAFTS = (
    ("gpt41_t0", "gpt-4.1-2025-04-14", 0.0),
    ("gpt41_t1", "gpt-4.1-2025-04-14", 1.0),
    ("gpt41mini_t0", "gpt-4.1-mini-2025-04-14", 0.0),
)
CAP_USD, STOP_USD = 1.0, 0.95
MAX_OUTPUT = 8000


def worst_case(model: str, prompt: str) -> float:
    p = PRICES[model]
    return len(prompt) / 3 * p.input + MAX_OUTPUT * p.output


def main() -> None:
    if META.exists():
        sys.exit(f"{META} exists; written once")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")
    client = OpenAI()
    user = brief()
    spent = 0.0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, model, temperature in DRAFTS:
        bound = worst_case(model, INSTRUCTIONS + user)
        if spent + bound > STOP_USD:
            rows.append({"name": name, "model": model, "status": "not_scheduled"})
            continue
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=MAX_OUTPUT,
                messages=[
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:  # recorded, never retried
            rows.append({"name": name, "model": model, "status": f"error: {exc!r}"[:300]})
            continue
        u = resp.usage
        p = PRICES[model]
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        cost = (
            (u.prompt_tokens - cached) * p.input
            + cached * p.cached_input
            + u.completion_tokens * p.output
        )
        spent += cost
        reply = resp.choices[0].message.content or ""
        (OUT_DIR / f"{name}.py").write_text(extract_code(reply))
        (OUT_DIR / f"{name}.reply.md").write_text(reply)
        rows.append(
            {
                "name": name,
                "model": model,
                "temperature": temperature,
                "status": "ok",
                "finish_reason": resp.choices[0].finish_reason,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "usd": round(cost, 4),
            }
        )
        print(f"{name}: {resp.choices[0].finish_reason}, {u.completion_tokens} out, ${cost:.3f}")
    META.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"spent ${spent:.3f} over {sum(r['status'] == 'ok' for r in rows)} drafts")


if __name__ == "__main__":
    main()
