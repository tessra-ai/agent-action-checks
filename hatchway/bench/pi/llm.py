"""Phase B arms as a dry run: every prompt is built and measured, and no model is called.

Phase B runs only after explicit approval and a budget. This module has no client and makes no
network call; it builds the exact prompts the preregistered design needs and counts them, so the
budget can be set from real sizes:

- **L-pol:** one call per test case. The starting policy's text and the case; the answer is
  ALLOW or ESCALATE.
- **L-prec:** one call per test case and training sample. L-pol plus this organization's
  `PRECEDENTS` most similar training decisions (same action, then most equal facts, then the
  closest amount).
- **L-ind:** one call per training sample. The starting policy, the training cases where the
  organization's decision differed from it, and a sample where it agreed. The answer is up to
  five rules in the DSL (fact literals or phrase literals), which S's significance gate then
  accepts or rejects for free.

Token counts use a 4-characters-per-token estimate.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

import numpy as np

from hatchway.bench.pi import evaluate as E
from hatchway.bench.pi import induce as S
from hatchway.bench.pi.cases import SEED, Case, load_policy
from hatchway.bench.pi.worlds import WORLDS, World, reduced_policy

PHASE_B_K = (0, 5, 10, 20)
PHASE_B_REPLICATES = 3
TEST_PER_WORLD = 200
PRECEDENTS = 8
AGREEING_SAMPLE = 40
MAX_OUTPUT_TOKENS = {"L-pol": 5, "L-prec": 5, "L-ind": 600}

_SYSTEM = (
    "You are the approval gate of a retail company. Decide whether the proposed action may run "
    "now (ALLOW) or must go to a human (ESCALATE), following the company's policy and, where "
    "given, how the company decided similar cases before. Answer with one word: ALLOW or "
    "ESCALATE."
)
_INDUCE = (
    "You are reviewing how a retail company actually decides proposed agent actions, against "
    "its written policy. Below are cases where the company's decision differed from the policy, "
    "and cases where it agreed. Propose at most five rules that explain the differences. Each "
    'rule is JSON: {"effect": "escalate" or "allow", "when": [literal, ...]}, where a '
    'literal is {"fact": name, "op": "is"|"eq"|"has"|"gt"|"le", "value": v} '
    'over the facts listed, or {"phrase": text} for words in the customer\'s messages. Return '
    "a JSON list only."
)


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _facts_line(c: Case) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(c.facts.items()))


def decision_prompt(policy: str, case: Case, precedents: Sequence[tuple[Case, bool]] = ()) -> str:
    parts = [_SYSTEM, "## Policy", policy]
    if precedents:
        parts.append("## How the company decided similar cases")
        for c, escalate in precedents:
            parts.append(f"{c.text}\nDECISION: {'ESCALATE' if escalate else 'ALLOW'}")
    parts += ["## Case to decide", case.text]
    return "\n\n".join(parts)


def induce_prompt(
    policy: str, differing: Sequence[tuple[Case, bool]], agreeing: Sequence[tuple[Case, bool]]
) -> str:
    facts = ", ".join((*S.BOOL_FACTS, *S.CAT_FACTS, *S.NUM_FACTS, "products"))
    parts = [_INDUCE, "## Policy", policy, f"## Facts available\n{facts}"]
    for title, rows in (("Differed from the policy", differing), ("Agreed", agreeing)):
        parts.append(f"## {title}")
        for c, escalate in rows:
            parts.append(
                f"{c.text}\nFACTS: {_facts_line(c)}\n"
                f"COMPANY DECISION: {'ESCALATE' if escalate else 'ALLOW'}"
            )
    return "\n\n".join(parts)


def similar(case: Case, pool: Sequence[Case], n: int = PRECEDENTS) -> list[Case]:
    def key(c: Case) -> tuple[int, int, float, str]:
        same = sum(
            c.facts[f] == case.facts[f] for f in (*S.BOOL_FACTS, "payment_source", "user_state")
        )
        shared = len(set(c.facts["products"]) & set(case.facts["products"]))
        return (
            int(c.action != case.action),
            -(same + shared),
            abs(float(c.facts["amount"]) - float(case.facts["amount"])),
            c.case_id,
        )

    return sorted(pool, key=key)[:n]


def test_subsample(p: E.Prepared, test_idx: np.ndarray, world: World) -> list[int]:
    rng = random.Random(f"{SEED}:phase-b-test:{world.name}")
    trig = [int(i) for i in test_idx if p.trigger[i]]
    rest = [int(i) for i in test_idx if not p.trigger[i]]
    half = TEST_PER_WORLD // 2
    return sorted(rng.sample(trig, min(half, len(trig))) + rng.sample(rest, min(half, len(rest))))


def dry_run(cases: Sequence[Case], worlds: Sequence[World] = WORLDS) -> dict[str, Any]:
    policy_text = load_policy()
    totals = {
        arm: {"calls": 0, "input_tokens": 0, "max_output_tokens": 0} for arm in MAX_OUTPUT_TOKENS
    }
    per_world: dict[str, Any] = {}

    def add(arm: str, prompt: str) -> None:
        totals[arm]["calls"] += 1
        totals[arm]["input_tokens"] += tokens(prompt)
        totals[arm]["max_output_tokens"] += MAX_OUTPUT_TOKENS[arm]

    for world in worlds:
        policy = reduced_policy(policy_text, world) if world.kind == "ablation" else policy_text
        p = E.Prepared(world, cases)
        train = np.array([E.is_train(f) for f in p.family], dtype=bool)
        test_idx = np.flatnonzero(~train)
        sub = test_subsample(p, test_idx, world)
        for i in sub:
            add("L-pol", decision_prompt(policy, p.cases[i]))
        samples = 0
        for k in PHASE_B_K:
            for rep in range(PHASE_B_REPLICATES):
                rng = random.Random(f"{SEED}:{world.name}:clean:{k}:{rep}")
                sample = E.training_sample(p, train, k, rng)
                if sample is None:
                    continue
                samples += 1
                pool = [p.cases[i] for i in sample]
                label = {p.cases[i].case_id: bool(p.truth[i]) for i in sample}
                if k > 0:
                    for i in sub:
                        prec = [(c, label[c.case_id]) for c in similar(p.cases[i], pool)]
                        add("L-prec", decision_prompt(policy, p.cases[i], prec))
                differing = [(p.cases[i], bool(p.truth[i])) for i in sample if p.trigger[i]]
                agreeing = [(p.cases[i], bool(p.truth[i])) for i in sample if not p.trigger[i]]
                agreeing = rng.sample(agreeing, min(AGREEING_SAMPLE, len(agreeing)))
                add("L-ind", induce_prompt(policy, differing, agreeing))
        per_world[world.name] = {"test_cases": len(sub), "training_samples": samples}
    return {
        "model_calls_made": 0,
        "design": {
            "k": list(PHASE_B_K),
            "replicates": PHASE_B_REPLICATES,
            "test_per_world": TEST_PER_WORLD,
            "precedents": PRECEDENTS,
            "agreeing_sample": AGREEING_SAMPLE,
            "token_estimate": "4 characters per token",
        },
        "totals": totals,
        "per_world": per_world,
        "example_prompts": {
            "L-pol": decision_prompt(policy_text, cases[0])[:3000],
            "L-ind_head": induce_prompt(policy_text, [], [])[:1500],
        },
    }
