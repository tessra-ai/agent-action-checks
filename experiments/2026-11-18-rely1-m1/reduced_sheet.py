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
from friend import action_tokens, focused, lookup_turns, norm_tokens, relevant  # noqa: E402
from sheet import DEFINITION, action, as_artifact  # noqa: E402

SHEET = "prithvi_reduced"
PAGE = (HERE / "reduced_template.html").read_text()
# Neutral headings and a seeded shuffle inside each block: neither the heading nor the position
# says which group an item came from (both yes, disagreement); that shows only after the blind
# answer (Codex review, 2026-11-20).
SEED = 20261118
# Cards are grouped by action (one conversation and ledger read once), actions in a seeded
# shuffle, statements before the action's agreement question (Prithvi, 2026-11-20).
BLOCKS = {
    "actions": "Actions",
    "gaming_mouse": "Shown separately: the Gaming Mouse case",
}
WHY = {
    "both yes": "both labellers marked it a material contradiction",
    "statement disagreement": "the labellers disagree",
    "agreement disagreement, action has a flagged statement": "the labellers disagree on "
    "agreement, and the action holds a statement either labeller flagged",
}
BLOCK_NOTES = {
    "actions": "Each action's cards are together: read its conversation once. Keys: Y / N / U "
    "answer the current card's first question, Enter shows the labellers' answers when allowed, "
    "J / K move to the next / previous card.",
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


def key_records(packet: dict, text: str, lead_in: str | None, turn: int) -> list[dict]:
    """The 3 lookups that best match the sentence (or the call), trimmed to matching fields;
    review tooling only, the full ledger stays on the card (friend.py's matching)."""
    want = norm_tokens(text) | norm_tokens(lead_in or "")
    want |= action_tokens(packet["proposed_action"]["arguments"])
    when = lookup_turns(packet)
    return [
        {
            "n": e["n"],
            "tool": e["tool"],
            "arguments": e["arguments"],
            "made": "a change the agent made" if e["kind"] == "write" else "a lookup",
            "when": "before" if when.get(e["n"], 0) < turn else "after",
            "focus": focused(e["result"], want),
            "error": e["error"],
        }
        for e in relevant(packet, text, lead_in, turn, k=3)
    ]


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
        block = "actions"
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
                "records": key_records(packets[w], u["text"], u["lead_in"], u["turn"]),
            }
        else:
            g = current[w]
            pa = packets[w]["proposed_action"]
            it |= {
                "kind": "agreement",
                "question": QUESTIONS["agreement"][0][1],
                "current": f"{g['agreed']} ({g['source']}): {g['reason']}",
                "records": key_records(
                    packets[w],
                    json.dumps(pa["arguments"]),
                    None,
                    len(packets[w]["conversation"]) + 1,
                ),
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
            "records": key_records(
                packets[gm["write_id"]],
                json.dumps(packets[gm["write_id"]]["proposed_action"]["arguments"]),
                None,
                len(packets[gm["write_id"]]["conversation"]) + 1,
            ),
        }
    )
    import random

    order = list(BLOCKS)
    actions = sorted({x["write_id"] for x in items if x["block"] == "actions"})
    random.Random(SEED).shuffle(actions)
    rank = {w: n for n, w in enumerate(actions)}

    def qnum(i: str) -> int:
        tail = i.split(".")[1]
        return int(tail[1:]) if tail.startswith("S") else 10_000

    items.sort(key=lambda x: (order.index(x["block"]), rank.get(x["write_id"], 0), qnum(x["id"])))
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
    counts = {
        "statement": sum(1 for x in items if x["kind"] == "statement"),
        "agreement": sum(1 for x in items if x["block"] == "actions" and x["kind"] == "agreement"),
    }
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
    # Answers given on an earlier version of this sheet (same items, other layout) carry over:
    # the page imports them from browser storage or an exported file under these fingerprints.
    prev = out / f"{SHEET}.html"
    if prev.exists():
        import re as _re

        old_html = prev.read_text()
        m = _re.search(r'"items_sha256": "([0-9a-f]{64})"', old_html)
        blob = _re.search(r"const DATA = (.*?);\nconst (SHEET|PRIOR)", old_html, _re.S)
        old = json.loads(blob.group(1).replace("<\\/", "</")) if blob else {}
        # Layout-only change: the same items with the same content, actions and policy; only
        # presentation fields (block, records shown, headings, order) may differ.
        content = (
            "key", "kind", "write_id", "text", "lead_in", "turn", "A", "B", "current",
            "prefilled_mc", "cited_by",
        )  # fmt: skip

        def sig(xs: list[dict]) -> list[str]:
            return sorted(json.dumps([x.get(c) for c in content]) for x in xs)

        same = (
            bool(old)
            and sig(old["items"]) == sig(items)
            and old.get("actions") == acts
            and old.get("policy") == policy
        )
        known = (
            set(json.loads((out / f"{SHEET}_versions.json").read_text()))
            if (out / f"{SHEET}_versions.json").exists()
            else set()
        )
        if m and m.group(1) != fingerprint and same:  # carry over only after layout changes
            known.add(m.group(1))
        (out / f"{SHEET}_versions.json").write_text(json.dumps(sorted(known)) + "\n")
    prior = (
        json.loads((out / f"{SHEET}_versions.json").read_text())
        if (out / f"{SHEET}_versions.json").exists()
        else []
    )
    page = page.replace("__PRIOR__", json.dumps(prior))
    (out / f"{SHEET}.html").write_text(page)
    (out / f"{SHEET}_artifact.html").write_text(as_artifact(page))
    print(intro)
    print(SHEET, (out / f"{SHEET}.html").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
