"""The policy oracle: an independent verdict on whether a proposed write may execute.

See `base` for the evidence rules and decisions, `registry` for the validators and the oracle
version. The package does not import `tau2`; evidence is plain data.
"""

from hatchway.bench.tau2.verdicts.base import (
    POLICY_DECISIONS,
    Check,
    PolicyDecision,
    PolicyVerdict,
    ProposalEvidence,
    ToolCallRef,
    Turn,
    evidence_from_json,
    evidence_to_json,
)
from hatchway.bench.tau2.verdicts.registry import ORACLE_VERSION, VALIDATORS, evaluate

__all__ = [
    "ORACLE_VERSION",
    "POLICY_DECISIONS",
    "VALIDATORS",
    "Check",
    "PolicyDecision",
    "PolicyVerdict",
    "ProposalEvidence",
    "ToolCallRef",
    "Turn",
    "evaluate",
    "evidence_from_json",
    "evidence_to_json",
]
