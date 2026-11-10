"""The sealed telecom holdout: its hash, its exclusion from development, and one opening."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hatchway.bench.drb import seal as S

SEAL = (
    Path(__file__).parents[1] / "experiments/2026-10-23-decision-record-benchmark/telecom-seal.json"
)


def test_the_committed_seal_verifies() -> None:
    seal = S.load_seal(SEAL)
    assert seal["counts"]["records"] == len(seal["records"]) == len(S.sealed_ids(seal))
    for r in seal["records"]:
        assert r["family_id"].startswith("telecom/")
        assert {"state_hash", "evidence_sha256", "domain_policy_hash", "agent_model"} <= set(r)
    # No per-record verdict is stored in the seal.
    assert not any("verdict" in r or "label" in r for r in seal["records"])


def test_an_edited_seal_is_refused(tmp_path: Path) -> None:
    seal = json.loads(SEAL.read_text())
    seal["records"] = seal["records"][1:]
    path = tmp_path / "seal.json"
    path.write_text(json.dumps(seal))
    with pytest.raises(ValueError, match="edited"):
        S.load_seal(path)


def test_sealed_records_are_refused_in_development() -> None:
    seal = S.load_seal(SEAL)
    some = next(iter(S.sealed_ids(seal)))
    S.assert_no_telecom(["synthetic-1", "retail-x"], seal, "fit")
    with pytest.raises(S.TelecomSealed):
        S.assert_no_telecom(["synthetic-1", some], seal, "fit")


def test_the_holdout_opens_once(tmp_path: Path) -> None:
    seal = S.load_seal(SEAL)
    S.open_telecom(tmp_path, seal, by="final-eval")
    with pytest.raises(S.TelecomSealed, match="already opened"):
        S.open_telecom(tmp_path, seal, by="final-eval")


def test_the_seal_is_written_once(tmp_path: Path) -> None:
    S.write_seal(tmp_path / "s.json", {"a": 1})
    with pytest.raises(SystemExit):
        S.write_seal(tmp_path / "s.json", {"a": 2})
