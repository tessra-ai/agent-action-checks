"""Plain-language cards for the second labeller's sheet (Prithvi, 2026-11-18).

Each card shows only what the labeller needs: the customer's request, their last message before
the action, the agent's sentence (with its list lead-in), the most relevant company record, and
the action, written out as words. The full conversation and every lookup sit behind "Show more".

"Most relevant record" is review tooling, not part of the model: the lookups whose results share
the most identifiers and numbers with the sentence and the action (generic token overlap; no rule
for any kind of statement). Nothing here reads a label, pre-fill, ruling or reason.
"""

from __future__ import annotations

import json
import re

TOKEN = re.compile(r"\$?\d[\d,]*(?:\.\d+)?|#?[A-Z0-9]{5,}|[a-z]+_[a-z]+_\d+|[a-z]+_\d{5,}")


def words(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def flat(value: object, prefix: str = "") -> list[str]:
    """JSON as readable "key: value" lines."""
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            key = f"{prefix} {k.replace('_', ' ')}".strip()
            out += flat(v, key)
        return out
    if isinstance(value, list):
        if all(not isinstance(x, (dict, list)) for x in value):
            return [
                f"{prefix}: {', '.join(map(str, value))}" if prefix else ", ".join(map(str, value))
            ]
        out = []
        for i, v in enumerate(value, start=1):
            out += flat(v, f"{prefix} {i}".strip())
        return out
    return [f"{prefix}: {value}" if prefix else str(value)]


def readable(text: str | None, limit: int = 40) -> str:
    try:
        lines = flat(json.loads(text or ""))
    except (ValueError, TypeError):
        lines = [(text or "").strip()]
    if len(lines) > limit:
        lines = [*lines[:limit], f"… ({len(lines) - limit} more lines under Show more)"]
    return "\n".join(lines)


KEEP_KEYS = re.compile(
    r"\b(name|prices?|amount|status|payment|balance|total|cabin|date|flight number|origin"
    r"|destination|item id|reservation id|order id|insurance|baggages?|created at|error)\b"
)


def focused(text: str | None, want: set[str], limit: int = 18) -> str:
    """The record's lines that share a value with the sentence or the action, plus the lines a
    reader needs to make sense of them (names, prices, amounts, status, dates, payment)."""
    try:
        value = json.loads(text or "")
    except (ValueError, TypeError):
        return readable(text, limit)
    if isinstance(value, list):  # a search result: keep the entries that match best
        scores = [len(norm_tokens(json.dumps(v)) & want) for v in value]
        if scores and max(scores) > 0:
            value = [v for v, sc in zip(value, scores, strict=True) if sc == max(scores)]
    lines = flat(value)
    personal = re.compile(r"\b(first name|last name|dob|address|email|phone)\b")
    keep = [
        ln
        for ln in lines
        if (norm_tokens(ln) & want or KEEP_KEYS.search(ln.split(":", 1)[0].strip()))
        and not personal.search(ln.split(":", 1)[0])
    ]
    if len(keep) > limit:
        keep = [*keep[:limit], f"… ({len(keep) - limit} more lines under Show more)"]
    elif len(keep) < len(lines):
        keep.append("(other details under Show more)")
    return "\n".join(keep)


def norm_tokens(text: str) -> set[str]:
    """Identifiers and amounts; bare numbers under three digits (counts, flags) match too much."""
    out = set()
    for t in TOKEN.findall(text or ""):
        v = t.lstrip("#$").replace(",", "")
        if v.isdigit() and len(v) < 3 and not t.startswith("$"):
            continue
        out.add(v)
    return out


IDENTITY = {"user_id", "payment_id", "payment_method_id", "first_name", "last_name", "dob"}


def action_tokens(args: object) -> set[str]:
    """Tokens of the call's arguments, leaving out who pays and who travels: those match the
    customer's profile, not the record a statement is about."""
    out: set[str] = set()

    def walk(v: object, k: str | None = None) -> None:
        if isinstance(v, dict):
            for kk, vv in v.items():
                walk(vv, kk)
        elif isinstance(v, list):
            for x in v:
                walk(x, k)
        elif k not in IDENTITY:
            out.update(norm_tokens(str(v)))

    walk(args)
    return out


def action_text(a: dict) -> str:
    return words(a["tool"]) + "\n" + "\n".join(flat(a["arguments"]))


def lookup_turns(packet: dict) -> dict[int, int]:
    """{ledger entry n: the T number of the agent turn that made the lookup}."""
    return {
        n: i
        for i, t in enumerate(packet["conversation"], start=1)
        for n in t.get("ledger_refs") or []
    }


def relevant(packet: dict, sentence: str, lead_in: str | None, turn: int, k: int = 2) -> list[dict]:
    """The best-matching lookups, preferring those made before the sentence (what the agent
    knew when it spoke) over later ones, which can reflect a change the agent made since."""
    said = norm_tokens(sentence) | norm_tokens(lead_in or "")
    acted = action_tokens(packet["proposed_action"]["arguments"])
    when = lookup_turns(packet)
    scored = []
    for e in packet["ledger"]:
        if e["result"] is None or str(e["result"]).startswith("(same as L"):
            continue
        have = norm_tokens(str(e["result"])) | norm_tokens(json.dumps(e["arguments"]))
        s = 3 * len(said & have) + len(acted & have)
        if s:
            before = when.get(e["n"], 0) < turn
            scored.append((before, s, e["n"], e))
    scored.sort(key=lambda x: (not x[0], -x[1], -x[2]))
    return [e for *_, e in scored[:k]]


def card(packet: dict, unit: dict, key: str) -> dict:
    conv = packet["conversation"]
    customers = [t["text"] for t in conv if t["role"] == "customer"]
    recs = relevant(packet, unit["text"], unit["lead_in"], unit["turn"])
    when = lookup_turns(packet)
    want = norm_tokens(unit["text"]) | norm_tokens(unit["lead_in"] or "")
    want |= action_tokens(packet["proposed_action"]["arguments"])
    record = (
        "\n\n".join(
            f"{words(e['tool'])}"
            + (f" ({', '.join(flat(e['arguments']))})" if e["arguments"] else "")
            + "\n["
            + ("A change the agent made" if e["kind"] == "write" else "Looked up")
            + (" before" if when.get(e["n"], 0) < unit["turn"] else " after")
            + f" the agent said this]\n{focused(e['result'], want)}"
            for e in recs
        )
        if recs
        else "No single record matched this sentence. Everything the agent looked up is under "
        "Show more."
    )
    turns = []
    for t in conv:
        text = t["text"].strip() or "(looked something up)"
        refs = t.get("ledger_refs") or []
        if refs:
            text += " [lookups " + ", ".join(f"L{n}" for n in refs) + "]"
        turns.append({"who": "Customer" if t["role"] == "customer" else "Agent", "text": text})
    all_records = "\n\n".join(
        f"L{e['n']} {words(e['tool'])} ({', '.join(flat(e['arguments'])) or 'no details'})\n"
        f"{readable(e['result'], limit=10_000)}"
        for e in packet["ledger"]
    )  # complete, with what was looked up: "Show more" is where the full evidence lives
    return {
        "key": key,
        "domain": packet["domain"],
        "request": customers[0] if customers else "",
        "last_customer": customers[-1] if customers else "",
        "text": unit["text"],
        "lead_in": unit["lead_in"],
        "record": record,
        "action": action_text(packet["proposed_action"]),
        "conversation": turns,
        "all_records": all_records,
    }
