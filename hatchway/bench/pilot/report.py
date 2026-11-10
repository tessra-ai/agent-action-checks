"""The pilot report: one HTML page from `analysis.json` and `final.json`.

Every rate is printed with its numerator and denominator. Groups below the coverage rule say
"insufficient: inconclusive". The autonomy comparison (ask rates, approvals saved) appears only
when the safety gates passed. An optional `recommendation.json` ({"decision", "reasons"}) is the
Phase 2 go/no-go written after reading the results; the page shows it last, as a judgement.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ARM_NAMES = {
    "D": "D: fixed baseline (policy_ok + matches_request)",
    "DC": "DC: fixed rule on shared concepts",
    "G1": "G1: learned model on shared concepts",
}
CONCEPT_NAMES = {
    "consent_obtained": "consent obtained",
    "terms_disclosed": "material terms disclosed",
    "ownership_authority": "ownership / authority",
    "prerequisites_satisfied": "prerequisites satisfied",
    "action_requested": "action requested",
}

CSS = """
:root { --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a64; --line:#e3e0d8; --card:#ffffff;
  --accent:#2a5bd7; --warn:#a15c00; --bad:#b3261e; --good:#1f7a3a; --chip:#f1efe8; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#171716; --fg:#ecebe6; --muted:#a3a29b; --line:#34332f; --card:#1f1f1d;
  --accent:#8fb0ff; --warn:#e7a54a; --bad:#ff8a80; --good:#7bd88f; --chip:#2a2a27;
  color-scheme:dark; } }
:root[data-theme="dark"] { --bg:#171716; --fg:#ecebe6; --muted:#a3a29b; --line:#34332f;
  --card:#1f1f1d; --accent:#8fb0ff; --warn:#e7a54a; --bad:#ff8a80; --good:#7bd88f;
  --chip:#2a2a27; color-scheme:dark; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system, "Segoe UI", Inter, system-ui, sans-serif; }
main { max-width:1040px; margin:0 auto; padding-block:24px 64px;
  padding-left:max(16px, env(safe-area-inset-left, 0px));
  padding-right:max(16px, env(safe-area-inset-right, 0px)); }
h1 { font-size:26px; margin:8px 0 4px; } h2 { font-size:19px; margin:36px 0 8px; }
h3 { font-size:15px; margin:20px 0 6px; }
p, li { max-width:72ch; } .muted { color:var(--muted); }
.banner { border:1px solid var(--warn); color:var(--warn); border-radius:8px; padding:10px 14px;
  margin:12px 0 20px; font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 14px; }
.card .k { color:var(--muted); font-size:13px; } .card .v { font-size:20px; font-weight:650; }
.scroll { overflow-x:auto; margin:8px 0; }
table { border-collapse:collapse; width:100%; font-size:13.5px; background:var(--card); }
th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left;
  vertical-align:top; }
th { font-weight:600; color:var(--muted); white-space:nowrap; }
td.num { font-variant-numeric:tabular-nums; white-space:nowrap; }
.chip { display:inline-block; padding:1px 8px; border-radius:99px; background:var(--chip);
  font-size:12px; } .pass { color:var(--good); } .fail { color:var(--bad); }
.inc { color:var(--warn); }
code { font-size:12.5px; background:var(--chip); padding:1px 4px; border-radius:4px; }
details { margin:8px 0; } summary { cursor:pointer; color:var(--accent); }
"""


def esc(v: Any) -> str:
    return html.escape(str(v))


def frac(r: Mapping[str, Any] | None) -> str:
    if not r:
        return "—"
    if r.get("rate") is None:
        return f"{r['n']}/{r['of']} (no denominator)"
    return f"{r['n']}/{r['of']} ({100 * r['rate']:.0f}%)"


def num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return esc(v)


def table(head: Sequence[str], rows: Sequence[Sequence[Any]], numeric_from: int = 1) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = []
    for row in rows:
        cells = []
        for i, c in enumerate(row):
            cls = " class='num'" if i >= numeric_from else ""
            cells.append(f"<td{cls}>{c}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='scroll'><table><tr>{th}</tr>{''.join(body)}</table></div>"


def gate_chip(g: str) -> str:
    cls = {"pass": "pass", "fail": "fail"}.get(g, "inc")
    return f"<span class='chip {cls}'>{esc(g)}</span>"


def spread(s: Mapping[str, Any] | None) -> str:
    if not s:
        return "—"
    return f"{s['median']:g} [{s['p10']:g}&ndash;{s['p90']:g}]"


def interval(d: Mapping[str, Any] | None, pct: bool = True) -> str:
    if not d:
        return "—"
    f = (lambda x: f"{100 * x:+.0f} pts") if pct else (lambda x: f"{x:+.2f}")
    return f"{f(d['median'])} (90%: {f(d['p05'])} to {f(d['p95'])})"


def outcome_rows(results: Mapping[str, Mapping[str, Any]], arms: Sequence[str]) -> list[list[str]]:
    return [
        [
            esc(ARM_NAMES.get(a, a)),
            frac(results[a]["false_allow_rate"]),
            frac(results[a]["ask_rate"]),
            frac(results[a]["approvals_saved_rate"]),
        ]
        for a in arms
        if a in results
    ]


OUTCOME_HEAD = [
    "Arm",
    "False allows (of should-escalate)",
    "Asks (of all)",
    "Approvals saved (of should-run)",
]


def dataset_section(analysis: Mapping[str, Any], final: Mapping[str, Any] | None) -> str:
    sets = {"revealed": analysis["data"]["revealed"], "promotion": analysis["data"]["promotion"]}
    if final:
        sets["holdout"] = final["holdout"]
    actions = sorted({a for s in sets.values() for a in s["by_action"]})
    rows = []
    for a in actions:
        cells = [esc(a)]
        for s in sets.values():
            e = s["by_action"].get(a)
            cells.append(
                "—"
                if not e
                else f"{e['writes']} · {e['ALLOW']} allow / {e['ASK']} ask / {e['DENY']} deny"
                + (f" / {e['UNKNOWN']} unknown" if e.get("UNKNOWN") else "")
            )
        rows.append(cells)
    summary = [
        [
            esc(name),
            esc(s["families"]),
            esc(s["writes"]),
            esc(s["labelled"]),
            esc(", ".join(f"{d} {n}" for d, n in s["by_domain"].items())),
            esc(", ".join(f"{j} {n}" for j, n in s["answered"].items())),
        ]
        for name, s in sets.items()
    ]
    return (
        "<h2>Data</h2><p>Completed simulations only. Families are scenario families, never split"
        " across datasets. The holdout was read once, by <code>final-eval</code>.</p>"
        + table(
            ["Dataset", "Families", "Writes", "With a verdict", "By domain", "Judge answered"],
            summary,
        )
        + "<h3>Verdicts per action</h3>"
        + table(["Action", *sets.keys()], rows)
    )


def primary_sections(final: Mapping[str, Any]) -> str:
    o = final["overall"]
    boot = final.get("bootstrap", {}).get("differences", {})
    auc = final.get("auc", {})

    def compare(a: str, b: str, title: str, question: str) -> str:
        key = f"{b}-{a}"
        d = boot.get(key, {})
        return (
            f"<h2>{esc(title)}</h2><p>{esc(question)}</p>"
            + table(
                [*OUTCOME_HEAD, "AUC"],
                [
                    [*r, num(auc.get(arm))]
                    for r, arm in zip(outcome_rows(o, [a, b]), [a, b], strict=True)
                ],
            )
            + "<p class='muted'>Family bootstrap of "
            + f"{esc(b)} &minus; {esc(a)}"
            + f": false-allow rate {interval(d.get('false_allow_rate'))}; ask rate"
            f" {interval(d.get('ask_rate'))}.</p>"
        )

    return compare(
        "D",
        "DC",
        "D vs DC: value of shared semantic concepts",
        "Both are fixed rules with the same threshold procedure; DC reads the shared concepts "
        "instead of the two policy questions.",
    ) + compare(
        "DC",
        "G1",
        "DC vs G1: value of learning",
        "Both read exactly the same concept inputs from the same judge call; G1 learns how to "
        "combine them.",
    )


def gates_section(final: Mapping[str, Any]) -> str:
    gates = final["safety_gates"]
    rows = []
    for g, e in gates["groups"].items():
        rows.append(
            [esc(g)]
            + [frac(e[a]["false_allow_rate"]) for a in ("D", "DC", "G1")]
            + [esc(e["G1"]["labelled"]), gate_chip(e["gate"])]
        )
    verdict = "passed" if gates["passed"] else "did not pass"
    rule = gates["coverage_rule"]
    auto = final["autonomy_comparison"]
    if isinstance(auto, str):
        autonomy = f"<p><strong>Autonomy comparison {esc(auto)}.</strong></p>"
    else:
        autonomy = table(
            ["Arm", "Asks (of all)", "Approvals saved (of should-run)"],
            [
                [esc(ARM_NAMES[a]), frac(auto["ask_rate"][a]), frac(auto["approvals_saved"][a])]
                for a in ("D", "DC", "G1")
            ],
        )
    return (
        "<h2>False allows overall, by action and by domain</h2>"
        f"<p>G1 may claim an autonomy gain only if its false allows are no worse than DC's and "
        f"D's overall and in every group with enough holdout data (at least {rule['min_labelled']}"
        f" writes with a verdict and {rule['min_should_escalate']} that should escalate). The"
        f" gates <strong>{verdict}</strong>"
        + (f": {esc('; '.join(gates['failures']))}" if gates["failures"] else "")
        + ".</p>"
        + table(
            [
                "Group",
                "D false allows",
                "DC false allows",
                "G1 false allows",
                "G1 labelled",
                "Gate",
            ],
            rows,
        )
        + "<h3>Ask rates and approvals saved</h3>"
        + autonomy
    )


def within_action_section(final: Mapping[str, Any]) -> str:
    rows = []
    for arm in ("D", "DC", "G1"):
        for action, r in final["by_action"][arm].items():
            rows.append(
                [
                    esc(action),
                    esc(arm),
                    frac(r["false_allow_rate"]),
                    frac(r["ask_rate"]),
                    frac(r["approvals_saved_rate"]),
                ]
            )
    rows.sort(key=lambda r: (r[0], r[1]))
    return (
        "<h2>Within-action performance (holdout)</h2><p>Each arm fitted on all revealed writes,"
        " evaluated on the holdout writes of each action.</p>"
        + table(["Action", "Arm", "False allows", "Asks", "Approvals saved"], rows, numeric_from=2)
    )


def transfer_section(final: Mapping[str, Any]) -> str:
    rows = []
    for action, e in final["transfer"].items():
        cov = e["coverage"]
        for arm in ("D", "DC", "G1"):
            a = e["arms"][arm]
            rows.append(
                [
                    esc(action),
                    gate_chip(e["status"]) if arm == "D" else "",
                    esc(arm),
                    f"{cov['labelled']} ({cov['should_escalate']} escalate)" if arm == "D" else "",
                    frac(a["within_action"]["false_allow_rate"])
                    + " · "
                    + frac(a["within_action"]["approvals_saved_rate"]),
                    frac(a["action_held_out"]["false_allow_rate"])
                    + " · "
                    + frac(a["action_held_out"]["approvals_saved_rate"]),
                    num(a.get("action_held_out_auc")),
                ]
            )
    return (
        "<h2>Held-out-action transfer (holdout)</h2><p>For each action: the arm fitted on all "
        "revealed writes (within-action) and on the revealed writes of <em>other actions only</em>"
        " (action held out), evaluated on that action's holdout writes. Cells: false allows · "
        "approvals saved.</p>"
        + table(
            [
                "Action",
                "Status",
                "Arm",
                "Holdout labelled",
                "Within-action",
                "Action held out",
                "AUC held out",
            ],
            rows,
            numeric_from=3,
        )
    )


def adaptation_section(analysis: Mapping[str, Any]) -> str:
    rows = []
    for concept, e in analysis["adaptation"].items():
        for arm in ("DC", "G1"):
            m = e["arms"].get(arm, {})

            def cell(k: str, m: Mapping[str, Any] = m) -> str:
                v = m.get(k)
                return "—" if not v else f"{v['escalated']}/{v['of']}"

            rows.append(
                [
                    esc(CONCEPT_NAMES.get(concept, concept)) if arm == "DC" else "",
                    gate_chip(e["status"]) if arm == "DC" else "",
                    esc(f"{e['orderings_usable']}/{e['orderings']}") if arm == "DC" else "",
                    esc(arm),
                    cell("before:same_action") + " → " + cell("after:same_action"),
                    cell("before:other_action") + " → " + cell("after:other_action"),
                    cell("before:should_run") + " → " + cell("after:should_run"),
                ]
            )
    return (
        "<h2>Adaptation from real corrections (revealed stream)</h2><p>In each ordering the first "
        "half of the families is revealed early. Writes there that the oracle says failed a "
        "concept are the corrections. Each arm is refitted without and then with them (no change"
        " to questions, prompts or rules) and measured on later, untouched writes failing the "
        "same concept: escalations caught before → after, for the same action as a correction "
        "and for other actions; and on later writes that should run, escalations they cost. "
        "Counts are summed over the usable orderings. Real oracle labels only.</p>"
        + table(
            [
                "Concept",
                "Status",
                "Usable orderings",
                "Arm",
                "Caught, same action",
                "Caught, other actions",
                "Escalated, should run",
            ],
            rows,
            numeric_from=4,
        )
    )


def curve_section(analysis: Mapping[str, Any]) -> str:
    lc = analysis["learning_curve"]
    rows = []
    for arm, points in lc["arms"].items():
        for p in points:
            rows.append(
                [
                    esc(arm),
                    esc(p["n"]),
                    spread(p["should_escalate"]),
                    spread(p["false_allows"]),
                    spread(p["asks"]),
                    spread(p["approvals_saved"]),
                ]
            )
    return (
        f"<h2>Learning curve (revealed stream, {lc['orderings']} family orderings)</h2>"
        "<p>Each write decided by the arm fitted on every labelled write before it. Cumulative "
        "counts after n decisions: median [10th&ndash;90th percentile] over orderings.</p>"
        + table(
            ["Arm", "n", "Should escalate", "False allows", "Asks", "Approvals saved"],
            rows,
            numeric_from=1,
        )
    )


def promotion_section(analysis: Mapping[str, Any]) -> str:
    p = analysis["promotion"]
    log = [
        [
            esc(v["version"]),
            esc(v["trained_on"]),
            num(v["threshold"]),
            f"{v['promotion_false_allows']} / {v['promotion_asks']} of {v['promotion_labelled']}",
            "<span class='chip pass'>promoted</span>" if v["promoted"] else "kept champion",
            esc(v["reason"]),
        ]
        for v in p["log_ordering_0"]
    ]
    per = p["per_ordering"]
    promos = sorted(x["promotions"] for x in per)
    fa = sorted(x["promotion_set"]["false_allows"] for x in per)
    rb = p["rollback_check"]
    return (
        "<h2>Promotion and safe evolution (promotion set)</h2>"
        f"<p>{esc(p['rule'])}. Ordering 0's version log:</p>"
        + table(
            [
                "Challenger",
                "Trained on",
                "Threshold",
                "Promotion set: false allows / asks",
                "Outcome",
                "Why",
            ],
            log,
        )
        + f"<p class='muted'>Over {len(per)} orderings: promotions per ordering "
        f"{promos[0]}&ndash;{promos[-1]}; final champion's false allows on the promotion set "
        f"{fa[0]}&ndash;{fa[-1]}. Rollback check: "
        + esc(
            "restored "
            + rb["restored"]
            + (", decisions identical" if rb.get("identical") else ", DECISIONS DIFFER")
            if rb.get("checked")
            else rb.get("reason")
        )
        + ".</p>"
    )


def secondary_section(analysis: Mapping[str, Any]) -> str:
    rows = [
        [
            esc(k),
            frac(v["false_allow_rate"]),
            frac(v["ask_rate"]),
            frac(v["approvals_saved_rate"]),
            num(v.get("auc")),
        ]
        for k, v in analysis["secondary_on_promotion_set"].items()
    ]
    prim = [[*r, ""] for r in outcome_rows(analysis["promotion_set_primary"], ("D", "DC", "G1"))]
    return (
        "<details><summary>Secondary diagnostics (promotion set; never primary)</summary>"
        "<p>Jev variants, G1 with per-action offsets, and G1 on both judges, fitted on revealed "
        "writes and evaluated on the promotion set, beside the primary arms on the same set.</p>"
        + table(["Variant", "False allows", "Asks", "Approvals saved", "AUC"], prim + rows)
        + "</details>"
    )


def cost_section(
    analysis: Mapping[str, Any], final: Mapping[str, Any] | None, ledger: Mapping[str, Any] | None
) -> str:
    calls = dict(analysis["calls"])
    rows = []
    for judge, c in calls.items():
        if final:
            h = final["calls"][judge]
            c = {
                **c,
                "scored": c["scored"] + h["scored"],
                "cost_usd_total": c["cost_usd_total"] + h["cost_usd_total"],
            }
        rows.append(
            [
                esc(judge),
                esc(c["scored"]),
                f"${c['cost_usd_total']:.4f}",
                "—" if c["cost_usd_per_call"] is None else f"${c['cost_usd_per_call']:.5f}",
                num(c["latency_ms_p50"], 0) + " ms",
                num(c["latency_ms_p95"], 0) + " ms",
            ]
        )
    led = ""
    if ledger:
        spent = ledger.get("committed", {}).get("total", 0.0)
        cap = ledger.get("caps", {}).get("total")
        led = (
            f"<p class='muted'>Scoring ledger: ${spent:.4f} committed against a ${cap:.2f} hard "
            "cap (every call reserved its maximum first).</p>"
        )
    return (
        "<h2>Cost and latency</h2><p>One judge call per write answers all ten concepts and both "
        "baseline questions, so D, DC and G1 cost the same. Latency is per call (p50 / p95 over "
        "revealed and promotion writes, plus the holdout once evaluated).</p>"
        + table(["Judge", "Calls", "Total", "Per call", "p50", "p95"], rows)
        + led
    )


def build(directory: Path) -> Path:
    analysis = json.loads((directory / "analysis.json").read_text())
    final_path = directory / "final.json"
    final = json.loads(final_path.read_text()) if final_path.exists() else None
    rec_path = directory / "recommendation.json"
    rec = json.loads(rec_path.read_text()) if rec_path.exists() else None
    ledger_path = directory / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else None
    for rows in (analysis, final or {}):
        assert "synthetic" not in json.dumps(rows.get("data", {})), "synthetic rows in a report"
    n = analysis["data"]["revealed"]["labelled"] + analysis["data"]["promotion"]["labelled"]
    if final:
        n += final["holdout"]["labelled"]
    parts = [
        "<h1>Decision-model pilot</h1>",
        "<p class='muted'>Shared decision concepts vs learning vs the fixed baseline, on the "
        "already-captured τ² stage-1 and smoke writes (Phases 0&ndash;1).</p>",
        f"<div class='banner'>Directional pilot, deterministic oracle only — unaudited, about {n}"
        " decisions. No independent human validation; not a publishable result.</div>",
    ]
    if rec:
        parts.append(
            f"<h2>Phase 2 recommendation: {esc(rec['decision'])}</h2><ul>"
            + "".join(f"<li>{esc(r)}</li>" for r in rec["reasons"])
            + "</ul><p class='muted'>A judgement on the results below, not a computed rule. "
            "Phase 2 capture needs its own go/no-go and was not started.</p>"
        )
    if final:
        parts.append(primary_sections(final))
        parts.append(gates_section(final))
        parts.append(within_action_section(final))
        parts.append(transfer_section(final))
    else:
        parts.append("<p><strong>The final evaluation has not run.</strong></p>")
    parts.append(adaptation_section(analysis))
    parts.append(curve_section(analysis))
    parts.append(promotion_section(analysis))
    parts.append(secondary_section(analysis))
    parts.append(dataset_section(analysis, final))
    parts.append(cost_section(analysis, final, ledger))
    page = (
        "<title>Decision-Model Pilot</title>"
        '<meta name="claude:viewport-fit-sides" content="cover">'
        f"<style>{CSS}</style><main>" + "".join(parts) + "</main>"
    )
    out = directory / "report" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
