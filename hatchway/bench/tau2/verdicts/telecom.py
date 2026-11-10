"""Policy validators for τ² telecom writes.

Rules checked (τ² telecom policy): the customer is identified (by phone, by id, or by name
with date of birth); the line is theirs and is the line the customer is using; roaming is
enabled only for a customer abroad whose line does not have it; more than 0 and at most 2 GB are
refueled, the amount the customer asked for, after the exact total charge was presented and the
customer confirmed it (a per-GB price alone is not the total); a payment request is sent only for
the customer's own overdue bill, and only when no other bill awaits payment.
A suspended line is resumed only when no bill is unpaid and its contract has not ended; roaming
is disabled only on request, on a line that has it, for a customer who is not abroad.

Facts about the world come from the pre-action state: where the customer is
(`user_db.surroundings.is_abroad`), which phone they are using (`surroundings.phone_number`),
what each line and bill looks like. What the customer asked for and agreed to comes only from
the conversation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from hatchway.bench.tau2.verdicts.base import Check, ProposalEvidence
from hatchway.bench.tau2.verdicts.evidence import (
    confirmation_chain,
    confirmation_check,
    digits,
    gb_amounts_in,
    money_in,
    parse_json,
    per_gb_rates_in,
    phone_numbers_in,
    same_amount,
    successful_calls,
    text_turns,
    without_per_gb_rates,
)

# sha256 of `Environment.get_policy()` for telecom at `TAU2_COMMIT`.
TELECOM_POLICY_HASHES = frozenset(
    {"065b48503bf780153fc671455cdfddb85b4c6ffb11e2ea93bd940233d804c3e9"}
)

MAX_REFUEL_GB = 2.0
_LOOKUPS = ("get_customer_by_phone", "get_customer_by_id", "get_customer_by_name")


def identified_customers(turns: Sequence[Any]) -> set[str]:
    """Customer ids returned by a successful lookup earlier in the conversation. A name lookup
    counts only when it gave a date of birth, as the policy requires."""
    found: set[str] = set()
    for call, result in successful_calls(turns, _LOOKUPS):
        if call.name == "get_customer_by_name" and not call.arguments.get("dob"):
            continue
        body = parse_json(result.content)
        for record in body if isinstance(body, list) else [body]:
            if isinstance(record, dict) and record.get("customer_id"):
                found.add(str(record["customer_id"]))
    return found


def _by_id(records: Any, key: str) -> dict[str, Mapping[str, Any]]:
    if isinstance(records, Mapping):
        return {str(k): v for k, v in records.items()}
    return {str(r.get(key)): r for r in records or [] if isinstance(r, Mapping)}


def _surroundings(ev: ProposalEvidence) -> Mapping[str, Any]:
    return (ev.user_db or {}).get("surroundings") or {}


def _customer_checks(ev: ProposalEvidence) -> tuple[list[Check], Mapping[str, Any] | None]:
    customer_id = str(ev.args.get("customer_id", ""))
    identified = identified_customers(ev.turns)
    customer = _by_id(ev.agent_db.get("customers"), "customer_id").get(customer_id)
    facts = {"customer_id": customer_id, "identified": sorted(identified)}
    if customer is None:
        return [Check("CUSTOMER_NOT_FOUND", "deny", customer_id, facts)], None
    if not identified:
        return [Check("CUSTOMER_NOT_IDENTIFIED", "ask", "no successful customer lookup", facts)], (
            customer
        )
    if customer_id not in identified:
        return [
            Check("CUSTOMER_MISMATCH", "deny", "not the customer identified in the chat", facts)
        ], customer
    return [Check("CUSTOMER_IDENTIFIED", "pass", "", facts)], customer


def _line_checks(
    ev: ProposalEvidence, customer: Mapping[str, Any]
) -> tuple[list[Check], Mapping[str, Any] | None]:
    """The line exists, belongs to the customer, and is the line the customer is using."""
    line_id = str(ev.args.get("line_id", ""))
    line = _by_id(ev.agent_db.get("lines"), "line_id").get(line_id)
    if line is None:
        return [Check("LINE_NOT_FOUND", "deny", line_id, {"line_id": line_id})], None
    if line_id not in (customer.get("line_ids") or []):
        return [
            Check(
                "LINE_NOT_OWNED",
                "deny",
                "the line belongs to another customer",
                {"line_id": line_id},
            )
        ], line
    checks = [Check("LINE_OWNED", "pass", "", {"line_id": line_id})]
    number = digits(str(line.get("phone_number") or ""))[-10:]
    device_number = digits(str(_surroundings(ev).get("phone_number") or ""))[-10:]
    if device_number:
        facts = {"line_number": number, "customer_phone": device_number, "source": "user_db"}
        if number == device_number:
            checks.append(Check("TARGET_LINE", "pass", "", facts))
        else:
            checks.append(Check("WRONG_LINE", "deny", "not the line the customer is using", facts))
        return checks, line
    stated = set()
    for t in text_turns(ev.turns):
        if t.role == "user":
            stated |= phone_numbers_in(t.content)
    for call, _ in successful_calls(ev.turns, ("get_customer_by_phone",)):
        stated |= phone_numbers_in(str(call.arguments.get("phone_number", "")))
    facts = {"line_number": number, "stated": sorted(stated), "source": "conversation"}
    if not stated:
        checks.append(Check("TARGET_LINE_UNSTATED", "ask", "the customer gave no number", facts))
    elif number in stated:
        checks.append(Check("TARGET_LINE", "pass", "", facts))
    elif len(stated) == 1:
        checks.append(Check("WRONG_LINE", "deny", "not the number the customer gave", facts))
    else:
        checks.append(
            Check("TARGET_LINE_UNCLEAR", "unknown", "several numbers, none this line", facts)
        )
    return checks, line


class EnableRoaming:
    domain = "telecom"
    action = "enable_roaming"
    version = "1"
    supported_policy_hashes = TELECOM_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        checks, customer = _customer_checks(ev)
        if customer is None:
            return checks
        line_checks, line = _line_checks(ev, customer)
        checks += line_checks
        if line is None:
            return checks
        abroad = _surroundings(ev).get("is_abroad")
        if abroad is True:
            checks.append(Check("CUSTOMER_ABROAD", "pass", "", {"is_abroad": True}))
        elif abroad is False:
            checks.append(
                Check(
                    "NOT_ABROAD",
                    "deny",
                    "the customer is in the home network",
                    {"is_abroad": False},
                )
            )
        else:
            checks.append(Check("LOCATION_UNKNOWN", "unknown", "no location in the user state"))
        if line.get("roaming_enabled"):
            checks.append(Check("ROAMING_ALREADY_ENABLED", "deny", "", {"roaming_enabled": True}))
        else:
            checks.append(Check("ROAMING_OFF", "pass", "", {"roaming_enabled": False}))
        return checks


class RefuelData:
    domain = "telecom"
    action = "refuel_data"
    version = "3"
    supported_policy_hashes = TELECOM_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        checks, customer = _customer_checks(ev)
        if customer is None:
            return checks
        line_checks, line = _line_checks(ev, customer)
        checks += line_checks
        if line is None:
            return checks
        try:
            amount = float(ev.args.get("gb_amount"))
        except (TypeError, ValueError):
            checks.append(Check("AMOUNT_INVALID", "deny", repr(ev.args.get("gb_amount"))))
            return checks
        if amount <= 0:
            checks.append(
                Check(
                    "AMOUNT_NOT_POSITIVE",
                    "deny",
                    f"{amount:g} GB; a refuel must add data",
                    {"gb_amount": amount},
                )
            )
        elif amount > MAX_REFUEL_GB:
            checks.append(
                Check(
                    "AMOUNT_OVER_LIMIT",
                    "deny",
                    f"{amount:g} GB; the limit is 2 GB",
                    {"gb_amount": amount},
                )
            )
        else:
            checks.append(Check("AMOUNT_WITHIN_LIMIT", "pass", "", {"gb_amount": amount}))

        asked = [
            (t.index, a)
            for t in text_turns(ev.turns)
            if t.role == "user"
            for a in gb_amounts_in(t.content)
        ]
        if not asked:
            checks.append(Check("AMOUNT_NOT_REQUESTED", "ask", "the customer named no amount"))
        elif same_amount(asked[-1][1], amount):
            checks.append(Check("AMOUNT_REQUESTED", "pass", "", {"turn": asked[-1][0]}))
        else:
            checks.append(
                Check(
                    "AMOUNT_DIFFERS",
                    "deny",
                    f"the customer last asked for {asked[-1][1]:g} GB",
                    {"turn": asked[-1][0], "requested": asked[-1][1], "gb_amount": amount},
                )
            )

        plan = _by_id(ev.agent_db.get("plans"), "plan_id").get(str(line.get("plan_id")))
        rate = None if plan is None else plan.get("data_refueling_price_per_gb")
        if rate is None:
            checks.append(Check("PRICE_UNKNOWN", "unknown", "no refuel price for the line's plan"))
            return checks
        price = amount * float(rate)

        def total_mentioned(text: str) -> bool:
            # A per-GB rate is not the total, even when the two amounts are equal (1 GB).
            return any(same_amount(m, price) for m in money_in(without_per_gb_rates(text)))

        facts = {"price": price, "rate_per_gb": float(rate)}
        if not any(total_mentioned(t.content) for t in text_turns(ev.turns)):
            rate_shown = any(
                t.role == "assistant"
                and any(same_amount(r, float(rate)) for r in per_gb_rates_in(t.content))
                for t in text_turns(ev.turns)
            )
            checks.append(
                Check(
                    "PRICE_TOTAL_NOT_PRESENTED",
                    "ask",
                    f"the total charge (${price:.2f}) was never presented"
                    + (" (only the price per GB was)" if rate_shown else ""),
                    {**facts, "rate_shown": rate_shown},
                )
            )
            return checks
        chain = confirmation_chain(ev.turns, total_mentioned)
        if chain.status == "ABSENT":
            # The total was stated, but no customer reply followed it before the call.
            checks.append(
                Check(
                    "PRICE_NOT_CONFIRMED",
                    "ask",
                    f"the total charge (${price:.2f}) was presented but never confirmed",
                    facts,
                )
            )
            return checks
        checks.append(confirmation_check({"price": chain}))
        return checks


class SendPaymentRequest:
    domain = "telecom"
    action = "send_payment_request"
    version = "1"
    supported_policy_hashes = TELECOM_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        checks, customer = _customer_checks(ev)
        if customer is None:
            return checks
        bill_id = str(ev.args.get("bill_id", ""))
        bills = _by_id(ev.agent_db.get("bills"), "bill_id")
        bill = bills.get(bill_id)
        customer_id = str(customer.get("customer_id"))
        if bill is None:
            checks.append(Check("BILL_NOT_FOUND", "deny", bill_id, {"bill_id": bill_id}))
            return checks
        if str(bill.get("customer_id")) != customer_id:
            checks.append(Check("BILL_NOT_OWNED", "deny", "", {"bill_id": bill_id}))
        status = bill.get("status")
        if status == "Overdue":
            checks.append(Check("BILL_OVERDUE", "pass", "", {"status": status}))
        else:
            checks.append(
                Check("BILL_NOT_OVERDUE", "deny", f"status is {status!r}", {"status": status})
            )
        awaiting = sorted(
            b_id
            for b_id, b in bills.items()
            if str(b.get("customer_id")) == customer_id and b.get("status") == "Awaiting Payment"
        )
        if awaiting:
            checks.append(
                Check(
                    "BILL_ALREADY_AWAITING",
                    "deny",
                    "another bill awaits payment",
                    {"awaiting": awaiting},
                )
            )
        else:
            checks.append(Check("NONE_AWAITING", "pass", ""))
        checks.append(
            Check(
                "RELEVANCE_UNVERIFIED",
                "unknown",
                "whether the request serves what the customer asked for is not checked "
                "deterministically",
            )
        )
        return checks


# The policy's "current time" (telecom policy header); a contract ending before it has ended.
POLICY_DATE = "2025-02-25"
_UNPAID = ("Overdue", "Awaiting Payment")
# A request, not a status report: "turn off roaming", "disable my data roaming", "switch roaming
# off". "Data roaming is off" or "roaming is disabled" describe the phone and do not count.
_DISABLE_ROAMING = re.compile(
    r"\b(disable|turn off|switch off|deactivate)\b[^.?!]{0,15}\broaming\b"
    r"|\b(turn|switch)\b[^.?!]{0,15}\broaming\b[^.?!]{0,10}\boff\b"
)


class ResumeLine:
    """Policy "Line Suspension": a suspended line of the identified customer is resumed only
    when the customer has no unpaid (overdue or awaiting payment) bill and the line's contract
    has not ended."""

    domain = "telecom"
    action = "resume_line"
    version = "1"
    supported_policy_hashes = TELECOM_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        checks, customer = _customer_checks(ev)
        if customer is None:
            return checks
        line_checks, line = _line_checks(ev, customer)
        checks += line_checks
        if line is None:
            return checks
        status = line.get("status")
        if status == "Suspended":
            checks.append(Check("LINE_SUSPENDED", "pass", "", {"status": status}))
        else:
            checks.append(
                Check("LINE_NOT_SUSPENDED", "deny", f"status is {status!r}", {"status": status})
            )
        end = str(line.get("contract_end_date") or "")
        if end and end < POLICY_DATE:
            checks.append(
                Check(
                    "CONTRACT_ENDED",
                    "deny",
                    f"the contract ended on {end}",
                    {"contract_end_date": end, "today": POLICY_DATE},
                )
            )
        elif not end:
            checks.append(Check("CONTRACT_END_UNKNOWN", "unknown", "no contract end date"))
        else:
            checks.append(Check("CONTRACT_CURRENT", "pass", "", {"contract_end_date": end}))
        customer_id = str(customer.get("customer_id"))
        unpaid = sorted(
            b_id
            for b_id, b in _by_id(ev.agent_db.get("bills"), "bill_id").items()
            if str(b.get("customer_id")) == customer_id and b.get("status") in _UNPAID
        )
        if unpaid:
            checks.append(
                Check("BILLS_UNPAID", "deny", "the customer has unpaid bills", {"unpaid": unpaid})
            )
        else:
            checks.append(Check("BILLS_PAID", "pass", ""))
        return checks


class DisableRoaming:
    """The policy offers roaming to travellers and says nothing about removing it, so a
    disable is in policy only when the customer asked for it, the line has roaming on, and the
    customer is not abroad (where it would cut their data)."""

    domain = "telecom"
    action = "disable_roaming"
    version = "1"
    supported_policy_hashes = TELECOM_POLICY_HASHES

    def evaluate(self, ev: ProposalEvidence) -> Sequence[Check]:
        checks, customer = _customer_checks(ev)
        if customer is None:
            return checks
        line_checks, line = _line_checks(ev, customer)
        checks += line_checks
        if line is None:
            return checks
        if line.get("roaming_enabled"):
            checks.append(Check("ROAMING_ON", "pass", "", {"roaming_enabled": True}))
        else:
            checks.append(Check("ROAMING_ALREADY_OFF", "deny", "", {"roaming_enabled": False}))
        abroad = _surroundings(ev).get("is_abroad")
        if abroad is True:
            checks.append(
                Check(
                    "CUSTOMER_ABROAD",
                    "deny",
                    "disabling roaming abroad cuts the customer's data",
                    {"is_abroad": True},
                )
            )
        elif abroad is False:
            checks.append(Check("CUSTOMER_HOME", "pass", "", {"is_abroad": False}))
        else:
            checks.append(Check("LOCATION_UNKNOWN", "unknown", "no location in the user state"))
        asked = [
            t.index
            for t in text_turns(ev.turns)
            if t.role == "user" and _DISABLE_ROAMING.search(t.content.lower())
        ]
        if asked:
            checks.append(Check("DISABLE_REQUESTED", "pass", "", {"turn": asked[-1]}))
        else:
            checks.append(
                Check(
                    "DISABLE_NOT_REQUESTED", "ask", "the customer never asked to turn roaming off"
                )
            )
        return checks
