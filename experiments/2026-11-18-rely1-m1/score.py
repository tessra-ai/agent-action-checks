"""Score the M1 gate under the model-labeller plan (Prithvi, 2026-11-19/20). Written and committed
before any of Prithvi's or John's answers exist; run once when both answer files are in review/.

    python experiments/2026-11-18-rely1-m1/score.py

The labels are model-labelled and human-checked: two model labellers answered every question
(labeller A: Codex CLI, gpt-6.2-sol, reasoning effort high; labeller B: the Gemini app, 4 Neon,
thinking High), and Prithvi rules on what his reduced sheet shows (reduced_sheet.py). The
first, no-reasoning run of A is reported as a comparison only.

Inputs: results/labeller_comparison.json (compare_labellers.py; its input hashes are checked),
the label files and their summaries, review/prithvi_reduced_answers.json (exported from
review/prithvi_reduced.html) and review/second_answers.json (John's download from the second
sheet, unchanged). Each answer file must match its sheet's fingerprint and be complete;
otherwise nothing is written.

Writes results/gate.json and results/labels_final.jsonl. Every number has its denominator.
1. A vs B, statements and the agreement question apart: the full table, raw agreement, kappa,
   agreement on "yes" alone; without the example-exposed actions; under / over 8,192 tokens.
   The same for A(no reasoning) vs B and A vs A(no reasoning).
2. Prithvi on his sheet, blind (before he saw the labellers) and final: the statements both
   labellers marked yes (how many he confirms); the disagreements (whom he sides with); the
   agreement disagreements; the Gaming Mouse case.
3. The 14 pre-filled contradictions: how many each labeller marks yes, and how many Prithvi
   confirms (those not on his sheet were marked yes by neither labeller).
4. John vs the labellers on his 35 (and vs Prithvi where his sheet has the same statement).
5. "No agreement": the current 32, A, B, both, and the final count.
6. The anchor cases; flagged statements in actions both labellers call agreed; the agreement
   disagreements left off Prithvi's sheet (unresolved: both answers kept).

Final labels (labels_final.jsonl): where A and B agree, their answer, except a statement both
mark yes, which takes Prithvi's ruling; where they disagree and Prithvi ruled, his ruling;
otherwise "unresolved" with both answers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from score_first_sheet import parse_turns, wilson

HERE = Path(__file__).parent
R = HERE / "results"
THREE = {"yes", "no", "unsure"}
RECORDS = {"supported", "contradicted", "not covered", "unsure"}
TO_MODEL = {"yes": "yes", "no": "no", "unsure": "not_sure"}  # a person's answer, model scale
AGREE_TO_MODEL = {"yes": "agreed", "no": "not_agreed", "unsure": "not_sure"}


def jsonl(name: str) -> list[dict]:
    return [json.loads(x) for x in (R / name).read_text().splitlines() if x.strip()]


def sheet_data(path: Path) -> dict:
    html = path.read_text()
    blob = re.search(r"const DATA = (.*?);\nconst (SHEET|KEY)", html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


def check(sheet: dict, second: dict, cmp_: dict, pa: dict, sa: dict) -> list[str]:
    """Problems that stop scoring: stale inputs, a file from another sheet, missing answers."""
    problems = []
    for f, h in cmp_["inputs_sha256"].items():
        if hashlib.sha256((R / f).read_bytes()).hexdigest() != h:
            problems.append(f"results/{f} changed since compare_labellers.py ran")
    for f, h in sheet["inputs"].items():
        if hashlib.sha256((R / f).read_bytes()).hexdigest() != h:
            problems.append(f"the reduced sheet was built from another results/{f}")
    if pa.get("sheet") != sheet["sheet"] or pa.get("items_sha256") != sheet["items_sha256"]:
        problems.append("prithvi_reduced_answers.json is not from the current reduced sheet")
    if sa.get("sheet") != "second" or sa.get("fingerprint") != second["fingerprint"]:
        problems.append("second_answers.json is not from the current second sheet")
    p = pa.get("answers", {})
    miss, bad_turns = [], []
    for it in sheet["items"]:
        a = p.get(it["key"]) or {}
        if it["kind"] == "statement":
            ok = a.get("mc") in THREE and a.get("material") in THREE and a.get("records") in RECORDS
        else:
            ok = a.get("agreed") in THREE
            conv = sheet["actions"][it["write_id"]]["conversation"]
            cust = {i for i, t in enumerate(conv, 1) if t["role"] == "customer"}
            turns = parse_turns(a.get("turns"), cust, len(conv))
            if turns is None or not set(turns) <= cust:
                bad_turns.append(it["key"])
        if not ok:
            miss.append(it["key"])
    if miss:
        problems.append(f"{len(miss)} items on the reduced sheet unanswered: {', '.join(miss)}")
    if bad_turns:
        problems.append(
            "agreement turns must be customer messages, as '31, 34' or 'T31-T34': "
            + ", ".join(bad_turns)
        )
    s_miss = [i["key"] for i in second["items"] if sa.get("answers", {}).get(i["key"]) not in THREE]
    if s_miss:
        problems.append(f"{len(s_miss)} second-sheet statements unanswered")
    return problems


def tally(pairs: list[tuple[str, str, str]]) -> dict:
    """Whom a ruling sides with: (ruling, A, B) on the model scale."""
    out = Counter()
    for r, a, b in pairs:
        out[
            "with A only"
            if r == a != b
            else "with B only"
            if r == b != a
            else "with both"
            if r == a == b
            else "with neither"
        ] += 1
    return {"n": len(pairs), **dict(sorted(out.items()))}


def score(cmp_: dict, sheet: dict, second: dict, pa: dict, sa: dict) -> tuple[dict, list[dict]]:
    a = {r["id"]: r for r in jsonl("labels_a.jsonl")}
    b = {r["id"]: r for r in jsonl("labels_b.jsonl")}
    key = json.loads((R / "pack_key.json").read_text())
    unit = {q: u for v in key.values() for q, u in v["questions"].items()}
    by_unit = {u: q for q, u in unit.items()}
    rows = {r["unit_key"]: r for r in jsonl("label_set.jsonl")}
    current = {r["write_id"]: r for r in jsonl("agreement.jsonl")}
    write_of = {p: v["write_id"] for p, v in key.items()}
    p = pa["answers"]
    items = {it["key"]: it for it in sheet["items"]}
    s_ids = sorted(i for i in a if ".S" in i)
    a_ids = sorted(i for i in a if i.endswith(".A"))

    def ruling(i: str, blind: bool) -> str | None:
        ans = p.get(i) or {}
        # Blind answers are frozen for every card of an action when any of its cards is revealed;
        # a card with none was answered before anything on its action was shown.
        src = (ans.get("blind") or ans) if blind else ans
        if ".S" in i:
            return TO_MODEL.get(src.get("mc"))
        return AGREE_TO_MODEL.get(src.get("agreed"))

    out: dict = {
        "labels": "Model-labelled and human-checked: labeller A and labeller B answered every "
        "question; Prithvi ruled on the items of his reduced sheet.",
        "labellers": {
            n: json.loads((R / f"{n}_summary.json").read_text())
            for n in ("labels_a", "labels_a_noreasoning", "labels_b")
        },
        "A_vs_B": cmp_["A_vs_B"],
        "A_noreasoning_vs_B": cmp_["A_noreasoning_vs_B"],
        "A_vs_A_noreasoning": cmp_["A_vs_A_noreasoning"],
    }
    for length in ("under_8192", "over_8192"):
        ids = [q for q in s_ids if rows[unit[q]]["length"] == length]
        out.setdefault("A_vs_B_statements_by_length", {})[length] = {
            "n": len(ids),
            "agree": sum(a[q]["answer"] == b[q]["answer"] for q in ids),
            "both_yes": sum(a[q]["answer"] == b[q]["answer"] == "yes" for q in ids),
            "either_yes": sum("yes" in (a[q]["answer"], b[q]["answer"]) for q in ids),
            "table_A_by_B": {
                x: dict(Counter(b[q]["answer"] for q in ids if a[q]["answer"] == x))
                for x in ("yes", "no", "not_sure")
            },
        }

    groups = {
        "both_yes": [
            k for k, it in items.items() if it.get("selected_because", "").startswith("both")
        ],
        "statement_disagreement": [
            k
            for k, it in items.items()
            if it["kind"] == "statement" and a[k]["answer"] != b[k]["answer"]
        ],
        "agreement_disagreement": [k for k, it in items.items() if it["block"] == "agreement"],
    }
    rulings = {}
    for when in ("blind", "final"):
        blind = when == "blind"
        bt = [ruling(k, blind) for k in groups["both_yes"]]
        k_yes = sum(r == "yes" for r in bt)
        rulings[when] = {
            "both_yes_confirmed": {
                "yes": k_yes,
                "n": len(bt),
                "no": bt.count("no"),
                "not_sure": bt.count("not_sure"),
                "wilson_95": [round(x, 3) for x in wilson(k_yes, len(bt))],
            },
            "statement_disagreements": tally(
                [
                    (ruling(k, blind), a[k]["answer"], b[k]["answer"])
                    for k in groups["statement_disagreement"]
                ]
            ),
            "agreement_disagreements": tally(
                [
                    (ruling(k, blind), a[k]["answer"], b[k]["answer"])
                    for k in groups["agreement_disagreement"]
                ]
            ),
        }
    gm = cmp_["sheet"]["gaming_mouse"]
    gid = f"{gm['packet']}.A"
    rulings["gaming_mouse"] = {
        "A": a[gid]["answer"],
        "B": b[gid]["answer"],
        "current": current[gm["write_id"]]["agreed"],
        "prithvi_initial_not_blind": ruling(gid, True),
        "prithvi_final": ruling(gid, False),
    }
    rulings["changed_after_reveal"] = sum(
        1 for k in items if (p.get(k) or {}).get("blind") and ruling(k, True) != ruling(k, False)
    )
    out["prithvi"] = rulings

    prefill = [q for q in s_ids if rows[unit[q]]["prefill"] == "MC"]
    on_sheet = [q for q in prefill if q in items]
    out["prefilled_mc_14"] = {
        **cmp_["prefilled_mc_14"],
        "on_prithvi_sheet": len(on_sheet),
        "prithvi_confirms_yes": sum(ruling(q, False) == "yes" for q in on_sheet),
        "not_on_sheet_marked_yes_by_neither": len(prefill) - len(on_sheet),
    }

    john = []
    for it in second["items"]:
        q = by_unit[it["key"]]
        j = TO_MODEL[sa["answers"][it["key"]]]
        john.append(
            (q, j, a[q]["answer"], b[q]["answer"], ruling(q, False) if q in items else None)
        )
    out["john"] = {
        "n": len(john),
        "agrees_with_A": sum(j == x for _, j, x, _, _ in john),
        "agrees_with_B": sum(j == y for _, j, _, y, _ in john),
        "on_prithvi_sheet": sum(1 for *_, r in john if r is not None),
        "agrees_with_prithvi": sum(j == r for _, j, _, _, r in john if r is not None),
        "table_john_by_A": {
            x: dict(Counter(a_ for _, j, a_, _, _ in john if j == x)) for x in TO_MODEL.values()
        },
        "table_john_by_B": {
            x: dict(Counter(b_ for _, j, _, b_, _ in john if j == x)) for x in TO_MODEL.values()
        },
    }

    finals = []
    for i in s_ids + a_ids:
        x, y = a[i]["answer"], b[i]["answer"]
        r = ruling(i, False) if i in items else None
        if r is not None:
            label, by = r, "Prithvi"
        elif x == y:
            label, by = x, "A and B"
        else:
            label, by = "unresolved", None
        finals.append(
            {
                "id": i,
                "unit_key": unit.get(i),
                "write_id": write_of[i.split(".")[0]],
                "kind": "statement" if ".S" in i else "agreement",
                "label": label,
                "decided_by": by,
                "A": x,
                "B": y,
            }
        )
    if gid in items:  # the Gaming Mouse ruling also settles its agreement label
        for f in finals:
            if f["id"] == gid:
                f["label"], f["decided_by"] = ruling(gid, False), "Prithvi"
    # Statements are labelled only on actions the customer agreed to (as in the label set): on an
    # action whose final agreement label is "not agreed" they leave the contradiction labels; on
    # one whose agreement is unresolved or unsure they are kept but flagged.
    agree_final = {f["write_id"]: f["label"] for f in finals if f["kind"] == "agreement"}
    for f in finals:
        if f["kind"] != "statement":
            continue
        g = agree_final[f["write_id"]]
        if g == "not_agreed":
            f["contradiction_label"], f["label"] = f["label"], "excluded: no agreement"
        elif g != "agreed":
            f["agreement_open"] = g
    final_no = {
        f["write_id"] for f in finals if f["kind"] == "agreement" and f["label"] == "not_agreed"
    }
    out["no_agreement"] = {
        **cmp_["no_agreement"],
        "final_not_agreed": len(final_no),
        "final_unresolved": sum(
            1 for f in finals if f["kind"] == "agreement" and f["label"] == "unresolved"
        ),
    }
    out["final_statement_labels"] = dict(
        Counter(f["label"] for f in finals if f["kind"] == "statement")
    )
    # Actions that were "no agreement" when the label set was built have no statement labels; if
    # the final label says agreed, their statements still need labelling (a follow-up).
    out["newly_agreed_without_statement_labels"] = sorted(
        w for w, g in agree_final.items() if g == "agreed" and current[w]["agreed"] == "no"
    )
    out["statements_on_actions_with_open_agreement"] = sum(
        1 for f in finals if f.get("agreement_open")
    )
    out["anchors"] = cmp_["anchors"]
    out["flagged_statements"] = cmp_["flagged_statements"]
    out["agreement_disagreements_left_off_sheet"] = cmp_["sheet"][
        "agreement_disagreements_left_off"
    ]
    return out, finals


def main() -> None:
    gate = R / "gate.json"
    if gate.exists():
        raise SystemExit("gate results exist; scored once")
    cmp_ = json.loads((R / "labeller_comparison.json").read_text())
    sheet = sheet_data(HERE / "review/prithvi_reduced.html")
    second = sheet_data(HERE / "review/second_sheet.html")
    pa = json.loads((HERE / "review/prithvi_reduced_answers.json").read_text())
    sa = json.loads((HERE / "review/second_answers.json").read_text())
    problems = check(sheet, second, cmp_, pa, sa)
    if problems:
        raise SystemExit("not scored: " + "; ".join(problems))
    result, finals = score(cmp_, sheet, second, pa, sa)
    (R / "labels_final.jsonl").write_text("".join(json.dumps(f) + "\n" for f in finals))
    gate.write_text(json.dumps(result, indent=1) + "\n")
    print(
        json.dumps(
            {k: result[k] for k in ("prithvi", "prefilled_mc_14", "john", "no_agreement")}, indent=1
        )
    )


if __name__ == "__main__":
    main()
