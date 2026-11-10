"""Phase 0 commands, in order (all zero-spend: no judge, LLM or capture):

    python -m hatchway.bench.drb seal-telecom   # 0A: before any model exists
    python -m hatchway.bench.drb generate       # synthetic records and their manifest
    python -m hatchway.bench.drb map-retail     # retail records and their manifest
    python -m hatchway.bench.drb freeze         # model spec, gate, manifests, code hashes
    python -m hatchway.bench.drb develop        # fit, learning curves, controls, gate; once
    python -m hatchway.bench.drb final-eval     # telecom, once, only if the gate passed
    python -m hatchway.bench.drb report

Generated files go to the experiment directory. Every command after `freeze` refuses to run if a
frozen input has changed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hatchway.bench.drb import evaluate as E
from hatchway.bench.drb import model as M
from hatchway.bench.drb import partitions as P
from hatchway.bench.drb import seal as S
from hatchway.bench.drb import synthetic as G
from hatchway.bench.drb.schema import DecisionRecord, canonical, from_json, sha256_text

EXPERIMENT_DIR = Path("experiments/2026-10-23-decision-record-benchmark")
SEAL_FILE = "telecom-seal.json"
SYN_FILE = "synthetic-records.jsonl.gz"
SYN_MANIFEST = "synthetic-manifest.json"
RETAIL_FILE = "retail-records.jsonl.gz"
RETAIL_MANIFEST = "retail-manifest.json"
FREEZE_FILE = "freeze.json"
DEVELOP_FILE = "results/internal.json"
TELECOM_FILE = "results/telecom.json"
STORES = {"targeted": Path("runs/targeted.db"), "smoke2": Path("runs/smoke2.db")}
# The commit each store was captured with (runs/targeted/experiment.json, runs/smoke2/summary.json).
CAPTURE = {
    "targeted": {
        "commit": "29b5af7d8a183ef7366efbfce810757803f7c37f",
        "experiment": "targeted stage 1",
    },
    "smoke2": {"commit": "6acd2e5bac10b2207ff70c8b28d0248a05317199", "experiment": "smoke run 2"},
}
RETAIL_SEED = 20261023
CONTROL_SEED = 99
CODE_FILES = (
    "schema.py",
    "synthetic.py",
    "partitions.py",
    "realmap.py",
    "realdata.py",
    "model.py",
    "evaluate.py",
    "sources.py",
    "seal.py",
    "run.py",
    "data/profiles.json",
    "data/synthetic_policy.json",
)


def policy_sha256() -> str:
    from hatchway.bench.tau2 import DEFAULT_POLICY

    return S.sha256_text(DEFAULT_POLICY.read_text())


def oracle_version() -> str:
    from hatchway.bench.tau2.verdicts.registry import ORACLE_VERSION

    return ORACLE_VERSION


def write_records(path: Path, records: Sequence[DecisionRecord]) -> None:
    lines = "".join(canonical(r.to_json()) + "\n" for r in records)
    path.write_bytes(gzip.compress(lines.encode(), mtime=0))


def read_records(path: Path) -> list[DecisionRecord]:
    text = gzip.decompress(path.read_bytes()).decode()
    return [from_json(json.loads(line)) for line in text.splitlines() if line]


def write_json(path: Path, data: Any, *, once: bool = False) -> None:
    if once and path.exists():
        raise SystemExit(f"{path} exists; it is written once")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(E.nan_free(data), indent=1, sort_keys=True) + "\n")


def load_seal(d: Path) -> dict[str, Any]:
    return S.load_seal(d / SEAL_FILE)


# --- Commands ------------------------------------------------------------------------------------


def cmd_seal_telecom(d: Path) -> dict[str, Any]:
    from hatchway.bench.pilot.data import tau2_family
    from hatchway.bench.tau2 import TAU2_COMMIT

    seal = S.build_seal(
        STORES,
        tau2_family,
        oracle_version=oracle_version(),
        policy_sha256=policy_sha256(),
        tau2_commit=TAU2_COMMIT,
        capture=CAPTURE,
    )
    S.write_seal(d / SEAL_FILE, seal)
    return {"dataset_sha256": seal["dataset_sha256"], "counts": seal["counts"]}


def build_synthetic() -> list[DecisionRecord]:
    return P.assign_synthetic(G.generate(G.SEED), G.SEED)


def cmd_generate(d: Path) -> dict[str, Any]:
    load_seal(d)  # the seal exists before any data or model
    records = build_synthetic()
    P.assert_family_isolation(records)
    bad = [r.record_id for r in records if G.validate_rendering(r, G.spec_of(r.action))]
    if bad:
        raise SystemExit(f"renderings disagree with latent facts: {bad[:5]}")
    write_records(d / SYN_FILE, records)
    manifest = P.manifest(
        "synthetic",
        records,
        {
            "generator_version": G.GENERATOR_VERSION,
            "seed": G.SEED,
            "policy_version": G.policy()["version"],
            "profiles_version": G.profiles()["version"],
            "held_out": {
                "action": P.HELD_OUT_ACTION,
                "domain": P.HELD_OUT_DOMAIN,
                "profile": P.HELD_OUT_PROFILE,
                "adapt_k": list(P.ADAPT_K),
            },
            "file_sha256": hashlib.sha256((d / SYN_FILE).read_bytes()).hexdigest(),
        },
    )
    write_json(d / SYN_MANIFEST, manifest)
    return {k: v for k, v in manifest.items() if k != "records"}


def build_retail(d: Path) -> tuple[list[DecisionRecord], dict[str, int], dict[str, str]]:
    from hatchway.bench.drb import realdata
    from hatchway.bench.pilot.data import tau2_family
    from hatchway.bench.tau2 import DEFAULT_POLICY
    from hatchway.policy import load_policy

    seal = load_seal(d)
    records, skipped = realdata.real_records(
        "retail",
        STORES,
        load_policy(DEFAULT_POLICY),
        policy_sha256(),
        oracle_version(),
        CAPTURE,
        tau2_family,
        seal,
    )
    S.assert_no_telecom([r.record_id for r in records], seal, "retail mapping")
    sizes: dict[str, int] = defaultdict(int)
    for r in records:
        sizes[r.family_id] += 1
    split = P.split_retail(sizes, RETAIL_SEED)
    return [r.with_split(split[r.family_id]) for r in records], skipped, split


def cmd_map_retail(d: Path) -> dict[str, Any]:
    from hatchway.bench.drb.realmap import MAPPING_VERSION

    records, skipped, _ = build_retail(d)
    P.assert_family_isolation(records)
    write_records(d / RETAIL_FILE, records)
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: {"ALLOW": 0, "ASK": 0, "DENY": 0})
    for r in records:
        coverage[r.action][r.verdict] += 1
    manifest = P.manifest(
        "retail",
        records,
        {
            "oracle_version": oracle_version(),
            "policy_sha256": policy_sha256(),
            "mapping_version": MAPPING_VERSION,
            "stores": {k: str(v) for k, v in STORES.items()},
            "capture": CAPTURE,
            "left_out": skipped,
            "coverage_by_action": dict(sorted(coverage.items())),
            "split_seed": RETAIL_SEED,
            "file_sha256": hashlib.sha256((d / RETAIL_FILE).read_bytes()).hexdigest(),
        },
    )
    write_json(d / RETAIL_MANIFEST, manifest)
    return {k: v for k, v in manifest.items() if k != "records"}


def code_hashes() -> dict[str, str]:
    here = Path(__file__).parent
    return {f: S.sha256_text((here / f).read_text()) for f in CODE_FILES}


def frozen_state(d: Path) -> dict[str, Any]:
    return {
        "model_spec": M.MODEL_SPEC,
        "model_spec_sha256": M.spec_hash(),
        "gate": E.GATE,
        "control_seed": CONTROL_SEED,
        "synthetic_manifest_sha256": S.sha256_text((d / SYN_MANIFEST).read_text()),
        "retail_manifest_sha256": S.sha256_text((d / RETAIL_MANIFEST).read_text()),
        "telecom_seal_sha256": load_seal(d)["dataset_sha256"],
        "code_sha256": code_hashes(),
        "concept_source": "authoritative",
        "oracle_version": oracle_version(),
        "policy_sha256": policy_sha256(),
    }


def cmd_freeze(d: Path) -> dict[str, Any]:
    from hatchway.bench.provenance import git_commit, git_tree_clean

    if not git_tree_clean():
        raise SystemExit("commit the code and data first: the freeze pins them")
    state = frozen_state(d)
    body = {**state, "hatchway_commit": git_commit()}
    body["freeze_sha256"] = sha256_text(canonical(body))
    write_json(d / FREEZE_FILE, body, once=True)
    return {"freeze_sha256": body["freeze_sha256"], "hatchway_commit": body["hatchway_commit"]}


def load_frozen(d: Path) -> dict[str, Any]:
    frozen = json.loads((d / FREEZE_FILE).read_text())
    now = frozen_state(d)
    diffs = [k for k in now if now[k] != frozen.get(k)]
    if diffs:
        raise SystemExit(f"frozen inputs changed since freeze: {diffs}")
    return frozen


def representation_conflicts(records: Sequence[DecisionRecord]) -> dict[str, Any]:
    """Groups with identical model inputs under one organization but different labels."""
    groups: dict[tuple[str, str], set[bool]] = defaultdict(set)
    for r in records:
        if r.hard_rule is None:
            groups[(r.org_profile, canonical(M.features(r).tolist()))].add(r.should_run)
    conflicts = [k for k, v in groups.items() if len(v) > 1]
    by_org: dict[str, int] = defaultdict(int)
    for org, _ in conflicts:
        by_org[org] += 1
    return {"groups": len(groups), "conflicting_groups": len(conflicts), "by_org": dict(by_org)}


def cmd_develop(d: Path) -> dict[str, Any]:
    frozen = load_frozen(d)
    seal = load_seal(d)
    syn = read_records(d / SYN_FILE)
    retail = read_records(d / RETAIL_FILE)
    S.assert_no_telecom([r.record_id for r in syn + retail], seal, "develop")
    assert all(r.source == "synthetic" for r in syn) and all(r.source == "retail" for r in retail)
    dev = [r for r in syn if r.split in ("syn_pretrain", "syn_promotion")]
    dev += [r for r in retail if r.split in ("retail_adapt", "retail_promotion")]
    conflicts = representation_conflicts(dev)
    fitted = E.fit_all(syn, retail)
    gate = E.internal_gate(syn, fitted)
    controls = {}
    for name, relabel in (
        ("shuffled_labels", G.shuffled_labels),
        ("no_shared_effect", G.no_shared_effect),
    ):
        c_syn = relabel(syn, CONTROL_SEED)
        c_fit = E.fit_all(c_syn, [])
        c_gate = E.internal_gate(c_syn, c_fit)
        controls[name] = {
            "apparent_transfer": c_gate["apparent_transfer"],
            "conditions": c_gate["conditions"],
            "union": c_gate["counts"]["union"],
        }
    g9 = not any(c["apparent_transfer"] for c in controls.values())
    conditions = {**gate["conditions"], "G9_controls_show_no_apparent_transfer": g9}
    passed = all(conditions.values()) and all(gate["coverage"].values())
    r_hold = E.by_split(retail, "retail_holdout")
    retail_models = {
        "escalate-all": M.ESCALATE_ALL,
        "DC": M.DC,
        "G-synthetic": fitted.g_syn,
        "G-retail": fitted.g_retail,
        "G-combined": fitted.g_comb_retail,
    }
    if passed:
        outcome = "PENDING_TELECOM"
    else:
        outcome = (
            "REVISE_REPRESENTATION" if conflicts["conflicting_groups"] else "STOP_MECHANISM_FAILED"
        )
    result = {
        "freeze_sha256": frozen["freeze_sha256"],
        "concept_source": "authoritative",
        "representation_conflicts": conflicts,
        "models": {
            "G-synthetic": {"version": fitted.g_syn.version, "threshold": fitted.g_syn.threshold},
            "promotion": {"promoted": fitted.promoted, "reason": fitted.promotion_reason},
            **{
                m.name: {
                    "version": m.version,
                    "threshold": m.threshold,
                    "trained_on": len(m.trained_on),
                }
                for m in [
                    *fitted.g_target.values(),
                    *fitted.g_comb.values(),
                    *(x for ms in fitted.p3.values() for x in ms.values()),
                    fitted.g_retail,
                    fitted.g_comb_retail,
                ]
                if m is not None
            },
            "training_hashes": {
                "syn_pretrain": sha256_text(
                    "\n".join(sorted(r.record_hash for r in E.by_split(syn, "syn_pretrain")))
                ),
                "retail_adapt": sha256_text(
                    "\n".join(sorted(r.record_hash for r in E.by_split(retail, "retail_adapt")))
                ),
            },
        },
        "gate": {**gate, "conditions": conditions, "passed": passed},
        "controls": {
            **controls,
            "structural": E.controls_structural(syn, fitted),
        },
        "learning_curves": E.learning_curves(syn, retail, fitted, G.SEED),
        "retail_internal_holdout": {
            name: E.count(E.fixed(m), r_hold).to_json() for name, m in retail_models.items()
        },
        "outcome_so_far": outcome,
        "cost_usd": 0.0,
        "external_calls": 0,
    }
    write_json(d / DEVELOP_FILE, result, once=True)
    return {"passed": passed, "conditions": conditions, "outcome_so_far": outcome}


def cmd_final_eval(d: Path) -> dict[str, Any]:
    from hatchway.bench.drb import realdata
    from hatchway.bench.pilot.data import tau2_family
    from hatchway.bench.tau2 import DEFAULT_POLICY
    from hatchway.policy import load_policy

    load_frozen(d)
    internal = json.loads((d / DEVELOP_FILE).read_text())
    if not internal["gate"]["passed"]:
        raise SystemExit(
            f"the internal gate failed ({internal['outcome_so_far']}): telecom stays sealed"
        )
    seal = load_seal(d)
    S.open_telecom(d / "results", seal, by="final-eval")
    syn = read_records(d / SYN_FILE)
    retail = read_records(d / RETAIL_FILE)
    fitted = E.fit_all(syn, retail)
    telecom, skipped = realdata.real_records(
        "telecom",
        STORES,
        load_policy(DEFAULT_POLICY),
        policy_sha256(),
        oracle_version(),
        CAPTURE,
        tau2_family,
        seal,
        final_eval=True,
    )
    if {r.record_id for r in telecom} - S.sealed_ids(seal):
        raise SystemExit("telecom records outside the seal")
    models = {
        "escalate-all": M.ESCALATE_ALL,
        "DC": M.DC,
        "G-synthetic": fitted.g_syn,
        "G-retail": fitted.g_retail,
        "G-combined": fitted.g_comb_retail,
    }
    result = E.telecom_eval(telecom, models, G.SEED)
    result["left_out"] = skipped
    result["model_versions"] = {k: m.version for k, m in models.items() if m is not None}
    write_json(d / TELECOM_FILE, result, once=True)
    return {"positive": result["positive"], "sufficient": result["sufficient"]}


def main(argv: Sequence[str] | None = None) -> int:
    commands = {
        "seal-telecom": cmd_seal_telecom,
        "generate": cmd_generate,
        "map-retail": cmd_map_retail,
        "freeze": cmd_freeze,
        "develop": cmd_develop,
        "final-eval": cmd_final_eval,
    }
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=[*commands, "report"])
    parser.add_argument("--dir", type=Path, default=EXPERIMENT_DIR)
    args = parser.parse_args(argv)
    if args.command == "report":
        from hatchway.bench.drb.report import build

        out: Any = {"written": str(build(args.dir))}
    else:
        out = commands[args.command](args.dir)
    json.dump(E.nan_free(out), sys.stdout, indent=2, sort_keys=True, default=str)
    print()
    return 0
