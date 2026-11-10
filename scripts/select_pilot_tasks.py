"""Choose the pilot and smoke-test τ² tasks and write their run configs.

Usage (needs τ² installed, as in the CI `tau2` job): python scripts/select_pilot_tasks.py

    python scripts/select_pilot_tasks.py targeted   # the targeted experiment's stage configs

The targeted experiment (`hatchway.bench.experiment`) uses only tasks whose reference plan has a
primary action (`hatchway.bench.tau2.families`): every retail `base` task with a return, and
`TARGETED_TELECOM_PER_INCIDENCE` telecom `base` tasks of each incidence (roaming and refuel,
refuel only, roaming only), ordered by a seeded shuffle of scenario families. Its three stage
configs are cumulative (`targeted-1` within `targeted-2` within `targeted-3`), so the resumable
harness only runs the new simulations of each stage. The `base` payment-request tasks
(descriptive only) come last, in stage 3.

Writes hatchway/bench/tau2/configs/{pilot,smoke}.yaml. Tasks come from each domain's `base`
split and are split by their ground truth: tasks with at least one assistant write tool call,
and tasks with none (the agent should refuse, transfer, or, in telecom, only guide the user
through device fixes). The pilot takes about 20% no-write tasks and covers every write tool
the split uses, the rare ones first; the order is fixed by `SEED`, so reruns give the same
configs. Nothing is run.
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import yaml
from tau2.config import DEFAULT_MAX_STEPS
from tau2.environment.toolkit import ToolType
from tau2.registry import registry
from tau2.run import get_tasks

from hatchway.bench import models
from hatchway.bench.tau2.config import (
    AGENT_SHARE,
    CONFIG_DIR,
    MEASURED_MINI_SIM_USD,
    CostEstimate,
    DomainTasks,
    RunConfig,
    estimate_cost,
)

SEED = 20261021
DOMAINS = ("retail", "telecom")
SPLIT = "base"
PILOT_TASKS = 50  # one trial each: ~50 simulations per agent model per domain
NO_WRITE_SHARE = 0.2
MIN_PER_WRITE_TOOL = 3  # or every task using the tool, if fewer
RUN_SEED = 300  # τ²'s default seed
PILOT_CAP_USD = 15.0
SMOKE_CAP_USD = 1.0
TARGETED_SEED = 20261023
TARGETED_TELECOM_PER_INCIDENCE = 8
TARGETED_STAGES = 3
TARGETED_CAPTURE_CAP_USD = 9.0
TARGETED_MAX_OUTPUT_TOKENS = 4096


def ground_truth_writes(domain: str) -> dict[str, list[str]]:
    """Task id -> the write tools its ground truth has the assistant call, in `SPLIT`."""
    tools = registry.get_env_constructor(domain)().tools
    writes = {name for name in tools.tools if tools.tool_type(name) is ToolType.WRITE}
    return {
        task.id: [
            a.name
            for a in task.evaluation_criteria.actions or []
            if a.requestor == "assistant" and a.name in writes
        ]
        for task in get_tasks(domain, task_split_name=SPLIT)
    }


def select(domain: str, n: int, rng: random.Random) -> DomainTasks:
    truth = ground_truth_writes(domain)
    write_ids = [t for t, w in truth.items() if w]
    no_write_ids = [t for t, w in truth.items() if not w]
    rng.shuffle(write_ids)
    rng.shuffle(no_write_ids)
    n_no_write = min(round(n * NO_WRITE_SHARE), len(no_write_ids))
    n_write = n - n_no_write
    chosen: list[str] = []
    counts = Counter(tool for t in write_ids for tool in set(truth[t]))
    covered: Counter[str] = Counter()
    for tool, _ in sorted(counts.items(), key=lambda kv: (kv[1], kv[0])):  # rarest first
        for task in write_ids:
            if covered[tool] >= min(MIN_PER_WRITE_TOOL, counts[tool]) or len(chosen) >= n_write:
                break
            if tool in truth[task] and task not in chosen:
                chosen.append(task)
                covered.update(set(truth[task]))
    chosen += [t for t in write_ids if t not in chosen][: n_write - len(chosen)]
    return DomainTasks(
        task_split=SPLIT,
        write_task_ids=sorted(chosen, key=write_ids.index),
        no_write_task_ids=no_write_ids[:n_no_write],
    )


def smoke(pilot: DomainTasks) -> DomainTasks:
    """Two simulations: the pilot's first write task and its first no-write task."""
    return DomainTasks(
        task_split=pilot.task_split,
        write_task_ids=pilot.write_task_ids[:1],
        no_write_task_ids=pilot.no_write_task_ids[:1],
    )


def config(
    name: str, domains: dict[str, DomainTasks], cap: float, max_output_tokens: int | None = None
) -> RunConfig:
    draft = RunConfig(
        name=name,
        domains=domains,
        agent_models=list(models.AGENT_MODELS),
        user_model=models.USER_SIMULATOR_MODEL,
        trials=1,
        seed=RUN_SEED,
        max_steps=DEFAULT_MAX_STEPS,
        max_concurrency=4,
        spend_cap_usd=cap,
        max_output_tokens=max_output_tokens,
        cost_estimate=CostEstimate(central_usd=0, upper_bound_usd=0),
    )
    total = estimate_cost(draft)["total"]
    estimate = CostEstimate(
        central_usd=round(total["central_usd"], 2),
        upper_bound_usd=round(total["upper_bound_usd"], 2),
    )
    return draft.model_copy(update={"cost_estimate": estimate})


def write(cfg: RunConfig, why: str) -> Path:
    estimate = estimate_cost(cfg)
    lines = [
        f"# {why}",
        "# Generated by scripts/select_pilot_tasks.py; edit the script, not this file.",
        f"# Agent + user cost estimate: ~${MEASURED_MINI_SIM_USD} per gpt-4.1-mini simulation,",
        "# scaled by model input price. Central: the agent is "
        f"{AGENT_SHARE:.0%} of a simulation's cost;",
        "# upper bound: all of it at the dearer model. Not measured per domain (telecom",
        "# conversations may run longer). Judge scoring is not included.",
    ]
    for key, row in estimate.items():
        lines.append(
            f"#   {key}: {row['simulations']} simulations, ${row['central_usd']:.2f} central, "
            f"${row['upper_bound_usd']:.2f} upper bound"
        )
    data = cfg.model_dump(mode="json")
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=200)
    path = CONFIG_DIR / f"{cfg.name}.yaml"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n" + body)
    return path


def _by_family(domain: str, tasks: list, rng: random.Random) -> list[str]:
    """Task ids with whole scenario families kept together, families in seeded order."""
    from hatchway.bench.tau2.families import scenario_family

    families: dict[str, list[str]] = {}
    for task in sorted(tasks, key=lambda t: t.id):
        families.setdefault(scenario_family(domain, task), []).append(task.id)
    order = sorted(families)
    rng.shuffle(order)
    return [task_id for family in order for task_id in families[family]]


def _stages(ids: list[str], n: int) -> list[list[str]]:
    """Cumulative prefixes: stage k holds the first k/n of `ids`."""
    return [ids[: round(len(ids) * (k + 1) / n)] for k in range(n)]


def targeted() -> list[Path]:
    """The targeted experiment's cumulative stage configs (see the module docstring)."""
    from hatchway.bench.tau2.families import DESCRIPTIVE_ACTIONS, incidence, reference_actions

    rng = random.Random(TARGETED_SEED)
    retail = [t for t in get_tasks("retail", task_split_name=SPLIT) if incidence(t)]
    retail_ids = _by_family("retail", retail, rng)
    telecom = get_tasks("telecom", task_split_name=SPLIT)
    groups: dict[tuple[str, ...], list] = {}
    for task in telecom:
        if incidence(task):
            groups.setdefault(incidence(task), []).append(task)
    chosen = []
    for key in sorted(groups):
        ids = _by_family("telecom", groups[key], rng)
        chosen += [t for t in groups[key] if t.id in ids[:TARGETED_TELECOM_PER_INCIDENCE]]
    telecom_ids = _by_family("telecom", chosen, rng)
    payments = sorted(
        t.id for t in telecom if reference_actions(t, DESCRIPTIVE_ACTIONS) and not incidence(t)
    )
    paths = []
    for k, (r, t) in enumerate(
        zip(
            _stages(retail_ids, TARGETED_STAGES),
            _stages(telecom_ids, TARGETED_STAGES),
            strict=True,
        )
    ):
        last = k == TARGETED_STAGES - 1
        domains = {
            "retail": DomainTasks(task_split=SPLIT, write_task_ids=r),
            "telecom": DomainTasks(task_split=SPLIT, write_task_ids=t + (payments if last else [])),
        }
        cfg = config(
            f"targeted-{k + 1}", domains, TARGETED_CAPTURE_CAP_USD, TARGETED_MAX_OUTPUT_TOKENS
        )
        paths.append(
            write(
                cfg,
                f"Targeted experiment, stage {k + 1} of {TARGETED_STAGES} (cumulative): "
                "primary-action tasks"
                + (", then the payment-request tasks (descriptive)." if last else "."),
            )
        )
    return paths


def main() -> int:
    if sys.argv[1:] == ["targeted"]:
        for path in targeted():
            print(path)
        return 0
    rng = random.Random(SEED)
    pilot = {domain: select(domain, PILOT_TASKS, rng) for domain in DOMAINS}
    print(write(config("pilot", pilot, PILOT_CAP_USD), "Pilot capture run: NOT run yet."))
    smoke_domains = {domain: smoke(tasks) for domain, tasks in pilot.items()}
    smoke_cfg = config("smoke", smoke_domains, SMOKE_CAP_USD)
    print(write(smoke_cfg, "Smoke test for the pilot: 2 simulations per model per domain."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
