"""Report metadata: the plain-language names the viewer shows for judges, judge questions,
actions and oracle reason codes. The names of decision strategies (arms) come from the replay's
`metrics.json` (`hatchway.bench.replay.ARM_METADATA`), never from here or the templates.

Every lookup falls back to something readable for ids this file does not know.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hatchway.bench.replay import JUDGE_DISPLAY_NAMES

# A judge's score spread (max - min policy score across judges) above this flags the action in
# "Where the judges disagreed". `python -m hatchway.bench.report --spread-threshold` overrides it.
SCORE_SPREAD_THRESHOLD = 0.5

# Questions every action asks; the rest are the action-specific predicates.
GENERAL_QUESTIONS = ("policy_ok", "matches_request", "risk")

QUESTION_LABELS = {
    "policy_ok": "Follows policy",
    "matches_request": "Matches the request",
    "risk": "Cost if wrong",
    "identity_ok": "Customer identified",
    "confirmed": "Details confirmed",
    "status_ok": "Order status allows it",
    "refund_ok": "Original payment method",
    "items_ok": "Items valid",
    "all_items_ok": "All items in one call",
    "payment_ok": "Payment method valid",
    "reason_ok": "Valid reason",
    "line_ok": "Correct line",
    "amount_ok": "Requested amount matches",
    "price_confirmed": "Total price confirmed",
    "overdue_ok": "Bill overdue",
    "one_awaiting": "No other bill awaiting payment",
    "traveling": "Customer abroad",
    "not_enabled": "Roaming not already on",
    "grounds_ok": "Grounds to suspend",
    "requested": "Customer asked for it",
    "bills_paid": "Overdue bills paid",
    "contract_ok": "Contract still valid",
}

REASON_TEXTS = {
    "INVALID_REFUND_METHOD": "refund not to the original payment method",
    "CONFIRMATION_MISSING": "details never confirmed by the customer",
    "CONFIRMATION_DECLINED": "the customer did not agree",
    "CONFIRMATION_UNCLEAR": "the customer's reply was not a clear yes or no",
    "DETAILS_CHANGED_AFTER_CONFIRMATION": "details changed after the customer confirmed",
    "NOT_AUTHENTICATED": "customer not authenticated",
    "ORDER_NOT_OWNED": "order belongs to someone else",
    "ORDER_NOT_DELIVERED": "order not delivered",
    "ITEMS_NOT_IN_ORDER": "items not in the order",
    "WRONG_LINE": "not the line the customer is using",
    "LINE_NOT_OWNED": "line belongs to someone else",
    "NOT_ABROAD": "customer is not abroad",
    "ROAMING_ALREADY_ENABLED": "roaming already on",
    "AMOUNT_OVER_LIMIT": "more than 2 GB",
    "AMOUNT_NOT_POSITIVE": "refuel of 0 GB or less",
    "AMOUNT_NOT_REQUESTED": "the customer named no amount",
    "AMOUNT_DIFFERS": "not the amount the customer asked for",
    "PRICE_TOTAL_NOT_PRESENTED": "total price was not presented",
    "PRICE_NOT_CONFIRMED": "total price never confirmed",
    "BILL_NOT_OVERDUE": "bill is not overdue",
    "BILL_ALREADY_AWAITING": "another bill already awaits payment",
    "RELEVANCE_UNVERIFIED": "relevance to the request not checked",
    "CUSTOMER_NOT_IDENTIFIED": "customer not identified",
    "CUSTOMER_MISMATCH": "not the customer identified in the chat",
}


def humanize(identifier: str) -> str:
    text = identifier.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def judge_label(judge: str, names: Mapping[str, str] | None = None) -> str:
    """A judge's display name: from the replay's metadata when given, else the defaults."""
    return (names or {}).get(judge) or JUDGE_DISPLAY_NAMES.get(judge) or humanize(judge)


def question_label(question_id: str) -> str:
    return QUESTION_LABELS.get(question_id) or humanize(question_id)


def reason_text(code: str, evidence: Mapping[str, Any] | None = None) -> str:
    """Plain words for an oracle reason code: the known text, else the check's own note."""
    if code in REASON_TEXTS:
        return REASON_TEXTS[code]
    note = ((evidence or {}).get(code) or {}).get("note")
    return str(note) if note else humanize(code.lower())


def action_title(action: str, args: Mapping[str, Any]) -> str:
    """A short description of a proposed action, for people who do not read tool calls."""
    if action == "refuel_data":
        return f"Refuel {args.get('gb_amount')} GB on {args.get('line_id')}"
    if action == "enable_roaming":
        return f"Enable roaming on {args.get('line_id')}"
    if action == "return_delivered_order_items":
        n = len(args.get("item_ids") or [])
        return (
            f"Return {n} item{'s' if n != 1 else ''} from {args.get('order_id')} to "
            f"{args.get('payment_method_id')}"
        )
    if action == "send_payment_request":
        return f"Payment request for bill {args.get('bill_id')}"
    return humanize(action)
