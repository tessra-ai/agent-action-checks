"""Stock Jev on the agreement question; both questions per action (Prithvi, 2026-11-20).
PROVISIONAL, MODEL-LABELLED: truth is the labellers' consensus; the good / bad rulings are the
existing action labels. Train and dev only.

    python stock_agreement.py build        # -> runs/stock_models/requests_agreement.jsonl
    python stock_models.py run --name jev_agreement --model jev-1.14.0 --key-env TYPESAFE_API_KEY \\
        --requests runs/stock_models/requests_agreement.jsonl --out runs/stock_models/agreement
    python stock_agreement.py summarize    # -> results/stock_agreement.json

`build` writes one System One request per action (all 174): the state is the packet text the
labellers saw, without its "# Questions" list; one yes/no ("noul") question whose instructions
are the labellers' agreement wording (prompt.txt, "QUESTION TYPE 2") verbatim. P(yes) is
P(agreed).

`summarize` reports:
1. Jev vs the labellers' agreement consensus (both agreed vs both not agreed): AUC, and at
   P(agreed) cut-offs how many of each side Jev calls not agreed.
2. Jev and the consensus against the good / bad rulings.
3. Both questions at the action level: an action is stopped when any of its statements is a
   contradiction or the customer did not agree. For the consensus: a both-yes statement, or both
   labellers not agreed. For Jev: P(contradiction) >= s on any statement, or P(agreed) < a, over a
   small grid of s and a. by_*_any counts overlap (an action can be stopped by both). Bad
   actions caught and good actions stopped, ungraded apart. Only the
   label-set statements were asked, so an action's other sentences are not checked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE / "runs/labeller_pack"
OUT = HERE / "runs/stock_models"
R = HERE / "results"
M0 = HERE.parent / "2026-11-18-rely1-m0"
AGREE_CUTS = (0.3, 0.5, 0.7)
STMT_CUTS = (0.5, 0.7, None)  # None: statements not used
AGREE_GRID = (0.3, 0.5, None)  # None: agreement not used


def agreement_wording() -> str:
    text = (PACK / "prompt.txt").read_text(encoding="utf-8")
    start = text.index("QUESTION TYPE 2: AGREEMENT")
    end = text.index('Allowed answers: "agreed", "not_agreed", "not_sure".', start)
    body = text[start:end].split("\n", 1)[1].strip()
    return body + "\n\nAnswer yes (agreed) or no (not agreed)."


def build() -> None:
    m = json.loads((PACK / "manifest.json").read_text())
    wording = agreement_wording()
    lines = []
    for c in m["calls"]:
        if not c["call"].endswith("-A"):
            continue
        text = (PACK / c["file"]).read_text(encoding="utf-8")
        state = text.split("\n# Questions\n", 1)[0].rstrip() + "\n"
        qid = c["questions"][0]["id"].replace(".", "_")
        lines.append(
            {
                "call": c["call"],
                "state": state,
                "questions": {qid: {"type": "noul", "instructions": wording}},
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "requests_agreement.jsonl"
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
    print(len(lines), "requests ->", path)


def replies(folder: Path) -> dict[str, float]:
    out = {}
    for f in folder.glob("P*-*.json"):
        for name, ans in json.loads(f.read_text())["response"]["answers"].items():
            out[name.replace("_", ".", 1)] = float(ans["noul"])
    return out


def auc(pos: list[float], neg: list[float]) -> float | None:
    pairs = len(pos) * len(neg)
    if not pairs:
        return None
    return round(sum((x > y) + 0.5 * (x == y) for x in pos for y in neg) / pairs, 3)


def summarize() -> None:
    a = {r["id"]: r for r in map(json.loads, (R / "labels_a.jsonl").read_text().splitlines())}
    b = {r["id"]: r for r in map(json.loads, (R / "labels_b.jsonl").read_text().splitlines())}
    key = json.loads((R / "pack_key.json").read_text())
    packets = {
        p["write_id"]: p
        for p in map(json.loads, (M0 / "runs/packets.jsonl").read_text().splitlines())
    }
    p_agree = replies(OUT / "agreement/jev_agreement")
    p_stmt = replies(OUT / "jev")
    if len(p_agree) != len(key):
        raise SystemExit(f"Jev answered {len(p_agree)} of {len(key)} agreement questions")

    ruled = {}
    for pid, v in key.items():
        t = packets[v["write_id"]]["meta"]["truth"]
        ruled[pid] = "ungraded" if t is None else ("good" if t["should_run"] else "bad")
    cons = {
        pid: a[f"{pid}.A"]["answer"] if a[f"{pid}.A"]["answer"] == b[f"{pid}.A"]["answer"] else None
        for pid in key
    }
    agreed = [pid for pid, c in cons.items() if c == "agreed"]
    not_agreed = [pid for pid, c in cons.items() if c == "not_agreed"]
    pa = lambda pid: p_agree[f"{pid}.A"]  # noqa: E731

    out: dict = {
        "status": "PROVISIONAL, MODEL-LABELLED: truth is the labellers' consensus (A: Codex "
        "gpt-6.2-sol reasoning high; B: Gemini 4 Neon High); rulings are the existing action "
        "labels. Train and dev only. Stock Jev (jev-1.14.0), untrained.",
        "agreement_vs_consensus": {
            "both_agreed": len(agreed),
            "both_not_agreed": len(not_agreed),
            "labellers_split": sum(1 for c in cons.values() if c is None),
            "auc_not_agreed": auc([1 - pa(p) for p in not_agreed], [1 - pa(p) for p in agreed]),
            **{
                f"called_not_agreed_if_P(agreed)<{c}": {
                    "of_both_not_agreed": sum(pa(p) < c for p in not_agreed),
                    "of_both_agreed": sum(pa(p) < c for p in agreed),
                }
                for c in AGREE_CUTS
            },
        },
    }
    by_ruling = {}
    for r in ("bad", "good", "ungraded"):
        ps = [p for p in key if ruled[p] == r]
        by_ruling[r] = {
            "n": len(ps),
            "labellers_both_not_agreed": sum(cons[p] == "not_agreed" for p in ps),
            **{f"jev_P(agreed)<{c}": sum(pa(p) < c for p in ps) for c in AGREE_CUTS},
        }
    out["agreement_vs_rulings"] = by_ruling

    stmts = {pid: [q for q in v["questions"] if ".S" in q] for pid, v in key.items()}
    both_yes = {q for qs in stmts.values() for q in qs if a[q]["answer"] == b[q]["answer"] == "yes"}
    missing = [q for qs in stmts.values() for q in qs if q not in p_stmt]
    if missing:
        raise SystemExit(
            f"Jev statement scores missing for {len(missing)} statements, e.g. {missing[:3]}"
        )

    def stopped_consensus(pid: str) -> bool:
        return any(q in both_yes for q in stmts[pid]) or cons[pid] == "not_agreed"

    combined = {"labellers_consensus": {}, "jev": {}}
    for r in ("bad", "good", "ungraded"):
        ps = [p for p in key if ruled[p] == r]
        combined["labellers_consensus"][r] = {
            "n": len(ps),
            "stopped": sum(stopped_consensus(p) for p in ps),
            "by_statement_any": sum(any(q in both_yes for q in stmts[p]) for p in ps),
            "by_agreement_any": sum(cons[p] == "not_agreed" for p in ps),
        }
    for s in STMT_CUTS:
        for g in AGREE_GRID:
            if s is None and g is None:
                continue
            name = f"stmt>={s}" if s is not None else "stmt off"
            name += f", P(agreed)<{g}" if g is not None else ", agreement off"
            row = {}
            for r in ("bad", "good", "ungraded"):
                ps = [p for p in key if ruled[p] == r]
                row[r] = sum(
                    (s is not None and any(p_stmt.get(q, 0) >= s for q in stmts[p]))
                    or (g is not None and pa(p) < g)
                    for p in ps
                )
            combined["jev"][name] = {
                "bad_caught": row["bad"],
                "good_stopped": row["good"],
                "ungraded_stopped": row["ungraded"],
            }
    out["both_questions_per_action"] = combined
    out["cost"] = {
        "agreement_input_tokens": sum(
            (json.loads(f.read_text())["response"].get("usage") or {}).get("input_tokens", 0)
            for f in (OUT / "agreement/jev_agreement").glob("P*-A.json")
        )
    }
    out["cost"]["agreement_usd"] = round(out["cost"]["agreement_input_tokens"] * 0.042e-6, 4)
    (R / "stock_agreement.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


def main() -> None:
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:] == ["summarize"]:
        summarize()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
