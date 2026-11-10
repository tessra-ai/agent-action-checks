"""Plan-level re-verification of extracted claims (README.md, Method).

`plan_verdict` takes a claim, the write's own call, the other calls of its plan, the per-call
`verify` function of the domain and a small domain adapter, and returns the per-call verdict
unchanged unless it was false and one of the three plan rules (other, sum, union) holds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

TOLERANCE = 0.01
PAYMENT_FIELDS = ("payment_id", "payment_method_id", "payment_methods")
MONEY_KINDS = ("refund", "charge", "price_quote", "cabin_change_cost")

Call = tuple[str, Mapping[str, Any], Mapping[str, Any]]  # action, args, pre-action db


def _key(action: str, args: Mapping[str, Any]) -> str:
    """The call without its payment fields."""
    return action + json.dumps(
        {k: v for k, v in args.items() if k not in PAYMENT_FIELDS}, sort_keys=True
    )


def plan_calls(
    own: tuple[str, int, str, Mapping[str, Any]],
    session: Sequence[tuple[str, int, Call]],
    so_far: bool,
) -> list[Call]:
    """The other calls of the plan: (write_id, seq, call) rows of one conversation, minus the
    write itself and its retries; only earlier ones when `so_far`."""
    write_id, seq, action, args = own
    out: list[Call] = []
    seen = {_key(action, args)}  # the write itself and its retries
    for w, s, call in sorted(session, key=lambda r: r[1]):
        if w == write_id or (so_far and s >= seq) or _key(call[0], call[1]) in seen:
            continue
        seen.add(_key(call[0], call[1]))  # a retry of another plan step counts once
        out.append(call)
    return out


def plan_verdict(
    claim: Mapping[str, Any],
    own: Call,
    others: Sequence[Call],
    verify: Callable[..., dict[str, Any]],
    list_match: Callable[[Mapping[str, Any], Call, list[Any]], bool | None],
) -> dict[str, Any]:
    """`list_match(claim, own_call, union_of_truths)` says whether a list claim matches the
    union (None when the claim is not a list kind)."""
    base = verify(claim, *own)
    base = {**base, "plan": None}
    if base["verdict"] != "false" or not others:
        return base
    results = [verify(claim, *o) for o in others]
    lists = [r["truth"] for r in [base, *results] if isinstance(r["truth"], list)]
    union = None
    if len(lists) > 1:
        union = [json.loads(x) for x in sorted({json.dumps(x) for lst in lists for x in lst})]
    union_holds = bool(union is not None and list_match(claim, own, union))
    for r in results:
        if r["verdict"] == "true":  # `union_holds` lets posthoc.py apply the union rule alone
            return {
                **base,
                "verdict": "true",
                "plan": "other",
                "why": "true of another call",
                "truth": r["truth"],
                "union_holds": union_holds,
            }
    kind, amount = claim.get("kind"), claim.get("amount")
    if kind in MONEY_KINDS and isinstance(amount, (int, float)):
        truths = [r["truth"] for r in [base, *results] if isinstance(r["truth"], (int, float))]
        if len(truths) > 1 and abs(amount - sum(truths)) <= TOLERANCE:
            return {**base, "verdict": "true", "plan": "sum", "truth": round(sum(truths), 2)}
    if union_holds:
        return {**base, "verdict": "true", "plan": "union", "truth": union}
    return base


ORDER_ID = re.compile(r"#W\d{7}")
