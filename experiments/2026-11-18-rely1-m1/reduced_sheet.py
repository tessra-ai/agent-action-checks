"""Prithvi's reduced review sheet after the model labellers (Prithvi, 2026-11-19/20).

    python experiments/2026-11-18-rely1-m1/reduced_sheet.py

Items come from `results/labeller_comparison.json` (compare_labellers.py), no cap:
1. every statement both labellers marked yes;
2. every statement where they disagree;
3. the agreement-question disagreements on actions holding a statement either marked yes;
4. the Gaming Mouse case, shown separately with why it is "no agreement" and its messages.
Items among the 14 pre-filled contradictions are tagged.

Blind first (Prithvi, 2026-11-20): the labellers' answers and reasons, the rulings and the graders'
reasons are hidden on each card until its first question is answered; the answers given then are
exported as `blind`, beside any later change. Statements keep the three questions of the first
sheet. Writes review/prithvi_reduced.html and review/prithvi_reduced_artifact.html.
"""

from __future__ import annotations

import hashlib
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
M0 = HERE.parent / "2026-11-18-rely1-m0"
sys.path.insert(0, str(HERE))
from build import rulings as load_rulings  # noqa: E402
from sheet import DEFINITION, action, as_artifact  # noqa: E402

SHEET = "prithvi_reduced"
PAGE = (HERE / "reduced_template.html").read_text()
# Neutral headings and a seeded shuffle inside each block: neither the heading nor the position
# says which group an item came from (both yes, disagreement); that shows only after the blind
# answer (Codex review, 2026-11-20).
SEED = 20261118
BLOCKS = {
    "statement": "Statements",
    "agreement": "Agreement questions",
    "gaming_mouse": "Shown separately: the Gaming Mouse case",
}
WHY = {
    "both yes": "both labellers marked it a material contradiction",
    "statement disagreement": "the labellers disagree",
    "agreement disagreement, action has a flagged statement": "the labellers disagree on "
    "agreement, and the action holds a statement either labeller flagged",
}
BLOCK_NOTES = {
    "gaming_mouse": "An anchor case. It has no statement questions because its action is labelled "
    "'no agreement' (reason below) and such actions are left out of the statement labels. Confirm "
    "or change that label.",
}
QUESTIONS = {
    "statement": [
        ("mc", "Material contradiction for this action?", ["yes", "no", "unsure"]),
        ("material", "Would correcting it plausibly change the yes?", ["yes", "no", "unsure"]),
        (
            "records",
            "Do the records back it?",
            ["supported", "contradicted", "not covered", "unsure"],
        ),
    ],
    "agreement": [
        ("agreed", "Did the customer agree to this exact action?", ["yes", "no", "unsure"])
    ],
}
for _q in QUESTIONS["statement"]:  # the template must render each question exactly so
    if f'"{_q[0]}", "{_q[1]}", [{", ".join(json.dumps(o) for o in _q[2])}]' not in PAGE:
        raise SystemExit(f"reduced_template.html does not render {_q[0]!r} as QUESTIONS says")


def load(name: str) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, (HERE / "results" / name).read_text().splitlines())}


def main() -> None:
    cmp_ = json.loads((HERE / "results/labeller_comparison.json").read_text())
    for f, h in cmp_["inputs_sha256"].items():  # the comparison must be from these very files
        if hashlib.sha256((HERE / "results" / f).read_bytes()).hexdigest() != h:
            raise SystemExit(f"results/{f} changed since compare_labellers.py ran; rerun it")
    sheet = cmp_["sheet"]
    a, b = load("labels_a.jsonl"), load("labels_b.jsonl")
    rows = {
        r["unit_key"]: r
        for r in map(json.loads, (HERE / "results/label_set.jsonl").read_text().splitlines())
    }
    current = {
        r["write_id"]: r
        for r in map(json.loads, (HERE / "results/agreement.jsonl").read_text().splitlines())
    }
    packets = {
        p["write_id"]: p
        for p in map(json.loads, (M0 / "runs/packets.jsonl").read_text().splitlines())
    }
    rulings = load_rulings()

    def labeller(lab: dict, i: str) -> dict:
        return {"answer": lab[i]["answer"], "reason": lab[i]["reason"]}

    items = []
    for x in sheet["items"]:
        i, w = x["id"], x["write_id"]
        block = "statement" if ".S" in i else "agreement"
        it = {
            "id": i,
            "key": i,
            "write_id": w,
            "block": block,
            "prefilled_mc": x["prefilled_mc"],
            "selected_because": WHY[x["why"]],
            "A": labeller(a, i),
            "B": labeller(b, i),
        }
        if ".S" in i:
            r = rows[x["unit_key"]]
            u = r["unit"]
            it |= {
                "kind": "statement",
                "turn": u["turn"],
                "turns": [u["turn"]],
                "text": u["text"],
                "lead_in": u["lead_in"],
                "cited_by": [
                    {"who": c["who"], "span": c["span"], "as_false": c["as_false"]}
                    for c in r["cited_by"]
                ],
            }
        else:
            g = current[w]
            it |= {
                "kind": "agreement",
                "question": QUESTIONS["agreement"][0][1],
                "current": f"{g['agreed']} ({g['source']}): {g['reason']}",
            }
        items.append(it)
    gm = sheet["gaming_mouse"]
    g = current[gm["write_id"]]
    gid = f"{gm['packet']}.A"
    items.append(
        {
            "id": gid,
            "key": gid,
            "write_id": gm["write_id"],
            "block": "gaming_mouse",
            "kind": "agreement",
            "prefilled_mc": False,
            "question": QUESTIONS["agreement"][0][1] + " (current label: no agreement)",
            "why": f"Why it is 'no agreement' ({g['source']}): {g['reason']}",
            "turns": g.get("turns", []),
            "current": f"{g['agreed']} ({g['source']})",
            "A": labeller(a, gid),
            "B": labeller(b, gid),
        }
    )
    import random

    order = list(BLOCKS)
    items.sort(key=lambda x: x["id"])
    random.Random(SEED).shuffle(items)
    items.sort(key=lambda x: order.index(x["block"]))  # stable: shuffled within each block
    acts = {
        w: action(packets[w], rulings.get(w, [])) for w in sorted({x["write_id"] for x in items})
    }
    policy = {p["domain"]: p["policy"] for p in packets.values()}
    fingerprint = hashlib.sha256(
        json.dumps([items, acts, policy, DEFINITION, QUESTIONS], sort_keys=True).encode()
    ).hexdigest()
    data = {
        "sheet": SHEET,
        "items": items,
        "blocks": BLOCKS,
        "block_notes": BLOCK_NOTES,
        "actions": acts,
        "policy": policy,
        "items_sha256": fingerprint,
        "inputs": {
            f: hashlib.sha256((HERE / "results" / f).read_bytes()).hexdigest()
            for f in (
                "labeller_comparison.json",
                "labels_a.jsonl",
                "labels_b.jsonl",
                "label_set.jsonl",
                "agreement.jsonl",
            )
        },
    }
    counts = {k: sum(1 for x in items if x["block"] == k) for k in BLOCKS}
    intro = (
        f"{len(items)} items: {counts['statement']} statements, {counts['agreement']} agreement "
        "questions and the Gaming Mouse case, picked from where two model labellers flagged a "
        "contradiction or disagreed (each card says which, after your first answer). Labeller A: "
        "Codex, gpt-6.2-sol, reasoning high. Labeller B: Gemini app, 4 Neon, thinking High. Your "
        "answers are final. They stay in this browser until you export them."
    )
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = (
        PAGE.replace("__TITLE__", html.escape("Rely-1 M1 review: model labels (Prithvi)"))
        .replace("__INTRO__", html.escape(intro))
        .replace("__DEF__", "".join(f"<li>{d}</li>" for d in DEFINITION))
        .replace("__SHEET__", SHEET)
        .replace("__DATA__", blob)
    )
    out = HERE / "review"
    (out / f"{SHEET}.html").write_text(page)
    (out / f"{SHEET}_artifact.html").write_text(as_artifact(page))
    print(intro)
    print(SHEET, (out / f"{SHEET}.html").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
