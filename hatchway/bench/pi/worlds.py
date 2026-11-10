"""Worlds: what the learner starts from, and what the organization actually decides.

Each world has a starting policy (`r0`) and a truth (`truth`); a case *triggers* when they
disagree. Two kinds:

- **ablation:** the starting policy is the retail oracle without one clause (its check codes are
  dropped); the truth is the full oracle. The clause is written in τ²'s public policy, so an LLM
  arm may know it from memory: Phase B's zero-decision control measures that.
- **hidden:** the starting policy is the full oracle; the truth adds one organization rule that
  τ²'s policy never states. H5 depends only on the raw conversation (a chargeback threat), never
  on a fact, so no learner restricted to the fact vocabulary can recover it.

Decisions combine like the oracle's: any deny gives DENY, else any ask gives ASK, else any unknown
gives UNKNOWN, else ALLOW. Learning never relaxes a DENY.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from hatchway.bench.pi.cases import THREATS, Case

RETURN = "return_delivered_order_items"
EXCHANGE = "exchange_delivered_order_items"
CANCEL = "cancel_pending_order"


def combine(outcomes: Mapping[str, str]) -> str:
    found = set(outcomes.values())
    for outcome, decision in (("deny", "DENY"), ("ask", "ASK"), ("unknown", "UNKNOWN")):
        if outcome in found:
            return decision
    return "ALLOW"


@dataclass(frozen=True)
class World:
    name: str
    kind: str  # "ablation" or "hidden"
    description: str
    removed_codes: tuple[str, ...] = ()
    # (old, new) replacements in τ²'s retail policy.md giving the starting policy's text
    # (Phase B): each clause is removed without touching another world's clause.
    removed_text: tuple[tuple[str, str], ...] = ()
    hidden: Callable[[Case], str | None] | None = None
    raw_signal: bool = False

    def r0(self, case: Case) -> str:
        return combine({c: o for c, o in case.failing().items() if c not in self.removed_codes})

    def r0_relaxable(self, case: Case) -> bool:
        """The starting policy escalates the case only for `ask` reasons (no deny, no unknown),
        so a learned exception may allow it."""
        kept = {c: o for c, o in case.failing().items() if c not in self.removed_codes}
        return bool(kept) and set(kept.values()) == {"ask"}

    def truth(self, case: Case) -> str:
        if self.hidden is not None:
            override = self.hidden(case)
            if override is not None:
                return override
        return case.decision

    def triggers(self, case: Case) -> bool:
        return escalates(self.r0(case)) != escalates(self.truth(case))


def escalates(decision: str) -> bool:
    return decision != "ALLOW"


def _escalate_if(cond: Callable[[Case], bool]) -> Callable[[Case], str | None]:
    def rule(case: Case) -> str | None:
        return "ASK" if case.decision == "ALLOW" and cond(case) else None

    return rule


def _waive_confirmation_small_cancel(case: Case) -> str | None:
    if (
        case.action == CANCEL
        and case.failing() == {"CONFIRMATION_MISSING": "ask"}
        and case.facts["order_total"] < 300
    ):
        return "ALLOW"
    return None


WORLDS: tuple[World, ...] = (
    World(
        "C_AUTH",
        "ablation",
        "Authenticate the customer first (email, or name and zip).",
        ("NOT_AUTHENTICATED",),
        (
            (
                "At the beginning of the conversation, you have to authenticate the user identity "
                "by locating their user id via email, or via name + zip code. This has to be done "
                "even when the user already provides the user id.",
                "",
            ),
        ),
    ),
    World(
        "C_OWNER",
        "ablation",
        "Act only for the authenticated customer.",
        ("ORDER_NOT_OWNED",),
        (
            (
                "You can only help one user per conversation (but you can handle multiple "
                "requests from the same user), and must deny any requests for tasks related to "
                "any other user.",
                "",
            ),
        ),
    ),
    World(
        "C_STATUS",
        "ablation",
        "Only pending orders are cancelled; only delivered orders are returned or exchanged.",
        ("ORDER_NOT_DELIVERED", "ORDER_NOT_PENDING"),
        (
            ("Generally, you can only take action on pending or delivered orders.", ""),
            (
                "An order can only be cancelled if its status is 'pending', and you should check "
                "its status before taking the action.",
                "",
            ),
            (
                "An order can only be returned if its status is 'delivered', and you should check "
                "its status before taking the action.",
                "",
            ),
            (
                "An order can only be exchanged if its status is 'delivered', and you should check "
                "its status before taking the action.",
                "",
            ),
        ),
    ),
    World(
        "C_REFUND",
        "ablation",
        "A refund goes to the original payment method or an existing gift card.",
        ("INVALID_REFUND_METHOD",),
        (
            (
                "The refund must either go to the original payment method, or an existing gift "
                "card.",
                "",
            ),
        ),
    ),
    World(
        "C_REASON",
        "ablation",
        "Cancel only for 'no longer needed' or 'ordered by mistake'.",
        ("INVALID_REASON",),
        (
            (" (either 'no longer needed' or 'ordered by mistake')", ""),
            (" Other reasons are not acceptable.", ""),
        ),
    ),
    World(
        "C_CONFIRM",
        "ablation",
        "List the details and get the customer's explicit yes before any write.",
        ("CONFIRMATION_MISSING", "CONFIRMATION_DECLINED"),
        (
            (
                "Before taking any action that updates the database (cancel, modify, return, "
                "exchange), you must list the action details and obtain explicit user "
                "confirmation (yes) to proceed.",
                "",
            ),
            (
                "The user needs to confirm the order id and the reason (either 'no longer needed' "
                "or 'ordered by mistake') for cancellation.",
                "The reason for cancellation must be either 'no longer needed' or 'ordered by "
                "mistake'.",
            ),
            ("The user needs to confirm the order id and the list of items to be returned.", ""),
            ("So you must confirm all the details are correct and be cautious", "Be cautious"),
        ),
    ),
    World(
        "H1_LARGE_REFUND",
        "hidden",
        "Escalate any return refunding more than $2,000.",
        hidden=_escalate_if(lambda c: c.action == RETURN and c.facts["amount"] > 2000),
    ),
    World(
        "H2_PRODUCT",
        "hidden",
        "Escalate any return or exchange that includes a Jigsaw Puzzle (the product in the most "
        "return and exchange families).",
        hidden=_escalate_if(
            lambda c: c.action in (RETURN, EXCHANGE) and "Jigsaw Puzzle" in c.facts["products"]
        ),
    ),
    World(
        "H3_REPEAT_CANCEL",
        "hidden",
        "Escalate a cancellation when the customer has cancelled an order before.",
        hidden=_escalate_if(lambda c: c.action == CANCEL and c.facts["user_cancelled"] >= 1),
    ),
    World(
        "H4_UPCHARGE",
        "hidden",
        "Escalate an exchange that charges the customer more than $25 extra.",
        hidden=_escalate_if(lambda c: c.action == EXCHANGE and c.facts["price_difference"] > 25),
    ),
    World(
        "H5_CHARGEBACK",
        "hidden",
        "Escalate any write when the customer threatens a chargeback or payment dispute, in any "
        "of six phrasings (raw conversation only).",
        hidden=_escalate_if(lambda c: any(t in c.text for t in THREATS)),
        raw_signal=True,
    ),
    World(
        "H6_SMALL_CANCEL_WAIVER",
        "hidden",
        "Allow a cancellation without the explicit yes when the order total is under $300 "
        "(a relaxation: the written policy escalates these).",
        hidden=_waive_confirmation_small_cancel,
    ),
    World(
        "H7_PAYPAL_RETURN",
        "hidden",
        "Escalate a return refunded to PayPal for more than $500 (a three-condition rule).",
        hidden=_escalate_if(
            lambda c: (
                c.action == RETURN
                and c.facts["payment_source"] == "paypal"
                and c.facts["amount"] > 500
            )
        ),
    ),
)

BY_NAME = {w.name: w for w in WORLDS}


def reduced_policy(policy_text: str, world: World) -> str:
    """τ²'s retail policy text without the world's removed sentences (ablation worlds)."""
    out = policy_text
    for old, new in world.removed_text:
        if out.count(old) != 1:
            raise ValueError(f"{world.name}: text not in the policy exactly once: {old[:60]!r}")
        out = out.replace(old, new)
    return out
