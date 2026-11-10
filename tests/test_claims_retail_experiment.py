"""The retail claims check of experiments/2026-11-05-claims-check-retail on a toy database."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[1] / "experiments/2026-11-05-claims-check-retail/claims_retail.py"
_spec = importlib.util.spec_from_file_location("claims_retail", _PATH)
claims = importlib.util.module_from_spec(_spec)
sys.modules["claims_retail"] = claims
_spec.loader.exec_module(claims)

DB = {
    "products": {
        "P1": {
            "product_id": "P1",
            "name": "Kettle",
            "variants": {
                "K1": {"item_id": "K1", "price": 100.0, "available": True},
                "K2": {"item_id": "K2", "price": 130.5, "available": True},
            },
        }
    },
    "users": {
        "ann_lee_1": {
            "payment_methods": {
                "paypal_1": {"source": "paypal", "id": "paypal_1"},
                "gift_card_1": {"source": "gift_card", "id": "gift_card_1", "balance": 20.0},
                "credit_card_1": {
                    "source": "credit_card",
                    "id": "credit_card_1",
                    "brand": "visa",
                    "last_four": "4321",
                },
            },
            "orders": ["#W1"],
        }
    },
    "orders": {
        "#W1": {
            "order_id": "#W1",
            "user_id": "ann_lee_1",
            "status": "delivered",
            "items": [
                {"item_id": "K1", "name": "Kettle", "price": 100.0, "product_id": "P1"},
                {"item_id": "M1", "name": "Mug", "price": 12.25, "product_id": "P2"},
            ],
            "payment_history": [
                {"transaction_type": "payment", "amount": 112.25, "payment_method_id": "paypal_1"}
            ],
        }
    },
}


def claim(kind, **fields):
    base = {
        "kind": kind,
        "quote": "",
        "amount": None,
        "payment": None,
        "item_ids": None,
        "item_names": None,
        "timing": None,
    }
    return {**base, **fields}


RETURN = {"order_id": "#W1", "item_ids": ["K1", "M1"], "payment_method_id": "paypal_1"}
EXCHANGE = {
    "order_id": "#W1",
    "item_ids": ["K1"],
    "new_item_ids": ["K2"],
    "payment_method_id": "gift_card_1",
}


def v(c, action="return_delivered_order_items", args=RETURN):
    return claims.verify(c, action, args, DB)["verdict"]


def test_refund_amounts():
    assert v(claim("refund", amount=112.25)) == "true"
    assert v(claim("refund", amount=100)) == "false"
    assert v(claim("refund", amount=112.25), "cancel_pending_order", {"order_id": "#W1"}) == "true"


def test_exchange_charge_and_balance():
    assert v(claim("charge", amount=30.5), "exchange_delivered_order_items", EXCHANGE) == "true"
    assert v(claim("refund", amount=30.5), "exchange_delivered_order_items", EXCHANGE) == "false"
    gone = claim("balance_after", amount=-10.5, payment="gift card")
    assert v(gone, "exchange_delivered_order_items", EXCHANGE) == "true"


def test_payment_method_resolution():
    assert v(claim("payment_method", payment="your PayPal account")) == "true"
    assert v(claim("payment_method", payment="the original payment method")) == "true"
    assert v(claim("payment_method", payment="Visa ending 4321")) == "false"
    assert v(claim("payment_method", payment="a card")) == "false"  # one credit card: resolves
    two_gift_cards = {
        **DB,
        "users": {
            "ann_lee_1": {
                **DB["users"]["ann_lee_1"],
                "payment_methods": {
                    **DB["users"]["ann_lee_1"]["payment_methods"],
                    "gift_card_12": {"source": "gift_card", "id": "gift_card_12"},
                },
            }
        },
    }
    gift = claim("payment_method", payment="gift card")
    ambiguous = claims.verify(gift, "return_delivered_order_items", RETURN, two_gift_cards)
    assert ambiguous["verdict"] == "unverifiable"  # "gift card" is not a credit card
    named = claim("payment_method", payment="gift_card_1")
    assert claims.resolve_payment("gift_card_1", two_gift_cards["users"]["ann_lee_1"], None) == (
        "gift_card_1"
    )
    to_gift_card = {**RETURN, "payment_method_id": "gift_card_1"}
    assert v(named, "return_delivered_order_items", to_gift_card) == "true"
    # a payment claim on a call that moves no money is unverifiable (README, second deviation)
    assert v(gift, "modify_user_address", {"user_id": "ann_lee_1"}) == "unverifiable"


def test_items_and_prices():
    assert v(claim("items", item_names=["kettle", "Mug"])) == "true"
    assert v(claim("items", item_names=["Kettle"])) == "false"
    assert v(claim("price_quote", item_names=["Mug"], amount=12.25)) == "true"
    assert v(claim("price_quote", item_ids=["K2"], amount=130.5)) == "true"
    assert v(claim("price_quote", item_ids=["K2"], amount=100)) == "false"


def test_refund_timing():
    assert v(claim("refund_timing", timing="days")) == "true"
    assert v(claim("refund_timing", timing="immediate")) == "false"
    to_card = {**RETURN, "payment_method_id": "gift_card_1"}
    assert v(claim("refund_timing", timing="immediate"), args=to_card) == "true"


def test_unverifiable_never_flags():
    assert v(claim("other")) == "unverifiable"
    assert v(claim("refund", payment="your PayPal")) == "unverifiable"  # no amount stated
    assert v(claim("refund"), "modify_user_address", {"user_id": "ann_lee_1"}) == "unverifiable"
    item = claims.SCHEMA["properties"]["claims"]["items"]
    assert set(item["required"]) == set(item["properties"])
