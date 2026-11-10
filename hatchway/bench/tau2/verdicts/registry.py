"""The validators the oracle knows, and the oracle version they define.

`ORACLE_VERSION` hashes every validator's (domain, action, version, supported policy hashes), so
changing a validator or the policy text it supports gives a new oracle version. Verdicts are
stored per oracle version and never rewritten: a new version appends new rows.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from hatchway.bench.tau2.verdicts.base import (
    NO_VALIDATOR,
    UNSUPPORTED_POLICY_VERSION,
    Check,
    PolicyValidator,
    PolicyVerdict,
    ProposalEvidence,
    combine,
)
from hatchway.bench.tau2.verdicts.retail import (
    CancelPendingOrder,
    ExchangeDeliveredOrderItems,
    ModifyPendingOrderItems,
    ModifyUserAddress,
    ReturnDeliveredOrderItems,
)
from hatchway.bench.tau2.verdicts.telecom import (
    DisableRoaming,
    EnableRoaming,
    RefuelData,
    ResumeLine,
    SendPaymentRequest,
)
from hatchway.state import canonical_json

ORACLE_FAMILY = "tau2-oracle-1"


def build_registry(
    validators: Iterable[PolicyValidator],
) -> dict[tuple[str, str], PolicyValidator]:
    out: dict[tuple[str, str], PolicyValidator] = {}
    for v in validators:
        key = (v.domain, v.action)
        if key in out:
            raise ValueError(f"two validators for {key}")
        out[key] = v
    return out


VALIDATORS = build_registry(
    [
        ReturnDeliveredOrderItems(),
        ExchangeDeliveredOrderItems(),
        ModifyPendingOrderItems(),
        CancelPendingOrder(),
        ModifyUserAddress(),
        EnableRoaming(),
        RefuelData(),
        SendPaymentRequest(),
        ResumeLine(),
        DisableRoaming(),
    ]
)


def oracle_version(validators: Mapping[tuple[str, str], PolicyValidator]) -> str:
    spec = sorted(
        [v.domain, v.action, v.version, sorted(v.supported_policy_hashes)]
        for v in validators.values()
    )
    digest = hashlib.sha256(canonical_json(spec).encode()).hexdigest()[:12]
    return f"{ORACLE_FAMILY}:{digest}"


ORACLE_VERSION = oracle_version(VALIDATORS)


def evaluate(
    evidence: ProposalEvidence,
    validators: Mapping[tuple[str, str], PolicyValidator] = VALIDATORS,
) -> PolicyVerdict:
    """The deterministic policy verdict for one proposal."""
    version = ORACLE_VERSION if validators is VALIDATORS else oracle_version(validators)
    validator = validators.get((evidence.domain, evidence.action))
    if validator is None:
        check = Check(
            NO_VALIDATOR,
            "unknown",
            f"no validator for {evidence.domain}/{evidence.action}",
            {"domain": evidence.domain, "action": evidence.action},
        )
        return combine([check], version)
    if evidence.domain_policy_hash not in validator.supported_policy_hashes:
        check = Check(
            UNSUPPORTED_POLICY_VERSION,
            "unknown",
            "the validator was not written for this policy text",
            {"domain_policy_hash": evidence.domain_policy_hash},
        )
        return combine([check], version)
    return combine(list(validator.evaluate(evidence)), version)
