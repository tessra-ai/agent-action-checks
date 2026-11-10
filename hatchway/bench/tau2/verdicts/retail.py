"""Policy validators for τ² retail writes.

Return (τ² retail policy, "Return delivered order"): the user is authenticated by email
or by name and zip; the order is theirs and delivered; the items are in the order; the refund
goes to the original payment method or an existing gift card; the agent listed the order, the
items and the payment method, and the customer said yes to those details, or to the plan that
carries them.

Exchange, modify items, cancel and address change: see each validator's docstring. Every one
needs an authenticated user acting on their own order or profile, and the customer's yes to the
details the policy names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hatchway.bench.tau2.verdicts.base import Check, ProposalEvidence
from hatchway.bench.tau2.verdicts.evidence import (
    ChainResult,
    confirmation_chain,
    confirmation_check,
    contains_phrase,
    order_ids_in,
    plan_confirmation,
    successful_calls,
)

# sha256 of `Environment.get_policy()` for retail at `TAU2_COMMIT`.
RETAIL_POLICY_HASHES = frozenset(
    {"2c9652afbce57d6e087768d37cda64d31c53d50b3e3225cfdb791bac66466467"}
)

_ALL_ITEMS = (
    "all items",
    "all the items",
    "all of the items",
    "all your items",
    "everything",
    "entire order",
    "whole order",
)


def authenticated_users(turns: Sequence[Any]) -> set[str]:
    """User ids found by `find_user_id_by_email` or `find_user_id_by_name_zip` earlier in the
    conversation, from calls that succeeded."""
    calls = successful_calls(turns, ("find_user_id_by_email", "find_user_id_by_name_zip"))
    return {result.content.strip().strip('"') for _, result in calls if result.content.strip()}


def original_payment_method(order: Mapping[str, Any]) -> str | None:
    """The method the order was paid with: the payment method of its `payment` transactions
    (refunds are ignored). None when there is no payment, or when payments came from more than
    one method, so which one is "original" is unclear."""
    methods = {
        p.get("payment_method_id")
        for p in order.get("payment_history") or []
        if p.get("transaction_type") == "payment"
    }
    methods.discard(None)
    return next(iter(methods)) if len(methods) == 1 else None


def payment_mention(method: Mapping[str, Any], user_methods: Mapping[str, Any]):
    """A matcher for messages that name this payment method: its id; "paypal" or "gift card"
    by type; a credit card by its last four digits, or by "credit card" or its brand when the
    user has only one credit card."""
    method_id = method.get("id", "")
    source = method.get("source")
    one_card = sum(1 for m in user_methods.values() if m.get("source") == "credit_card") == 1

    def mentions(text: str) -> bool:
        if method_id and method_id.lower() in text.lower():
            return True
        if source == "paypal":
            return contains_phrase(text, "paypal")
        if source == "gift_card":
            return contains_phrase(text, "gift card")
        if source == "credit_card":
            last_four = str(method.get("last_four") or "")
            if last_four and last_four in text:
                return True
            brand = str(method.get("brand") or "")
            named = contains_phrase(text, "credit card") or (brand and contains_phrase(text, brand))
            return bool(named) and one_card
        return False

    return mentions


class ReturnDeliveredOrderItems:
    domain = "retail"
    action = "return_delivered_order_items"
    version = "2"
    supported_policy_hashes = RETAIL_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        users: Mapping[str, Any] = ev.agent_db.get("users") or {}
        orders: Mapping[str, Any] = ev.agent_db.get("orders") or {}
        order_id = str(ev.args.get("order_id", ""))
        item_ids = list(ev.args.get("item_ids") or [])
        method_id = str(ev.args.get("payment_method_id", ""))
        checks: list[Check] = []

        authed = authenticated_users(ev.turns)
        if authed:
            checks.append(Check("AUTHENTICATED", "pass", "", {"user_ids": sorted(authed)}))
        else:
            checks.append(
                Check("NOT_AUTHENTICATED", "ask", "no successful lookup by email or name and zip")
            )

        order = orders.get(order_id)
        if order is None:
            checks.append(Check("ORDER_NOT_FOUND", "deny", order_id, {"order_id": order_id}))
            return checks
        owner = order.get("user_id")
        if authed and owner not in authed:
            checks.append(
                Check(
                    "ORDER_NOT_OWNED",
                    "deny",
                    "the order belongs to another user",
                    {"order_user_id": owner, "authenticated": sorted(authed)},
                )
            )
        status = order.get("status")
        checks.append(
            Check("ORDER_DELIVERED", "pass", "", {"status": status})
            if status == "delivered"
            else Check("ORDER_NOT_DELIVERED", "deny", f"status is {status!r}", {"status": status})
        )

        order_items = order.get("items") or []
        available = [i.get("item_id") for i in order_items]
        missing = [i for i in item_ids if i not in available]
        if not item_ids or missing or len(set(item_ids)) != len(item_ids):
            checks.append(
                Check(
                    "ITEMS_NOT_IN_ORDER",
                    "deny",
                    "items missing from the order, repeated, or none given",
                    {"item_ids": item_ids, "missing": missing},
                )
            )
        else:
            checks.append(Check("ITEMS_IN_ORDER", "pass", "", {"item_ids": item_ids}))

        user_methods: Mapping[str, Any] = (users.get(owner) or {}).get("payment_methods") or {}
        method = user_methods.get(method_id)
        original = original_payment_method(order)
        facts = {"payment_method_id": method_id, "original": original}
        if method is not None and method.get("source") == "gift_card":
            checks.append(Check("REFUND_METHOD_OK", "pass", "an existing gift card", facts))
        elif original is None:
            checks.append(
                Check(
                    "ORIGINAL_PAYMENT_UNCLEAR",
                    "unknown",
                    "the order has no single original payment method",
                    facts,
                )
            )
        elif method_id != original:
            checks.append(
                Check(
                    "INVALID_REFUND_METHOD",
                    "deny",
                    "the refund must go to the original payment method or a gift card",
                    facts,
                )
            )
        else:
            checks.append(Check("REFUND_METHOD_OK", "pass", "the original payment method", facts))

        names = {i.get("item_id"): str(i.get("name") or "") for i in order_items}
        whole_order = bool(item_ids) and sorted(item_ids) == sorted(available)

        def items_mentioned(text: str) -> bool:
            if all(i in text for i in item_ids):
                return True
            wanted = [names.get(i, "") for i in item_ids]
            if wanted and all(n and contains_phrase(text, n) for n in wanted):
                return True
            return (
                whole_order
                and order_id.lower() in text.lower()
                and any(contains_phrase(text, p) for p in _ALL_ITEMS)
            )

        def order_mentioned(text: str) -> bool:
            return order_id in order_ids_in(text)

        def other_order(text: str) -> bool:
            found = order_ids_in(text)
            return bool(found) and order_id not in found

        chains: dict[str, ChainResult] = {
            "order": confirmation_chain(ev.turns, order_mentioned, other_order),
            "items": confirmation_chain(ev.turns, items_mentioned),
        }
        conflicts: dict[str, Any] = {"order": other_order, "items": None}
        if method is not None:
            others = [
                payment_mention(m, user_methods) for k, m in user_methods.items() if k != method_id
            ]
            this = payment_mention(method, user_methods)

            def other_method(text: str) -> bool:
                return any(o(text) for o in others) and not this(text)

            chains["payment_method"] = confirmation_chain(ev.turns, this, other_method)
            conflicts["payment_method"] = other_method
        checks.append(confirmation_check(plan_confirmation(ev.turns, chains, conflicts)))
        return checks


# --- Shared checks for the other retail writes -------------------------------------------------

CANCEL_REASONS = ("no longer needed", "ordered by mistake")
# How customers say each cancellation reason in their own words.
_REASON_PHRASES = {
    "no longer needed": ("no longer need", "don't need", "do not need", "not needed"),
    "ordered by mistake": ("by mistake", "mistake", "by accident", "accidentally"),
}


def _auth_check(ev: ProposalEvidence) -> tuple[Check, set[str]]:
    authed = authenticated_users(ev.turns)
    if authed:
        return Check("AUTHENTICATED", "pass", "", {"user_ids": sorted(authed)}), authed
    return Check(
        "NOT_AUTHENTICATED", "ask", "no successful lookup by email or name and zip"
    ), authed


def _order_checks(
    ev: ProposalEvidence, authed: set[str], status_needed: str
) -> tuple[list[Check], Mapping[str, Any] | None]:
    """The order exists, belongs to the authenticated user, and has the status the action
    needs. Returns the checks and the order (None when it does not exist)."""
    order_id = str(ev.args.get("order_id", ""))
    order = (ev.agent_db.get("orders") or {}).get(order_id)
    if order is None:
        return [Check("ORDER_NOT_FOUND", "deny", order_id, {"order_id": order_id})], None
    checks: list[Check] = []
    owner = order.get("user_id")
    if authed and owner not in authed:
        checks.append(
            Check(
                "ORDER_NOT_OWNED",
                "deny",
                "the order belongs to another user",
                {"order_user_id": owner, "authenticated": sorted(authed)},
            )
        )
    status = order.get("status")
    if status == status_needed:
        checks.append(Check(f"ORDER_{status_needed.upper()}", "pass", "", {"status": status}))
    else:
        checks.append(
            Check(
                f"ORDER_NOT_{status_needed.upper()}",
                "deny",
                f"status is {status!r}",
                {"status": status},
            )
        )
    return checks, order


def _order_matchers(order_id: str):
    def mentioned(text: str) -> bool:
        return order_id in order_ids_in(text)

    def other(text: str) -> bool:
        found = order_ids_in(text)
        return bool(found) and order_id not in found

    return mentioned, other


def _swap_checks(
    ev: ProposalEvidence, order: Mapping[str, Any], *, same_item_allowed: bool
) -> tuple[list[Check], list[Mapping[str, Any]]]:
    """Exchange and modify-items rules: each old item is in the order (with multiplicity), the
    lists have the same length, each new item is an available variant of the old item's
    product with a different option, the payment method is the owner's, and a gift card covers
    the price difference. Returns the checks and the new variants found."""
    item_ids = [str(i) for i in ev.args.get("item_ids") or []]
    new_ids = [str(i) for i in ev.args.get("new_item_ids") or []]
    products: Mapping[str, Any] = ev.agent_db.get("products") or {}
    order_items = list(order.get("items") or [])
    in_order = [i.get("item_id") for i in order_items]
    checks: list[Check] = []
    missing = [i for i in set(item_ids) if item_ids.count(i) > in_order.count(i)]
    if not item_ids or missing:
        checks.append(
            Check(
                "ITEMS_NOT_IN_ORDER",
                "deny",
                "items missing from the order, or none given",
                {"item_ids": item_ids, "missing": sorted(missing)},
            )
        )
        return checks, []
    checks.append(Check("ITEMS_IN_ORDER", "pass", "", {"item_ids": item_ids}))
    if len(item_ids) != len(new_ids):
        checks.append(
            Check(
                "ITEM_COUNT_MISMATCH",
                "deny",
                f"{len(item_ids)} items for {len(new_ids)} new items",
                {"item_ids": item_ids, "new_item_ids": new_ids},
            )
        )
        return checks, []
    by_id = {i.get("item_id"): i for i in order_items}
    bad: list[dict[str, Any]] = []
    variants: list[Mapping[str, Any]] = []
    diff = 0.0
    for old_id, new_id in zip(item_ids, new_ids, strict=True):
        item = by_id[old_id]
        product = products.get(str(item.get("product_id"))) or {}
        variant = (product.get("variants") or {}).get(new_id)
        if variant is None:
            bad.append({"new_item_id": new_id, "problem": "not a variant of the same product"})
        elif not variant.get("available"):
            bad.append({"new_item_id": new_id, "problem": "not available"})
        elif new_id == old_id and not same_item_allowed:
            bad.append({"new_item_id": new_id, "problem": "the same item"})
        else:
            variants.append(variant)
            diff += float(variant.get("price") or 0) - float(item.get("price") or 0)
    if bad:
        checks.append(
            Check("NEW_ITEMS_INVALID", "deny", "; ".join(b["problem"] for b in bad), {"bad": bad})
        )
        return checks, variants
    checks.append(Check("NEW_ITEMS_VALID", "pass", "", {"new_item_ids": new_ids}))

    owner = order.get("user_id")
    user_methods: Mapping[str, Any] = ((ev.agent_db.get("users") or {}).get(owner) or {}).get(
        "payment_methods"
    ) or {}
    method_id = str(ev.args.get("payment_method_id", ""))
    method = user_methods.get(method_id)
    facts = {"payment_method_id": method_id, "price_difference": round(diff, 2)}
    if method is None:
        checks.append(Check("PAYMENT_METHOD_NOT_OWNED", "deny", method_id, facts))
    elif method.get("source") == "gift_card" and float(method.get("balance") or 0) < diff:
        checks.append(
            Check(
                "GIFT_CARD_INSUFFICIENT", "deny", "the balance does not cover the difference", facts
            )
        )
    else:
        checks.append(Check("PAYMENT_METHOD_OK", "pass", "", facts))
    return checks, variants


def _swap_confirmation(
    ev: ProposalEvidence, order: Mapping[str, Any], variants: Sequence[Mapping[str, Any]]
) -> Check:
    """The customer confirmed the order, the old items, the new items and (when it is theirs)
    the payment method. A new item counts as named by its id or by all of its option values."""
    order_id = str(ev.args.get("order_id", ""))
    item_ids = [str(i) for i in ev.args.get("item_ids") or []]
    names = {i.get("item_id"): str(i.get("name") or "") for i in order.get("items") or []}

    def old_items(text: str) -> bool:
        if all(i in text for i in item_ids):
            return True
        return all(names.get(i) and contains_phrase(text, names[i]) for i in item_ids)

    def new_items(text: str) -> bool:
        def named(v: Mapping[str, Any]) -> bool:
            if str(v.get("item_id")) in text:
                return True
            values = [str(x) for x in (v.get("options") or {}).values()]
            return bool(values) and all(contains_phrase(text, x) for x in values)

        return bool(variants) and all(named(v) for v in variants)

    mentioned, other = _order_matchers(order_id)
    chains: dict[str, ChainResult] = {
        "order": confirmation_chain(ev.turns, mentioned, other),
        "items": confirmation_chain(ev.turns, old_items),
        "new_items": confirmation_chain(ev.turns, new_items),
    }
    conflicts: dict[str, Any] = {"order": other, "items": None, "new_items": None}
    users: Mapping[str, Any] = ev.agent_db.get("users") or {}
    user_methods = (users.get(order.get("user_id")) or {}).get("payment_methods") or {}
    method_id = str(ev.args.get("payment_method_id", ""))
    method = user_methods.get(method_id)
    if method is not None:
        this = payment_mention(method, user_methods)
        others = [
            payment_mention(m, user_methods) for k, m in user_methods.items() if k != method_id
        ]

        def other_method(text: str) -> bool:
            return any(o(text) for o in others) and not this(text)

        chains["payment_method"] = confirmation_chain(ev.turns, this, other_method)
        conflicts["payment_method"] = other_method
    return confirmation_check(plan_confirmation(ev.turns, chains, conflicts))


class ExchangeDeliveredOrderItems:
    """Policy "Exchange delivered order": authenticated owner; delivered order; each item
    swapped for an available, different variant of the same product; the payment method is
    the user's and a gift card covers the difference; the customer confirmed the details.
    (The reminder to list every item is not checked: it has no reliable textual form.)"""

    domain = "retail"
    action = "exchange_delivered_order_items"
    version = "1"
    supported_policy_hashes = RETAIL_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        auth, authed = _auth_check(ev)
        order_checks, order = _order_checks(ev, authed, "delivered")
        checks = [auth, *order_checks]
        if order is None:
            return checks
        swap, variants = _swap_checks(ev, order, same_item_allowed=False)
        checks += swap
        checks.append(_swap_confirmation(ev, order, variants))
        return checks


class ModifyPendingOrderItems:
    """Policy "Modify items": as an exchange, but on a pending order."""

    domain = "retail"
    action = "modify_pending_order_items"
    version = "1"
    supported_policy_hashes = RETAIL_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        auth, authed = _auth_check(ev)
        order_checks, order = _order_checks(ev, authed, "pending")
        checks = [auth, *order_checks]
        if order is None:
            return checks
        swap, variants = _swap_checks(ev, order, same_item_allowed=False)
        checks += swap
        checks.append(_swap_confirmation(ev, order, variants))
        return checks


class CancelPendingOrder:
    """Policy "Cancel pending order": authenticated owner; pending order; the reason is one of
    the two accepted ones; the customer confirmed the order id and the reason."""

    domain = "retail"
    action = "cancel_pending_order"
    version = "1"
    supported_policy_hashes = RETAIL_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        auth, authed = _auth_check(ev)
        order_checks, order = _order_checks(ev, authed, "pending")
        checks = [auth, *order_checks]
        if order is None:
            return checks
        reason = str(ev.args.get("reason", ""))
        if reason not in CANCEL_REASONS:
            checks.append(Check("INVALID_REASON", "deny", repr(reason), {"reason": reason}))
            return checks
        checks.append(Check("REASON_ACCEPTED", "pass", "", {"reason": reason}))

        def reason_named(text: str) -> bool:
            return any(contains_phrase(text, p) for p in _REASON_PHRASES[reason])

        (other_reason,) = (r for r in CANCEL_REASONS if r != reason)

        def other_named(text: str) -> bool:
            return not reason_named(text) and any(
                contains_phrase(text, p) for p in _REASON_PHRASES[other_reason]
            )

        mentioned, other = _order_matchers(str(ev.args.get("order_id", "")))
        chains = {
            "order": confirmation_chain(ev.turns, mentioned, other),
            "reason": confirmation_chain(ev.turns, reason_named, other_named),
        }
        conflicts = {"order": other, "reason": other_named}
        checks.append(confirmation_check(plan_confirmation(ev.turns, chains, conflicts)))
        return checks


class ModifyUserAddress:
    """Policy: an authenticated user may change their own default address after confirming
    the new address (named by its first line and its city or zip)."""

    domain = "retail"
    action = "modify_user_address"
    version = "1"
    supported_policy_hashes = RETAIL_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        auth, authed = _auth_check(ev)
        checks = [auth]
        user_id = str(ev.args.get("user_id", ""))
        if user_id not in (ev.agent_db.get("users") or {}):
            checks.append(Check("USER_NOT_FOUND", "deny", user_id, {"user_id": user_id}))
            return checks
        if authed and user_id not in authed:
            checks.append(
                Check(
                    "USER_MISMATCH",
                    "deny",
                    "not the authenticated user",
                    {"user_id": user_id, "authenticated": sorted(authed)},
                )
            )
        else:
            checks.append(Check("USER_OK", "pass", "", {"user_id": user_id}))
        current = (ev.agent_db.get("users") or {})[user_id].get("address") or {}
        fields = ("address1", "address2", "city", "state", "country", "zip")
        if all(str(current.get(f, "")) == str(ev.args.get(f, "")) for f in fields):
            checks.append(
                Check(
                    "ADDRESS_UNCHANGED",
                    "deny",
                    "the new address is the current one; the write changes nothing asked for",
                    {"address": {f: current.get(f) for f in fields}},
                )
            )
        line1 = str(ev.args.get("address1", ""))
        city, zip_code = str(ev.args.get("city", "")), str(ev.args.get("zip", ""))

        def address_named(text: str) -> bool:
            return (
                bool(line1)
                and contains_phrase(text, line1)
                and (
                    (bool(city) and contains_phrase(text, city))
                    or (bool(zip_code) and zip_code in text)
                )
            )

        chain = confirmation_chain(ev.turns, address_named)
        checks.append(confirmation_check({"address": chain}))
        return checks
