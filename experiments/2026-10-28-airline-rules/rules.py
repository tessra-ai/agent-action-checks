"""Deterministic airline rules over the database as it was just before a proposed write.

Each rule reads the proposed call, the pre-action database (`flights`, `reservations`, `users`)
and two things taken from the conversation without a model: the user ids the customer typed and
the writes that already succeeded. It returns a block (with the rule id and a reason) or nothing.
A rule that needs a fact only a reader can supply (`reason_covered`) says so instead of
deciding. See README.md for the policy clause behind each rule.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

NOW = "2024-05-15T15:00:00"
TODAY = NOW[:10]
DAY_BEFORE = "2024-05-14T15:00:00"
FREE_BAGS = {
    "regular": {"basic_economy": 0, "economy": 1, "business": 2},
    "silver": {"basic_economy": 1, "economy": 2, "business": 3},
    "gold": {"basic_economy": 2, "economy": 3, "business": 4},
}
BAG_FEE, INSURANCE_FEE = 50, 30
RESERVATION_TOOLS = (
    "cancel_reservation",
    "update_reservation_flights",
    "update_reservation_baggages",
    "update_reservation_passengers",
)


@dataclass(frozen=True)
class Block:
    rule: str
    reason: str


@dataclass
class Outcome:
    blocks: list[Block] = field(default_factory=list)
    needs: set[str] = field(default_factory=set)  # facts a reader must supply

    @property
    def blocked(self) -> bool:
        return bool(self.blocks)


@dataclass(frozen=True)
class Context:
    """What the gate knows when the call is proposed."""

    action: str
    args: Mapping[str, Any]
    db: Mapping[str, Any]
    typed_user_ids: frozenset[str]
    prior_writes: tuple[tuple[str, Mapping[str, Any]], ...]  # successful (tool, args), in order


def context_from(action: str, args: Mapping[str, Any], db: Mapping[str, Any], messages) -> Context:
    """Build the context from a pre-action snapshot's messages (τ² message dicts)."""
    users = set(db.get("users", {}))
    typed: set[str] = set()
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            typed |= {t for t in re.findall(r"[a-z]+_[a-z]+_\d+", m["content"]) if t in users}
    calls = {}
    prior = []
    for m in messages:
        for c in m.get("tool_calls") or []:
            calls[c["id"]] = (c["name"], c.get("arguments") or {})
        if m.get("role") == "tool" and not m.get("error") and m.get("id") in calls:
            name, a = calls[m["id"]]
            if name in (*RESERVATION_TOOLS, "book_reservation", "send_certificate"):
                prior.append((name, a))
    return Context(action, args, db, frozenset(typed), tuple(prior))


def flown(db: Mapping[str, Any], flight_number: str, date: str) -> bool:
    status = db["flights"].get(flight_number, {}).get("dates", {}).get(date, {}).get("status")
    return date < TODAY or status in ("landed", "flying")


def flight_status(db: Mapping[str, Any], flight_number: str, date: str) -> str | None:
    return db["flights"].get(flight_number, {}).get("dates", {}).get(date, {}).get("status")


def legs(db: Mapping[str, Any], flights: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """(origin, destination) of each requested flight, from the flight table."""
    out = []
    for f in flights:
        row = db["flights"].get(f.get("flight_number"), {})
        out.append((row.get("origin"), row.get("destination")))
    return out


def route_ok(trip: str, origin: str, destination: str, pairs: Sequence[tuple[str, str]]) -> bool:
    """The legs chain from origin to destination (one way), or out to destination and back to
    origin (round trip)."""
    if not pairs or any(None in p for p in pairs):
        return False
    if any(pairs[i][1] != pairs[i + 1][0] for i in range(len(pairs) - 1)):
        return False
    if pairs[0][0] != origin:
        return False
    if trip == "one_way":
        return pairs[-1][1] == destination
    return pairs[-1][1] == origin and any(p[1] == destination for p in pairs)


def free_bags(membership: str, cabin: str, passengers: int) -> int:
    return FREE_BAGS.get(membership, FREE_BAGS["regular"]).get(cabin, 0) * passengers


def _reservation(ctx: Context) -> Mapping[str, Any] | None:
    return ctx.db["reservations"].get(ctx.args.get("reservation_id"))


def _user(ctx: Context, user_id: str | None) -> Mapping[str, Any]:
    return ctx.db["users"].get(user_id or "", {})


def check(ctx: Context, *, duplicate_rule: bool = True) -> Outcome:
    out = Outcome()

    def block(rule: str, reason: str) -> None:
        out.blocks.append(Block(rule, reason))

    a, args, db = ctx.action, ctx.args, ctx.db
    res = _reservation(ctx) if a in RESERVATION_TOOLS else None
    owner = res.get("user_id") if res else args.get("user_id")

    # OWN
    if a in RESERVATION_TOOLS and res is None:
        block("OWN", f"reservation {args.get('reservation_id')} does not exist")
    elif owner not in ctx.typed_user_ids:
        block("OWN", f"{owner} is not a user id the customer typed")

    # ACTIVE
    if res is not None and res.get("status") == "cancelled":
        block("ACTIVE", "the reservation is already cancelled")

    if a == "cancel_reservation" and res is not None:
        if any(flown(db, f["flight_number"], f["date"]) for f in res["flights"]):
            block("FLOWN_CANCEL", "a flight of the reservation has already been flown")
        within_24h = res.get("created_at", "") >= DAY_BEFORE
        airline_cancelled = any(
            flight_status(db, f["flight_number"], f["date"]) == "cancelled" for f in res["flights"]
        )
        if not (within_24h or airline_cancelled or res.get("cabin") == "business"):
            if res.get("insurance") == "yes":
                out.needs.add("reason_covered")
            else:
                block(
                    "CANCEL_ELIGIBLE",
                    f"{res.get('cabin')}, booked {res.get('created_at')}, no insurance, "
                    "no airline cancellation",
                )

    if a == "update_reservation_flights" and res is not None:
        new = [(f.get("flight_number"), f.get("date")) for f in args.get("flights") or []]
        old = [(f["flight_number"], f["date"]) for f in res["flights"]]
        if res.get("cabin") == "basic_economy" and sorted(new) != sorted(old):
            block("BASIC_NO_FLIGHT_CHANGE", "basic economy flights cannot be changed")
        if not route_ok(
            res.get("flight_type"),
            res.get("origin"),
            res.get("destination"),
            legs(db, args.get("flights") or []),
        ):
            block(
                "SAME_ROUTE",
                f"new flights do not keep {res.get('origin')}-{res.get('destination')} "
                f"{res.get('flight_type')}",
            )
        if args.get("cabin") != res.get("cabin") and any(flown(db, *f) for f in old):
            block("FLOWN_CABIN", "cabin change with a flight already flown")
        price = _update_price(db, res, args)
        _pay_update(ctx, res, price, block)

    if a == "update_reservation_baggages" and res is not None:
        total, nonfree = args.get("total_baggages", 0), args.get("nonfree_baggages", 0)
        if total < res.get("total_baggages", 0):
            block("BAGS_NO_REMOVE", f"total bags go from {res.get('total_baggages')} to {total}")
        allowance = free_bags(
            _user(ctx, owner).get("membership", "regular"), res["cabin"], len(res["passengers"])
        )
        if nonfree != max(0, total - allowance):
            block("BAG_FEE", f"{nonfree} paid bags for {total} total, {allowance} free")
        fee = BAG_FEE * max(0, nonfree - res.get("nonfree_baggages", 0))
        _pay_update(ctx, res, fee, block)

    if (
        a == "update_reservation_passengers"
        and res is not None
        and len(args.get("passengers") or []) != len(res["passengers"])
    ):
        block("PAX", "the number of passengers changes")

    if a == "book_reservation":
        _book(ctx, block, duplicate_rule)

    if a == "send_certificate":
        _certificate(ctx, block)

    return out


def _update_price(db, res, args) -> float:
    """What `update_reservation_flights` will charge (negative: refund), as τ² computes it."""
    pax = len(res["passengers"])
    total = 0.0
    for f in args.get("flights") or []:
        kept = next(
            (
                r
                for r in res["flights"]
                if r["flight_number"] == f.get("flight_number")
                and r["date"] == f.get("date")
                and args.get("cabin") == res.get("cabin")
            ),
            None,
        )
        if kept is not None:
            total += kept["price"] * pax
            continue
        day = db["flights"].get(f.get("flight_number"), {}).get("dates", {}).get(f.get("date"), {})
        total += (day.get("prices") or {}).get(args.get("cabin"), 0) * pax
    return total - sum(r["price"] for r in res["flights"]) * pax


def _pay_update(ctx: Context, res, charge: float, block) -> None:
    pid = ctx.args.get("payment_id")
    method = _user(ctx, res.get("user_id")).get("payment_methods", {}).get(pid)
    if method is None:
        block("PAY_UPDATE", f"{pid} is not in the user's profile")
    elif method.get("source") == "certificate":
        block("PAY_UPDATE", "a certificate cannot pay for a change")
    elif method.get("source") == "gift_card" and charge > 0 and method.get("amount", 0) < charge:
        block("PAY_UPDATE", f"gift card balance {method.get('amount')} is below {charge:.0f}")


def _book(ctx: Context, block, duplicate_rule: bool) -> None:
    args, db = ctx.args, ctx.db
    user = _user(ctx, args.get("user_id"))
    pax = args.get("passengers") or []
    cabin = args.get("cabin")
    if len(pax) > 5:
        block("PAX", f"{len(pax)} passengers")
    flights = args.get("flights") or []
    if not route_ok(
        args.get("flight_type"), args.get("origin"), args.get("destination"), legs(db, flights)
    ):
        block("ROUTE_BOOK", "the flights do not match origin, destination and trip type")
    price = 0.0
    for f in flights:
        day = db["flights"].get(f.get("flight_number"), {}).get("dates", {}).get(f.get("date"), {})
        if day.get("status") != "available":
            block("ROUTE_BOOK", f"{f.get('flight_number')} is not available on {f.get('date')}")
        price += (day.get("prices") or {}).get(cabin, 0) * len(pax)
    if args.get("insurance") == "yes":
        price += INSURANCE_FEE * len(pax)
    total, nonfree = args.get("total_baggages", 0), args.get("nonfree_baggages", 0)
    allowance = free_bags(user.get("membership", "regular"), cabin, len(pax))
    if nonfree != max(0, total - allowance):
        block("BAG_FEE", f"{nonfree} paid bags for {total} total, {allowance} free")
    price += BAG_FEE * nonfree
    methods = user.get("payment_methods", {})
    pays = args.get("payment_methods") or []
    kinds = Counter()
    for p in pays:
        m = methods.get(p.get("payment_id"))
        if m is None:
            block("PAY_BOOK", f"{p.get('payment_id')} is not in the user's profile")
            continue
        kinds[m.get("source")] += 1
        if m.get("source") in ("gift_card", "certificate") and m.get("amount", 0) < p.get(
            "amount", 0
        ):
            block("PAY_BOOK", f"{p.get('payment_id')} balance is below {p.get('amount')}")
    if kinds["certificate"] > 1 or kinds["credit_card"] > 1 or kinds["gift_card"] > 3:
        block("PAY_BOOK", f"payment mix {dict(kinds)} exceeds the limits")
    paid = sum(p.get("amount", 0) for p in pays)
    if abs(paid - price) > 0.005:
        block("PAY_BOOK", f"payments add up to {paid}, the price is {price:.0f}")
    if duplicate_rule:
        wanted = {(f.get("flight_number"), f.get("date")) for f in flights}
        people = {(p.get("first_name"), p.get("last_name"), p.get("dob")) for p in pax}
        for r in db["reservations"].values():
            if r.get("status") == "cancelled":
                continue
            seats = {(f["flight_number"], f["date"]) for f in r["flights"]}
            held = {(p["first_name"], p["last_name"], p["dob"]) for p in r["passengers"]}
            if seats & wanted and held & people:
                block(
                    "DUPLICATE_SEAT",
                    f"a passenger already holds a seat on these flights ({r['reservation_id']})",
                )
                break


def _certificate(ctx: Context, block) -> None:
    db, args = ctx.db, ctx.args
    uid = args.get("user_id")
    user = _user(ctx, uid)
    mine = [
        db["reservations"][r]
        for r in user.get("reservations", [])
        if r in db["reservations"] and db["reservations"][r].get("status") != "cancelled"
    ]
    everything = [
        db["reservations"][r] for r in user.get("reservations", []) if r in db["reservations"]
    ]
    if user.get("membership", "regular") == "regular" and not any(
        r.get("insurance") == "yes" or r.get("cabin") == "business" for r in mine
    ):
        block("COMP_ELIGIBLE", "regular member without insurance or business")
    changed = {
        a.get("reservation_id")
        for name, a in ctx.prior_writes
        if name in ("update_reservation_flights", "cancel_reservation")
    }
    amount = args.get("amount")
    allowed = set()
    for r in everything:
        statuses = {flight_status(db, f["flight_number"], f["date"]) for f in r["flights"]}
        if "cancelled" in statuses:
            allowed.add(100 * len(r["passengers"]))
        if "delayed" in statuses and r["reservation_id"] in changed:
            allowed.add(50 * len(r["passengers"]))
    if amount not in allowed:
        block("COMP_CAUSE", f"${amount} matches no cancelled or delayed-and-changed reservation")


def to_json(outcome: Outcome) -> dict[str, Any]:
    return {
        "blocks": [{"rule": b.rule, "reason": b.reason} for b in outcome.blocks],
        "needs": sorted(outcome.needs),
    }
