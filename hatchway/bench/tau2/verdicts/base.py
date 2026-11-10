"""Types for the policy oracle: the evidence a validator sees and the verdict it returns.

A policy verdict answers one question about a proposed write: may it execute now, under the
domain's written policy? It is computed from evidence that exists before the call reaches the
backend, and only from that evidence:

- the proposed action and its arguments;
- the environment's databases as they were just before the call (`agent_db`, and the
  simulated user's device and surroundings in `user_db` where the domain has one);
- the conversation up to the proposing turn, structured (`turns`);
- the writes proposed earlier in the session.

`ProposalEvidence` has no field for the backend's answer, the task's reward or any judge's
score, so no validator can read them: a verdict cannot depend on what happened after the call,
and the judges being evaluated never grade themselves.

Decisions:

- `ALLOW`: the call follows the policy and everything it requires (identity, confirmation) is
  in the conversation.
- `ASK`: something the policy requires is objectively missing (no confirmation was asked for,
  the price was never stated).
- `DENY`: the call breaks the policy outright, or targets the wrong entity or arguments.
- `UNKNOWN`: the evidence exists but cannot be classified reliably, or no validator covers the
  action. UNKNOWN verdicts go to manual review and are left out of the primary metrics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

PolicyDecision = Literal["ALLOW", "ASK", "DENY", "UNKNOWN"]
CheckOutcome = Literal["pass", "ask", "deny", "unknown"]
VerdictSource = Literal["deterministic_oracle", "manual_review"]

POLICY_DECISIONS: tuple[PolicyDecision, ...] = ("ALLOW", "ASK", "DENY", "UNKNOWN")

# Reason codes the registry itself returns.
NO_VALIDATOR = "NO_VALIDATOR"
UNSUPPORTED_POLICY_VERSION = "UNSUPPORTED_POLICY_VERSION"


@dataclass(frozen=True)
class ToolCallRef:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class Turn:
    """One τ² message before the proposing turn. `requestor` says whose tool a `tool` turn
    answers (`assistant` or `user`); `error` marks a tool result the environment rejected."""

    index: int
    role: Literal["assistant", "user", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCallRef, ...] = ()
    tool_call_id: str | None = None
    requestor: str | None = None
    error: bool = False

    @property
    def is_text(self) -> bool:
        """An assistant or user message with words in it (not a tool-call-only turn)."""
        return self.role in ("assistant", "user") and bool(self.content.strip())


@dataclass(frozen=True)
class ProposalEvidence:
    """Everything a validator may look at for one proposed write.

    `turns` are the messages before the one carrying the proposed call; `proposing_text` is that
    message's own text, if any. `prior_writes` are the session's earlier writes as
    `(action, args)`, including calls proposed earlier in the same message.
    """

    domain: str
    task_id: str | None
    session_id: str
    seq: int
    action: str
    args: Mapping[str, Any]
    agent_db: Mapping[str, Any]
    user_db: Mapping[str, Any] | None
    turns: tuple[Turn, ...]
    domain_policy_hash: str
    proposing_text: str = ""
    prior_writes: tuple[tuple[str, Mapping[str, Any]], ...] = ()


@dataclass(frozen=True)
class Check:
    """One policy condition. `facts` holds what the check looked at (ids, turn indexes, db
    fields), so a reviewer can see why it passed or failed."""

    code: str
    outcome: CheckOutcome
    note: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyVerdict:
    expected_decision: PolicyDecision
    should_execute_now: bool | None
    reason_codes: tuple[str, ...]
    explanation: str
    evidence: Mapping[str, Any]
    source: VerdictSource
    oracle_version: str

    def to_json(self) -> dict[str, Any]:
        return {
            "expected_decision": self.expected_decision,
            "should_execute_now": self.should_execute_now,
            "reason_codes": list(self.reason_codes),
            "explanation": self.explanation,
            "evidence": dict(self.evidence),
            "source": self.source,
            "oracle_version": self.oracle_version,
        }


class PolicyValidator(Protocol):
    """Checks one action in one domain. `version` changes whenever `evaluate` changes;
    `supported_policy_hashes` are the policy texts (sha256 of `Environment.get_policy()`) the
    checks were written against."""

    domain: str
    action: str
    version: str
    supported_policy_hashes: frozenset[str]

    def evaluate(self, evidence: ProposalEvidence) -> Sequence[Check]: ...


def should_execute(decision: PolicyDecision) -> bool | None:
    return None if decision == "UNKNOWN" else decision == "ALLOW"


def combine(checks: Sequence[Check], oracle_version: str) -> PolicyVerdict:
    """Any `deny` gives DENY; else any `ask` gives ASK; else any `unknown` gives UNKNOWN; else
    ALLOW. Reason codes are the codes of the checks that did not pass, sorted; the evidence
    keeps every check, passed or not."""
    failed = [c for c in checks if c.outcome != "pass"]
    outcomes = {c.outcome for c in failed}
    decision: PolicyDecision
    if "deny" in outcomes:
        decision = "DENY"
    elif "ask" in outcomes:
        decision = "ASK"
    elif "unknown" in outcomes:
        decision = "UNKNOWN"
    else:
        decision = "ALLOW"
    order = {"deny": 0, "ask": 1, "unknown": 2}
    shown = sorted(failed, key=lambda c: (order[c.outcome], c.code))
    if shown:
        explanation = "; ".join(f"{c.code} ({c.outcome}): {c.note}" for c in shown)
    else:
        explanation = f"all {len(checks)} checks passed"
    evidence = {
        c.code: {"outcome": c.outcome, "note": c.note, "facts": dict(c.facts)} for c in checks
    }
    return PolicyVerdict(
        expected_decision=decision,
        should_execute_now=should_execute(decision),
        reason_codes=tuple(sorted({c.code for c in failed})),
        explanation=explanation,
        evidence=evidence,
        source="deterministic_oracle",
        oracle_version=oracle_version,
    )


def evidence_to_json(ev: ProposalEvidence) -> dict[str, Any]:
    return {
        "domain": ev.domain,
        "task_id": ev.task_id,
        "session_id": ev.session_id,
        "seq": ev.seq,
        "action": ev.action,
        "args": dict(ev.args),
        "agent_db": dict(ev.agent_db),
        "user_db": None if ev.user_db is None else dict(ev.user_db),
        "turns": [turn_to_json(t) for t in ev.turns],
        "domain_policy_hash": ev.domain_policy_hash,
        "proposing_text": ev.proposing_text,
        "prior_writes": [[a, dict(args)] for a, args in ev.prior_writes],
    }


def evidence_from_json(data: Mapping[str, Any]) -> ProposalEvidence:
    return ProposalEvidence(
        domain=data["domain"],
        task_id=data.get("task_id"),
        session_id=data["session_id"],
        seq=data["seq"],
        action=data["action"],
        args=dict(data["args"]),
        agent_db=dict(data["agent_db"]),
        user_db=None if data.get("user_db") is None else dict(data["user_db"]),
        turns=tuple(turn_from_json(t) for t in data["turns"]),
        domain_policy_hash=data["domain_policy_hash"],
        proposing_text=data.get("proposing_text", ""),
        prior_writes=tuple((a, dict(args)) for a, args in data.get("prior_writes", [])),
    )


def turn_to_json(t: Turn) -> dict[str, Any]:
    out: dict[str, Any] = {"index": t.index, "role": t.role, "content": t.content}
    if t.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "name": c.name, "arguments": dict(c.arguments)} for c in t.tool_calls
        ]
    if t.tool_call_id is not None:
        out["tool_call_id"] = t.tool_call_id
    if t.requestor is not None:
        out["requestor"] = t.requestor
    if t.error:
        out["error"] = True
    return out


def turn_from_json(data: Mapping[str, Any]) -> Turn:
    return Turn(
        index=data["index"],
        role=data["role"],
        content=data.get("content") or "",
        tool_calls=tuple(
            ToolCallRef(c["id"], c["name"], dict(c.get("arguments") or {}))
            for c in data.get("tool_calls") or []
        ),
        tool_call_id=data.get("tool_call_id"),
        requestor=data.get("requestor"),
        error=bool(data.get("error", False)),
    )
