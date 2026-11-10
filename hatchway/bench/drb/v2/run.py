"""v2 commands, in order (zero spend):

    python -m hatchway.bench.drb.v2 calibrate        # P1/P2 calibration pools (seed 20261024)
    python -m hatchway.bench.drb.v2 develop          # development run on v1 stand-ins (rerunnable)
    python -m hatchway.bench.drb.v2 freeze
    python -m hatchway.bench.drb.v2 generate-fresh   # seed from the freeze hash
    python -m hatchway.bench.drb.v2 evaluate         # once
    python -m hatchway.bench.drb.v2 report

Telecom is never loaded: v2 imports no telecom loader, and every record set is checked against the
v1 seal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hatchway.bench.drb import seal as S
from hatchway.bench.drb.run import EXPERIMENT_DIR as V1_DIR
from hatchway.bench.drb.run import read_records, write_json, write_records
from hatchway.bench.drb.schema import DecisionRecord, canonical, dataset_hash, sha256_text
from hatchway.bench.drb.v2 import adapt as A
from hatchway.bench.drb.v2 import evaluate as E
from hatchway.bench.drb.v2 import pools as P
from hatchway.bench.drb.v2 import risk as R

V2_DIR = Path("experiments/2026-10-23-decision-record-benchmark-v2")
CAL_FILE = "calibration-records.jsonl.gz"
CAL_MANIFEST = "calibration-manifest.json"
FRESH_FILE = "fresh-records.jsonl.gz"
FRESH_MANIFEST = "fresh-manifest.json"
FREEZE_FILE = "freeze.json"
DEV_FILE = "results/development.json"
RESULT_FILE = "results/v2.json"
CONTROL_SEED = 99
DEV_SPLITS = ("syn_pretrain", "syn_promotion", "syn_final")
CODE_FILES = (
    "v2/risk.py",
    "v2/adapt.py",
    "v2/pools.py",
    "v2/evaluate.py",
    "v2/run.py",
    "schema.py",
    "synthetic.py",
    "partitions.py",
    "model.py",
    "seal.py",
    "data/profiles.json",
    "data/synthetic_policy.json",
)


def seal() -> dict[str, Any]:
    return S.load_seal(V1_DIR / "telecom-seal.json")


def v1_synthetic() -> list[DecisionRecord]:
    return read_records(V1_DIR / "synthetic-records.jsonl.gz")


def v1_retail() -> list[DecisionRecord]:
    return read_records(V1_DIR / "retail-records.jsonl.gz")


def development_pool(v1: Sequence[DecisionRecord]) -> list[DecisionRecord]:
    """The v1 P1/P2 in-distribution records; never the v1 held-out action, domain or P3."""
    return [r for r in v1 if r.split in DEV_SPLITS]


def check_no_telecom(world: Mapping[str, Sequence[DecisionRecord]], where: str) -> None:
    ids = [r.record_id for rs in world.values() for r in rs]
    S.assert_no_telecom(ids, seal(), where)
    if any(r.source == "telecom" or r.domain == "telecom" for rs in world.values() for r in rs):
        raise S.TelecomSealed(f"{where}: a telecom record")


def write_pool(
    d: Path, file: str, manifest_file: str, pools: Mapping[str, list], extra: dict
) -> dict:
    records = [r for rs in pools.values() for r in rs]
    write_records(d / file, records)
    manifest = {
        **extra,
        "dataset_sha256": dataset_hash(records),
        "pools": {
            name: {
                "records": len(rs),
                "families": len({r.family_id for r in rs}),
                "eligible_families": R.eligible_families(rs),
                "should_run": sum(r.should_run for r in rs if r.hard_rule is None),
                "should_escalate": sum(not r.should_run for r in rs if r.hard_rule is None),
                "sha256": dataset_hash(rs),
            }
            for name, rs in pools.items()
        },
    }
    write_json(d / manifest_file, manifest, once=True)
    return manifest


def load_pools(d: Path, file: str) -> dict[str, list[DecisionRecord]]:
    out: dict[str, list[DecisionRecord]] = {}
    for r in read_records(d / file):
        out.setdefault(r.split, []).append(r)
    return out


# --- Commands ------------------------------------------------------------------------------------


def cmd_calibrate(d: Path) -> dict[str, Any]:
    pools = P.calibration_pools()
    check_no_telecom(pools, "calibration pools")
    m = write_pool(d, CAL_FILE, CAL_MANIFEST, pools, {"seed": P.CALIBRATION_SEED})
    return {k: v for k, v in m.items()}


def stand_in(v1: Sequence[DecisionRecord]) -> dict[str, list[DecisionRecord]]:
    """Development stand-ins for the fresh pools, from v1 records (development evidence only)."""

    def split(name: str) -> list[DecisionRecord]:
        return [r for r in v1 if r.split == name]

    return {
        "fresh_final": [],
        "fresh_action": split("syn_holdout_action"),
        "fresh_domain": split("syn_holdout_domain"),
        "fresh_p3_corrections": split("syn_p3_adapt"),
        "fresh_p3_promotion": split("syn_p3_eval"),
        "fresh_p3_eval": split("syn_p3_eval"),
        "fresh_hard": split("syn_hard"),
    }


def full_run(
    world: dict[str, list[DecisionRecord]], retail: list[DecisionRecord]
) -> dict[str, Any]:
    check_no_telecom({**world, "retail": retail}, "v2 run")
    models, gate = E.run_world(world)
    controls = {}
    for control in ("shuffled_labels", "no_shared_effect"):
        _, cgate = E.run_world(E.relabel_world(world, control, CONTROL_SEED))
        controls[control] = {
            "apparent_transfer": cgate["apparent_transfer"],
            "conditions": cgate["conditions"],
            "overall": cgate["counts"]["overall"],
        }
    conditions = {
        **gate["conditions"],
        "V9_controls_show_no_apparent_transfer": not any(
            c["apparent_transfer"] for c in controls.values()
        ),
    }
    union = [r for s in E.SLICES for r in world[s]]
    retail_result = E.retail_rotation(retail, models.g_syn)
    return {
        "models": E.describe(models),
        "gate": {**gate, "conditions": conditions, "passed": all(conditions.values())},
        "controls": controls,
        "retail": retail_result,
        "learning_curve": E.learning_curve(
            world["dev"], {"cal_P1": world["cal_P1"], "cal_P2": world["cal_P2"]}, union
        ),
        "operating_curves": E.operating_curves(models, union),
        "intervals_G-combined_minus_DC-score": {
            f"{s}:{metric}": E.bootstrap(models.comb(), models.dcs(), rs, metric)
            for s, rs in [("overall", union), *((s, world[s]) for s in E.SLICES)]
            if rs
            for metric in ("failing_families", "over_escalations", "false_allows")
        },
        "outcome": outcome(conditions, retail_result["verdict"]),
        "cost_usd": 0.0,
        "external_calls": 0,
    }


def outcome(conditions: Mapping[str, bool], retail: str) -> str:
    """RFC v2 §8, first match wins."""
    stop = (
        "V4_over_escalations_down_20pct_overall",
        "V5_over_escalations_down_20pct_action_or_domain",
        "V8_beats_target_only_on_a_transfer_measure",
    )
    if not all(conditions[k] for k in stop):
        return "STOP_LEARNED_ORG_MODEL_PATH"
    if not all(conditions.values()):
        return "STOP_MECHANISM_FAILED"
    if retail == "clear_regression":
        return "NO_SYNTHETIC_VALUE_OVER_RETAIL"
    if retail != "favorable":
        return "INCONCLUSIVE_NEEDS_REAL_DATA"
    return "GATE_PASSED_AWAITING_TELECOM_APPROVAL"


def cmd_develop(d: Path) -> dict[str, Any]:
    v1 = v1_synthetic()
    cal = load_pools(d, CAL_FILE)
    world = {"dev": development_pool(v1), **cal, **stand_in(v1)}
    result = full_run(world, v1_retail())
    result["note"] = (
        "development evidence on v1 stand-ins (v1 held-out action, domain and P3); not the gate"
    )
    write_json(d / DEV_FILE, result)
    return {"conditions": result["gate"]["conditions"], "outcome_if_real": result["outcome"]}


def code_hashes() -> dict[str, str]:
    here = Path(__file__).parents[1]
    return {f: sha256_text((here / f).read_text()) for f in CODE_FILES}


def frozen_state(d: Path) -> dict[str, Any]:
    v1 = v1_synthetic()
    return {
        "spec": {
            "alpha": R.ALPHA,
            "confidence": R.CONFIDENCE,
            "candidate_risk": R.CANDIDATE_RISK,
            "min_eligible": R.MIN_ELIGIBLE,
            "pool_eligible": R.POOL_ELIGIBLE,
            "g_grid": list(R.G_GRID),
            "dc_grid": list(R.DC_GRID),
            "crossfit": {"folds": R.CROSSFIT_FOLDS, "seed": R.CROSSFIT_SEED},
            "lambda_adapt": A.LAMBDA_ADAPT,
            "delta": A.DELTA,
            "cumulative": A.CUMULATIVE,
            "batches": A.N_BATCHES,
            "p3_steps": list(E.P3_STEPS),
            "reduction": E.REDUCTION,
            "bootstrap": E.BOOTSTRAP,
            "calibration_seed": P.CALIBRATION_SEED,
            "control_seed": CONTROL_SEED,
            "fresh_seed_rule": "int(freeze_sha256[:8], 16)",
        },
        "code_sha256": code_hashes(),
        "development_pool_sha256": dataset_hash(development_pool(v1)),
        "v1_synthetic_sha256": dataset_hash(v1),
        "v1_retail_sha256": dataset_hash(v1_retail()),
        "calibration_manifest_sha256": sha256_text((d / CAL_MANIFEST).read_text()),
        "telecom_seal_sha256": seal()["dataset_sha256"],
        "concept_source": "authoritative",
    }


def cmd_freeze(d: Path) -> dict[str, Any]:
    from hatchway.bench.drb.run import load_frozen as v1_frozen
    from hatchway.bench.provenance import git_commit, git_tree_clean

    v1_frozen(V1_DIR)  # v1 untouched
    if not git_tree_clean():
        raise SystemExit("commit everything first: the freeze pins it")
    body = {**frozen_state(d), "hatchway_commit": git_commit()}
    body["freeze_sha256"] = sha256_text(canonical(body))
    write_json(d / FREEZE_FILE, body, once=True)
    return {"freeze_sha256": body["freeze_sha256"], "hatchway_commit": body["hatchway_commit"]}


def load_frozen(d: Path) -> dict[str, Any]:
    frozen = json.loads((d / FREEZE_FILE).read_text())
    now = frozen_state(d)
    diffs = [k for k in now if now[k] != frozen.get(k)]
    if diffs:
        raise SystemExit(f"frozen v2 inputs changed: {diffs}")
    return frozen


def fresh_seed(frozen: Mapping[str, Any]) -> int:
    return int(frozen["freeze_sha256"][:8], 16)


def cmd_generate_fresh(d: Path) -> dict[str, Any]:
    frozen = load_frozen(d)
    seed = fresh_seed(frozen)
    pools = P.fresh_pools(seed)
    check_no_telecom(pools, "fresh pools")
    dev_fams = {r.family_id for r in v1_synthetic()} | {
        r.family_id for rs in load_pools(d, CAL_FILE).values() for r in rs
    }
    overlap = dev_fams & {r.family_id for rs in pools.values() for r in rs}
    if overlap:
        raise SystemExit(f"fresh families overlap development: {sorted(overlap)[:3]}")
    m = write_pool(
        d,
        FRESH_FILE,
        FRESH_MANIFEST,
        pools,
        {"seed": seed, "freeze_sha256": frozen["freeze_sha256"]},
    )
    return {"seed": seed, "dataset_sha256": m["dataset_sha256"], "pools": m["pools"]}


def cmd_evaluate(d: Path) -> dict[str, Any]:
    frozen = load_frozen(d)
    if (d / RESULT_FILE).exists():
        raise SystemExit(f"{RESULT_FILE} exists: v2 is evaluated once")
    manifest = json.loads((d / FRESH_MANIFEST).read_text())
    if manifest["freeze_sha256"] != frozen["freeze_sha256"] or manifest["seed"] != fresh_seed(
        frozen
    ):
        raise SystemExit("the fresh holdout does not belong to this freeze")
    fresh = load_pools(d, FRESH_FILE)
    if dataset_hash([r for rs in fresh.values() for r in rs]) != manifest["dataset_sha256"]:
        raise SystemExit("fresh records differ from their manifest")
    world = {"dev": development_pool(v1_synthetic()), **load_pools(d, CAL_FILE), **fresh}
    result = full_run(world, v1_retail())
    result["freeze_sha256"] = frozen["freeze_sha256"]
    result["fresh_manifest_sha256"] = sha256_text((d / FRESH_MANIFEST).read_text())
    result["telecom"] = "sealed; not opened"
    write_json(d / RESULT_FILE, result, once=True)
    return {"outcome": result["outcome"], "conditions": result["gate"]["conditions"]}


def main(argv: Sequence[str] | None = None) -> int:
    commands = {
        "calibrate": cmd_calibrate,
        "develop": cmd_develop,
        "freeze": cmd_freeze,
        "generate-fresh": cmd_generate_fresh,
        "evaluate": cmd_evaluate,
    }
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=[*commands, "report"])
    parser.add_argument("--dir", type=Path, default=V2_DIR)
    args = parser.parse_args(argv)
    if args.command == "report":
        from hatchway.bench.drb.v2.report import build

        out: Any = {"written": str(build(args.dir))}
    else:
        out = commands[args.command](args.dir)
    json.dump(out, sys.stdout, indent=2, sort_keys=True, default=str)
    print()
    return 0
