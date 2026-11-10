"""Build policy-oracle evidence from a τ² environment and trajectory.

Used live by the harnesses, just before a proposed write reaches the environment, and offline by
`scripts/extract_verdict_fixtures.py`, which rebuilds the same state with τ²'s
`Environment.set_state`. Works on τ² objects by duck typing (`model_dump`, `tools.db`), so this
module does not import `tau2`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hatchway.bench.store import (
    CapturedWrite,
    OutcomeRecord,
    PreActionSnapshot,
    PreExecution,
    VerdictRecord,
)
from hatchway.bench.tau2.verdicts.base import PolicyVerdict, ProposalEvidence, ToolCallRef, Turn
from hatchway.bench.tau2.verdicts.registry import evaluate
from hatchway.state import canonical_json


def policy_hash(policy_text: str) -> str:
    """sha256 of the domain policy text the agent was given."""
    return hashlib.sha256(policy_text.encode()).hexdigest()


def db_hash(db: Mapping[str, Any] | None) -> str | None:
    return None if db is None else hashlib.sha256(canonical_json(db).encode()).hexdigest()


def db_snapshot(environment: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The agent database and, where the domain has one, the user's (device and surroundings),
    as JSON-ready dicts. Deep copies: later tool calls cannot change them."""
    agent_db = environment.tools.db.model_dump(mode="json")
    user_tools = getattr(environment, "user_tools", None)
    user_db = user_tools.db.model_dump(mode="json") if user_tools is not None else None
    return agent_db, user_db


def _as_dict(message: Any) -> Mapping[str, Any]:
    return message if isinstance(message, Mapping) else message.model_dump(mode="json")


def turns_from_messages(messages: Sequence[Any]) -> tuple[Turn, ...]:
    """τ² messages (objects or their JSON dumps) as oracle `Turn`s, indexed by position."""
    turns = []
    for index, message in enumerate(messages):
        m = _as_dict(message)
        role = m.get("role")
        if role not in ("assistant", "user", "tool"):
            continue
        calls = tuple(
            ToolCallRef(str(c.get("id")), str(c.get("name")), dict(c.get("arguments") or {}))
            for c in m.get("tool_calls") or []
        )
        turns.append(
            Turn(
                index=index,
                role=role,
                content=m.get("content") or "",
                tool_calls=calls,
                tool_call_id=str(m["id"]) if role == "tool" and m.get("id") else None,
                requestor=m.get("requestor") if role == "tool" else None,
                error=bool(m.get("error")) if role == "tool" else False,
            )
        )
    return tuple(turns)


def build_evidence(
    *,
    domain: str,
    task_id: str | None,
    session_id: str,
    seq: int,
    action: str,
    args: Mapping[str, Any],
    agent_db: Mapping[str, Any],
    user_db: Mapping[str, Any] | None,
    prior_messages: Sequence[Any],
    proposing_text: str,
    policy_text: str,
    prior_writes: Sequence[tuple[str, Mapping[str, Any]]],
) -> ProposalEvidence:
    """Evidence for one proposed call. `prior_messages` are the messages before the one that
    carries the call."""
    return ProposalEvidence(
        domain=domain,
        task_id=task_id,
        session_id=session_id,
        seq=seq,
        action=action,
        args=dict(args),
        agent_db=agent_db,
        user_db=user_db,
        turns=turns_from_messages(prior_messages),
        domain_policy_hash=policy_hash(policy_text),
        proposing_text=proposing_text,
        prior_writes=tuple((a, dict(w)) for a, w in prior_writes),
    )


def verdict_record(verdict: PolicyVerdict) -> VerdictRecord:
    return VerdictRecord(
        oracle_version=verdict.oracle_version,
        expected_decision=verdict.expected_decision,
        should_execute_now=verdict.should_execute_now,
        reason_codes=verdict.reason_codes,
        explanation=verdict.explanation,
        evidence=dict(verdict.evidence),
    )


def split_trajectory(trajectory: Sequence[Any], tool_call: Any) -> tuple[list[Any], str]:
    """The messages before the one carrying `tool_call`, and that message's text. A call not
    found in the trajectory (it is always there in τ²'s orchestrator) is treated as proposed
    after every message, with no text."""
    for i, message in enumerate(trajectory):
        if any(call is tool_call for call in getattr(message, "tool_calls", None) or ()):
            return list(trajectory[:i]), getattr(message, "content", None) or ""
    return list(trajectory), ""


@dataclass(frozen=True)
class LiveProposal:
    """What the harness captures about one proposed call before it reaches the environment:
    the hook that commits the snapshot and verdict with the write, and the database hashes to
    compare with after the call."""

    pre_execution: PreExecution
    agent_db_hash: str | None
    user_db_hash: str | None


def live_proposal(
    environment: Any, trajectory: Sequence[Any], tool_call: Any, *, domain: str, task_id: str
) -> LiveProposal:
    """Snapshot the environment now, before the call runs, and build the hook that evaluates
    the proposal once the store has fixed its `seq` and earlier writes."""
    agent_db, user_db = db_snapshot(environment)
    prior, proposing_text = split_trajectory(trajectory, tool_call)
    prior_dump = [dict(_as_dict(m)) for m in prior]
    policy_text = environment.get_policy()

    def pre_execution(
        write: CapturedWrite, prior_writes: list[tuple[str, dict[str, Any]]]
    ) -> tuple[PreActionSnapshot, VerdictRecord]:
        evidence = build_evidence(
            domain=domain,
            task_id=task_id,
            session_id=write.session_id,
            seq=write.seq,
            action=write.action,
            args=write.args,
            agent_db=agent_db,
            user_db=user_db,
            prior_messages=prior_dump,
            proposing_text=proposing_text,
            policy_text=policy_text,
            prior_writes=prior_writes,
        )
        snapshot = PreActionSnapshot(
            tool_call_id=getattr(tool_call, "id", None),
            agent_db=agent_db,
            user_db=user_db,
            messages=prior_dump,
            proposing_text=proposing_text,
            domain_policy_hash=evidence.domain_policy_hash,
        )
        return snapshot, verdict_record(evaluate(evidence))

    return LiveProposal(pre_execution, db_hash(agent_db), db_hash(user_db))


def executed_outcome(proposal: LiveProposal, result: Any, environment: Any) -> OutcomeRecord:
    """What the environment did with a call that ran: `REJECTED` when it answered with an error
    (a business rule refused it), else `ACCEPTED`; `state_changed` when either database differs
    from the snapshot."""
    agent_db, user_db = db_snapshot(environment)
    after = (db_hash(agent_db), db_hash(user_db))
    error = bool(getattr(result, "error", False))
    return OutcomeRecord(
        outcome="REJECTED" if error else "ACCEPTED",
        state_changed=after != (proposal.agent_db_hash, proposal.user_db_hash),
        backend_error=(getattr(result, "content", None) or "") if error else None,
        agent_db_hash_after=after[0],
        user_db_hash_after=after[1],
    )


def evidence_from_store(store: Any, write: CapturedWrite) -> ProposalEvidence | None:
    """Rebuild a stored write's evidence from its snapshot (for a new oracle version). None if
    the write has no snapshot."""
    snapshot = store.snapshot(write.write_id)
    if snapshot is None:
        return None
    prior = [(w.action, w.args) for w in store.writes(write.session_id) if w.seq < write.seq]
    return ProposalEvidence(
        domain=write.domain or "",
        task_id=write.task_id,
        session_id=write.session_id,
        seq=write.seq,
        action=write.action,
        args=dict(write.args),
        agent_db=snapshot.agent_db,
        user_db=snapshot.user_db,
        turns=turns_from_messages(snapshot.messages),
        domain_policy_hash=snapshot.domain_policy_hash,
        proposing_text=snapshot.proposing_text,
        prior_writes=tuple(prior),
    )
