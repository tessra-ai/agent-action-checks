"""The planned fourth draft, from Claude Sonnet 5.5, under the same brief (one call).

    python experiments/2026-11-05-model-drafted-rules/draft_claude.py

Needs `ANTHROPIC_API_KEY` in the environment (it is saved on the cloud environment but did not
reach the session that ran the other three drafts, see README.md). Same cap logic as
`draft.py`: worst case reserved before the call, hard cap $1, refuses above $0.95, never
retries, refuses to overwrite an existing draft. Prices: $2 / $10 per million tokens in / out
(Claude Sonnet 5.5). The model accepts no sampling parameters (the API rejects `temperature`),
so this draft is at the model's default sampling, unlike the OpenAI drafts at 0 and 1. Writes
`results/drafts/claude_sonnet55.py`, the reply beside it, and one line in
`results/drafts_claude.jsonl`. Then `run_drafts.py` scores it like the others.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anthropic

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from brief import INSTRUCTIONS, brief, extract_code  # noqa: E402

MODEL = "claude-sonnet-5-5"
# `b`: the second call (README, Deviation): thinking off and a 32k output budget, after the first
# call spent its 8k budget mostly on thinking and returned a truncated module.
VARIANT = sys.argv[1] if len(sys.argv) > 1 else ""
NAME = "claude_sonnet55_b" if VARIANT == "b" else "claude_sonnet55"
OUT_DIR = HERE / "results/drafts"
META = HERE / "results/drafts_claude.jsonl"
IN_PER_TOKEN, OUT_PER_TOKEN = 2.0 / 1e6, 10.0 / 1e6
CAP_USD, STOP_USD = 1.0, 0.95
MAX_OUTPUT = 32000 if VARIANT == "b" else 8000
THINKING = {"type": "between_tools"} if VARIANT == "b" else None  # off: no tools in this call


def main() -> None:
    if (OUT_DIR / f"{NAME}.py").exists():
        sys.exit(f"{OUT_DIR / NAME}.py exists; written once")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")
    user = brief()
    bound = len(INSTRUCTIONS + user) / 3 * IN_PER_TOKEN + MAX_OUTPUT * OUT_PER_TOKEN
    if bound > STOP_USD:
        sys.exit(f"worst case ${bound:.2f} is over the cap; not calling")
    client = anthropic.Anthropic()
    extra = {"thinking": THINKING} if THINKING else {}
    # Streamed: the SDK refuses a non-streaming call whose output budget could run long.
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_OUTPUT,  # Sonnet 5.5 takes no sampling parameters: model default
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": user}],
        **extra,
    ) as stream:
        resp = stream.get_final_message()
    reply = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    cost = resp.usage.input_tokens * IN_PER_TOKEN + resp.usage.output_tokens * OUT_PER_TOKEN
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{NAME}.py").write_text(extract_code(reply))
    (OUT_DIR / f"{NAME}.reply.md").write_text(reply)
    row = {
        "name": NAME,
        "model": MODEL,
        "max_tokens": MAX_OUTPUT,
        "thinking": THINKING,
        "temperature": None,  # not accepted by this model; its default sampling
        "status": "ok",
        "stop_reason": resp.stop_reason,
        "prompt_tokens": resp.usage.input_tokens,
        "completion_tokens": resp.usage.output_tokens,
        "usd": round(cost, 4),
    }
    with META.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"{NAME}: {resp.stop_reason}, {resp.usage.output_tokens} out, ${cost:.3f}")


if __name__ == "__main__":
    main()
