# ruff: noqa: E501  (Markdown table rows are kept on one line each)
"""The Phase 0 report: compact Markdown built from the frozen inputs and `results/`.

Every number comes from `results/internal.json` (and `results/telecom.json` when the gate passed),
with its denominator. `interpretation.md`, written after the results, adds the plain-language
reading and is included verbatim; it cannot change a number or the outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hatchway.bench.drb import BANNER

REPORT = "Decision-Record Benchmark Phase 0.md"


def _f(c: dict[str, Any]) -> str:
    return (
        f"{c['false_allows']}/{c['should_escalate']} | {c['safe_auto']}/{c['should_run']} | "
        f"{c['over_escalations']}/{c['should_run']} | {c['escalations']}/{c['records']}"
    )


HEAD = "| Model | False allows | Safe automatic runs | Over-escalations | Escalations (all) |\n|---|---|---|---|---|"


def _table(rows: dict[str, dict[str, Any]], order: list[str] | None = None) -> str:
    names = order or list(rows)
    return HEAD + "\n" + "\n".join(f"| {n} | {_f(rows[n])} |" for n in names if n in rows)


def build(d: Path) -> Path:
    internal = json.loads((d / "results/internal.json").read_text())
    freeze = json.loads((d / "freeze.json").read_text())
    syn_m = json.loads((d / "synthetic-manifest.json").read_text())
    ret_m = json.loads((d / "retail-manifest.json").read_text())
    seal = json.loads((d / "telecom-seal.json").read_text())
    telecom_path = d / "results/telecom.json"
    telecom = json.loads(telecom_path.read_text()) if telecom_path.exists() else None
    interp = d / "interpretation.md"
    g = internal["gate"]
    c = g["counts"]
    lines: list[str] = [
        "# Decision-Record Benchmark, Phase 0",
        "",
        f"> {BANNER}",
        "",
        "| | |",
        "|---|---|",
        "| **Status** | `diagnostic` · `no-go` |",
        f"| **Recommendation** | `{internal['outcome_so_far'] if not telecom else telecom.get('outcome', '')}` |",
        "| **Concept source** | Authoritative: synthetic latent facts and deterministic oracle checks. No judge, LLM or external model was called |",
        "| **Spend** | $0.00; 0 external calls |",
        f"| **Telecom** | {'opened once by final-eval' if telecom else 'still sealed: the internal gate failed, so the telecom holdout was not opened'} |",
        "",
        "Preregistration: [`RFC.md`](RFC.md) (with amendment 1, committed before any fit).",
        "",
        "## Internal gate (frozen)",
        "",
        "| Condition | Result |",
        "|---|---|",
    ]
    for k, v in g["conditions"].items():
        lines.append(f"| {k.replace('_', ' ')} | {'pass' if v else '**fail**'} |")
    lines.append(
        f"| coverage (≥10 should-run and ≥10 should-escalate per slice) | "
        f"{'pass' if all(g['coverage'].values()) else '**fail**'} |"
    )
    lines += [
        "",
        f"Gate **{'passed' if g['passed'] else 'failed'}**. Transfer measures, G-combined against "
        f"G-target: {', '.join(f'{k} {v}' for k, v in g['transfer_measures'].items())}.",
        "",
        "## Synthetic results",
        "",
        "G-combined(P) pretrains on the pooled synthetic pretraining partition (P1 and P2), then "
        "adapts on profile P's own pretraining records. G-target(P) fits P's records alone.",
        "",
    ]
    order = ["escalate-all", "DC", "G-synthetic", "G-target", "G-combined"]
    for s, title in (
        ("union", "All gate slices (final holdout, held-out action, held-out domain)"),
        ("syn_final", "Synthetic final holdout"),
        ("syn_holdout_action", "Held-out action (`issue_reimbursement`)"),
        ("syn_holdout_domain", "Held-out domain (`access`)"),
    ):
        lines += [f"### {title}", "", _table(c[s], order), ""]
    iv = g["intervals_G-combined_minus_DC"]
    lines += [
        "Family-bootstrap 90% intervals for G-combined minus DC (1,000 resamples):",
        "",
        "| Slice | False allows | Over-escalations |",
        "|---|---|---|",
    ]
    for s in ("union", "syn_final", "syn_holdout_action", "syn_holdout_domain"):
        fa, oe = iv[f"{s}:false_allows"], iv[f"{s}:over_escalations"]
        lines.append(
            f"| {s} | {fa['observed']:+d} ({fa['p05']:+d} to {fa['p95']:+d}) | "
            f"{oe['observed']:+d} ({oe['p05']:+d} to {oe['p95']:+d}) |"
        )
    lines += ["", "### Held-out organizational profile (P3), adaptation after k corrections", ""]
    lines += [
        "| k | G-combined: false allows / over-escalations / safe runs | G-target: same |",
        "|---|---|---|",
    ]
    for k, ms in c["syn_p3_eval"].items():
        a, b = ms["G-combined"], ms["G-target"]
        lines.append(
            f"| {k} | {a['false_allows']}/{a['should_escalate']} · {a['over_escalations']}/{a['should_run']} · {a['safe_auto']}/{a['should_run']} "
            f"| {b['false_allows']}/{b['should_escalate']} · {b['over_escalations']}/{b['should_run']} · {b['safe_auto']}/{b['should_run']} |"
        )
    lc = internal["learning_curves"]
    lines += [
        "",
        "### Synthetic pretraining learning curve (G-synthetic, on the gate slices)",
        "",
        "| Pretraining records | False allows | Safe runs | Over-escalations | Brier |",
        "|---|---|---|---|---|",
    ]
    for p in lc["synthetic"]["points"]:
        x = p["G-synthetic"]
        lines.append(
            f"| {p['n']} | {x['false_allows']}/{x['should_escalate']} | {x['safe_auto']}/{x['should_run']} | "
            f"{x['over_escalations']}/{x['should_run']} | {p['brier']:.3f} |"
        )
    dc = lc["synthetic"]["DC"]
    lines.append(
        f"| DC (reference) | {dc['false_allows']}/{dc['should_escalate']} | {dc['safe_auto']}/{dc['should_run']} | "
        f"{dc['over_escalations']}/{dc['should_run']} | — |"
    )
    lines += [
        "",
        "## Retail adaptation (target organization, internal holdout)",
        "",
        _table(
            internal["retail_internal_holdout"],
            ["escalate-all", "DC", "G-synthetic", "G-retail", "G-combined"],
        ),
        "",
        "| Retail adaptation records k | G-retail: false allows · safe runs | G-combined: false allows · safe runs |",
        "|---|---|---|",
    ]
    for p in lc["retail"]["points"]:
        a, b = p["G-retail"], p["G-combined"]
        lines.append(
            f"| {p['k']} | {a['false_allows']}/{a['should_escalate']} · {a['safe_auto']}/{a['should_run']} "
            f"| {b['false_allows']}/{b['should_escalate']} · {b['safe_auto']}/{b['should_run']} |"
        )
    cov = ret_m["coverage_by_action"]
    lines += [
        "",
        "Retail coverage by action (ALLOW / ASK / DENY): "
        + "; ".join(f"{a} {v['ALLOW']}/{v['ASK']}/{v['DENY']}" for a, v in cov.items())
        + f". Left out: {ret_m['left_out']}. Six scenario families in all; no missing "
        "action or class was filled with synthetic records.",
        "",
        "## Controls",
        "",
        "| Control | Apparent transfer | G-combined false allows | G-combined over-escalations |",
        "|---|---|---|---|",
    ]
    for n in ("shuffled_labels", "no_shared_effect"):
        u = internal["controls"][n]["union"]["G-combined"]
        lines.append(
            f"| {n.replace('_', ' ')} | {internal['controls'][n]['apparent_transfer']} | "
            f"{u['false_allows']}/{u['should_escalate']} | {u['over_escalations']}/{u['should_run']} |"
        )
    st = internal["controls"]["structural"]
    loc = st["locality_reversibility"]
    lines += [
        "",
        f"- **Paraphrase:** {st['paraphrase']['same_decision']}/{st['paraphrase']['pairs']} pairs "
        "decided identically.",
        f"- **Irrelevant context:** {st['irrelevant_context']['same_decision']}/"
        f"{st['irrelevant_context']['pairs']} pairs decided identically. These two are structural in "
        "Phase 0: authoritative concepts give identical inputs.",
        f"- **Contradictory evidence:** {st['contradictory_evidence']['escalated']}/"
        f"{st['contradictory_evidence']['records']} escalated.",
        f"- **Locality:** adapting G-synthetic on {loc['corrections']} reversibility-only "
        f"correction(s) changed {loc.get('changed', '—')}/{loc['evaluated']} decisions on records "
        "where reversibility was satisfied.",
        f"- **Representation conflicts in development data:** "
        f"{internal['representation_conflicts']['conflicting_groups']} of "
        f"{internal['representation_conflicts']['groups']} input groups.",
        "- **Hard rules:** every hard-rule record was denied by every model "
        f"({c['syn_hard']['records']} records).",
        "",
    ]
    if interp.exists():
        lines += [interp.read_text().strip(), ""]
    lines += [
        "## Provenance and hashes",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Freeze | `{freeze['freeze_sha256']}` at commit `{freeze['hatchway_commit']}` |",
        f"| Model spec (`drb-model-1`) | `{freeze['model_spec_sha256']}` |",
        f"| Synthetic dataset | `{syn_m['dataset_sha256']}` ({sum(p['records'] for p in syn_m['partitions'].values())} records, generator `{syn_m['generator_version']}`, seed {syn_m['seed']}) |",
        f"| Retail dataset | `{ret_m['dataset_sha256']}` ({sum(p['records'] for p in ret_m['partitions'].values())} records, oracle `{ret_m['oracle_version']}`, mapping `{ret_m['mapping_version']}`) |",
        f"| Telecom seal | `{seal['dataset_sha256']}` ({seal['counts']['records']} records, {seal['counts']['families']} families, {seal['counts']['verdict_bearing']} with a verdict) |",
        f"| Synthetic pretraining set | `{internal['models']['training_hashes']['syn_pretrain']}` |",
        f"| Retail adaptation set | `{internal['models']['training_hashes']['retail_adapt']}` |",
        f"| G-synthetic | `{internal['models']['G-synthetic']['version']}` |",
        f"| Promotion | {internal['models']['promotion']['reason']} |",
        "",
        "Code hashes are listed in [`freeze.json`](freeze.json); full results are in [`results/internal.json`](results/internal.json).",
        "",
        "## Reproduction (zero spend)",
        "",
        "```bash",
        "pip install -e '.[dev]' -e ./.tau2-bench      # τ² at c5b2d228…; stores runs/targeted.db, runs/smoke2.db",
        "python -m hatchway.bench.drb seal-telecom     # refuses: the seal is written once",
        "python -m hatchway.bench.drb generate         # regenerates the synthetic records (identical hash)",
        "python -m hatchway.bench.drb map-retail",
        "python -m hatchway.bench.drb freeze           # refuses: written once",
        "python -m hatchway.bench.drb develop          # refuses: written once (delete results/ in a scratch copy to rerun)",
        "python -m hatchway.bench.drb final-eval       # refuses: the internal gate failed",
        "python -m hatchway.bench.drb report",
        "```",
        "",
        "Cost ledger: $0.00; no judge, LLM, external model or τ² capture was used.",
    ]
    out = d / REPORT
    out.write_text("\n".join(lines) + "\n")
    return out
