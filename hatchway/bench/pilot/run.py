"""The pilot's commands, in order. Each refuses to run on a changed definition.

    python -m hatchway.bench.pilot freeze --dir runs/pilot \\
        --store targeted=runs/targeted.db --store smoke2=runs/smoke2.db
    python -m hatchway.bench.pilot verdicts --dir runs/pilot   # verdicts at the frozen oracle
    python -m hatchway.bench.pilot split --dir runs/pilot      # label-free, holdout sealed
    python -m hatchway.bench.pilot score --dir runs/pilot      # ≤ $1, hard ledger cap
    python -m hatchway.bench.pilot analyze --dir runs/pilot    # revealed + promotion only
    python -m hatchway.bench.pilot final-eval --dir runs/pilot # once; reads the holdout
    python -m hatchway.bench.pilot report --dir runs/pilot

`freeze` pins the arm specs, the analysis constants, the pilot code, the oracle version, the
policy file, the judges, the stores' candidate writes and the seeds (`pilot.json`). Nothing is
examined before it: no verdict, score or label is read. Later commands recompute the pinned
fields and stop if any differs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from hatchway.bench import models
from hatchway.bench.pilot import analysis as A
from hatchway.bench.pilot import arms, concepts, data
from hatchway.bench.provenance import git_commit, git_tree_clean, tau2_commit
from hatchway.bench.tau2 import DEFAULT_POLICY, TAU2_COMMIT
from hatchway.policy import load_policy

log = logging.getLogger("hatchway")

STATUS = "directional pilot, deterministic oracle only — unaudited"
DEFINITION = "pilot.json"
SPLIT = "split.json"
ANALYSIS = "analysis.json"
FINAL = "final.json"
LEDGER = "ledger.db"
SCORING_CAP_USD = 1.0
SPLIT_SEED = 20261023
ORDERING_SEED = 7
BOOTSTRAP_SEED = 11
JUDGES = {"openai_decisions": models.DECISIONS_MODEL, "jev": models.JEV_MODEL}
# Concepts whose real corrections the adaptation analysis reveals.
ADAPT_CONCEPTS = (
    "consent_obtained",
    "terms_disclosed",
    "ownership_authority",
    "prerequisites_satisfied",
    "action_requested",
)
CODE_FILES = ("arms.py", "analysis.py", "concepts.py", "data.py", "run.py")
PINNED = (
    "specs",
    "spec_sha256",
    "constants",
    "code_sha256",
    "oracle_version",
    "policy_sha256",
    "rubric_hashes",
    "judges",
    "stores",
    "candidates",
    "tau2_commit_pinned",
)


class DefinitionChanged(SystemExit):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def constants() -> dict[str, Any]:
    return {
        "catch_target": arms.CATCH_TARGET,
        "primary_judge": arms.PRIMARY_JUDGE,
        "orderings": A.ORDERINGS,
        "ordering_seed": ORDERING_SEED,
        "checkpoints": list(A.CHECKPOINTS),
        "promote_every": A.PROMOTE_EVERY,
        "gate_min_labelled": A.MIN_GROUP_LABELLED,
        "gate_min_should_escalate": A.MIN_GROUP_NEGATIVE,
        "adapt_concepts": list(ADAPT_CONCEPTS),
        "adapt_min_corrections": A.MIN_CORRECTIONS,
        "adapt_min_later_failures": A.MIN_LATER_FAILURES,
        "bootstrap": A.BOOTSTRAP,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "split_seed": SPLIT_SEED,
        "split_targets": data.SPLIT_TARGETS,
        "split_draws": data.SPLIT_DRAWS,
        "scoring_cap_usd": SCORING_CAP_USD,
    }


def current(stores: Mapping[str, str]) -> dict[str, Any]:
    """Everything pinned, as it is now."""
    from hatchway.bench.tau2.verdicts.registry import ORACLE_VERSION

    policy = load_policy(DEFAULT_POLICY)
    rubrics = concepts.rubrics(policy)
    here = Path(__file__).parent
    cands = data.candidates({k: Path(v) for k, v in stores.items()}, rubrics)
    return {
        "specs": arms.PILOT_SPECS,
        "spec_sha256": arms.spec_hash(),
        "constants": constants(),
        "code_sha256": {f: sha256_file(here / f) for f in CODE_FILES},
        "oracle_version": ORACLE_VERSION,
        "policy_sha256": sha256_file(DEFAULT_POLICY),
        "rubric_hashes": {a: h for a, (_, h) in sorted(rubrics.items())},
        "judges": JUDGES,
        "stores": dict(stores),
        "candidates": {
            "writes": len(cands),
            "families": len({c.family for c in cands}),
            "sha256": data.candidates_digest(cands),
        },
        "tau2_commit_pinned": TAU2_COMMIT,
    }


def freeze(directory: Path, stores: Mapping[str, str]) -> dict[str, Any]:
    path = directory / DEFINITION
    if path.exists():
        raise SystemExit(f"{path} exists: the pilot is frozen once")
    if not git_tree_clean():
        raise SystemExit("commit the pilot code first: the definition pins it")
    state = current(stores)
    body = {
        **state,
        "status": STATUS,
        "hatchway_commit": git_commit(),
        "tau2_commit_installed": tau2_commit(),
    }
    body["definition_sha256"] = arms.spec_hash(body)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    return body


def load(directory: Path) -> dict[str, Any]:
    path = directory / DEFINITION
    if not path.exists():
        raise SystemExit(f"no {path}: run `freeze` first")
    definition = json.loads(path.read_text())
    body = {k: v for k, v in definition.items() if k != "definition_sha256"}
    if arms.spec_hash(body) != definition["definition_sha256"]:
        raise DefinitionChanged(f"{path} was edited after freezing")
    now = current(definition["stores"])
    diffs = [k for k in PINNED if now[k] != definition[k]]
    if diffs:
        raise DefinitionChanged(
            "the frozen pilot definition no longer matches: " + ", ".join(diffs)
        )
    return definition


def write_once(path: Path, payload: Any) -> str:
    if path.exists():
        raise SystemExit(f"{path} exists; it is written once")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def stores_of(definition: Mapping[str, Any]) -> dict[str, Path]:
    return {k: Path(v) for k, v in definition["stores"].items()}


def all_candidates(definition: Mapping[str, Any]) -> list[data.Candidate]:
    return data.candidates(stores_of(definition), definition["rubric_hashes"])


def load_split(directory: Path) -> dict[str, Any]:
    path = directory / SPLIT
    if not path.exists():
        raise SystemExit(f"no {path}: run `split` first")
    return json.loads(path.read_text())


def scoped_rows(
    directory: Path, definition: Mapping[str, Any], scope: data.Scope, *, final_eval: bool = False
) -> tuple[list[arms.Row], dict[str, Any]]:
    cands = data.in_scope(
        all_candidates(definition), load_split(directory), scope, final_eval=final_eval
    )
    return data.rows(
        cands,
        stores_of(definition),
        load_policy(DEFAULT_POLICY),
        definition["oracle_version"],
        definition["rubric_hashes"],
        definition["judges"],
    )


# --- Commands ------------------------------------------------------------------------------------


def cmd_verdicts(directory: Path) -> dict[str, Any]:
    from hatchway.bench.store import BenchStore
    from hatchway.bench.tau2.verdicts.__main__ import recompute

    definition = load(directory)
    out = {}
    for name, path in stores_of(definition).items():
        with BenchStore(path) as store:
            out[name] = dict(recompute(store))
    return out


def cmd_split(directory: Path) -> dict[str, Any]:
    definition = load(directory)
    split = data.freeze_split(all_candidates(definition), SPLIT_SEED)
    split["definition_sha256"] = definition["definition_sha256"]
    write_once(directory / SPLIT, split)
    return {k: v for k, v in split.items() if k != "holdout"} | {
        "holdout": {"families": len(split["holdout"]["family_sha256"])}
    }


async def cmd_score(directory: Path, judges: Sequence[str], dry_run: bool) -> dict[str, Any]:
    from hatchway.bench.budget import Caps, Ledger
    from hatchway.bench.score import make_judge, score_store
    from hatchway.bench.store import BenchStore

    definition = load(directory)
    policy = load_policy(DEFAULT_POLICY)
    rubrics = concepts.rubrics(policy)
    ledger = Ledger(directory / LEDGER, Caps({"scoring": SCORING_CAP_USD}, SCORING_CAP_USD))
    by_store: dict[str, set[str]] = {}
    for c in all_candidates(definition):
        by_store.setdefault(c.store, set()).add(c.write_id)
    out: dict[str, Any] = {"stores": {}}
    for name, path in stores_of(definition).items():
        with BenchStore(path) as store:
            built = [make_judge(f"{j}:{definition['judges'][j]}", store) for j in judges]
            try:
                summary = await score_store(
                    store,
                    policy,
                    built,
                    concurrency=4,
                    dry_run=dry_run,
                    ledger=ledger,
                    rubrics=rubrics,
                    write_ids=by_store.get(name, set()),
                )
            finally:
                for j in built:
                    aclose = getattr(j, "aclose", None)
                    if aclose is not None:
                        await aclose()
            out["stores"][name] = asdict(summary)
    out["ledger"] = ledger.summary()
    return out


def cmd_analyze(directory: Path) -> dict[str, Any]:
    definition = load(directory)
    if (directory / FINAL).exists():
        raise SystemExit("final-eval has run; the analyses before it are closed")
    revealed, calls = scoped_rows(directory, definition, "revealed")
    promotion, promo_calls = scoped_rows(directory, definition, "promotion")
    assert not any(r.synthetic for r in revealed + promotion)
    orderings = A.family_orderings({r.family for r in revealed}, A.ORDERINGS, ORDERING_SEED)
    log_, registry = A.promotion_run(A.stream(revealed, orderings[0]), promotion)
    champions = []
    for order in orderings:
        _, reg = A.promotion_run(A.stream(revealed, order), promotion)
        champions.append(
            {
                "promotions": len(reg.history) - 1,
                "final_champion": reg.champion.version,
                "promotion_set": A.outcomes(reg.champion, promotion).to_json(),
            }
        )
    fitted = {a: arms.fit_arm(a, revealed) for a in arms.PRIMARY_ARMS}
    actions = sorted({r.action for r in revealed})
    secondary = {
        "jev:D": arms.fit_arm("D", revealed, "jev"),
        "jev:DC": arms.fit_arm("DC", revealed, "jev"),
        "jev:G1": arms.fit_g1(revealed, "jev", arm="G1-jev", inputs=arms.g1_inputs),
        "G1+action_offsets": arms.fit_g1(
            revealed, arm="G1+offsets", inputs=arms.offsets_inputs(actions)
        ),
        "G1 two judges": arms.fit_g1(
            revealed, arm="G1-two-judges", inputs=arms.two_judge_inputs("jev")
        ),
    }
    result = {
        "definition_sha256": definition["definition_sha256"],
        "status": STATUS,
        "data": {
            "revealed": dataset_summary(revealed),
            "promotion": dataset_summary(promotion),
        },
        "learning_curve": A.learning_curve(revealed, orderings),
        "promotion": {
            "rule": "promote only if false allows on the promotion set are no more than the "
            "champion's, then only if fewer false allows or fewer escalations; v0 escalates "
            "everything",
            "log_ordering_0": [vars(v) for v in log_],
            "per_ordering": champions,
            "rollback_check": rollback_check(registry, promotion),
        },
        "adaptation": A.adaptation(revealed, orderings, ADAPT_CONCEPTS),
        "promotion_set_primary": {a: A.outcomes(f, promotion).to_json() for a, f in fitted.items()},
        "secondary_on_promotion_set": {
            k: {**A.outcomes(f, promotion).to_json(), "auc": A.auc(f, promotion)}
            for k, f in secondary.items()
        },
        "calls": call_summary({**calls, **promo_calls}),
    }
    path = directory / ANALYSIS
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def rollback_check(registry: A.Registry, rows: Sequence[arms.Row]) -> dict[str, Any]:
    """Rolling back restores the previous champion's decisions exactly."""
    if len(registry.history) < 2:
        return {"checked": False, "reason": "no promotion to roll back"}
    before = [registry.history[-2].decide(r) for r in rows]
    restored = registry.rollback()
    after = [restored.decide(r) for r in rows]
    return {"checked": True, "identical": before == after, "restored": restored.version}


def dataset_summary(rows: Sequence[arms.Row]) -> dict[str, Any]:
    by_action: dict[str, dict[str, int]] = {}
    for r in rows:
        e = by_action.setdefault(r.action, {"writes": 0, "ALLOW": 0, "ASK": 0, "DENY": 0})
        e["writes"] += 1
        if r.verdict in ("ALLOW", "ASK", "DENY"):
            e[r.verdict] += 1
        else:
            e.setdefault("UNKNOWN", 0)
            e["UNKNOWN"] += 1
    return {
        "writes": len(rows),
        "families": len({r.family for r in rows}),
        "labelled": sum(1 for r in rows if r.label is not None),
        "answered": {j: sum(1 for r in rows if j in r.concepts) for j in JUDGES},
        "by_action": dict(sorted(by_action.items())),
        "by_domain": {
            d: sum(1 for r in rows if r.domain == d) for d in sorted({r.domain for r in rows})
        },
    }


def call_summary(calls: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for judge in JUDGES:
        facts = [f[judge] for f in calls.values() if f.get(judge)]
        lat = sorted(f["latency_ms"] for f in facts if f.get("latency_ms") is not None)
        cost = [f["cost_usd"] for f in facts if f.get("cost_usd") is not None]
        out[judge] = {
            "writes": len(calls),
            "scored": len(facts),
            "ok": sum(1 for f in facts if f["status"] == "ok"),
            "cost_usd_total": sum(cost),
            "cost_usd_per_call": sum(cost) / len(cost) if cost else None,
            "latency_ms_p50": lat[len(lat) // 2] if lat else None,
            "latency_ms_p95": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
        }
    return out


def decision_records(
    fitted: Mapping[str, arms.FittedArm],
    rows: Sequence[arms.Row],
    definition: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Per write and arm: the concept vector, model version, recommendation, effective
    decision, override and policy version."""
    out = []
    for r in rows:
        vector = r.concepts.get(arms.PRIMARY_JUDGE)
        for name, arm in fitted.items():
            recommendation = arm.decide(r)
            out.append(
                {
                    "write_id": r.write_id,
                    "action": r.action,
                    "domain": r.domain,
                    "verdict": r.verdict,
                    "arm": name,
                    "model_version": arm.version,
                    "score": arm.score(r),
                    "threshold": arm.threshold,
                    "recommendation": recommendation,
                    # No hard rule exists for τ² (M8), so nothing overrides the arm.
                    "override": None,
                    "effective_decision": recommendation,
                    "policy_version": {
                        "policy_sha256": definition["policy_sha256"],
                        "oracle_version": definition["oracle_version"],
                    },
                    "concepts": None
                    if vector is None
                    else {
                        c: {
                            "applicable": a.applicable,
                            "assessment": a.assessment,
                            "confidence": a.confidence,
                            "evidence": a.evidence,
                        }
                        for c, a in vector.items()
                    },
                }
            )
    return out


def cmd_final_eval(directory: Path) -> dict[str, Any]:
    definition = load(directory)
    if (directory / FINAL).exists():
        raise SystemExit("final-eval has already run; it runs once")
    if not (directory / ANALYSIS).exists():
        raise SystemExit("run `analyze` first: the holdout is read last")
    revealed, _ = scoped_rows(directory, definition, "revealed")
    holdout, calls = scoped_rows(directory, definition, "holdout", final_eval=True)
    assert not any(r.synthetic for r in revealed + holdout)
    fitted = {a: arms.fit_arm(a, revealed) for a in arms.PRIMARY_ARMS}
    gates = A.safety_gates(fitted, holdout)
    result = {
        "definition_sha256": definition["definition_sha256"],
        "status": STATUS,
        "holdout": dataset_summary(holdout),
        "fitted": {
            a: {"version": f.version, "threshold": f.threshold, "trained_on": len(f.training_ids)}
            for a, f in fitted.items()
        },
        "overall": {a: A.outcomes(f, holdout).to_json() for a, f in fitted.items()},
        "auc": {a: A.auc(f, holdout) for a, f in fitted.items()},
        "by_action": {
            a: {k: o.to_json() for k, o in A.grouped(f, holdout, lambda r: r.action).items()}
            for a, f in fitted.items()
        },
        "by_domain": {
            a: {k: o.to_json() for k, o in A.grouped(f, holdout, lambda r: r.domain).items()}
            for a, f in fitted.items()
        },
        "safety_gates": gates,
        "autonomy_comparison": (
            {
                "ask_rate": {
                    a: A.outcomes(f, holdout).to_json()["ask_rate"] for a, f in fitted.items()
                },
                "approvals_saved": {
                    a: A.outcomes(f, holdout).to_json()["approvals_saved_rate"]
                    for a, f in fitted.items()
                },
            }
            if gates["passed"]
            else "withheld: the safety gates did not pass"
        ),
        "transfer": A.transfer(revealed, holdout),
        "bootstrap": A.bootstrap(
            fitted, holdout, [("DC", "D"), ("G1", "DC"), ("G1", "D")], BOOTSTRAP_SEED
        ),
        "calls": call_summary(calls),
        "records": decision_records(fitted, holdout, definition),
    }
    digest = write_once(directory / FINAL, result)
    (directory / "final.sha256").write_text(digest + "\n")
    return {"sha256": digest, "gates_passed": gates["passed"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command",
        choices=["freeze", "verdicts", "split", "score", "analyze", "final-eval", "report"],
    )
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--store", action="append", default=[], help="name=path (freeze)")
    parser.add_argument("--judge", action="append", choices=sorted(JUDGES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    if args.command == "freeze":
        stores = dict(s.split("=", 1) for s in args.store)
        if not stores:
            parser.error("freeze needs --store name=path")
        out: Any = freeze(args.dir, stores)
    elif args.command == "verdicts":
        out = cmd_verdicts(args.dir)
    elif args.command == "split":
        out = cmd_split(args.dir)
    elif args.command == "score":
        out = asyncio.run(cmd_score(args.dir, args.judge or ["openai_decisions"], args.dry_run))
    elif args.command == "analyze":
        cmd_analyze(args.dir)
        out = {"written": str(args.dir / ANALYSIS)}
    elif args.command == "final-eval":
        out = cmd_final_eval(args.dir)
    else:
        from hatchway.bench.pilot.report import build

        out = {"written": str(build(args.dir))}
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0
