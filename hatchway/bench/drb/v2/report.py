# ruff: noqa: E501  (Markdown table rows are kept on one line each)
"""The v2 report: compact Markdown from the frozen inputs and `results/v2.json`.

Every count comes from the results file with its record and family denominators.
`interpretation.md`, written after the results, adds the plain-language reading verbatim; it
cannot change a number or the outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hatchway.bench.drb import BANNER

REPORT = "Decision-Record Benchmark v2.md"
MODELS = ("DC-score", "G-synthetic", "G-target", "G-combined")


def _row(name: str, x: dict[str, Any]) -> str:
    return (
        f"| {name} | {x['failing_families']}/{x['eligible_families']} (UCB {x['family_ucb']:.3f}) "
        f"| {x['false_allows']}/{x['should_escalate']} | {x['safe_auto']}/{x['should_run']} "
        f"| {x['over_escalations']}/{x['should_run']} |"
    )


HEAD = (
    "| Model | Failing families (certified unit) | False allows (records) | Safe automatic runs | Over-escalations |\n"
    "|---|---|---|---|---|"
)


def _thr(v: Any) -> str:
    return "escalate all" if v is None else f"{v:g}"


def build(d: Path) -> Path:
    res = json.loads((d / "results/v2.json").read_text())
    freeze = json.loads((d / "freeze.json").read_text())
    fresh = json.loads((d / "fresh-manifest.json").read_text())
    cal = json.loads((d / "calibration-manifest.json").read_text())
    g = res["gate"]
    c = g["counts"]
    m = res["models"]
    lines = [
        "# Decision-Record Benchmark v2",
        "",
        f"> {BANNER}",
        "",
        "| | |",
        "|---|---|",
        "| **Status** | `diagnostic` · `no-go` |",
        f"| **Outcome** | `{res['outcome']}` |",
        "| **What changed from v1** | The decision procedure only: family-level certified thresholds, matched safety, bounded local adaptation. Concepts, generator, answer key and seal are unchanged |",
        "| **Concept source** | Authoritative (synthetic latent facts). No judge, LLM or external model was called |",
        "| **Spend** | $0.00; 0 external calls |",
        "| **Telecom** | Still sealed and never opened |",
        "",
        "Preregistration: [`RFC-v2.md`](RFC-v2.md), including amendment 1, which records the development run before the freeze.",
        "",
        "## Gate (frozen; evaluated once on the fresh holdout)",
        "",
        "| Condition | Result |",
        "|---|---|",
    ]
    order = sorted(g["conditions"], key=lambda k: int(k.split("_")[0][1:]))
    for k in order:
        lines.append(f"| {k.replace('_', ' ')} | {'pass' if g['conditions'][k] else '**fail**'} |")
    lines += [
        "",
        "Transfer measures, G-combined against G-target: "
        + ", ".join(f"{k} {v}" for k, v in g["transfer_measures"].items())
        + ".",
        "",
        "## Matched safety on the fresh holdout",
        "",
        "Every model's threshold was chosen by cross-fitting and certified on untouched calibration families (one-sided 95% Clopper-Pearson UCB at most 0.10 on family risk). A record of profile P is decided by that profile's model.",
        "",
    ]
    for s, title in (
        ("overall", "Overall (final, held-out action and held-out domain)"),
        ("fresh_final", "Fresh final (in-distribution)"),
        ("fresh_action", "Held-out action (`issue_reimbursement`)"),
        ("fresh_domain", "Held-out domain (`access`)"),
    ):
        lines += [f"### {title}", "", HEAD, *(_row(n, c[s][n]) for n in MODELS), ""]
    iv = res["intervals_G-combined_minus_DC-score"]
    lines += [
        "Family-bootstrap 90% intervals, G-combined minus DC-score:",
        "",
        "| Slice | Failing families | Over-escalations |",
        "|---|---|---|",
    ]
    for s in ("overall", "fresh_final", "fresh_action", "fresh_domain"):
        a, b = iv[f"{s}:failing_families"], iv[f"{s}:over_escalations"]
        lines.append(
            f"| {s} | {a['observed']:+d} ({a['p05']:+d} to {a['p95']:+d}) | {b['observed']:+d} ({b['p05']:+d} to {b['p95']:+d}) |"
        )
    lines += [
        "",
        "## Thresholds and certificates",
        "",
        "| Model | Threshold | Certificate |",
        "|---|---|---|",
        f"| G-synthetic | {_thr(m['G-synthetic']['threshold'])} | {m['G-synthetic'].get('certificate')} |",
    ]
    for k, v in m["DC-score"].items():
        lines.append(f"| DC-score({k}) | {_thr(v['threshold'])} | {v.get('certificate')} |")
    for k, v in m["G-target"].items():
        lines.append(f"| G-target({k}) | {_thr(v['threshold'])} | {v.get('certificate')} |")
    for k, v in m["G-target(P3)"].items():
        lines.append(f"| G-target(P3, k={k}) | {_thr(v['threshold'])} | {v.get('certificate')} |")
    lines += [
        "",
        "## Adaptation",
        "",
        "| Organization | Looks | Promoted | Promotion-pool over-escalations: champion / challenger |",
        "|---|---|---|---|",
    ]
    for k, v in m["G-combined"].items():
        looks = v["looks"]
        lines.append(
            f"| {k} | {len(looks)} | {sum(lk['promoted'] for lk in looks)} | "
            + ", ".join(
                f"{lk['champion_pool']['over_escalations']}/{lk['challenger_pool']['over_escalations']}"
                for lk in looks
            )
            + " |"
        )
    p3l = m["G-combined(P3)"]["looks"]
    lines.append(
        f"| P3 (held out) | {len(p3l)} | {sum(lk['promoted'] for lk in p3l)} | "
        + ", ".join(
            f"{lk['champion_pool']['over_escalations']}/{lk['challenger_pool']['over_escalations']}"
            for lk in p3l
        )
        + " |"
    )
    lines += [
        "",
        "Certification holds per promotion look, with no multiplicity correction (at most 5 looks per organization, 3 for P3).",
        "",
        "### Held-out profile (P3) evaluation set, after k corrections",
        "",
        "| k | G-combined: failing families · over-escalations · safe runs | G-target: same |",
        "|---|---|---|",
    ]
    for k, v in g["p3"].items():
        a, b = v["G-combined"], v["G-target"]
        lines.append(
            f"| {k} | {a['failing_families']}/{a['eligible_families']} · {a['over_escalations']}/{a['should_run']} · {a['safe_auto']}/{a['should_run']} "
            f"| {b['failing_families']}/{b['eligible_families']} · {b['over_escalations']}/{b['should_run']} · {b['safe_auto']}/{b['should_run']} |"
        )
    loc = g["locality"]
    lines += [
        "",
        f"Locality (V10): {loc['flips']} flips in {loc['checked_decisions']} checked decisions. No update was accepted, so the check is vacuous; the unit tests prove the property by construction.",
        "",
        "## Operating curves on the fresh holdout (descriptive only)",
        "",
        "Failing families and over-escalations at each grid threshold, overall.",
        "",
        "| Threshold | " + " | ".join(MODELS) + " |",
        "|---|" + "---|" * len(MODELS),
    ]
    curves = {n: {p["threshold"]: p for p in res["operating_curves"][n]} for n in MODELS}
    for t in sorted({t for n in MODELS for t in curves[n]}, reverse=True):
        cells = []
        for n in MODELS:
            p = curves[n].get(t)
            cells.append("—" if p is None else f"{p['failing_families']} · {p['over_escalations']}")
        lines.append(f"| {t:g} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Synthetic pretraining learning curve (G-synthetic, overall)",
        "",
        "| Pretraining records | Threshold | Certificate | Failing families | Over-escalations |",
        "|---|---|---|---|---|",
    ]
    for p in res["learning_curve"]:
        x = p["counts"]
        lines.append(
            f"| {p['n']} | {_thr(p['threshold'])} | {p['certificate']} | {x['failing_families']}/{x['eligible_families']} | {x['over_escalations']}/{x['should_run']} |"
        )
    r = res["retail"]
    lines += [
        "",
        "## Retail (development-grade, not a gate condition)",
        "",
        f"Six families, all opened in v1, so no certification is possible. Leave-one-family-out rotation verdict: **{r['verdict']}** (G-combined worse in {r['worse_folds']} of 6 folds, favorable in {r['favorable_folds']}).",
        "",
        "| Model (pooled over 6 folds) | False allows | Safe automatic runs |",
        "|---|---|---|",
    ]
    for k, v in r["pooled"].items():
        lines.append(
            f"| {k} | {v['false_allows']}/{v['should_escalate']} | {v['safe_auto']}/{v['should_run']} |"
        )
    lines += [
        "",
        "This is not reliable statistical evidence.",
        "",
        "## Negative controls (V9)",
        "",
        "| Control | Apparent transfer | G-combined failing families / over-escalations |",
        "|---|---|---|",
    ]
    for k, v in res["controls"].items():
        x = v["overall"]["G-combined"]
        lines.append(
            f"| {k.replace('_', ' ')} | {v['apparent_transfer']} | {x['failing_families']}/{x['eligible_families']} · {x['over_escalations']}/{x['should_run']} |"
        )
    interp = d / "interpretation.md"
    if interp.exists():
        lines += ["", interp.read_text().strip()]
    lines += [
        "",
        "## Provenance and hashes",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Freeze | `{freeze['freeze_sha256']}` at commit `{freeze['hatchway_commit']}` |",
        f"| Development pool (v1 P1/P2 in-distribution) | `{freeze['development_pool_sha256']}` |",
        f"| Calibration pools (seed {cal['seed']}) | `{cal['dataset_sha256']}`: "
        + ", ".join(
            f"{k} {v['eligible_families']} eligible families" for k, v in cal["pools"].items()
        )
        + " |",
        f"| Fresh holdout (seed {fresh['seed']}, from the freeze) | `{fresh['dataset_sha256']}`: "
        + ", ".join(f"{k} {v['families']} families" for k, v in fresh["pools"].items())
        + " |",
        f"| Telecom seal (unopened) | `{freeze['telecom_seal_sha256']}` |",
        f"| Fresh manifest | `{res['fresh_manifest_sha256']}` |",
        "",
        "Code hashes are in [`freeze.json`](freeze.json). Full results: [`results/v2.json`](results/v2.json). Development run: [`results/development.json`](results/development.json).",
        "",
        "## Reproduction (zero spend)",
        "",
        "```bash",
        "python -m hatchway.bench.drb.v2 calibrate        # refuses: written once (regenerates identically from seed 20261024)",
        "python -m hatchway.bench.drb.v2 develop          # development evidence on v1 stand-ins",
        "python -m hatchway.bench.drb.v2 freeze           # refuses: written once",
        "python -m hatchway.bench.drb.v2 generate-fresh   # refuses: written once (seed from the freeze hash)",
        "python -m hatchway.bench.drb.v2 evaluate         # refuses: evaluated once",
        "python -m hatchway.bench.drb.v2 report",
        "```",
        "",
        "Cost ledger: $0.00. No judge, LLM, external model or τ² capture was used.",
    ]
    out = d / REPORT
    out.write_text("\n".join(lines) + "\n")
    return out
