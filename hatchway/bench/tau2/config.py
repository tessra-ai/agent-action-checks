"""Run configs for τ² capture runs: domains, task ids, agent and user models, trials, and a
cost estimate. Loaded without τ² installed, so configs are checked in every test job.

Cost estimate: one simulation with a gpt-4.1-mini agent and a gpt-4.1-mini user cost about
`MEASURED_MINI_SIM_USD` in earlier runs. Other models scale with their input price relative
to gpt-4.1-mini (output prices scale the same way for the gpt-4.1 family). The split of that
cost between agent and user was not measured, so two figures are given:

- `central`: the agent is `AGENT_SHARE` of a simulation's cost and the user the rest; each part
  scales with its own model's price.
- `upper_bound`: the whole simulation scales with the dearer of the two models. No agent/user
  split can cost more, unless simulations run longer (more turns) with another agent model.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hatchway.judges.llm_baseline import PRICES

MEASURED_MINI_SIM_USD = 0.013
AGENT_SHARE = 0.7
REFERENCE_MODEL = "gpt-4.1-mini"

CONFIG_DIR = Path(__file__).with_name("configs")


class DomainTasks(BaseModel):
    """Task ids for one domain. Every id is listed once, under whether its ground truth has an
    assistant write (`write_task_ids`) or none (`no_write_task_ids`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_split: str = "base"
    write_task_ids: list[str]
    no_write_task_ids: list[str] = Field(default_factory=list)

    @property
    def task_ids(self) -> list[str]:
        return [*self.write_task_ids, *self.no_write_task_ids]

    @model_validator(mode="after")
    def _unique(self) -> DomainTasks:
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task ids must be unique")
        return self


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    central_usd: float
    upper_bound_usd: float


class RunConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    domains: dict[str, DomainTasks] = Field(min_length=1)
    agent_models: list[str] = Field(min_length=1)
    user_model: str
    trials: int = Field(ge=1)
    seed: int
    temperature: float = 0.0
    max_steps: int = 200  # τ²'s DEFAULT_MAX_STEPS
    max_concurrency: int = Field(default=4, ge=1)
    spend_cap_usd: float | None = None
    # Output cap (`max_tokens`) for every agent and user call. A hard budget needs it: each
    # call's maximum cost is reserved before the call (`hatchway.bench.budget`).
    max_output_tokens: int | None = Field(default=None, ge=1)
    # The estimate the config was committed with; tests check it matches `estimate_cost`.
    cost_estimate: CostEstimate

    def simulations(self, domain: str) -> int:
        """Simulations per agent model in `domain`."""
        return len(self.domains[domain].task_ids) * self.trials


def price_ratio(model: str) -> float:
    """Input price relative to gpt-4.1-mini."""
    return PRICES[model].input / PRICES[REFERENCE_MODEL].input


def per_simulation_usd(agent_model: str, user_model: str) -> tuple[float, float]:
    """(central, upper bound) estimated cost of one simulation."""
    agent, user = price_ratio(agent_model), price_ratio(user_model)
    central = MEASURED_MINI_SIM_USD * (AGENT_SHARE * agent + (1 - AGENT_SHARE) * user)
    return central, MEASURED_MINI_SIM_USD * max(agent, user)


def estimate_cost(config: RunConfig) -> dict[str, dict[str, float]]:
    """Estimated cost per `domain/agent_model` and in total."""
    out: dict[str, dict[str, float]] = {}
    total_central = total_upper = 0.0
    for domain in config.domains:
        n = config.simulations(domain)
        for model in config.agent_models:
            central, upper = per_simulation_usd(model, config.user_model)
            out[f"{domain}/{model}"] = {
                "simulations": n,
                "central_usd": n * central,
                "upper_bound_usd": n * upper,
            }
            total_central += n * central
            total_upper += n * upper
    out["total"] = {
        "simulations": sum(config.simulations(d) for d in config.domains)
        * len(config.agent_models),
        "central_usd": total_central,
        "upper_bound_usd": total_upper,
    }
    return out


def load_run_config(path: str | Path) -> RunConfig:
    return RunConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
