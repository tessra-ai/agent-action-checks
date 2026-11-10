# ruff: noqa: E501  (Markdown table rows are kept on one line each)
"""The robustness report: compact Markdown from `robustness/manifest.json` and
`results/robustness.json`. `robustness-interpretation.md`, written after the results, is added
verbatim; it cannot change a number."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from hatchway.bench.pi import robust as R
from hatchway.bench.pi.report import BANNER

REPORT = "Policy Induction Robustness.md"


def _p(ok: bool) -> str:
    return "pass" if ok else "**fail**"


def _k(v: Any) -> str:
    return "—" if v is None else str(v)


def build(d: Path) -> Path:
    res = json.loads((d / R.RESULT_FILE).read_text())
    man = json.loads((d / R.MANIFEST).read_text())
    r1, r2, r3, r4, r5 = (res[k] for k in ("R1", "R2", "R3", "R4", "R5"))
    kinds = Counter(r["kind"] for r in man["rules"])
    lines = [
        "# Policy Induction: Robustness Pack",
        "",
        f"> {BANNER}",
        "",
        "| | |",
        "|---|---|",
        "| **Status** | `diagnostic` |",
        f"| **Results** | R1 replication {_p(r1['passed'])} · R3 targeted audits {_p(r3['passed'])} · R4 certified exceptions {_p(r4['passed'])} · R2 and R5 descriptive |",
        f"| **Data** | Fresh generator seed {man['seed']}: {man['families']} families, {man['cases']} cases; split {man['split']} |",
        f"| **Random rules** | {kinds['escalate']} escalation and {kinds['relax']} relaxation rules from the preregistered grammar (seed {man['rule_seed']}) |",
        "| **Spend** | $0.00; 0 external calls |",
        "",
        "Preregistration: [`RFC-robustness.md`](RFC-robustness.md). Phase A ([`RFC.md`](RFC.md)) is unchanged.",
        "",
        "## R1: Replication on a fresh seed",
        "",
        f"Frozen Phase A sweep on the fresh cases: outcome there `{r1['fresh_outcome']}`; checks {r1['fresh_checks']['checks']}. Worlds within one k step of Phase A: {sum(r1['within_one_step'].values())} of 13 (bar 11).",
        "",
        "| World | k* Phase A | k* fresh seed | Within one step |",
        "|---|---|---|---|",
    ]
    for n, ok in r1["within_one_step"].items():
        lines.append(
            f"| {n} | {_k(r1['k_star_phase_a'][n])} | {_k(r1['k_star_fresh'][n])} | {'yes' if ok else '**no**'} |"
        )
    lines += [
        "",
        f"Fresh-seed learnable worlds (A2): {', '.join(r1['fresh_checks']['learnable_worlds'])}.",
        "",
        "## R2: Randomly drawn rules (arm S, clean labels)",
        "",
        "Share of rules recovered (recovery rate ≥ 0.8 across 10 replicates) within k examples.",
        "",
        "| Rule type | Rules | k* ≤ 5 | k* ≤ 10 | k* ≤ 20 |",
        "|---|---|---|---|---|",
    ]
    tot = {"rules": 0, "k5": 0, "k10": 0, "k20": 0}
    for t, v in sorted(r2["by_type"].items()):
        lines.append(f"| {t} | {v['rules']} | {v['k5']} | {v['k10']} | {v['k20']} |")
        for key in tot:
            tot[key] += v[key]
    lines.append(f"| **All** | {tot['rules']} | {tot['k5']} | {tot['k10']} | {tot['k20']} |")
    buckets: dict[str, list[int]] = {}
    for v in r2["rules"].values():
        share = v["trigger_share"]
        b = (
            "≤ 2%"
            if share <= 0.02
            else "2-5%"
            if share <= 0.05
            else "5-10%"
            if share <= 0.10
            else "> 10%"
        )
        buckets.setdefault(b, [0, 0])
        buckets[b][0] += 1
        buckets[b][1] += v["k_star"] is not None and v["k_star"] <= 10
    lines += [
        "",
        "By how often the rule fires (share of in-scope cases it changes):",
        "",
        "| Fires on | Rules | Recovered within 10 |",
        "|---|---|---|",
        *(f"| {b} | {n} | {r} |" for b, (n, r) in buckets.items()),
        "",
        "## R3: Pricing audits",
        "",
        f"Cells (rule, k) where some audit rate reached recovery: {r3['cells_reached']}; targeted needed at most half of random's rate in {r3['cells_targeted_at_most_half']} (bar: half of the cells). Targeted-shuffled control any-rule rate: {r3['targeted_shuffled_any_rule_rate']:.3f} (bar 0.05).",
        "",
        "Needed audit rate (smallest with recovery ≥ 0.8; — none up to 100%):",
        "",
        "| World | Train triggering families | k=10 random / targeted | k=20 random / targeted | k=40 random / targeted |",
        "|---|---|---|---|---|",
    ]
    for n, w in r3["worlds"].items():
        if w.get("available") is False:
            continue
        cells = [
            f"{_k(w[str(k)]['random']['needed_rate'])} / {_k(w[str(k)]['targeted']['needed_rate'])}"
            for k in R.R3_K
        ]
        lines.append(f"| {n} | {w['train_families']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## R4: Specific, certified exceptions",
        "",
        f"Pooled out-of-sample failure rate among test families where an exception allowed a case: S {r4['pooled_failure_rate']['S']:.3f} ({r4['pooled_fired']['S'][1]}/{r4['pooled_fired']['S'][0]}), S-cert {r4['pooled_failure_rate']['S-cert']:.3f} ({r4['pooled_fired']['S-cert'][1]}/{r4['pooled_fired']['S-cert'][0]}). Bar: S-cert ≤ 0.10 and S > 0.10.",
        "",
        "| World | k | S catch · failing families | S-cert catch · failing families | Exceptions certified |",
        "|---|---|---|---|---|",
    ]
    for n, w in r4["worlds"].items():
        for k, row in w["by_k"].items():
            if not row.get("available"):
                continue
            s, c = row["S"], row["S-cert"]
            lines.append(
                f"| {n} | {k} | {s['catch_mean']:.2f} · {s['failing_families_mean']:.1f} | {c['catch_mean']:.2f} · {c['failing_families_mean']:.1f} | {row['certified_share']:.2f} |"
            )
    v2 = r4["v2"]
    o = v2["slices"]["overall"]
    lines += [
        "",
        f"v2 side check with S-cert (descriptive): overall {o['failing_families']}/{o['eligible_families']} failing families, {o['false_allows']}/{o['should_escalate']} false allows, {o['over_escalations']}/{o['should_run']} over-escalations (uncertified S in Phase A: 49/96 failing, 0/255 over-escalations; DC-score 0/96, 149/255).",
        "",
    ]
    for prof, log in v2["certification"].items():
        for c in log:
            lines.append(
                f"- {prof}: {c['rule']}: certified {c['certified']} ({c['failing_families']}/{c['eligible_families']} failing calibration families, UCB {c['ucb']:.3f})"
            )
    lines += [
        "",
        "## R5: Imperfect perception (arm S, clean labels, k = 10)",
        "",
        "Mean catch / mean false invention on the test split at each fact-error rate.",
        "",
        "| World | " + " | ".join(f"e = {e}" for e in R.R5_RATES) + " |",
        "|---|" + "---|" * len(R.R5_RATES),
    ]
    for n, w in r5["worlds"].items():
        cells = []
        for e in R.R5_RATES:
            v = w[str(e)]["by_k"].get("10", {})
            cells.append(
                "n/a"
                if not v.get("available")
                else f"{v['catch_mean']:.2f} / {v['false_invention_mean']:.3f}"
            )
        lines.append(f"| {n} | " + " | ".join(cells) + " |")
    interp = d / "robustness-interpretation.md"
    if interp.exists():
        lines += ["", interp.read_text().strip()]
    lines += [
        "",
        "## Provenance and reproduction",
        "",
        f"Cases `{man['dataset_sha256']}`; code hashes in [`robustness/manifest.json`](robustness/manifest.json). Full results: [`results/robustness.json`](results/robustness.json).",
        "",
        "```bash",
        "python -m hatchway.bench.pi.robust generate   # refuses: written once",
        "python -m hatchway.bench.pi.robust evaluate   # refuses: evaluated once",
        "python -m hatchway.bench.pi.robust report",
        "```",
    ]
    out = d / REPORT
    out.write_text("\n".join(lines) + "\n")
    return out
