"""Phase A commands: generate, evaluate (once), side-check, dry-run, report.

    python -m hatchway.bench.pi generate     # cases.jsonl.gz + cases-manifest.json (needs τ² data)
    python -m hatchway.bench.pi evaluate     # results/phase-a.json, written once
    python -m hatchway.bench.pi side-check   # results/v2-side-check.json (descriptive)
    python -m hatchway.bench.pi dry-run      # results/phase-b-dry-run.json (0 model calls)
    python -m hatchway.bench.pi report

`evaluate` reads only the committed cases file and refuses to run when its hash differs from
the manifest, or when results already exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hatchway.bench.pi import cases as C
from hatchway.bench.pi import evaluate as E
from hatchway.bench.pi import induce as S

EXPERIMENT = Path(__file__).parents[3] / "experiments/2026-10-25-policy-induction"
CASES_FILE = "cases.jsonl.gz"
MANIFEST = "cases-manifest.json"
RESULT_FILE = "results/phase-a.json"
SIDE_FILE = "results/v2-side-check.json"
DRY_FILE = "results/phase-b-dry-run.json"
CODE_FILES = ("__init__.py", "cases.py", "worlds.py", "induce.py", "evaluate.py", "run.py")
FACT_HIDDEN = ("H1_LARGE_REFUND", "H2_PRODUCT", "H3_REPEAT_CANCEL", "H4_UPCHARGE")
FACT_HIDDEN += ("H6_SMALL_CANCEL_WAIVER", "H7_PAYPAL_RETURN")
LEARNABLE_MIN = 4
SHUFFLED_MAX = 0.05


def code_hashes() -> dict[str, str]:
    here = Path(__file__).parent
    return {f: hashlib.sha256((here / f).read_bytes()).hexdigest() for f in CODE_FILES}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def cmd_generate(d: Path) -> dict[str, Any]:
    if (d / MANIFEST).exists():
        raise SystemExit("cases already generated (written once)")
    cases = C.generate()
    sha = C.write_cases(d / CASES_FILE, cases)
    counts: dict[str, Any] = {
        "cases": len(cases),
        "families": len({c.family_id for c in cases}),
        "train_families": len({c.family_id for c in cases if E.is_train(c.family_id)}),
    }
    for decision in ("ALLOW", "ASK", "DENY", "UNKNOWN"):
        counts[decision] = sum(c.decision == decision for c in cases)
    manifest = {
        "generator": C.GENERATOR,
        "seed": C.SEED,
        "tau2_commit": "c5b2d228d850c59b749b93cf32c4745d3aa53967",
        "retail_policy_sha256": C.POLICY_HASH,
        "dataset_sha256": sha,
        "counts": counts,
        "code_sha256": code_hashes(),
    }
    _write_json(d / MANIFEST, manifest)
    return manifest


def load_cases(d: Path) -> list[C.Case]:
    manifest = json.loads((d / MANIFEST).read_text())
    cases = C.read_cases(d / CASES_FILE)
    if C.dataset_sha256(cases) != manifest["dataset_sha256"]:
        raise SystemExit("the cases file does not match its manifest")
    return cases


def outcome(worlds: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any]]:
    """The preregistered Phase A checks (RFC) and the first matching outcome."""
    by = {w["world"]: w for w in worlds}
    shuffled: dict[str, float] = {}
    for arm in E.ARMS:
        cells = [
            v
            for w in worlds
            for v in w["arms"][arm]["shuffled"]["by_k"].values()
            if v.get("available")
        ]
        runs = sum(v["replicates"] for v in cells)
        shuffled[arm] = sum(v["any_rule_rate"] * v["replicates"] for v in cells) / runs
    k_stars = {n: by[n]["arms"]["S"]["clean"]["k_star"] for n in FACT_HIDDEN}
    learnable = [n for n, k in k_stars.items() if k is not None and k <= 10]
    h5 = by["H5_CHARGEBACK"]["arms"]["S"]["clean"]["by_k"]
    h5_best = max(v["recovery_rate"] for v in h5.values() if v.get("available"))
    checks = {
        "A1_shuffled_control": all(r <= SHUFFLED_MAX for r in shuffled.values()),
        "A2_learnable": len(learnable) >= LEARNABLE_MIN,
        "A3_discriminating": h5_best < E.K_STAR_RATE,
    }
    detail = {
        "shuffled_any_rule_rate": shuffled,
        "k_star_S_clean": k_stars,
        "learnable_worlds": learnable,
        "h5_best_recovery_rate_S": h5_best,
    }
    if not checks["A1_shuffled_control"]:
        label = "BENCHMARK_INVALID_CONTROL"
    elif not checks["A2_learnable"]:
        label = "BENCHMARK_TOO_HARD"
    elif not checks["A3_discriminating"]:
        label = "BENCHMARK_LEAKS_RAW_SIGNAL"
    else:
        label = "BENCHMARK_VALID"
    return label, {"checks": checks, **detail}


def cmd_evaluate(d: Path) -> dict[str, Any]:
    if (d / RESULT_FILE).exists():
        raise SystemExit("Phase A already evaluated once; results are written once")
    manifest = json.loads((d / MANIFEST).read_text())
    if manifest["code_sha256"] != code_hashes():
        raise SystemExit("code changed since the cases were generated")
    cases = load_cases(d)
    worlds = E.run_all(cases)
    label, detail = outcome(worlds)
    result = {
        "outcome": label,
        **detail,
        "dataset_sha256": manifest["dataset_sha256"],
        "code_sha256": code_hashes(),
        "parameters": {
            "background": E.BACKGROUND,
            "audit_rate": E.AUDIT_RATE,
            "k_grid": list(E.K_GRID),
            "conditions": list(E.CONDITIONS),
            "replicates": E.REPLICATES,
            "alpha": S.ALPHA,
            "max_literals": S.MAX_LITERALS,
            "max_rules": S.MAX_RULES,
            "min_positives": S.MIN_POSITIVES,
        },
        "spend_usd": 0.0,
        "external_calls": 0,
        "worlds": worlds,
    }
    _write_json(d / RESULT_FILE, result)
    return result


def cmd_side_check(d: Path) -> dict[str, Any]:
    from hatchway.bench.pi import v2check

    result = {"descriptive_only": True, **v2check.run()}
    _write_json(d / SIDE_FILE, result)
    return result


def cmd_dry_run(d: Path) -> dict[str, Any]:
    from hatchway.bench.pi import llm

    result = llm.dry_run(load_cases(d))
    _write_json(d / DRY_FILE, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hatchway.bench.pi")
    ap.add_argument("command", choices=("generate", "evaluate", "side-check", "dry-run", "report"))
    ap.add_argument("--dir", type=Path, default=EXPERIMENT)
    a = ap.parse_args(argv)
    if a.command == "generate":
        m = cmd_generate(a.dir)
        print(json.dumps(m["counts"]), m["dataset_sha256"])
    elif a.command == "evaluate":
        r = cmd_evaluate(a.dir)
        print(r["outcome"], json.dumps(r["checks"]))
    elif a.command == "side-check":
        cmd_side_check(a.dir)
    elif a.command == "dry-run":
        r = cmd_dry_run(a.dir)
        print(json.dumps(r["totals"]))
    else:
        from hatchway.bench.pi import report

        print(report.build(a.dir))
    return 0
