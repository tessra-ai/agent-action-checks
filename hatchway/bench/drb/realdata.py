"""τ² records as decision records. Retail is the target organization's history; telecom is
sealed and loads only for the final evaluation (`seal.open_telecom` first).

Only writes of completed simulations with an established verdict (ALLOW / ASK / DENY) become
records; UNKNOWN verdicts are counted and left out.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hatchway.bench.drb import realmap, seal
from hatchway.bench.drb.schema import DecisionRecord, sha256_text
from hatchway.bench.store import BenchStore
from hatchway.policy import Policy


def real_records(
    domain: str,
    stores: Mapping[str, Path],
    policy: Policy,
    policy_sha256: str,
    oracle_version: str,
    capture: Mapping[str, Mapping[str, Any]],
    family_of: Callable[[str, str], str],
    telecom_seal: Mapping[str, Any],
    *,
    final_eval: bool = False,
) -> tuple[list[DecisionRecord], dict[str, int]]:
    """Decision records for one domain, and counts of what was left out."""
    if domain == "telecom" and not final_eval:
        raise seal.TelecomSealed("telecom records load only in final-eval")
    sealed = seal.sealed_ids(telecom_seal)
    out: list[DecisionRecord] = []
    skipped = {"unknown_verdict": 0, "no_verdict": 0}
    for name, path in stores.items():
        with BenchStore(path) as store:
            done = {s.session_id for s in store.simulations("done") if s.reward is not None}
            for w in store.writes():
                if w.session_id not in done or w.domain != domain:
                    continue
                if domain != "telecom" and w.write_id in sealed:
                    raise seal.TelecomSealed(f"{w.write_id}: sealed record outside telecom")
                verdict = store.verdict(w.write_id, oracle_version)
                if verdict is None:
                    skipped["no_verdict"] += 1
                    continue
                if verdict.expected_decision == "UNKNOWN":
                    skipped["unknown_verdict"] += 1
                    continue
                meta = policy.actions[w.action].metadata
                assert meta is not None
                checks = verdict.evidence
                out.append(
                    DecisionRecord(
                        record_id=w.write_id,
                        family_id=family_of(domain, w.task_id or ""),
                        source=domain,  # type: ignore[arg-type]
                        org_profile=f"tau2-{domain}@{policy_sha256[:12]}",
                        domain=domain,
                        action=w.action,
                        arguments=dict(w.args),
                        state={"state_hash": w.state_hash},
                        policy_version=f"policy:{policy_sha256[:12]}+{oracle_version}",
                        evidence=f"snapshot:{name}:{w.write_id}",
                        latent=None,
                        concepts=realmap.concepts_from_checks(
                            w.action, checks, {"impact": meta.impact, "reversible": meta.reversible}
                        ),
                        verdict=verdict.expected_decision,  # type: ignore[arg-type]
                        reason_codes=tuple(verdict.reason_codes),
                        hard_rule=realmap.hard_rule_of(checks),
                        split="unassigned",
                        seed=None,
                        generator_version=(
                            f"tau2-capture@{capture[name]['commit'][:12]}+{realmap.MAPPING_VERSION}"
                        ),
                    ).sealed()
                )
    return sorted(out, key=lambda r: r.record_id), skipped


def checks_digest(records: list[DecisionRecord]) -> str:
    return sha256_text("\n".join(sorted(f"{r.record_id}:{r.record_hash}" for r in records)))
