"""Live gated τ²-bench pass (M7): the agent's writes go through the gated check.

This is a separate mode next to the shadow capture harness (`harness.py`), which it reuses but
does not change. Reads pass through. Each write is captured as in shadow mode, scored live by
the frozen arm's judges, and decided by the arm; an `ASK` goes to the simulated approver. An
allowed or approved write runs. A rejected one never reaches the environment: the agent gets
`hatchway.bench.DENIAL_RESULT` as the tool result. See `hatchway.bench.gated`.

τ² scores a simulation by replaying its tool calls in a fresh environment and checking that each
gives the recorded result. A denied call never ran, so it is scored on the trajectory without
its denied calls and their denial results (`executed_trajectory`); the saved simulation keeps
the full trajectory, denials included, as the agent saw it.

Gated run (makes LLM and judge API calls; needs the agent and user model keys plus the judges'
`OPENAI_API_KEY` / `TYPESAFE_API_KEY`):

    python -m hatchway.bench.tau2.gated --arm runs/m6/frozen_E.json --approver noisy \\
        --domain retail --task-ids 0 1 2 --trials 2 --agent-llm gpt-4.1-mini-2025-04-14 \\
        --spend-cap 20 --store runs/m7.db --out runs/m7/retail-noisy

The agent and user models default to the pinned snapshots in `hatchway.bench.models`; the
judges and their model ids come from the frozen arm. The spend cap covers judge, agent and user
cost together. Once it is reached no new simulation
starts; simulations already running finish, so it can be exceeded by what they spend.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
from tau2.data_model.message import AssistantMessage, Message, ToolCall, ToolMessage
from tau2.data_model.simulation import SimulationRun
from tau2.data_model.tasks import Task
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.registry import registry
from tau2.run import get_info, get_tasks
from tau2.user.base import BaseUser
from tau2.user.user_simulator import UserSimulator

from hatchway.bench import DENIAL_RESULT, models
from hatchway.bench.frozen import FrozenArm
from hatchway.bench.gated import (
    GatedGate,
    SimulatedApprover,
    kill_test,
    load_arm_metrics,
    summarize_gated,
)
from hatchway.bench.score import make_judge
from hatchway.bench.store import BenchStore, OutcomeRecord
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.bench.tau2.harness import (
    AgentFactory,
    UserFactory,
    _cost,
    _save,
    is_write,
    passed,
    render_transcript,
    trial_seeds,
)
from hatchway.bench.tau2.label import GroundTruth
from hatchway.bench.tau2.snapshot import executed_outcome, live_proposal
from hatchway.ulid import new_ulid


class GatedOrchestrator(Orchestrator):
    """A τ² orchestrator whose environment runs the agent's tool calls only when the gated
    check lets them through."""

    def __init__(
        self, *args: Any, gate: GatedGate, session_id: str, trial: int | None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.gate = gate
        self.session_id = session_id
        self.trial = trial
        self.truth = GroundTruth.from_task(self.task)
        self.denied_call_ids: set[str] = set()
        self._gating = False
        self._get_response = self.environment.get_response
        self.environment.get_response = self._gated_response

    def initialize(self) -> None:
        super().initialize()  # replays the task's initial state, which is not gated
        self._gating = True

    def _gated_response(self, tool_call: ToolCall) -> ToolMessage:
        if not (self._gating and tool_call.requestor == "assistant"):
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
        # The write, its snapshot and its policy verdict are committed before the gate decides.
        decision = self.gate.check(
            tool_call.name,
            tool_call.arguments,
            context,
            session_id=self.session_id,
            pre_execution=None if proposal is None else proposal.pre_execution,
            truth=self.truth,
            task_id=self.task.id,
            trial=self.trial,
        )
        if decision is None:
            return self._get_response(tool_call)
        if not decision.executed:
            self.denied_call_ids.add(tool_call.id)
            if proposal is not None:
                self.gate.store.record_outcome(
                    decision.write_id, OutcomeRecord(outcome="NOT_EXECUTED", state_changed=False)
                )
            return ToolMessage(
                id=tool_call.id,
                role="tool",
                content=DENIAL_RESULT,
                requestor=tool_call.requestor,
                error=False,
            )
        if proposal is None:
            return self._get_response(tool_call)
        try:
            result = self._get_response(tool_call)
        except Exception as exc:
            self.gate.store.record_outcome(
                decision.write_id,
                OutcomeRecord(
                    outcome="TECHNICAL_ERROR", backend_error=f"{type(exc).__name__}: {exc}"
                ),
            )
            raise
        self.gate.store.record_outcome(
            decision.write_id, executed_outcome(proposal, result, self.environment)
        )
        return result


def executed_trajectory(messages: Sequence[Message], denied_call_ids: set[str]) -> list[Message]:
    """The trajectory without the denied tool calls and their denial results. An assistant
    message left with neither text nor tool calls is dropped."""
    out: list[Message] = []
    for message in messages:
        if isinstance(message, ToolMessage) and message.id in denied_call_ids:
            continue
        if isinstance(message, AssistantMessage) and message.tool_calls:
            calls = [c for c in message.tool_calls if c.id not in denied_call_ids]
            if len(calls) != len(message.tool_calls):
                if not calls and not message.content:
                    continue
                message = message.model_copy(update={"tool_calls": calls or None})
        out.append(message)
    return out


def run_gated_simulation(
    domain: str,
    task: Task,
    *,
    trial: int,
    seed: int | None,
    gate: GatedGate,
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
    """`harness.run_simulation` with the gated check in place of shadow capture.
    `session_id` defaults to a new ULID."""
    if gate.domain != domain:
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
    orchestrator = GatedOrchestrator(
        domain=domain,
        agent=agent,
        user=user,
        environment=environment,
        task=task,
        max_steps=max_steps,
        max_errors=max_errors,
        seed=seed,
        gate=gate,
        session_id=session_id,
        trial=trial,
    )
    simulation = orchestrator.run()
    simulation.id = session_id
    simulation.trial = trial
    executed = executed_trajectory(simulation.messages, orchestrator.denied_call_ids)
    simulation.reward_info = evaluate_simulation(
        simulation=simulation.model_copy(update={"messages": executed}),
        task=task,
        evaluation_type=EvaluationType.ALL,
        solo_mode=False,
        domain=domain,
    )
    return simulation


@dataclass
class GatedRunReport:
    simulations: list[SimulationRun] = field(default_factory=list)
    not_run: list[dict[str, Any]] = field(default_factory=list)  # left unstarted by the cap
    failed: list[dict[str, Any]] = field(default_factory=list)  # raised; recorded as failed


def run_gated_batch(
    domain: str,
    tasks: Sequence[Task],
    *,
    gate: GatedGate,
    num_trials: int,
    seed: int = DEFAULT_SEED,
    max_concurrency: int = 1,
    spend_cap_usd: float | None = None,
    **simulation_kwargs: Any,
) -> GatedRunReport:
    """Run every task for every trial, in (trial, task) order, until the spend cap is reached.

    Each simulation is recorded in the gate's store as it starts and finishes (mode `gated`),
    so the writes of one that never finishes are abandoned and left out of offline scoring
    (`BenchStore.abandoned_session_ids`). A simulation that raises is recorded as failed and
    reported; the batch goes on. Gated runs are not resumed: every run starts every job.
    """
    store = gate.store
    agent_model = simulation_kwargs.get("agent_model") or gate.agent_model
    if not agent_model:
        raise ValueError("a gated run needs an agent model to record its simulations")
    jobs = [
        (task, trial, trial_seed)
        for trial, trial_seed in enumerate(trial_seeds(seed, num_trials))
        for task in tasks
    ]
    report = GatedRunReport()
    lock = threading.Lock()
    sim_cost = 0.0

    def spent() -> float:
        return gate.judge_cost_usd + sim_cost

    def run(job: tuple[Task, int, int]) -> SimulationRun | None:
        nonlocal sim_cost
        task, trial, trial_seed = job
        with lock:
            if spend_cap_usd is not None and spent() >= spend_cap_usd:
                report.not_run.append({"task_id": task.id, "trial": trial})
                return None
        session_id = new_ulid()
        store.start_simulation(
            session_id=session_id,
            mode="gated",
            domain=domain,
            task_id=task.id,
            trial=trial,
            agent_model=agent_model,
            user_model=simulation_kwargs.get("user_model"),
            seed=trial_seed,
        )
        try:
            sim = run_gated_simulation(
                domain,
                task,
                trial=trial,
                seed=trial_seed,
                gate=gate,
                session_id=session_id,
                **simulation_kwargs,
            )
        except Exception as exc:
            store.fail_simulation(session_id, f"{type(exc).__name__}: {exc}")
            logger.error(f"task {task.id} trial {trial} failed: {type(exc).__name__}: {exc}")
            with lock:
                report.failed.append(
                    {"task_id": task.id, "trial": trial, "error": type(exc).__name__}
                )
            return None
        store.finish_simulation(
            session_id,
            reward=sim.reward_info.reward if sim.reward_info else None,
            agent_cost_usd=sim.agent_cost,
            user_cost_usd=sim.user_cost,
            simulation=sim.model_dump_json(),
        )
        with lock:
            sim_cost += _cost([sim])
        logger.info(f"task {task.id} trial {trial}: reward {sim.reward_info.reward}")
        return sim

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        report.simulations = [s for s in pool.map(run, jobs) if s is not None]
    order = {(task.id, trial): i for i, (task, trial, _) in enumerate(jobs)}
    report.not_run.sort(key=lambda j: order[(j["task_id"], j["trial"])])
    return report


def gated_summary(
    store: BenchStore, simulations: Sequence[SimulationRun], gate: GatedGate
) -> dict[str, Any]:
    """Final task outcomes (per simulation) and cost, plus `summarize_gated` (per write,
    against policy verdicts) for the given simulations."""
    n = len(simulations)
    approver = gate.approver
    return {
        "arm": gate.arm.arm,
        "judges": [list(key) for key in gate.arm.judges],
        "approver": {
            "mode": approver.mode,
            "seed": approver.seed,
            "flip_rate": approver.flip_rate if approver.mode == "noisy" else 0.0,
        },
        "judge_timeout_s": gate.retry.timeout_s,
        "simulations": n,
        "final_task_outcome": {
            "unit": "simulation",
            "passed": sum(map(passed, simulations)),
            "pass_rate": sum(map(passed, simulations)) / n if n else None,
        },
        "rewards": {f"{s.task_id}/{s.trial}": s.reward_info.reward for s in simulations},
        "agent_user_cost_usd": _cost(simulations),
        **summarize_gated(store, {s.id for s in simulations}),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arm", type=Path, required=True, help="frozen_<arm>.json from M6")
    parser.add_argument("--approver", choices=["perfect", "noisy"], required=True)
    parser.add_argument("--approver-seed", type=int, default=0)
    parser.add_argument("--flip-rate", type=float, default=0.05)
    parser.add_argument("--domain", default="retail")
    parser.add_argument("--task-ids", nargs="+", required=True)
    parser.add_argument("--task-split", default="base")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--agent-llm", default=models.GPT_4_1_MINI)
    parser.add_argument("--user-llm", default=models.USER_SIMULATOR_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--judge-timeout", type=float, default=3.0, help="seconds, one attempt")
    parser.add_argument(
        "--spend-cap", type=float, required=True, help="USD: judges, agent and user together"
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--store", type=Path, required=True, help="benchmark SQLite file")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--kill-test-metrics", type=Path, help="M6 metrics JSON")
    parser.add_argument(
        "--kill-test-set",
        choices=["common_support", "end_to_end"],
        default="common_support",
        help="M6 evaluation set the kill test compares on",
    )
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    from hatchway.judges.runner import RetryPolicy

    logger.remove()
    logger.add(sys.stderr, level=args.log_level)
    args.out.mkdir(parents=True, exist_ok=True)
    arm = FrozenArm.load(args.arm)
    tasks = get_tasks(args.domain, task_split_name=args.task_split, task_ids=args.task_ids)
    llm_args = {"temperature": args.temperature}
    approver = SimulatedApprover(args.approver, seed=args.approver_seed, flip_rate=args.flip_rate)
    with BenchStore(args.store) as store:
        judges = [make_judge(f"{name}:{model_id}", store) for name, model_id in arm.judges]
        with GatedGate(
            args.policy,
            store=store,
            arm=arm,
            judges=judges,
            approver=approver,
            domain=args.domain,
            agent_model=args.agent_llm,
            retry=RetryPolicy(max_attempts=1, timeout_s=args.judge_timeout),
        ) as gate:
            report = run_gated_batch(
                args.domain,
                tasks,
                gate=gate,
                num_trials=args.trials,
                seed=args.seed,
                max_concurrency=args.max_concurrency,
                spend_cap_usd=args.spend_cap,
                agent_model=args.agent_llm,
                agent_llm_args=llm_args,
                user_model=args.user_llm,
                user_llm_args=llm_args,
                max_steps=args.max_steps,
            )
            summary = gated_summary(store, report.simulations, gate)
    info = get_info(
        domain=args.domain,
        agent="llm_agent",
        user="user_simulator",
        llm_agent=args.agent_llm,
        llm_args_agent=llm_args,
        llm_user=args.user_llm,
        llm_args_user=llm_args,
        num_trials=args.trials,
        max_steps=args.max_steps,
        max_errors=DEFAULT_MAX_ERRORS,
        seed=args.seed,
    )
    _save(args.out / "gated.json", info, tasks, report.simulations)
    summary["spend_cap_usd"] = args.spend_cap
    summary["total_cost_usd"] = summary["judge_cost_usd"] + summary["agent_user_cost_usd"]
    summary["spend_cap_reached"] = bool(report.not_run)
    summary["not_run"] = report.not_run
    summary["failed"] = report.failed
    if args.kill_test_metrics:
        metrics = json.loads(args.kill_test_metrics.read_text())
        summary["kill_test"] = kill_test(load_arm_metrics(metrics, args.kill_test_set), arm.arm)
        summary["kill_test"]["claims"] = metrics.get("claims")
        if (metrics.get("claims") or {}).get("blocked"):
            summary["kill_test"]["note"] = (
                "claims blocked: the replay's test set cannot support a kill-or-continue call"
            )
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
