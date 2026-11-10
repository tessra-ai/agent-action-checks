"""Pinned model ids for the benchmark: the τ² agents, the τ² user simulator and the judges.

The harness and scorer default to these ids, so every run names the same model snapshot. OpenAI
ids are the dated snapshots `GET /v1/models` listed on 2026-10-21; an alias such as
`gpt-4.1-mini` can move to a new snapshot without notice, a dated id does not.

- `gpt-6-luna`, the only OpenAI Decisions model, has no dated id: `GET /v1/models` lists only
  the alias. Its responses carry no snapshot either, so a silent model update would go unseen.
- Jev is versioned by name (`jev-1.14.0`).
"""

from __future__ import annotations

from hatchway.judges import jev, openai_decisions

GPT_4_1_NANO = "gpt-4.1-nano-2025-04-14"
GPT_4_1_MINI = "gpt-4.1-mini-2025-04-14"
GPT_4_1 = "gpt-4.1-2025-04-14"

# τ² agent models, cheapest first.
AGENT_MODELS = (GPT_4_1_NANO, GPT_4_1_MINI, GPT_4_1)
USER_SIMULATOR_MODEL = GPT_4_1_MINI

LLM_BASELINE_MODEL = GPT_4_1_MINI
DECISIONS_MODEL = openai_decisions.DEFAULT_MODEL  # no dated id exists
JEV_MODEL = jev.DEFAULT_MODEL

__all__ = [
    "AGENT_MODELS",
    "DECISIONS_MODEL",
    "GPT_4_1",
    "GPT_4_1_MINI",
    "GPT_4_1_NANO",
    "JEV_MODEL",
    "LLM_BASELINE_MODEL",
    "USER_SIMULATOR_MODEL",
]
