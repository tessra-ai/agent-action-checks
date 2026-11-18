"""Rely-1 M1: the first label set, pre-filled, and the two review sheets (README.md). Run once.

    python experiments/2026-11-18-rely1-m1/build.py

Train and dev only (M0 `runs/packets.jsonl`, packet v1). No test action is read.

1. Units: every agent sentence before the action, with a list item's lead-in (`units.py`).
2. Selection (M0 decision 6: the claims-check verdict only picks what to look at). Each earlier
   extracted claim is located in the unit(s) it was quoted from; a unit's stratum is the worst
   verdict among its claims: `mismatch` (any false), `unchecked` (any unverifiable), `matched`
   (all true), or `no_claim`. Every mismatch unit and every unit a ruling or grader quotes is
   taken; matched, unchecked and no-claim units are then sampled.
3. Pre-fill, never from the claims check: Prithvi's rulings and corrections, and the graders'
   reasons. A unit is *cited* when a reason quotes words that appear in it, *as false* when a
   falsity word sits in the quote's own clause, otherwise *as support*. Cited as false -> `MC`
   (records: contradicted, material: yes); cited as support only -> `not MC` (nothing else
   pre-filled: a support quote may be the grader's own inference); not cited on an action with a
   truth label -> `not MC`; otherwise none. Every action-level ruling and reason is shown next
   to the unit, cited or not.
4. Review sets: Prithvi reviews every unit pre-filled `MC` plus a random 40 of those pre-filled
   `not MC` (the gate compares the pre-fill with his labels on them); a
   second person labels a random 30 of Prithvi's set, blind (no pre-fill, rulings or reasons).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
EXP = HERE.parent
M0 = EXP / "2026-11-18-rely1-m0"
sys.path.insert(0, str(HERE))
from units import units  # noqa: E402

SEED = 20261118
SAMPLE = {"matched": 70, "unchecked": 60, "no_claim": 40}
PRITHVI_RANDOM = 40
SECOND = 30
LIMIT = 8192

PACKETS = M0 / "runs/packets.jsonl"
CLAIMS = [
    EXP / "2026-11-05-airline-holdout/results/claims_airline1_verified.jsonl",
    EXP / "2026-11-05-airline-holdout/results/claims_retail_verified.jsonl",
]
TOKENS = M0 / "results/token_lengths_v1.json"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def norm(s: str) -> str:
    s = s.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
    s = re.sub(r"[*`_]", "", s)
    s = re.sub(r"(^|\n)\s*(?:[-•]|\d+[.)])\s+", r"\1", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def pieces(text: str, cut_sentences: bool = False) -> list[str]:
    """A quote or a reason's quoted span, cut at ellipses and line breaks (and, for an extracted
    claim, at sentence ends, colons and semicolons, since one claim can span several units);
    pieces of 3+ words."""
    parts = re.split(r"\.\.\.|…|\n", text)
    if cut_sentences:
        parts = [q for p in parts for q in re.split(r"(?<=[.!?:;])\s+", p)]
    return [norm(p) for p in parts if len(norm(p).split()) >= 3]


# Quoted spans in free-text reasons: double quotes of any style, or single quotes that open after
# a space or bracket and close before punctuation or a space (so "customer's" does not open one).
QUOTED = re.compile(
    '["\u201c]([^"\u201d]{8,}?)["\u201d]'
    "|(?:(?<=[\\s(])|^)['\u2018]([^'\u2019]{8,}?)['\u2019](?=[\\s.,;:)!?]|$)"
)


def quoted_spans(reason: str) -> list[str]:
    return [a or b for a, b in QUOTED.findall(reason or "")]


# A reason quotes a statement either as false ("the agent wrongly claimed it was 'booked within
# 24 hours'") or as support ("the agent listed '3 checked bags' and the user said yes"). A
# falsity word in the quote's own clause decides. Review tooling only, never run time.
FALSITY = re.compile(
    r"\b(false(ly)?|wrong(ly)?|incorrect(ly)?|misstat\w*|mislead\w*|untrue|inaccurate|not true"
    r"|contradict\w*|never (said|quoted|stated|named|mentioned|told)|is not|was not|isn't"
    r"|wasn't|did not|didn't|does not|doesn't|claim\w*|despite)\b",
    re.I,
)


def cited_as_false(reason: str, span: str) -> bool:
    """A falsity word in the clause around the quote: the text from the previous comma,
    semicolon or sentence end to the next one, outside the quote itself. "The reason is 'change
    of plan', so …, and the claim that it was booked within 24 hours is false" does not mark
    'change of plan': the falsity words are in another clause."""
    i = reason.find(span)
    if i < 0:
        return False
    j = i + len(span)
    before = re.split(r"[,;:]\s|\.\s", reason[:i])[-1]
    after = re.split(r"[,;:]\s|\.\s|\.$", reason[j:].lstrip("'\"\u2019\u201d"))[0]
    return bool(FALSITY.search(before + " " + after))


# --------------------------------------------------------------------------------------------
# Rulings and reasons per action (airline 1 and retail; the person's and the graders').


def rulings() -> dict[str, list[dict]]:
    """{write_id: [{who, decision, reason}]}: graders' reasons (3 per graded airline action),
    the person's blind answers and his corrections. Retail has no graders."""
    out: dict[str, list[dict]] = {}
    d = EXP / "2026-10-28-airline-veto"
    key = {
        k["case"]: k["write_id"] for k in json.loads((d / "review/key.json").read_text())["cases"]
    }
    for g in jsonl(d / "results/grades.jsonl"):
        for label, reason in zip(g["labels"], g["reasons"], strict=False):
            out.setdefault(g["write_id"], []).append(
                {"who": "grader", "decision": label, "reason": reason}
            )
    for c, a in json.loads((d / "review/answers.json").read_text())["answers"].items():
        out.setdefault(key[c], []).append(
            {"who": "Prithvi (blind review)", "decision": a["decision"], "reason": a["reason"]}
        )
    for c in json.loads((d / "review/corrections.json").read_text())["corrections"]:
        out.setdefault(key[c["case"]], []).append(
            {"who": "Prithvi (correction)", "decision": c["corrected"], "reason": c["reason"]}
        )
    d = EXP / "2026-10-25-docent-vs-oracle"
    key = {
        k["case"]: k["write_id"] for k in json.loads((d / "review/key.json").read_text())["cases"]
    }
    for c, a in json.loads((d / "review/answers.json").read_text())["answers"].items():
        out.setdefault(key[c], []).append(
            {"who": "Prithvi (review)", "decision": a["decision"], "reason": a["reason"]}
        )
    return out


# --------------------------------------------------------------------------------------------


def locate(claim: dict, us: list[dict], conv_customer: str) -> tuple[list[str], str]:
    """The units a claim was extracted from. The complete quote is tried first; if no single
    unit holds it, it is cut into pieces (line breaks, ellipses, sentence ends, colons) and the
    claim goes to every unit that holds a piece. A piece found in several units goes to the
    latest one (flagged). Customer text and tool-call strings are not units (M0 rule R8)."""
    if re.match(r"^\w+\(\{", claim["quote"].strip()):
        return [], "tool call text"

    def holders(p: str) -> list[dict]:
        # A fragment found only in a list's lead-in belongs to the lead-in's own unit.
        return [u for u in us if quotes_unit(p, u)]

    whole = norm(claim["quote"])
    hits = holders(whole) if len(whole.split()) >= 3 else []
    if hits:
        many = len({u["id"] for u in hits}) > 1
        return [hits[-1]["id"]], "several units, latest taken" if many else "one unit"
    found: list[str] = []
    repeated = False
    for p in pieces(claim["quote"], cut_sentences=True):
        hits = holders(p)
        repeated |= len({u["id"] for u in hits}) > 1
        if hits and hits[-1]["id"] not in found:
            found.append(hits[-1]["id"])
    if found:
        how = "spans units" if len(found) > 1 else "one unit"
        return found, how + (" (a piece in several units, latest taken)" if repeated else "")
    ps = pieces(claim["quote"], cut_sentences=True)
    if not ps:
        return [], "too short"
    if any(p in norm(conv_customer) for p in ps):
        return [], "customer text"
    return [], "not found"


def quotes_unit(piece: str, u: dict) -> bool:
    """A quoted piece cites a unit when it reaches into the unit's own text. A quote of a list
    lead-in alone cites the lead-in's own unit, not every list item under it."""
    text_n = norm(u["text"])
    full_n = norm((u["lead_in"] or "") + " " + u["text"])
    return piece in text_n or (piece in full_n and piece not in norm(u["lead_in"] or ""))


def main() -> None:
    out_path = HERE / "results/label_set.jsonl"
    if out_path.exists():
        raise SystemExit("label set exists; built once")
    train = {r["write_id"] for r in json.loads((M0 / "splits/train.json").read_text())}
    dev = {r["write_id"] for r in json.loads((M0 / "splits/dev.json").read_text())}
    packets = {p["write_id"]: p for p in map(json.loads, PACKETS.read_text().splitlines())}
    if set(packets) != train | dev:
        raise SystemExit("M0 packets must be exactly train + dev (rebuild with M0 packets.py)")
    if {p["packet_version"] for p in packets.values()} != {"rely1-packet-v1"}:
        raise SystemExit("packet v1 required")
    tok = json.loads(TOKENS.read_text())
    if tok["packets_sha256"] != hashlib.sha256(PACKETS.read_bytes()).hexdigest():
        raise SystemExit("token counts are for another packet file; rerun M0 tokens.py")
    tokens = {r["write_id"]: r["state_tokens"] for r in tok["rows"]}
    claims = {
        r["write_id"]: r["claims"] for f in CLAIMS for r in jsonl(f) if r["write_id"] in packets
    }
    reasons = rulings()

    rows = []
    located = Counter()
    for w, p in packets.items():
        us = units(p)
        customer = " ".join(t["text"] for t in p["conversation"] if t["role"] == "customer")
        by_unit: dict[str, list[dict]] = {}
        for c in claims.get(w, []):
            uids, how = locate(c, us, customer)
            located[(how, c["verdict"])] += 1
            for uid in uids:
                by_unit.setdefault(uid, []).append({**c, "located": how})
        rs = reasons.get(w, [])
        truth = p["meta"]["truth"]
        for u in us:
            cs = by_unit.get(u["id"], [])
            verdicts = {c["verdict"] for c in cs}
            stratum = (
                "mismatch"
                if "false" in verdicts
                else "unchecked"
                if "unverifiable" in verdicts
                else "matched"
                if verdicts
                else "no_claim"
            )
            cited = []
            for r in rs:
                for span in quoted_spans(r["reason"]):
                    if any(quotes_unit(pc, u) for pc in pieces(span)):
                        cited.append(
                            {**r, "span": span, "as_false": cited_as_false(r["reason"], span)}
                        )
            as_false = [c for c in cited if c["as_false"]]
            # Only a quote called false says something about the records and the yes; a quote used
            # as support may be the grader's own inference, so it pre-fills neither.
            material = "yes" if as_false else None
            records = "contradicted" if as_false else None
            if as_false:
                prefill, src = "MC", sorted({c["who"] + ", quoted as false" for c in as_false})
            elif cited:
                prefill, src = "not MC", sorted({c["who"] + ", quoted as support" for c in cited})
            elif truth is not None and rs:
                prefill, src = "not MC", ["ruled; no reason quotes it"]
            elif truth is not None:
                prefill, src = "not MC", ["action has a truth label; no written reasons"]
            else:
                prefill, src = None, []
            rows.append(
                {
                    "unit_key": f"{w}:{u['id']}",
                    "write_id": w,
                    "split": "train" if w in train else "dev",
                    "domain": p["domain"],
                    "task_id": p["meta"]["task_id"],
                    "unit": u,
                    "stratum": stratum,
                    "claims": [
                        {k: c[k] for k in ("kind", "scope", "verdict", "quote", "located")}
                        for c in cs
                    ],
                    "action_truth": None
                    if truth is None
                    else ("good" if truth["should_run"] else "bad"),
                    "length": "over_8192" if tokens[w] > LIMIT else "under_8192",
                    "prefill": prefill,
                    "prefill_material": material,
                    "prefill_records": records,
                    "prefill_source": src,
                    "cited_by": cited,
                }
            )

    rng = random.Random(SEED)
    # Every mismatch unit, and every unit a ruling or grader quotes, whatever its stratum.
    chosen = [r for r in rows if r["stratum"] == "mismatch" or r["cited_by"]]
    for r in chosen:
        r["chosen_because"] = "mismatch" if r["stratum"] == "mismatch" else "cited by a reason"
    for stratum, n in SAMPLE.items():
        pool = [r for r in rows if r["stratum"] == stratum and r not in chosen]
        picked = rng.sample(pool, min(n, len(pool)))
        for r in picked:
            r["chosen_because"] = f"sample of {stratum}"
        chosen += picked
    chosen.sort(key=lambda r: (r["write_id"], r["unit"]["turn"], r["unit"]["id"]))

    mc = [r for r in chosen if r["prefill"] == "MC"]
    # The gate compares pre-fill with Prithvi on the random 40, so they are drawn from units that
    # have a pre-fill; units with none (ungraded actions) stay in the label set.
    rest = [r for r in chosen if r["prefill"] == "not MC"]
    prithvi = mc + rng.sample(rest, min(PRITHVI_RANDOM, len(rest)))
    second = rng.sample(prithvi, min(SECOND, len(prithvi)))
    for r in chosen:
        r["review"] = {
            "prithvi": r in prithvi,
            "prithvi_reason": "pre-filled MC"
            if r in mc
            else ("random 40" if r in prithvi else None),
            "second": r in second,
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in chosen)
    )

    def combo(rs: list[dict]) -> dict:
        c = Counter(
            (
                r["stratum"],
                r["prefill"] or "none",
                r["action_truth"] or "ungraded",
                r["length"],
                r["split"],
            )
            for r in rs
        )
        return {" | ".join(k): v for k, v in sorted(c.items())}

    summary = {
        "seed": SEED,
        "label_set_sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        "packets_sha256": tok["packets_sha256"],
        "units_in_train_dev": len(rows),
        "units_by_stratum": dict(Counter(r["stratum"] for r in rows)),
        "claims_located": {f"{h} | {v}": n for (h, v), n in sorted(located.items())},
        "chosen": len(chosen),
        "chosen_by_stratum": dict(Counter(r["stratum"] for r in chosen)),
        "chosen_because": dict(Counter(r["chosen_because"] for r in chosen)),
        "chosen_by_prefill": dict(Counter(r["prefill"] or "none" for r in chosen)),
        "prithvi_set": len(prithvi),
        "prithvi_prefilled_mc": len(mc),
        "second_set": len(second),
        "combinations": combo(chosen),
        "combination_key": "stratum | prefill | action truth | length | split",
    }
    (HERE / "results/summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "combinations"}, indent=1))


if __name__ == "__main__":
    main()
