# ruff: noqa: E501  (Markdown table rows are kept on one line each)
"""The Phase A report: compact Markdown from the manifest and the results files.

Every number comes from `results/phase-a.json`, `results/v2-side-check.json` or
`results/phase-b-dry-run.json`. `interpretation.md`, written after the results, adds the
plain-language reading verbatim; it cannot change a number or the outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT = "Policy Induction Phase A.md"
BANNER = (
    "Controlled benchmark built from τ²-bench retail data and its deterministic oracle. "
    "Demonstrates mechanism behavior only; does not establish real organizational performance."
)
KS = ("1", "2", "5", "10", "20")


def _k(v: Any) -> str:
    return "—" if v is None else f"{v}"


def _cell(by_k: dict[str, Any], k: str) -> str:
    v = by_k.get(k, {})
    if not v.get("available"):
        return "n/a"
    return f"{v['recovery_rate']:.2f} ({v['catch_mean']:.2f}/{v['false_invention_mean']:.3f})"


def _rule(world: dict[str, Any]) -> str:
    by_k = world["arms"]["S"]["clean"]["by_k"]
    for k in ("20", "10", "5"):
        v = by_k.get(k, {})
        if v.get("available"):
            rules = [r["rule"] for r in v["example_rules"]]
            return f"k={k}: " + ("; ".join(rules) if rules else "none")
    return "—"


def _counts(x: dict[str, Any]) -> str:
    return (
        f"{x['failing_families']}/{x['eligible_families']} · {x['false_allows']}/{x['should_escalate']} · "
        f"{x['over_escalations']}/{x['should_run']}"
    )


def _p3(x: dict[str, Any]) -> str:
    return f"{x['failing_families']}/{x['eligible_families']} · {x['over_escalations']}/{x['should_run']}"


def build(d: Path) -> Path:
    res = json.loads((d / "results/phase-a.json").read_text())
    manifest = json.loads((d / "cases-manifest.json").read_text())
    side = json.loads((d / "results/v2-side-check.json").read_text())
    dry = json.loads((d / "results/phase-b-dry-run.json").read_text())
    worlds = res["worlds"]
    lines = [
        "# Policy Induction, Phase A",
        "",
        f"> {BANNER}",
        "",
        "| | |",
        "|---|---|",
        "| **Status** | `diagnostic` |",
        f"| **Outcome** | `{res['outcome']}` |",
        "| **Question** | Can a learner recover an organization's rules, written or unwritten, from its decisions, while inventing none and staying safe? |",
        "| **Arms run** | R0 (starting policy), S and S-text (symbolic rule induction), ceiling (truth). The LLM arms are a dry run only |",
        "| **Spend** | $0.00; 0 external calls; 0 model calls |",
        f"| **Data** | {manifest['counts']['families']} families, {manifest['counts']['cases']} cases from τ² retail at `{manifest['tau2_commit'][:7]}`, labelled by the unchanged oracle (0 UNKNOWN) |",
        "",
        "Preregistration: [`RFC.md`](RFC.md). Evaluated once; [`results/phase-a.json`](results/phase-a.json).",
        "",
        "## Preregistered checks",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    c = res["checks"]
    sh = res["shuffled_any_rule_rate"]
    lines += [
        f"| A1 shuffled control (any accepted rule in ≤ 5% of shuffled runs) | {'pass' if c['A1_shuffled_control'] else '**fail**'} | S {sh['S']:.4f}, S-text {sh['S-text']:.4f} |",
        f"| A2 learnable (S k* ≤ 10 in ≥ 4 of 6 fact-expressible hidden worlds) | {'pass' if c['A2_learnable'] else '**fail**'} | {len(res['learnable_worlds'])} of 6: {', '.join(res['learnable_worlds'])} |",
        f"| A3 discriminating (S never recovers H5) | {'pass' if c['A3_discriminating'] else '**fail**'} | best S recovery rate on H5: {res['h5_best_recovery_rate_S']:.2f} |",
        "",
        "k* per hidden world (S, clean): "
        + ", ".join(f"{n} {_k(k)}" for n, k in res["k_star_S_clean"].items())
        + ".",
        "",
        "## Recovery by world (arm S, clean labels)",
        "",
        "Each cell: recovery rate over 20 replicates (mean catch / mean false invention). Recovered means catch ≥ 0.95 and false invention ≤ 0.01 on every test-family case. n/a: the training split has fewer triggering families than k.",
        "",
        "| World | Kind | Train triggering families | k=1 | k=2 | k=5 | k=10 | k=20 | k* | Rule learned (replicate 0) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for w in worlds:
        by_k = w["arms"]["S"]["clean"]["by_k"]
        lines.append(
            f"| {w['world']} | {w['kind']}{' (raw signal)' if w['raw_signal'] else ''} | {w['train_triggering_families']} | "
            + " | ".join(_cell(by_k, k) for k in KS)
            + f" | {_k(w['arms']['S']['clean']['k_star'])} | {_rule(w)} |"
        )
    lines += [
        "",
        "## Noise, selection and text (k* by condition)",
        "",
        "`selection` labels only what a live gate sees: every case the starting policy escalates, plus a 10% audit of the cases it allows. — means not recovered at any k ≤ 20.",
        "",
        "| World | S clean | S noise10 | S noise20 | S selection | S shuffled (any-rule rate, k=20) | S-text clean |",
        "|---|---|---|---|---|---|---|",
    ]
    for w in worlds:
        a = w["arms"]["S"]
        shuf = a["shuffled"]["by_k"].get("20", {})
        shuf_s = f"{shuf['any_rule_rate']:.2f}" if shuf.get("available") else "n/a"
        lines.append(
            f"| {w['world']} | {_k(a['clean']['k_star'])} | {_k(a['noise10']['k_star'])} | {_k(a['noise20']['k_star'])} | "
            f"{_k(a['selection']['k_star'])} | {shuf_s} | {_k(w['arms']['S-text']['clean']['k_star'])} |"
        )
    lines += [
        "",
        "## Safety against the starting policy (arm S, clean labels, mean over replicates)",
        "",
        "Failing families are families where any case the truth escalates was allowed (test split: 391 families).",
        "",
        "| World | R0 failing families · false allows · over-escalations | S k=5 | S k=10 | S k=20 |",
        "|---|---|---|---|---|",
    ]
    for w in worlds:
        b = w["baselines"]["R0"]
        by_k = w["arms"]["S"]["clean"]["by_k"]
        cells = []
        for k in ("5", "10", "20"):
            v = by_k.get(k, {})
            cells.append(
                "n/a"
                if not v.get("available")
                else f"{v['failing_families_mean']:.1f} · {v['false_allows_mean']:.1f} · {v['over_escalations_mean']:.1f}"
            )
        lines.append(
            f"| {w['world']} | {b['failing_families']}/{b['eligible_families']} · {b['false_allows']} · {b['over_escalations']} | "
            + " | ".join(cells)
            + " |"
        )
    lines += [
        "",
        "## Side check on the decision-record benchmark v2 (descriptive only)",
        "",
        "S started from DC-score at 1.0 and learned exceptions from v2's development records; evaluated on v2's already-used fresh holdout. Cells: failing families · false allows · over-escalations.",
        "",
        "| Slice | S (learned) | DC-score@1.0 (start) | v2 DC-score | v2 G-combined | v2 G-target |",
        "|---|---|---|---|---|---|",
    ]
    for s, row in side["slices"].items():
        lines.append(
            f"| {s} | "
            + " | ".join(
                _counts(row[m])
                for m in (
                    "S",
                    "DC-score@1.0 (start)",
                    "v2 DC-score",
                    "v2 G-combined",
                    "v2 G-target",
                )
            )
            + " |"
        )
    p3 = side["p3"]
    lines += [
        "",
        "Held-out profile P3, after k corrections (failing families · over-escalations): "
        + "; ".join(
            f"k={k}: S {_p3(p3[k]['S'])} ({len(p3[k]['rules'])} rules), v2 G-combined {_p3(p3[k]['v2 G-combined'])}, v2 G-target {_p3(p3[k]['v2 G-target'])}"
            for k in ("0", "5", "10", "25")
        )
        + ".",
    ]
    lines += ["", "Rules S learned:", ""]
    for p, rules in side["rules"].items():
        for r in rules:
            lines.append(f"- {p}: {r['rule']} (covers {r['covered']}, {r['positives']} positives)")
    lines += [
        "",
        "## Phase B dry run (0 model calls)",
        "",
        "Every Phase B prompt in the preregistered design was built and measured (4 characters per token).",
        "",
        "| Arm | Calls | Input tokens | Max output tokens |",
        "|---|---|---|---|",
    ]
    for arm, t in dry["totals"].items():
        lines.append(
            f"| {arm} | {t['calls']:,} | {t['input_tokens']:,} | {t['max_output_tokens']:,} |"
        )
    interp = d / "interpretation.md"
    if interp.exists():
        lines += ["", interp.read_text().strip()]
    lines += [
        "",
        "## Provenance",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Cases (`{manifest['generator']}`, seed {manifest['seed']}) | `{manifest['dataset_sha256']}` |",
        f"| τ² retail policy | `{manifest['retail_policy_sha256']}` |",
        f"| Parameters | background {res['parameters']['background']}, audit rate {res['parameters']['audit_rate']}, k {res['parameters']['k_grid']}, {res['parameters']['replicates']} replicates, alpha {res['parameters']['alpha']}, ≤ {res['parameters']['max_literals']} literals, ≤ {res['parameters']['max_rules']} rules per kind |",
        "",
        "Code hashes are in [`cases-manifest.json`](cases-manifest.json) and the results file.",
        "",
        "## Reproduction (zero spend)",
        "",
        "```bash",
        "python -m hatchway.bench.pi generate     # refuses: written once (regenerates identically with τ² data)",
        "python -m hatchway.bench.pi evaluate     # refuses: evaluated once",
        "python -m hatchway.bench.pi side-check",
        "python -m hatchway.bench.pi dry-run",
        "python -m hatchway.bench.pi report",
        "```",
    ]
    out = d / REPORT
    out.write_text("\n".join(lines) + "\n")
    return out
