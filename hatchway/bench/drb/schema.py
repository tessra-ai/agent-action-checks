"""The shared decision record (schema `drb-record-1`), for synthetic, retail and telecom records.

A record holds one proposed action, everything needed to audit its answer, and the nine shared
concepts. Each concept is:

- `applicable`: whether the concept bears on this action at all;
- `state`: `satisfied`, `not_satisfied` or `unknown`. `satisfied` is always the condition that
  favors automatic execution. For `potential_harm` it means the potential harm is low; for
  `reversibility`, that the action can be undone; for `evidence_uncertainty`, that the evidence
  is clear;
- `confidence`: from 0 to 1;
- `evidence_ref`: the latent fact or oracle check the state comes from.

An inapplicable concept is never satisfied: its state is `unknown` and it contributes no model
feature. A concept is set only from a latent fact (synthetic) or an independent oracle check
(real), never from the verdict.

The model input is the concepts alone. The verdict, reason codes, hard-rule result, latent facts,
action, domain, family and organization are carried for audit and evaluation only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

SCHEMA_VERSION = "drb-record-1"
CONCEPTS = (
    "actor_identified",
    "action_requested",
    "terms_disclosed",
    "consent_obtained",
    "ownership_authority",
    "prerequisites_satisfied",
    "potential_harm",
    "reversibility",
    "evidence_uncertainty",
)
STATES = ("satisfied", "not_satisfied", "unknown")
VERDICTS = ("ALLOW", "ASK", "DENY")

State = Literal["satisfied", "not_satisfied", "unknown"]
Source = Literal["synthetic", "retail", "telecom"]


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class ConceptValue:
    applicable: bool
    state: State
    confidence: float
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown state {self.state!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if not self.applicable and self.state != "unknown":
            raise ValueError("an inapplicable concept has no state: use 'unknown'")


NOT_APPLICABLE = ConceptValue(False, "unknown", 0.0, None)


@dataclass(frozen=True)
class DecisionRecord:
    record_id: str
    family_id: str
    source: Source
    org_profile: str  # profile id and version, e.g. "P1@drb-profiles-1"
    domain: str
    action: str
    arguments: Mapping[str, Any]
    state: Mapping[str, Any]
    policy_version: str
    evidence: str  # rendered conversation (synthetic) or a reference to it (real)
    latent: Mapping[str, Any] | None
    concepts: Mapping[str, ConceptValue]
    verdict: Literal["ALLOW", "ASK", "DENY"]
    reason_codes: tuple[str, ...]
    hard_rule: str | None  # the hard rule that denied it, else None
    split: str
    seed: int | None
    generator_version: str
    record_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if set(self.concepts) != set(CONCEPTS):
            raise ValueError(f"{self.record_id}: concepts must be exactly {CONCEPTS}")
        if self.verdict not in VERDICTS:
            raise ValueError(f"{self.record_id}: verdict {self.verdict!r}")
        if self.hard_rule is not None and self.verdict != "DENY":
            raise ValueError(f"{self.record_id}: a hard rule always denies")

    @property
    def should_run(self) -> bool:
        """The learner's binary target: ALLOW runs automatically; ASK and DENY escalate."""
        return self.verdict == "ALLOW"

    def body(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("record_hash")
        out["schema_version"] = SCHEMA_VERSION
        out["reason_codes"] = list(self.reason_codes)
        return out

    def computed_hash(self) -> str:
        return sha256_text(canonical(self.body()))

    def sealed(self) -> DecisionRecord:
        return replace(self, record_hash=self.computed_hash())

    def with_split(self, split: str) -> DecisionRecord:
        return replace(self, split=split).sealed()

    def to_json(self) -> dict[str, Any]:
        return {**self.body(), "record_hash": self.record_hash or self.computed_hash()}


def from_json(data: Mapping[str, Any]) -> DecisionRecord:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"not a {SCHEMA_VERSION} record")
    rec = DecisionRecord(
        record_id=data["record_id"],
        family_id=data["family_id"],
        source=data["source"],
        org_profile=data["org_profile"],
        domain=data["domain"],
        action=data["action"],
        arguments=dict(data["arguments"]),
        state=dict(data["state"]),
        policy_version=data["policy_version"],
        evidence=data["evidence"],
        latent=None if data["latent"] is None else dict(data["latent"]),
        concepts={k: ConceptValue(**v) for k, v in data["concepts"].items()},
        verdict=data["verdict"],
        reason_codes=tuple(data["reason_codes"]),
        hard_rule=data["hard_rule"],
        split=data["split"],
        seed=data["seed"],
        generator_version=data["generator_version"],
        record_hash=data["record_hash"],
    )
    if rec.computed_hash() != rec.record_hash:
        raise ValueError(f"{rec.record_id}: record hash mismatch")
    return rec


def dataset_hash(records: list[DecisionRecord]) -> str:
    return sha256_text("\n".join(sorted(f"{r.record_id}:{r.record_hash}" for r in records)))
