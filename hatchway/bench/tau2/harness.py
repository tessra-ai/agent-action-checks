"""Run τ²-bench simulations with every agent write captured by the shadow gate.

The harness wraps the live environment of one simulation. Reads pass through untouched; every
tool call the agent makes goes through `Gate.check()` first, which captures writes (tools the
policy marks `kind: write`) and always returns `ALLOW` in shadow mode, so the agent sees exactly
the results it would see unwrapped. Calls made by the simulated user (telecom device tools) and
the replay of a task's initial state are never captured. Evaluation replays the trajectory in
fresh, unwrapped environments, so it captures nothing either.

Each simulation is one session: its ULID is both the store's `session_id` and the τ²
`SimulationRun.id`, so captured writes join to saved simulations.

Runs are resumable. Each simulation is keyed on (mode, domain, task_id, trial, agent_model,
seed) and recorded in the store's `simulations` table when it starts and again, with its full
`SimulationRun`, the moment it finishes. A rerun skips every key already done; a simulation
that was killed or failed runs again under a new session, and the writes its first attempt
captured are left out of scoring (`BenchStore.abandoned_session_ids`). `--spend-cap USD`
stops starting new simulations once this run's agent and user cost (litellm's, as τ² reports
it) reaches the cap; simulations already running finish, so the cap can be exceeded by up to
`--max-concurrency - 1` simulations.

A hard cap instead goes through a `budget.Ledger` (`run_config(ledger=...)`, used by
`hatchway.bench.experiment`): `budget_guard` reserves every agent and user LLM call's maximum
cost before it is sent and refuses a call that could exceed the cap. A refused call aborts its
simulation, which is recorded as failed, so none of its writes is analysed.

Pass-rate check (makes LLM calls through litellm; the agent and user models need API keys):

    python -m hatchway.bench.tau2.harness --domain retail --task-ids 0 1 2 3 4 --trials 2 \\
        --store runs/m4.db --out runs/m4

Capture run from a committed config (wrapped only; models pinned in `hatchway.bench.models`):

    python -m hatchway.bench.tau2.harness --config hatchway/bench/tau2/configs/smoke.yaml \\
        --store runs/smoke.db --out runs/smoke
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from tau2.agent.base import BaseAgent
from tau2.agent.llm_agent import LLMAgent
from tau2.config import (
    DEFAULT_LLM_ARGS_AGENT,
    DEFAULT_LLM_ARGS_USER,
    DEFAULT_MAX_ERRORS,
    DEFAULT_MAX_STEPS,
    DEFAULT_SEED,
)
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.data_model.simulation import Results, SimulationRun
from tau2.data_model.tasks import Task
from tau2.environment.environment import Environment
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.registry import registry
from tau2.run import get_info, get_tasks
from tau2.user.base import BaseUser
from tau2.user.user_simulator import UserSimulator

from hatchway.bench import models
from hatchway.bench.budget import BudgetRefused, Ledger, llm_call_max_usd
from hatchway.bench.outcomes import task_passed
from hatchway.bench.provenance import git_commit
from hatchway.bench.store import BenchStore, OutcomeRecord
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.bench.tau2.config import RunConfig, load_run_config
from hatchway.bench.tau2.snapshot import executed_outcome, live_proposal
from hatchway.gate import Gate
from hatchway.policy import Kind, Policy
from hatchway.state import render_call
from hatchway.ulid import new_ulid

AgentFactory = Callable[[Environment, Task], BaseAgent]
UserFactory = Callable[[Environment, Task], BaseUser]


class CaptureOrchestrator(Orchestrator):
    """A τ² orchestrator whose environment sends the agent's tool calls through the gate."""

    def __init__(
        self, *args: Any, gate: Gate, session_id: str, trial: int | None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.gate = gate
        self.session_id = session_id
        self.trial = trial
        self._capturing = False
        self._get_response = self.environment.get_response
        self.environment.get_response = self._gated_response

    def initialize(self) -> None:
        super().initialize()  # replays the task's initial state, which is not captured
        self._capturing = True

    def _gated_response(self, tool_call: ToolCall) -> ToolMessage:
        if not (self._capturing and tool_call.requestor == "assistant"):
            return self._get_response(tool_call)
        context = {
            "policy": self.environment.get_policy(),
            "conversation": render_transcript(self.trajectory, tool_call),
        }
        proposal = None
        if is_write(self.gate.policy, tool_call.name):
            proposal = live_proposal(
                self.environment,
                self.trajectory,
                tool_call,
                domain=self.domain,
                task_id=self.task.id,
            )
        # Shadow mode always allows. The write, its pre-action snapshot and its policy verdict
        # are committed before the tool runs. Store errors propagate and stop the run: the
        # environment would otherwise turn them into a tool error the agent sees.
        decision = self.gate.check(
            tool_call.name,
            tool_call.arguments,
            context,
            session_id=self.session_id,
            task_id=self.task.id,
            trial=self.trial,
            pre_execution=None if proposal is None else proposal.pre_execution,
        )
        if proposal is None or decision.receipt_id is None:
            return self._get_response(tool_call)
        try:
            result = self._get_response(tool_call)
        except Exception as exc:
            self.gate.store.record_outcome(
                decision.receipt_id,
                OutcomeRecord(
                    outcome="TECHNICAL_ERROR", backend_error=f"{type(exc).__name__}: {exc}"
                ),
            )
            raise
        self.gate.store.record_outcome(
            decision.receipt_id, executed_outcome(proposal, result, self.environment)
        )
        return result


def render_transcript(messages: Sequence[Message], pending: ToolCall) -> str:
    """The conversation before `pending`, one line per message, tool call or tool result.

    The message carrying `pending` contributes its text only: its tool calls have no results
    yet, and the proposed call is rendered separately in the judge state.
    """
    lines = []
    for message in messages:
        if isinstance(message, AssistantMessage | UserMessage):
            if message.content:
                lines.append(f"{message.role}: {message.content}")
            calls = message.tool_calls or []
            if any(call is pending for call in calls):
                break
            lines.extend(f"{message.role} -> {render_call(c.name, c.arguments)}" for c in calls)
        elif isinstance(message, ToolMessage):
            lines.append(f"tool ({message.requestor}): {message.content}")
    return "\n".join(lines)


def run_simulation(
    domain: str,
    task: Task,
    *,
    trial: int,
    seed: int | None,
    gate: Gate | None = None,
    agent_model: str | None = None,
    agent_llm_args: dict[str, Any] | None = None,
    user_model: str | None = None,
    user_llm_args: dict[str, Any] | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_errors: int = DEFAULT_MAX_ERRORS,
    make_agent: AgentFactory | None = None,
    make_user: UserFactory | None = None,
    session_id: str | None = None,
) -> SimulationRun:
    """Run and evaluate one simulation, as `tau2.run.run_task` does for `llm_agent` with
    `user_simulator`. With a gate the agent's tool calls are captured; without one the run is
    plain τ². `make_agent` and `make_user` replace the LLM agent and user (tests use scripted
    ones). `session_id` defaults to a new ULID."""
    if gate is not None and gate.domain != domain:
        raise ValueError(f"gate domain {gate.domain!r} does not match {domain!r}")
    environment = registry.get_env_constructor(domain)()
    if make_agent is None:
        agent: BaseAgent = LLMAgent(
            tools=environment.get_tools(),
            domain_policy=environment.get_policy(),
            llm=agent_model,
            llm_args=dict(DEFAULT_LLM_ARGS_AGENT if agent_llm_args is None else agent_llm_args),
        )
    else:
        agent = make_agent(environment, task)
    if make_user is None:
        user: BaseUser = UserSimulator(
            tools=environment.get_user_tools() if environment.user_tools else None,
            instructions=str(task.user_scenario),
            llm=user_model,
            llm_args=dict(DEFAULT_LLM_ARGS_USER if user_llm_args is None else user_llm_args),
        )
    else:
        user = make_user(environment, task)

    session_id = session_id or new_ulid()
    settings = dict(
        domain=domain,
        agent=agent,
        user=user,
        environment=environment,
        task=task,
        max_steps=max_steps,
        max_errors=max_errors,
        seed=seed,
    )
    if gate is None:
        orchestrator = Orchestrator(**settings)
    else:
        orchestrator = CaptureOrchestrator(
            **settings, gate=gate, session_id=session_id, trial=trial
        )
    simulation = orchestrator.run()
    simulation.id = session_id
    simulation.trial = trial
    simulation.reward_info = evaluate_simulation(
        simulation=simulation,
        task=task,
        evaluation_type=EvaluationType.ALL,
        solo_mode=False,
        domain=domain,
    )
    return simulation


def trial_seeds(seed: int, num_trials: int) -> list[int]:
    """Per-trial seeds, derived as `tau2.run.run_tasks` derives them."""
    rng = random.Random(seed)
    return [rng.randint(0, 1000000) for _ in range(num_trials)]


class SpendTracker:
    """This run's agent and user cost against an optional cap; shared across batches."""

    def __init__(self, cap_usd: float | None = None) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self.unpriced = 0  # simulations whose cost τ² could not compute (counted as free)
        self._lock = threading.Lock()

    def reached(self) -> bool:
        with self._lock:
            return self.cap_usd is not None and self.spent_usd >= self.cap_usd

    def add(self, simulation: SimulationRun) -> None:
        with self._lock:
            if simulation.agent_cost is None or simulation.user_cost is None:
                self.unpriced += 1
            self.spent_usd += sim_cost(simulation)


@dataclass
class RunReport:
    """What one `run_batch` call did. `simulations` holds every finished simulation of the
    requested jobs, resumed or new, in (trial, task) order."""

    simulations: list[SimulationRun] = field(default_factory=list)
    resumed: int = 0
    ran: int = 0
    failed: list[dict[str, Any]] = field(default_factory=list)
    not_started: int = 0  # left out by the spend cap
    cost_usd: float = 0.0  # simulations run by this call


@contextmanager
def budget_guard(ledger: Ledger, category: str = "capture") -> Iterator[None]:
    """Route every τ² LLM call (agent and user simulator) through `ledger`: before a call,
    reserve its maximum cost (the request's tokens counted by litellm plus 10%, and its whole
    `max_tokens` allowance, at litellm's prices); after it, settle at litellm's computed cost.
    A call without `max_tokens`, or for a model without a price, is refused: its maximum is
    unbounded."""
    import litellm
    import tau2.utils.llm_utils as llm_utils

    original = llm_utils.completion

    def guarded(*args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model") or (args[0] if args else None)
        max_out = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
        price = litellm.model_cost.get(model or "")
        if not max_out or not price:
            raise BudgetRefused(f"{model}: no output cap or no price, so no maximum cost")
        tokens = litellm.token_counter(
            model=model, messages=kwargs.get("messages"), tools=kwargs.get("tools")
        )
        max_usd = llm_call_max_usd(
            math.ceil(tokens * 1.1) + 64,
            int(max_out),
            price["input_cost_per_token"],
            price["output_cost_per_token"],
        )
        with ledger.call(f"{category}:{model}", category, max_usd) as call:
            response = original(*args, **kwargs)
            try:
                call.cost = float(litellm.completion_cost(completion_response=response))
            except Exception:
                call.cost = None  # settles at the reservation
        return response

    llm_utils.completion = guarded
    try:
        yield
    finally:
        llm_utils.completion = original


def run_batch(
    domain: str,
    tasks: Sequence[Task],
    *,
    num_trials: int,
    seed: int = DEFAULT_SEED,
    max_concurrency: int = 1,
    store: BenchStore | None = None,
    mode: Literal["wrapped", "unwrapped"] = "wrapped",
    spend: SpendTracker | None = None,
    can_start: Callable[[], bool] | None = None,
    **simulation_kwargs: Any,
) -> RunReport:
    """Run every task for every trial.

    With a `store`, the run is resumable (see the module docstring): keys already done are
    loaded instead of run, each simulation is recorded as it starts and finishes, and a
    simulation that raises is recorded as failed and reported instead of stopping the batch.
    The key's agent model is `simulation_kwargs["agent_model"]`, which a store requires.
    Without a store, errors propagate. `spend` stops new simulations once its cap is reached.
    """
    agent_model = simulation_kwargs.get("agent_model")
    user_model = simulation_kwargs.get("user_model")
    gate = simulation_kwargs.get("gate")
    if store is not None and not agent_model:
        raise ValueError("a resumable run needs agent_model to key its simulations")
    if (gate is not None) != (mode == "wrapped"):
        raise ValueError("wrapped runs need a gate and unwrapped runs must not have one")
    jobs = [
        (task, trial, trial_seed)
        for trial, trial_seed in enumerate(trial_seeds(seed, num_trials))
        for task in tasks
    ]
    done = store.done_simulations() if store is not None else {}
    report = RunReport()
    lock = threading.Lock()

    def key(job: tuple[Task, int, int]) -> tuple:
        task, trial, trial_seed = job
        return (mode, domain, task.id, trial, agent_model, trial_seed)

    def run(job: tuple[Task, int, int]) -> SimulationRun | None:
        task, trial, trial_seed = job
        previous = done.get(key(job))
        if previous is not None:
            if previous.user_model != user_model:
                raise ValueError(
                    f"task {task.id} trial {trial} was run with user model "
                    f"{previous.user_model!r}, not {user_model!r}; use another store"
                )
            with lock:
                report.resumed += 1
            return SimulationRun.model_validate_json(previous.simulation or "")
        if (spend is not None and spend.reached()) or (can_start is not None and not can_start()):
            with lock:
                report.not_started += 1
            return None
        session_id = new_ulid()
        if store is not None:
            store.start_simulation(
                session_id=session_id,
                mode=mode,
                domain=domain,
                task_id=task.id,
                trial=trial,
                agent_model=agent_model,
                user_model=user_model,
                seed=trial_seed,
            )
        try:
            sim = run_simulation(
                domain,
                task,
                trial=trial,
                seed=trial_seed,
                session_id=session_id,
                **simulation_kwargs,
            )
        except Exception as exc:
            if store is None:
                raise
            store.fail_simulation(session_id, f"{type(exc).__name__}: {exc}")
            logger.error(f"task {task.id} trial {trial} failed: {type(exc).__name__}: {exc}")
            with lock:
                report.failed.append(
                    {"task_id": task.id, "trial": trial, "error": type(exc).__name__}
                )
            return None
        if store is not None:
            store.finish_simulation(
                session_id,
                reward=sim.reward_info.reward if sim.reward_info else None,
                agent_cost_usd=sim.agent_cost,
                user_cost_usd=sim.user_cost,
                simulation=sim.model_dump_json(),
            )
        if spend is not None:
            spend.add(sim)
        with lock:
            report.ran += 1
            report.cost_usd += sim_cost(sim)
        logger.info(f"task {task.id} trial {trial}: reward {sim.reward_info.reward}")
        return sim

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        report.simulations = [sim for sim in pool.map(run, jobs) if sim is not None]
    return report


def passed(simulation: SimulationRun) -> bool:
    """The simulation's final task outcome is a pass (`hatchway.bench.outcomes`)."""
    return task_passed(simulation.reward_info.reward if simulation.reward_info else None)


def is_write(policy: Policy, action: str) -> bool:
    """Captured by the gate: every tool the policy does not mark `kind: read`."""
    spec = policy.actions.get(action)
    return spec is None or spec.kind is not Kind.READ


def compare_pass_rates(wrapped: Sequence[bool], unwrapped: Sequence[bool]) -> dict[str, Any]:
    """Wrapped against unwrapped pass rate. "Within noise" means the difference is at most two
    pooled standard errors of a difference of two proportions."""
    n_w, n_u = len(wrapped), len(unwrapped)
    if not n_w or not n_u:
        raise ValueError("both arms need at least one simulation")
    p_w, p_u = sum(wrapped) / n_w, sum(unwrapped) / n_u
    pooled = (sum(wrapped) + sum(unwrapped)) / (n_w + n_u)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_w + 1 / n_u))
    return {
        "wrapped": {"n": n_w, "passed": sum(wrapped), "pass_rate": p_w},
        "unwrapped": {"n": n_u, "passed": sum(unwrapped), "pass_rate": p_u},
        "difference": p_w - p_u,
        "noise_bound": 2 * se,
        "within_noise": abs(p_w - p_u) <= 2 * se,
    }


def sim_cost(simulation: SimulationRun) -> float:
    return (simulation.agent_cost or 0.0) + (simulation.user_cost or 0.0)


def _cost(simulations: Sequence[SimulationRun]) -> float:
    return sum(map(sim_cost, simulations))


def _save(path: Path, info: Any, tasks: Sequence[Task], sims: Sequence[SimulationRun]) -> None:
    results = Results(info=info, tasks=list(tasks), simulations=list(sims))
    path.write_text(results.model_dump_json(indent=2))


def _summarize(reports: dict[str, RunReport]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, report in reports.items():
        sims = report.simulations
        out[name] = {
            "simulations": len(sims),
            "resumed": report.resumed,
            "ran": report.ran,
            "failed": report.failed,
            "not_started": report.not_started,
            "passed": sum(map(passed, sims)),
            "pass_rate": sum(map(passed, sims)) / len(sims) if sims else None,
            "cost_usd_this_run": report.cost_usd,
            "cost_usd_all_finished": _cost(sims),
            "rewards": {
                f"{s.task_id}/{s.trial}": s.reward_info.reward if s.reward_info else None
                for s in sims
            },
        }
    return out


def _info(domain: str, agent: str, user: str, llm_args: dict[str, Any], **kwargs: Any) -> Any:
    return get_info(
        domain=domain,
        agent="llm_agent",
        user="user_simulator",
        llm_agent=agent,
        llm_args_agent=llm_args,
        llm_user=user,
        llm_args_user=llm_args,
        max_errors=DEFAULT_MAX_ERRORS,
        **kwargs,
    )


def run_config(
    config: RunConfig,
    store: BenchStore,
    out: Path,
    *,
    policy: Path = DEFAULT_POLICY,
    spend_cap_usd: float | None = None,
    max_concurrency: int | None = None,
    ledger: Ledger | None = None,
    start_margin_usd: float = 0.0,
) -> dict[str, Any]:
    """Capture every (domain, agent model) in `config`, wrapped only, resumably. The spend cap
    (`spend_cap_usd`, else the config's) covers the whole run. Writes one τ² results file per
    domain and agent model under `out` and returns the summary.

    With a `ledger`, the cap is hard (`budget_guard`), and no new simulation starts while less
    than `start_margin_usd` of the capture budget is left, so few simulations are cut short."""
    cap = spend_cap_usd if spend_cap_usd is not None else config.spend_cap_usd
    spend = SpendTracker(cap)
    llm_args: dict[str, Any] = {"temperature": config.temperature}
    if config.max_output_tokens is not None:
        llm_args["max_tokens"] = config.max_output_tokens
    if ledger is not None and config.max_output_tokens is None:
        raise ValueError("a hard budget needs max_output_tokens in the run config")
    can_start = None
    if ledger is not None:

        def can_start() -> bool:
            return ledger.remaining("capture") >= start_margin_usd

    guard = budget_guard(ledger) if ledger is not None else nullcontext()
    with guard:
        reports = _run_config_batches(
            config, store, out, policy, spend, can_start, llm_args, max_concurrency
        )
    summary = {
        "config": config.name,
        "seed": config.seed,
        "hatchway_commit": git_commit(),
        "runs": _summarize(reports),
    }
    summary["spend_cap_usd"] = cap
    summary["spent_usd_this_run"] = spend.spent_usd
    summary["spend_cap_reached"] = spend.reached()
    summary["unpriced_simulations"] = spend.unpriced
    if ledger is not None:
        summary["ledger"] = ledger.summary()
    return summary


def _run_config_batches(
    config: RunConfig,
    store: BenchStore,
    out: Path,
    policy: Path,
    spend: SpendTracker,
    can_start: Callable[[], bool] | None,
    llm_args: dict[str, Any],
    max_concurrency: int | None,
) -> dict[str, RunReport]:
    reports: dict[str, RunReport] = {}
    for domain, domain_tasks in config.domains.items():
        tasks = get_tasks(
            domain, task_split_name=domain_tasks.task_split, task_ids=domain_tasks.task_ids
        )
        for agent_model in config.agent_models:
            gate = Gate(policy, store=store, domain=domain, agent_model=agent_model)
            report = run_batch(
                domain,
                tasks,
                num_trials=config.trials,
                seed=config.seed,
                max_concurrency=max_concurrency or config.max_concurrency,
                store=store,
                mode="wrapped",
                spend=spend,
                can_start=can_start,
                gate=gate,
                agent_model=agent_model,
                agent_llm_args=llm_args,
                user_model=config.user_model,
                user_llm_args=llm_args,
                max_steps=config.max_steps,
            )
            reports[f"{domain}/{agent_model}"] = report
            info = _info(
                domain,
                agent_model,
                config.user_model,
                llm_args,
                num_trials=config.trials,
                max_steps=config.max_steps,
                seed=config.seed,
            )
            path = out / domain / f"{agent_model}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            _save(path, info, tasks, report.simulations)
    return reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, help="run config (domains, models, tasks)")
    parser.add_argument("--domain", default="retail")
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument("--task-split", default="base")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--agent-llm", default=models.GPT_4_1_MINI)
    parser.add_argument("--user-llm", default=models.USER_SIMULATOR_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--max-concurrency", type=int, default=None, help="default 4")
    parser.add_argument("--mode", choices=["both", "wrapped", "unwrapped"], default="both")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--spend-cap", type=float, default=None, help="USD for this run")
    parser.add_argument("--store", type=Path, required=True, help="benchmark SQLite file")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    if (args.config is None) == (args.task_ids is None):
        parser.error("give either --config or --task-ids")

    logger.remove()
    logger.add(sys.stderr, level=args.log_level)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.config is not None:
        with BenchStore(args.store) as store:
            summary = run_config(
                load_run_config(args.config),
                store,
                args.out,
                policy=args.policy,
                spend_cap_usd=args.spend_cap,
                max_concurrency=args.max_concurrency,
            )
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return 0

    tasks = get_tasks(args.domain, task_split_name=args.task_split, task_ids=args.task_ids)
    llm_args = {"temperature": args.temperature}
    spend = SpendTracker(args.spend_cap)
    common = dict(
        num_trials=args.trials,
        seed=args.seed,
        max_concurrency=args.max_concurrency or 4,
        spend=spend,
        agent_model=args.agent_llm,
        agent_llm_args=llm_args,
        user_model=args.user_llm,
        user_llm_args=llm_args,
        max_steps=args.max_steps,
    )
    info = _info(
        args.domain,
        args.agent_llm,
        args.user_llm,
        llm_args,
        num_trials=args.trials,
        max_steps=args.max_steps,
        seed=args.seed,
    )

    reports: dict[str, RunReport] = {}
    with BenchStore(args.store) as store:
        for mode in ("unwrapped", "wrapped"):
            if args.mode not in ("both", mode):
                continue
            gate = None
            if mode == "wrapped":
                gate = Gate(
                    args.policy, store=store, domain=args.domain, agent_model=args.agent_llm
                )
            reports[mode] = run_batch(
                args.domain, tasks, store=store, mode=mode, gate=gate, **common
            )
            _save(args.out / f"{mode}.json", info, tasks, reports[mode].simulations)
        session_ids = (
            {s.id for s in reports["wrapped"].simulations} if "wrapped" in reports else set()
        )
        captured = sum(1 for w in store.writes() if w.session_id in session_ids)

    summary: dict[str, Any] = _summarize(reports)
    summary["captured_writes"] = captured
    summary["spent_usd_this_run"] = spend.spent_usd
    summary["spend_cap_reached"] = spend.reached()
    summary["unpriced_simulations"] = spend.unpriced
    if len(reports) == 2 and all(r.simulations for r in reports.values()):
        summary["comparison"] = compare_pass_rates(
            [passed(s) for s in reports["wrapped"].simulations],
            [passed(s) for s in reports["unwrapped"].simulations],
        )
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
