"""The sealed telecom holdout (Phase 0A).

Every telecom write of a completed simulation in the benchmark stores is listed once, with what
identifies it and what it was computed from, before any model of this experiment exists. The
manifest is written once and committed; `load_seal` re-checks its dataset hash. Every development
path drops these record ids (`assert_no_telecom`), and only the final evaluation may open them
(`open_telecom`), which it records in `telecom-opened.json`, once.

The manifest stores no verdict per record, only how many records carry an established verdict.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hatchway.bench.store import BenchStore

MANIFEST_VERSION = "drb-telecom-seal-1"
OPENED_FILE = "telecom-opened.json"


class TelecomSealed(RuntimeError):
    """Something other than the final evaluation tried to use a sealed telecom record."""


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def telecom_records(
    stores: Mapping[str, Path],
    family_of: Any,
    oracle_version: str,
    capture: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Manifest entries for every telecom write of a completed simulation, and how many carry an
    established (non-UNKNOWN) verdict at `oracle_version`."""
    from hatchway.bench.tau2.snapshot import evidence_from_store
    from hatchway.bench.tau2.verdicts import evidence_to_json

    out = []
    established = 0
    for name, path in stores.items():
        with BenchStore(path) as store:
            sims = {s.session_id: s for s in store.simulations("done") if s.reward is not None}
            for w in store.writes():
                if w.session_id not in sims or w.domain != "telecom":
                    continue
                evidence = evidence_from_store(store, w)
                if evidence is None:
                    raise ValueError(f"{w.write_id}: no pre-action snapshot")
                verdict = store.verdict(w.write_id, oracle_version)
                if verdict is not None and verdict.expected_decision != "UNKNOWN":
                    established += 1
                sim = sims[w.session_id]
                out.append(
                    {
                        "record_id": w.write_id,
                        "family_id": family_of(w.domain, w.task_id),
                        "action": w.action,
                        "source": {
                            "store": name,
                            "session_id": w.session_id,
                            "seq": w.seq,
                            "task_id": w.task_id,
                            "capture_commit": capture[name]["commit"],
                        },
                        "state_hash": w.state_hash,
                        "evidence_sha256": sha256_text(canonical(evidence_to_json(evidence))),
                        "domain_policy_hash": evidence.domain_policy_hash,
                        "agent_model": sim.agent_model,
                        "user_simulator_model": sim.user_model,
                    }
                )
    return sorted(out, key=lambda r: r["record_id"]), established


def build_seal(
    stores: Mapping[str, Path],
    family_of: Any,
    *,
    oracle_version: str,
    policy_sha256: str,
    tau2_commit: str,
    capture: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    records, established = telecom_records(stores, family_of, oracle_version, capture)
    body = {
        "manifest_version": MANIFEST_VERSION,
        "purpose": "sealed retrospective telecom evaluation set; final-eval only",
        "caveat": "inspected in earlier experiments; directional evidence only",
        "oracle_version": oracle_version,
        "policy_sha256": policy_sha256,
        "tau2_commit": tau2_commit,
        "capture": {k: dict(v) for k, v in sorted(capture.items())},
        "counts": {
            "records": len(records),
            "families": len({r["family_id"] for r in records}),
            "verdict_bearing": established,
            "by_action": {
                a: sum(1 for r in records if r["action"] == a)
                for a in sorted({r["action"] for r in records})
            },
        },
        "records": records,
    }
    body["dataset_sha256"] = sha256_text(canonical(records))
    return body


def write_seal(path: Path, seal: Mapping[str, Any]) -> None:
    if path.exists():
        raise SystemExit(f"{path} exists: the telecom seal is written once")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seal, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def load_seal(path: Path) -> dict[str, Any]:
    seal = json.loads(path.read_text())
    if seal.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(f"{path}: not a {MANIFEST_VERSION} manifest")
    if sha256_text(canonical(seal["records"])) != seal["dataset_sha256"]:
        raise ValueError(f"{path}: records do not match the dataset hash; the seal was edited")
    return seal


def sealed_ids(seal: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(r["record_id"] for r in seal["records"])


def assert_no_telecom(record_ids: Iterable[str], seal: Mapping[str, Any], where: str) -> None:
    """Raise `TelecomSealed` if any sealed telecom record id is in a development path."""
    leaked = sealed_ids(seal) & set(record_ids)
    if leaked:
        raise TelecomSealed(f"{where}: {len(leaked)} sealed telecom records in a development path")


def open_telecom(directory: Path, seal: Mapping[str, Any], *, by: str) -> dict[str, Any]:
    """Record that the telecom holdout is being opened. Refuses a second opening."""
    path = directory / OPENED_FILE
    if path.exists():
        raise TelecomSealed(f"{path} exists: the telecom holdout was already opened; it is locked")
    record = {"opened_by": by, "dataset_sha256": seal["dataset_sha256"]}
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record
