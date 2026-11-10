"""The claims check of experiments/2026-10-28-claims-check on a toy database."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parents[1] / "experiments"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


claims = _load("claims_check", _ROOT / "2026-10-28-claims-check/claims.py")


def _day(eco, biz=500, status="available"):
    return {
        "status": status,
        "prices": {"basic_economy": 40, "economy": eco, "business": biz},
        "available_seats": {"basic_economy": 9, "economy": 9, "business": 9},
    }


def _flight(origin, dest, dep, arr, days):
    return {
        "origin": origin,
        "destination": dest,
        "scheduled_departure_time_est": dep,
        "scheduled_arrival_time_est": arr,
        "dates": days,
    }


DB = {
    "flights": {
        "D1": _flight("AAA", "BBB", "08:00:00", "10:00:00", {"2024-05-24": _day(200)}),
        "S1": _flight("AAA", "CCC", "06:00:00", "07:00:00", {"2024-05-24": _day(50)}),
        "S2": _flight("CCC", "BBB", "09:00:00", "11:00:00", {"2024-05-24": _day(60)}),
        "S3": _flight("CCC", "BBB", "06:30:00", "08:00:00", {"2024-05-24": _day(10)}),
    },
    "users": {
        "ann_lee_1": {
            "membership": "gold",
            "payment_methods": {
                "credit_card_1": {
                    "source": "credit_card",
                    "id": "credit_card_1",
                    "last_four": "7447",
                },
                "gift_card_1": {"source": "gift_card", "id": "gift_card_1", "amount": 280.0},
                "certificate_1": {"source": "certificate", "id": "certificate_1", "amount": 500.0},
            },
            "reservations": ["R1"],
        }
    },
    "reservations": {
        "R1": {
            "reservation_id": "R1",
            "user_id": "ann_lee_1",
            "origin": "AAA",
            "destination": "BBB",
            "flight_type": "one_way",
            "cabin": "economy",
            "flights": [{"flight_number": "D1", "date": "2024-05-24", "price": 200}],
            "passengers": [{"first_name": "Ann", "last_name": "Lee", "dob": "1990-01-01"}],
            "payment_history": [{"payment_id": "gift_card_1", "amount": 200}],
            "created_at": "2024-05-01T10:00:00",
            "insurance": "no",
            "total_baggages": 0,
            "nonfree_baggages": 0,
            "status": None,
        }
    },
}


def claim(kind, **fields):
    base = {
        "kind": kind,
        "quote": "",
        "amount": None,
        "payment": None,
        "flights": None,
        "cabin": None,
        "total_bags": None,
        "paid_bags": None,
        "remaining_usable": None,
        "rank": None,
        "cancellable": None,
    }
    return {**base, **fields}


BOOK = {
    "user_id": "ann_lee_1",
    "origin": "AAA",
    "destination": "BBB",
    "flight_type": "one_way",
    "cabin": "economy",
    "flights": [{"flight_number": "D1", "date": "2024-05-24"}],
    "passengers": [{"first_name": "Ann", "last_name": "Lee", "dob": "1990-01-01"}],
    "payment_methods": [{"payment_id": "certificate_1", "amount": 200}],
    "total_baggages": 0,
    "nonfree_baggages": 0,
    "insurance": "no",
}


def _verdict(c, action="book_reservation", args=BOOK, db=DB):
    return claims.verify(c, action, args, db)["verdict"]


def test_charge_and_price():
    assert _verdict(claim("charge", amount=200)) == "true"
    assert _verdict(claim("charge", amount=299)) == "false"
    assert (
        _verdict(
            claim(
                "price_quote",
                amount=200,
                flights=[{"flight_number": "D1", "date": None}],
                cabin="economy",
            )
        )
        == "true"
    )


def test_certificate_remainder_is_not_left():
    left = claim("balance_after", amount=300, payment="certificate", remaining_usable=True)
    assert _verdict(left) == "false"
    lost = claim("balance_after", amount=300, payment="certificate", remaining_usable=False)
    assert _verdict(lost) == "true"


def test_cabin_change_cost_when_already_in_that_cabin():
    down = {
        "reservation_id": "R1",
        "cabin": "basic_economy",
        "flights": [{"flight_number": "D1", "date": "2024-05-24"}],
        "payment_id": "gift_card_1",
    }
    said = claim("cabin_change_cost", cabin="economy", amount=340)
    assert _verdict(said, "update_reservation_flights", down) == "false"
    assert _verdict(claim("refund", amount=160), "update_reservation_flights", down) == "true"


def test_option_rank():
    # Options: S1+S3 is not bookable (S3 leaves before S1 lands); S1+S2 = 110; D1 = 200.
    assert _verdict(claim("option_rank", rank="cheapest")) == "false"
    assert _verdict(claim("option_rank", rank="second_cheapest")) == "true"
    one_stop = {
        **BOOK,
        "flights": [
            {"flight_number": "S1", "date": "2024-05-24"},
            {"flight_number": "S2", "date": "2024-05-24"},
        ],
    }
    assert _verdict(claim("option_rank", rank="cheapest"), args=one_stop) == "true"


def test_payment_method_and_cancellable():
    assert _verdict(claim("payment_method", payment="the card ending in 7447")) == "false"
    assert _verdict(claim("payment_method", payment="certificate_1")) == "true"
    business = copy.deepcopy(DB)
    up = {
        "reservation_id": "R1",
        "cabin": "business",
        "flights": [{"flight_number": "D1", "date": "2024-05-24"}],
        "payment_id": "credit_card_1",
    }
    assert (
        _verdict(claim("cancellable", cancellable=True), "update_reservation_flights", up, business)
        == "true"
    )
    stay = {**up, "cabin": "economy"}
    assert (
        _verdict(claim("cancellable", cancellable=True), "update_reservation_flights", stay)
        == "false"
    )


def test_unverifiable_kinds_never_flag():
    assert _verdict(claim("other")) == "unverifiable"
    assert _verdict(claim("charge")) == "unverifiable"


def test_schema_is_strict():
    item = claims.SCHEMA["properties"]["claims"]["items"]
    assert set(item["required"]) == set(item["properties"])
    assert item["additionalProperties"] is False
