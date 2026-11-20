"""Compare the model labellers, and pick what Prithvi reviews (Prithvi, 2026-11-19/20).

    python experiments/2026-11-18-rely1-m1/compare_labellers.py

Labeller A is the reasoning run (Codex, gpt-6.2-sol, reasoning effort high:
`results/labels_a.jsonl`); the earlier no-reasoning run (`results/labels_a_noreasoning.jsonl`)
is reported alongside as a comparison. Labeller B is the Gemini app run
(`results/labels_b.jsonl`). The pack key maps IDs back to statements and actions.

Writes `results/labeller_comparison.json`:
- statement and agreement tables, labeller by labeller (yes / no / not sure; agreed /
  not agreed / not sure), raw agreement, Cohen's kappa, and agreement on "yes" alone
  (both yes over either yes), for A vs B, A(no reasoning) vs B, and A vs A(no reasoning); each
  also without the actions exposed to the prompt's worked examples;
- the 14 statements pre-filled MC: how many each labeller marks yes;
- "no agreement" per labeller, against the current agreement labels;
- each anchor case: what each labeller said;
- flagged statements (either labeller yes) in actions both labellers call agreed;
- Prithvi's sheet: every statement both mark yes; every statement where they disagree; the
  agreement-question disagreements on actions holding a statement either marks yes; the Gaming
  Mouse case apart. No cap. Items among the 14 pre-fills are flagged. The agreement
  disagreements left off the sheet are listed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
R = HERE / "results"
M0 = HERE.parent / "2026-11-18-rely1-m0"
sys.path.insert(0, str(M0))
from packets import ANCHORS  # noqa: E402

GAMING_MOUSE = "01M5JZ4FQ7N37RJXVD6FW00S14"
S_ANS = ["yes", "no", "not_sure"]
A_ANS = ["agreed", "not_agreed", "not_sure"]


def load(name: str) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, (R / name).read_text().splitlines())}


def table(x: dict, y: dict, ids: list[str], answers: list[str]) -> dict:
    t = {a: {b: 0 for b in answers} for a in answers}
    for i in ids:
        t[x[i]["answer"]][y[i]["answer"]] += 1
    n = len(ids)
    same = sum(t[a][a] for a in answers)
    pe = sum(sum(t[a].values()) * sum(t[b][a] for b in answers) for a in answers) / (n * n or 1)
    po = same / (n or 1)
    pos = answers[0]
    both = t[pos][pos]
    either = sum(t[pos].values()) + sum(t[b][pos] for b in answers) - both
    return {
        "n": n,
        "table_rows_first_cols_second": t,
        "agree": same,
        "agree_rate": round(po, 3),
        "cohen_kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
        f"both_{pos}": both,
        f"either_{pos}": either,
        f"{pos}_agreement_both_over_either": round(both / either, 3) if either else None,
    }


def pair(x: dict, y: dict, s_ids: list[str], a_ids: list[str], skip: set[str]) -> dict:
    keep = lambda ids: [i for i in ids if i.split(".")[0] not in skip]  # noqa: E731
    return {
        "statements": table(x, y, s_ids, S_ANS),
        "agreement": table(x, y, a_ids, A_ANS),
        "without_example_exposed": {
            "statements": table(x, y, keep(s_ids), S_ANS),
            "agreement": table(x, y, keep(a_ids), A_ANS),
        },
    }


def main() -> None:
    a, a0, b = (load(f) for f in ("labels_a.jsonl", "labels_a_noreasoning.jsonl", "labels_b.jsonl"))
    key = json.loads((R / "pack_key.json").read_text())
    exposed = set(json.loads((R / "pack_summary.json").read_text())["example_exposed"]["packets"])
    unit = {q: u for v in key.values() for q, u in v["questions"].items()}
    write_of = {p: v["write_id"] for p, v in key.items()}
    pid_of = {w: p for p, w in write_of.items()}
    rows = {
        r["unit_key"]: r for r in map(json.loads, (R / "label_set.jsonl").read_text().splitlines())
    }
    current = {
        r["write_id"]: r for r in map(json.loads, (R / "agreement.jsonl").read_text().splitlines())
    }
    s_ids = sorted(i for i in a if ".S" in i)
    a_ids = sorted(i for i in a if i.endswith(".A"))
    for lab in (a0, b):
        if set(lab) != set(a):
            raise SystemExit("labellers must answer the same IDs")

    prefill_mc = {q for q in s_ids if rows[unit[q]]["prefill"] == "MC"}
    yes = lambda lab, q: lab[q]["answer"] == "yes"  # noqa: E731
    agreed = lambda lab, p: lab[f"{p}.A"]["answer"] == "agreed"  # noqa: E731

    out: dict = {
        "labellers": {
            "A": "Codex CLI, gpt-6.2-sol, reasoning effort high (results/labels_a_summary.json)",
            "A_noreasoning": "Codex CLI, gpt-6.2-sol, reasoning effort none (comparison)",
            "B": "Gemini app, Deeper analysis - 4 Neon, Thinking level High",
        },
        "A_vs_B": pair(a, b, s_ids, a_ids, exposed),
        "A_noreasoning_vs_B": pair(a0, b, s_ids, a_ids, exposed),
        "A_vs_A_noreasoning": pair(a, a0, s_ids, a_ids, exposed),
        "example_exposed_packets": len(exposed),
        # reduced_sheet.py refuses a comparison built from other files than these.
        "inputs_sha256": {
            f: hashlib.sha256((R / f).read_bytes()).hexdigest()
            for f in (
                "labels_a.jsonl",
                "labels_a_noreasoning.jsonl",
                "labels_b.jsonl",
                "pack_key.json",
                "label_set.jsonl",
                "agreement.jsonl",
            )
        },
    }

    out["prefilled_mc_14"] = {
        "statements": len(prefill_mc),
        **{
            name: sum(yes(lab, q) for q in prefill_mc)
            for name, lab in (("A_yes", a), ("A_noreasoning_yes", a0), ("B_yes", b))
        },
        "both_A_and_B_yes": sum(yes(a, q) and yes(b, q) for q in prefill_mc),
    }

    cur_no = {pid_of[w] for w, r in current.items() if r["agreed"] == "no"}
    no_of = {
        name: {i.split(".")[0] for i in a_ids if lab[i]["answer"] == "not_agreed"}
        for name, lab in (("A", a), ("A_noreasoning", a0), ("B", b))
    }
    out["no_agreement"] = {
        "current_labels": len(cur_no),
        **{f"{n}_not_agreed": len(s) for n, s in no_of.items()},
        **{f"{n}_overlap_with_current": len(s & cur_no) for n, s in no_of.items()},
        "A_and_B_both_not_agreed": len(no_of["A"] & no_of["B"]),
    }

    anchors = {}
    for w, name in ANCHORS.items():
        p = pid_of[w]
        qs = [q for q in s_ids if q.startswith(p + ".")]
        anchors[name] = {
            "packet": p,
            "statements_in_pack": len(qs),
            **{
                lab_name: {
                    "statements_yes": [q for q in qs if yes(lab, q)],
                    "agreement": lab[f"{p}.A"]["answer"],
                }
                for lab_name, lab in (("A", a), ("A_noreasoning", a0), ("B", b))
            },
        }
    out["anchors"] = anchors

    flagged = [q for q in s_ids if yes(a, q) or yes(b, q)]
    out["flagged_statements"] = {
        "either_yes": len(flagged),
        "in_actions_both_call_agreed": sum(
            1 for q in flagged if agreed(a, q.split(".")[0]) and agreed(b, q.split(".")[0])
        ),
    }

    # Prithvi's sheet.
    both_yes = [q for q in s_ids if yes(a, q) and yes(b, q)]
    s_dis = [q for q in s_ids if a[q]["answer"] != b[q]["answer"]]
    flagged_actions = {q.split(".")[0] for q in flagged}
    a_dis = [i for i in a_ids if a[i]["answer"] != b[i]["answer"]]
    a_dis_on = [i for i in a_dis if i.split(".")[0] in flagged_actions]
    a_dis_off = [i for i in a_dis if i.split(".")[0] not in flagged_actions]
    gm = pid_of[GAMING_MOUSE]

    def item(i: str, why: str) -> dict:
        p = i.split(".")[0]
        return {
            "id": i,
            "why": why,
            "write_id": write_of[p],
            "unit_key": unit.get(i),
            "A": a[i]["answer"],
            "B": b[i]["answer"],
            "prefilled_mc": i in prefill_mc,
        }

    sheet = (
        [item(q, "both yes") for q in both_yes]
        + [item(q, "statement disagreement") for q in s_dis]
        + [item(i, "agreement disagreement, action has a flagged statement") for i in a_dis_on]
    )
    out["sheet"] = {
        "total": len(sheet) + 1,
        "both_yes": len(both_yes),
        "statement_disagreements": len(s_dis),
        "agreement_disagreements_on_flagged_actions": len(a_dis_on),
        "gaming_mouse_case": 1,
        "items_among_14_prefills": sum(1 for x in sheet if x["prefilled_mc"]),
        "prefills_not_on_sheet": sorted(q for q in prefill_mc if q not in {x["id"] for x in sheet}),
        "items": sheet,
        "gaming_mouse": {"packet": gm, "write_id": GAMING_MOUSE, "A": a[f"{gm}.A"]["answer"],
                         "B": b[f"{gm}.A"]["answer"]},
        "agreement_disagreements_left_off": [
            {"id": i, "write_id": write_of[i.split(".")[0]], "A": a[i]["answer"],
             "B": b[i]["answer"], "current": current[write_of[i.split(".")[0]]]["agreed"]}
            for i in a_dis_off
        ],
    }  # fmt: skip
    (R / "labeller_comparison.json").write_text(json.dumps(out, indent=1) + "\n")
    s = out["sheet"]
    print(
        f"sheet total {s['total']}: both yes {s['both_yes']}, statement disagreements "
        f"{s['statement_disagreements']}, agreement disagreements on flagged actions "
        f"{s['agreement_disagreements_on_flagged_actions']}, + Gaming Mouse; among the 14 "
        f"pre-fills: {s['items_among_14_prefills']}"
    )
    print("agreement disagreements left off:", len(s["agreement_disagreements_left_off"]))
    print(
        json.dumps({k: out[k] for k in ("prefilled_mc_14", "no_agreement", "flagged_statements")})
    )


if __name__ == "__main__":
    main()
