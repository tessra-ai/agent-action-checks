"""The airline rules of experiments/2026-10-28-airline-rules on a toy database."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "experiments/2026-10-28-airline-rules/rules.py"
_spec = importlib.util.spec_from_file_location("airline_rules", _PATH)
rules = importlib.util.module_from_spec(_spec)
sys.modules["airline_rules"] = rules  # dataclasses look the module up
_spec.loader.exec_module(rules)


def _day(status="available", eco=100, biz=300, seats=9):
    return {
        "status": status,
        "prices": {"basic_economy": 50, "economy": eco, "business": biz},
        "available_seats": {"basic_economy": seats, "economy": seats, "business": seats},
    }


DB = {
    "flights": {
        "F1": {"origin": "AAA", "destination": "BBB", "dates": {"2024-05-20": _day()}},
        "F2": {"origin": "BBB", "destination": "AAA", "dates": {"2024-05-22": _day()}},
        "F3": {"origin": "AAA", "destination": "CCC", "dates": {"2024-05-20": _day()}},
        "F4": {"origin": "AAA", "destination": "BBB", "dates": {"2024-05-21": _day()}},
        "F9": {"origin": "AAA", "destination": "BBB", "dates": {"2024-05-10": _day("landed")}},
        "FX": {"origin": "AAA", "destination": "BBB", "dates": {"2024-05-20": _day("cancelled")}},
    },
    "users": {
        "ann_lee_1": {
            "membership": "regular",
            "payment_methods": {
                "credit_card_1": {"source": "credit_card", "id": "credit_card_1"},
                "gift_card_1": {"source": "gift_card", "id": "gift_card_1", "amount": 30.0},
                "certificate_1": {"source": "certificate", "id": "certificate_1", "amount": 500.0},
            },
            "reservations": ["R1"],
        },
        "bob_kim_2": {"membership": "gold", "payment_methods": {}, "reservations": []},
    },
    "reservations": {
        "R1": {
            "reservation_id": "R1",
            "user_id": "ann_lee_1",
            "origin": "AAA",
            "destination": "BBB",
            "flight_type": "round_trip",
            "cabin": "economy",
            "flights": [
                {"flight_number": "F1", "date": "2024-05-20", "price": 100},
                {"flight_number": "F2", "date": "2024-05-22", "price": 100},
            ],
            "passengers": [{"first_name": "Ann", "last_name": "Lee", "dob": "1990-01-01"}],
            "created_at": "2024-05-01T10:00:00",
            "insurance": "no",
            "total_baggages": 1,
            "nonfree_baggages": 0,
            "status": None,
        }
    },
}


def _ctx(action, args, db=None, typed=("ann_lee_1",), prior=()):
    return rules.Context(action, args, db or DB, frozenset(typed), tuple(prior))


def _rules(outcome):
    return {b.rule for b in outcome.blocks}


def _db(**reservation_changes):
    db = copy.deepcopy(DB)
    db["reservations"]["R1"].update(reservation_changes)
    return db


def test_ownership_needs_a_typed_user_id():
    assert "OWN" in _rules(
        rules.check(_ctx("cancel_reservation", {"reservation_id": "R1"}, typed=()))
    )
    assert "OWN" in _rules(rules.check(_ctx("cancel_reservation", {"reservation_id": "NOPE"})))


def test_cancel_eligibility():
    cancel = {"reservation_id": "R1"}
    assert "CANCEL_ELIGIBLE" in _rules(rules.check(_ctx("cancel_reservation", cancel)))
    assert not rules.check(_ctx("cancel_reservation", cancel, _db(cabin="business"))).blocked
    recent = _db(created_at="2024-05-15T09:00:00")
    assert not rules.check(_ctx("cancel_reservation", cancel, recent)).blocked
    insured = rules.check(_ctx("cancel_reservation", cancel, _db(insurance="yes")))
    assert not insured.blocked and insured.needs == {"reason_covered"}
    airline = _db(flights=[{"flight_number": "FX", "date": "2024-05-20", "price": 100}])
    assert not rules.check(_ctx("cancel_reservation", cancel, airline)).blocked


def test_cancel_refuses_flown_reservations():
    flown = _db(
        cabin="business", flights=[{"flight_number": "F9", "date": "2024-05-10", "price": 100}]
    )
    assert "FLOWN_CANCEL" in _rules(
        rules.check(_ctx("cancel_reservation", {"reservation_id": "R1"}, flown))
    )


def _update(flights, cabin="economy", payment="credit_card_1"):
    return {"reservation_id": "R1", "cabin": cabin, "flights": flights, "payment_id": payment}


SAME = [
    {"flight_number": "F1", "date": "2024-05-20"},
    {"flight_number": "F2", "date": "2024-05-22"},
]


def test_flight_changes():
    other_day = [{"flight_number": "F4", "date": "2024-05-21"}, SAME[1]]
    assert not rules.check(_ctx("update_reservation_flights", _update(other_day))).blocked
    basic = _db(cabin="basic_economy")
    out = rules.check(
        _ctx("update_reservation_flights", _update(other_day, "basic_economy"), basic)
    )
    assert "BASIC_NO_FLIGHT_CHANGE" in _rules(out)
    # A cabin change on the same flights is allowed even for basic economy.
    assert not rules.check(_ctx("update_reservation_flights", _update(SAME), basic)).blocked
    new_city = [{"flight_number": "F3", "date": "2024-05-20"}, SAME[1]]
    assert "SAME_ROUTE" in _rules(
        rules.check(_ctx("update_reservation_flights", _update(new_city)))
    )


def test_update_payment():
    out = rules.check(_ctx("update_reservation_flights", _update(SAME, "business", "gift_card_1")))
    assert "PAY_UPDATE" in _rules(out)  # $400 upgrade on a $30 gift card
    out = rules.check(
        _ctx("update_reservation_flights", _update(SAME, "business", "certificate_1"))
    )
    assert "PAY_UPDATE" in _rules(out)


@pytest.mark.parametrize(
    ("total", "nonfree", "blocked"),
    [(2, 1, False), (2, 0, True), (2, 2, True), (0, 0, True)],
)
def test_bags(total, nonfree, blocked):
    args = {
        "reservation_id": "R1",
        "total_baggages": total,
        "nonfree_baggages": nonfree,
        "payment_id": "credit_card_1",
    }
    assert rules.check(_ctx("update_reservation_baggages", args)).blocked is blocked


def _book(**changes):
    args = {
        "user_id": "ann_lee_1",
        "origin": "AAA",
        "destination": "BBB",
        "flight_type": "one_way",
        "cabin": "economy",
        "flights": [{"flight_number": "F4", "date": "2024-05-21"}],
        "passengers": [{"first_name": "Cy", "last_name": "Lee", "dob": "2000-01-01"}],
        "payment_methods": [{"payment_id": "credit_card_1", "amount": 100}],
        "total_baggages": 1,
        "nonfree_baggages": 0,
        "insurance": "no",
    }
    return {**args, **changes}


def test_booking():
    assert not rules.check(_ctx("book_reservation", _book())).blocked
    short = _book(payment_methods=[{"payment_id": "credit_card_1", "amount": 90}])
    assert "PAY_BOOK" in _rules(rules.check(_ctx("book_reservation", short)))
    wrong_way = _book(flights=[{"flight_number": "F2", "date": "2024-05-22"}])
    assert "ROUTE_BOOK" in _rules(rules.check(_ctx("book_reservation", wrong_way)))
    bags = _book(total_baggages=2, nonfree_baggages=0)
    assert "BAG_FEE" in _rules(rules.check(_ctx("book_reservation", bags)))


def test_duplicate_seat():
    again = _book(
        flights=[{"flight_number": "F1", "date": "2024-05-20"}],
        passengers=[{"first_name": "Ann", "last_name": "Lee", "dob": "1990-01-01"}],
    )
    assert "DUPLICATE_SEAT" in _rules(rules.check(_ctx("book_reservation", again)))
    assert "DUPLICATE_SEAT" not in _rules(
        rules.check(_ctx("book_reservation", again), duplicate_rule=False)
    )


def test_compensation():
    cert = {"user_id": "ann_lee_1", "amount": 100}
    out = rules.check(_ctx("send_certificate", cert))
    assert {"COMP_ELIGIBLE", "COMP_CAUSE"} <= _rules(out)
    gold = copy.deepcopy(DB)
    gold["users"]["ann_lee_1"]["membership"] = "gold"
    gold["reservations"]["R1"]["flights"][0] = {
        "flight_number": "FX",
        "date": "2024-05-20",
        "price": 100,
    }
    assert not rules.check(_ctx("send_certificate", cert, gold)).blocked


def test_context_reads_typed_ids_and_successful_writes():
    messages = [
        {"role": "user", "content": "I am ann_lee_1, not zed_q_9"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}}
            ],
        },
        {"role": "tool", "id": "c1", "error": False, "content": "{}"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c2", "name": "send_certificate", "arguments": {}}],
        },
        {"role": "tool", "id": "c2", "error": True, "content": "Error"},
    ]
    ctx = rules.context_from("send_certificate", {}, DB, messages)
    assert ctx.typed_user_ids == {"ann_lee_1"}
    assert ctx.prior_writes == (("cancel_reservation", {"reservation_id": "R1"}),)
