"""Pinned model ids and the committed τ² run configs (no τ² needed; the `tau2` CI job checks the
task ids against τ²'s ground truth)."""

import pytest

from hatchway.bench import models
from hatchway.bench.score import make_judge
from hatchway.bench.tau2.config import (
    CONFIG_DIR,
    estimate_cost,
    load_run_config,
    per_simulation_usd,
)
from hatchway.judges import llm_baseline

CONFIGS = ["pilot", "smoke"]


def test_pinned_openai_models_are_dated_snapshots() -> None:
    for model in (*models.AGENT_MODELS, models.USER_SIMULATOR_MODEL, models.LLM_BASELINE_MODEL):
        assert model.endswith("-2025-04-14"), model
        assert model in llm_baseline.PRICES and model in llm_baseline.BATCH_PRICES
    assert models.DECISIONS_MODEL == "gpt-6-luna"  # no dated id exists
    assert models.JEV_MODEL == "jev-1.14.0"


def test_scorer_defaults_to_the_pinned_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-real")
    assert make_judge("llm_baseline", None).model_id == models.LLM_BASELINE_MODEL  # type: ignore[arg-type]
    assert make_judge("openai_decisions", None).model_id == models.DECISIONS_MODEL  # type: ignore[arg-type]
    assert make_judge("jev", None).model_id == models.JEV_MODEL  # type: ignore[arg-type]
    assert make_judge("llm_baseline:gpt-4.1-nano", None).model_id == "gpt-4.1-nano"  # type: ignore[arg-type]


def test_standard_and_batch_prices_follow_the_price_page() -> None:
    mini = llm_baseline.PRICES[models.GPT_4_1_MINI]
    assert (mini.input, mini.cached_input, mini.output) == pytest.approx(
        (0.40e-6, 0.10e-6, 1.60e-6)
    )
    batch = llm_baseline.BATCH_PRICES[models.GPT_4_1_MINI]
    assert (batch.input, batch.output) == pytest.approx((mini.input / 2, mini.output / 2))
    assert batch.cached_input == batch.input  # no batch cached-input price is listed


@pytest.mark.parametrize("name", CONFIGS)
def test_config_uses_the_pinned_models_and_its_estimate_is_current(name: str) -> None:
    config = load_run_config(CONFIG_DIR / f"{name}.yaml")
    assert config.name == name
    assert set(config.domains) == {"retail", "telecom"}
    assert config.agent_models == list(models.AGENT_MODELS)
    assert config.user_model == models.USER_SIMULATOR_MODEL
    total = estimate_cost(config)["total"]
    assert config.cost_estimate.central_usd == round(total["central_usd"], 2)
    assert config.cost_estimate.upper_bound_usd == round(total["upper_bound_usd"], 2)
    assert config.spend_cap_usd is not None
    assert config.spend_cap_usd >= config.cost_estimate.upper_bound_usd


def test_pilot_size_and_no_write_share() -> None:
    config = load_run_config(CONFIG_DIR / "pilot.yaml")
    for domain, tasks in config.domains.items():
        assert config.simulations(domain) == 50, domain
        share = len(tasks.no_write_task_ids) / len(tasks.task_ids)
        # Retail's base split has only 9 tasks without a write.
        assert 0.18 <= share <= 0.2, domain


def test_smoke_is_two_simulations_per_model_per_domain_drawn_from_the_pilot() -> None:
    smoke = load_run_config(CONFIG_DIR / "smoke.yaml")
    pilot = load_run_config(CONFIG_DIR / "pilot.yaml")
    for domain, tasks in smoke.domains.items():
        assert smoke.simulations(domain) == 2
        assert len(tasks.write_task_ids) == len(tasks.no_write_task_ids) == 1
        assert set(tasks.task_ids) <= set(pilot.domains[domain].task_ids)


def test_cost_scales_with_model_price() -> None:
    mini = per_simulation_usd(models.GPT_4_1_MINI, models.GPT_4_1_MINI)
    assert mini == pytest.approx((0.013, 0.013))
    central, upper = per_simulation_usd(models.GPT_4_1, models.GPT_4_1_MINI)
    assert central == pytest.approx(0.013 * (0.7 * 5 + 0.3))
    assert upper == pytest.approx(0.013 * 5)
    central, upper = per_simulation_usd(models.GPT_4_1_NANO, models.GPT_4_1_MINI)
    assert central == pytest.approx(0.013 * (0.7 * 0.25 + 0.3))
    assert upper == pytest.approx(0.013)
