"""Synthetic benchmark stores with a known multi-question signal, for replay tests and demos.

A write may execute (policy verdict ALLOW) when it both follows the policy and matches the
customer's request; one that breaks the policy is DENY, one that only misses the request is ASK,
and a few are UNKNOWN. The verdicts are recorded under the oracle version `synthetic`. Each judge
sees both facts through different questions:

- `policy_ok` spreads widely but is noisy;
- `matches_request` sits in a narrow band near 0.85 but separates the classes cleanly;
- `risk` puts more mass on `high` for intervention-required writes.

The fixed scalar of arms B-D (the mean of the yes_no answers) is dominated by the noisy, wide
`policy_ok` and ignores `risk`, so a model that weights the questions does better: arm E should
beat the best scalar arm. `jev` is the strongest judge, `openai_decisions` a noisier copy and
`llm_baseline` the weakest.

    python -m hatchway.bench.synthetic runs/synthetic.db --tasks 120 --seed 0 --two-domains
"""

from __future__ import annotations

import argparse
import math
import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hatchway.bench.store import BenchStore, PolicyDecision, ScoreRecord, VerdictRecord
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.judges.base import ChoiceAnswer, QuestionVector, YesNoAnswer
from hatchway.policy import Kind, load_policy

SYNTHETIC_ORACLE_VERSION = "synthetic"
JUDGES = {"jev": "jev-1.14.0", "openai_decisions": "gpt-6-luna", "llm_baseline": "gpt-4.1-mini"}
# Per judge: (policy_ok noise sd, matches_request separation, risk separation).
_JUDGE_NOISE = {"jev": (1.6, 0.08, 0.30), "openai_decisions": (2.0, 0.05, 0.20)}
_JUDGE_NOISE["llm_baseline"] = (2.4, 0.03, 0.10)
ACTIONS = (
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "return_delivered_order_items",
)
TELECOM_ACTIONS = ("suspend_line", "resume_line", "enable_roaming", "refuel_data")
TWO_DOMAINS = {"retail": ACTIONS, "telecom": TELECOM_ACTIONS}


@dataclass(frozen=True)
class Case:
    action: str
    verdict: PolicyDecision
    vectors: dict[str, QuestionVector]


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def judge_vector(
    rng: random.Random, judge: str, policy_true: bool, request_true: bool, shifted: bool = False
) -> QuestionVector:
    """`shifted` reverses what `matches_request` and `risk` say about correctness: a domain
    whose question-to-correctness signal differs from the default one."""
    noise, sep, risk_sep = _JUDGE_NOISE[judge]
    if shifted:
        sep, risk_sep = -sep, -risk_sep
    p_policy = _sigmoid(rng.gauss(1.5 if policy_true else -0.5, noise))
    p_match = 0.85 + (sep if request_true else -sep) + rng.gauss(0, 0.02)
    p_match = min(max(p_match, 0.0), 1.0)
    bad = not (policy_true and request_true)
    high = rng.gauss(0.25 - min(risk_sep, 0.0) + (risk_sep if bad else 0.0), 0.1)
    high = min(max(high, 0.0), 0.9)
    low = (1.0 - high) * 0.6
    return QuestionVector(
        judge=judge,
        model_id=JUDGES[judge],
        answers={
            "policy_ok": YesNoAnswer(p_yes=p_policy),
            "matches_request": YesNoAnswer(p_yes=p_match),
            "risk": ChoiceAnswer(probs={"low": low, "medium": 1.0 - high - low, "high": high}),
        },
    )


def make_case(
    rng: random.Random,
    *,
    actions: Sequence[str] = ACTIONS,
    judges: Sequence[str] = tuple(JUDGES),
    p_policy_bad: float = 0.15,
    p_request_bad: float = 0.12,
    p_ambiguous: float = 0.0,
    shifted: bool = False,
) -> Case:
    action = rng.choice(list(actions))
    policy_true = rng.random() >= p_policy_bad
    request_true = rng.random() >= p_request_bad
    verdict: PolicyDecision = "ALLOW"
    if not policy_true:
        verdict = "DENY"
    elif not request_true:
        verdict = "ASK"
    if rng.random() < p_ambiguous:
        verdict = "UNKNOWN"
    vectors = {j: judge_vector(rng, j, policy_true, request_true, shifted) for j in judges}
    return Case(action, verdict, vectors)


def build_store(
    path: str | Path,
    *,
    tasks: int = 60,
    sessions_per_task: int = 3,
    writes_per_session: int = 3,
    seed: int = 0,
    judges: Sequence[str] = tuple(JUDGES),
    duplicate_rate: float = 0.2,
    error_rate: float = 0.02,
    slow_rate: float = 0.02,
    p_ambiguous: float = 0.03,
    domains: Mapping[str, Sequence[str]] | None = None,
    shifted_domains: Collection[str] = (),
) -> Path:
    """Write a scored synthetic store with policy verdicts. A duplicate session replays an
    earlier session of the same task, so its writes share score rows.

    `domains` maps each domain to its actions (default: retail only); tasks alternate between
    domains. Domains in `shifted_domains` use the reversed signal (see `judge_vector`)."""
    domains = dict(domains or {"retail": ACTIONS})
    names = list(domains)
    rng = random.Random(seed)
    policy = load_policy(DEFAULT_POLICY)
    path = Path(path)
    with BenchStore(path) as store:
        for t in range(tasks):
            domain = names[t % len(names)]
            task_id = f"syn-{t:04d}"
            context = {"task": task_id}
            sessions: list[list[tuple[str, dict[str, object], Case]]] = []
            for s in range(sessions_per_task):
                if sessions and rng.random() < duplicate_rate:
                    script = rng.choice(sessions)
                else:
                    script = []
                    for i in range(writes_per_session):
                        case = make_case(
                            rng,
                            actions=domains[domain],
                            judges=judges,
                            p_ambiguous=p_ambiguous,
                            shifted=domain in shifted_domains,
                        )
                        script.append((case.action, {"task": task_id, "i": s * 100 + i}, case))
                sessions.append(script)
                session_id = f"{task_id}-s{s}"
                for action, args, case in script:
                    rubric = policy.actions[action].rubric_hash
                    write = store.record_write(
                        session_id=session_id,
                        action=action,
                        args=args,
                        context=context,
                        rubric_hash=rubric,
                        domain=domain,
                        agent_model="synthetic-agent",
                        task_id=task_id,
                        trial=s,
                    )
                    store.record_verdict(
                        write.write_id,
                        VerdictRecord(
                            oracle_version=SYNTHETIC_ORACLE_VERSION,
                            expected_decision=case.verdict,
                            should_execute_now=None
                            if case.verdict == "UNKNOWN"
                            else case.verdict == "ALLOW",
                        ),
                    )
                    for judge, vector in case.vectors.items():
                        if store.get_score(write.state_hash, rubric, judge, JUDGES[judge]):
                            continue
                        slow = rng.random() < slow_rate
                        latency = 4000.0 if slow else 400.0 + 400.0 * rng.random()
                        if rng.random() < error_rate:
                            record = ScoreRecord(
                                state_hash=write.state_hash,
                                rubric_hash=rubric,
                                judge_name=judge,
                                model_id=JUDGES[judge],
                                status="error",
                                attempts=3,
                                first_attempt_latency_ms=latency,
                                error="synthetic error",
                            )
                        else:
                            record = ScoreRecord(
                                state_hash=write.state_hash,
                                rubric_hash=rubric,
                                judge_name=judge,
                                model_id=JUDGES[judge],
                                status="ok",
                                question_vector=vector,
                                first_attempt_latency_ms=latency,
                                cost_usd=0.001,
                            )
                        store.put_score(record)
    assert all(policy.actions[a].kind is Kind.WRITE for acts in domains.values() for a in acts)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("store", type=Path)
    parser.add_argument("--tasks", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--two-domains", action="store_true", help="retail and telecom tasks")
    args = parser.parse_args(argv)
    domains = TWO_DOMAINS if args.two_domains else None
    build_store(args.store, tasks=args.tasks, seed=args.seed, domains=domains)
    print(args.store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
