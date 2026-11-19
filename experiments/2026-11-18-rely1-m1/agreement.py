"""Per-action agreement labels for train + dev (Prithvi's decision, 2026-11-18). Run once.

    python experiments/2026-11-18-rely1-m1/agreement.py

The label: did the customer agree to this exact action (yes / no), and which customer messages
carry the agreement. The agreement runs from the yes through any later message that only adjusts
a detail (picking a card). It replaces M0's single consent-turn marker, which is no longer part
of the packet. Actions with no agreement are left out of the material-contradiction labels and
reported as their own group.

Sources:
1. `prithvi`: Prithvi's ruling on the 13 actions whose last customer message has no "yes"
   (M0 `review/consent_13.json`): 7 agreed, 6 did not. Final.
2. `prefill`, for Prithvi's review on his sheet; a label only after he answers it. Two kinds
   (`basis`):
   - `rule`: a code pre-fill of "yes" when the last customer message opens with a clear yes and
     has no hedge, refusal or question; no write ran between it and this call; and the agent's
     confirmation right before it (or the yes itself) names every identifying argument of the call
     (reservation, order, item and flight IDs, each as often as the call uses it) and every date.
     Until 2026-11-19 this was a final label; the Codex pre-commit review kept finding calls it
     let through that differed from the yes (a wider cabin change, a different date, payment
     terms), so on Prithvi's decision it no longer bypasses review.
   - `read`: a Claude reading against a written rubric (`review/agreement_prefill.json`).
   Until Prithvi answers, pre-filled `no` is applied provisionally.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
M0 = HERE.parent / "2026-11-18-rely1-m0"
OUT = HERE / "results/agreement.jsonl"

YES = re.compile(
    r"^\W*(yes|yeah|yep|sure|ok(ay)?|correct|that'?s (correct|right)"
    r"|please (go ahead|proceed)|go ahead|i confirm|confirmed|all (the )?details are correct"
    r"|everything looks (correct|good))\b",
    re.I,
)
HEDGE = re.compile(
    r"\b(no|not|don'?t|doesn'?t|instead|but|wait|actually|if|however|only|except|keep|change"
    r"|why|how|what)\b|\?",
    re.I,
)
SKIP_KEYS = {
    "user_id", "payment_id", "payment_method_id", "reason", "cabin", "flight_type", "insurance",
    "origin", "destination", "first_name", "last_name", "dob",
}  # fmt: skip

# Prithvi's ruling on the 13 (M0 review/consent_13.json), with the turns that carry the
# agreement (for the 7) or show the refusal / mismatch (for the 6).
PRITHVI_13 = {
    "01M61PXM3NRZ465H5C04ZSK9HS": ("yes", [31, 34]),
    "01M61PXMEYT40YTMG6Z2179RRR": ("yes", [31, 34]),
    "01M61Q71WGYZWHH0AW1FCWVKP6": ("yes", [18, 22]),
    "01M61Q95BW3S5HF0MZV7BCFSZS": ("yes", [16, 19]),
    "01M61Q96DSP7Z14FDFD7DBCK08": ("yes", [22, 24]),
    "01M5JZ4HDTBD3TFZNSCV5SF34S": ("yes", [13]),
    "01M5JZ91W7FWACM25ZX0E5W1KG": ("yes", [18]),
    "01M5JZ53BEFJZ298SGE8SY5R9V": ("no", [13]),
    "01M61Q1KSECAJ17000CGCZRZ6J": ("no", [7]),
    "01M5JZ53HDAV2K8DP4RDA51Y1V": ("no", [13]),
    "01M5JZ5BZQ37Z0YKPTD97HJA3A": ("no", [24]),
    "01M5JZ4D5E6CMP314QYVP9GPAN": ("no", [4]),
    "01M61QBD9PW1G7Y0B2Y885TT4F": ("no", [10]),
}


def identifiers(args: object) -> list[str]:
    """Identifying argument values, with repeats: a flight number used on two legs counts twice."""
    out: list[str] = []

    def walk(v: object, k: str | None = None) -> None:
        if isinstance(v, dict):
            for kk, vv in v.items():
                walk(vv, kk)
        elif isinstance(v, list):
            for x in v:
                walk(x, k)
        elif isinstance(v, str) and len(v) >= 5 and k not in SKIP_KEYS:
            out.append(v.lstrip("#"))

    walk(args)
    return out


ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
MONTHS = "January February March April May June July August September October November December"


def mentions(text: str, value: str) -> int:
    """How often a value is named; an ISO date also counts as "May 28" / "May 28th"."""
    n = text.count(value)
    m = re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", value)
    if m:
        month = MONTHS.split()[int(m.group(1)) - 1]
        n += len(re.findall(rf"\b{month} 0?{int(m.group(2))}(?:st|nd|rd|th)?\b", text))
    return n


def obvious(p: dict) -> int | None:
    """The T number of the agreeing message when the rule applies, else None."""
    turns = p["conversation"]
    last = max(i for i, t in enumerate(turns) if t["role"] == "customer")
    text = turns[last]["text"]
    if not YES.search(text) or HEDGE.search(text):
        return None
    after = [n for t in turns[last + 1 :] for n in t.get("ledger_refs", [])]
    if any(p["ledger"][n - 1]["kind"] == "write" for n in after):
        return None
    prev = max([i for i, t in enumerate(turns[:last]) if t["role"] == "customer"], default=-1)
    confirmation = " ".join(t["text"] for t in turns[prev + 1 : last] if t["role"] == "agent")
    # Every identifying argument (reservation, order, item and flight IDs) must be named in the
    # confirmation or the yes: one shared identifier does not show agreement to the whole call
    # (a yes to upgrading the outbound flight does not cover a call that upgrades both legs).
    # Each must appear at least as often as the call uses it, so a call that books the same
    # flight on both legs is not covered by a confirmation that names it once. Dates must be
    # named too, written either way ("2024-05-28" or "May 28"), but once is enough: two legs on
    # one day share it.
    said = confirmation + " " + text
    ids = Counter(identifiers(p["proposed_action"]["arguments"]))
    if not ids or any(mentions(said, i) < (1 if ISO.fullmatch(i) else n) for i, n in ids.items()):
        return None
    return last + 1


def main() -> None:
    if OUT.exists():
        raise SystemExit("agreement labels exist; built once")
    packets = [json.loads(x) for x in (M0 / "runs/packets.jsonl").read_text().splitlines()]
    prefill = {
        r["write_id"]: r for r in json.loads((HERE / "review/agreement_prefill.json").read_text())
    }
    rows = []
    for p in packets:
        w = p["write_id"]
        if w in PRITHVI_13:
            agreed, turns = PRITHVI_13[w]
            row = {
                "agreed": agreed,
                "turns": turns,
                "source": "prithvi",
                "reason": "consent_13 ruling",
            }
        elif (t := obvious(p)) is not None:
            row = {
                "agreed": "yes",
                "turns": [t],
                "source": "prefill",
                "basis": "rule",
                "reason": "code rule: a clear yes, with the confirmation naming every identifier "
                "and date of the call (payment amounts and the operation are not checked)",
            }
        else:
            r = prefill[w]
            row = {
                "agreed": r["agreed"],
                "turns": r["turns"],
                "source": "prefill",
                "basis": "read",
                "reason": r["reason"],
            }
            if r.get("note"):
                row["note"] = r["note"]
        rows.append({"write_id": w, "domain": p["domain"], "task_id": p["meta"]["task_id"], **row})
    missing = {r["write_id"] for r in rows if r.get("basis") == "read"} ^ set(prefill)
    if missing:
        raise SystemExit(
            f"pre-fill and rule disagree on which actions need a reading: {sorted(missing)}"
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    c = Counter((r["source"], r.get("basis", "-"), r["agreed"]) for r in rows)
    print(len(rows), dict(sorted(c.items())))


if __name__ == "__main__":
    sys.exit(main())
