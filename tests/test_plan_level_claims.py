"""Plan-level claim rules of experiments/2026-11-05-plan-level-claims on toy calls."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[1] / "experiments/2026-11-05-plan-level-claims/plan.py"
_spec = importlib.util.spec_from_file_location("plan", _PATH)
plan = importlib.util.module_from_spec(_spec)
sys.modules["plan"] = plan
_spec.loader.exec_module(plan)


def verify(claim, action, args, db):
    """A toy per-call verifier: refund truth = args['refund']; items truth = args['items']."""
    if claim["kind"] == "refund":
        ok = abs(claim["amount"] - args["refund"]) <= 0.01
        return {"verdict": "true" if ok else "false", "truth": args["refund"], "why": "refund"}
    if claim["kind"] == "items":
        ok = sorted(claim["items"]) == sorted(args["items"])
        return {"verdict": "true" if ok else "false", "truth": sorted(args["items"]), "why": "i"}
    return {"verdict": "unverifiable", "truth": None, "why": "x"}


def match(claim, own, union):
    return sorted(claim["items"]) == sorted(union) if claim["kind"] == "items" else None


A = ("return", {"order_id": "#W1", "refund": 10.0, "items": ["a"]}, {})
B = ("return", {"order_id": "#W2", "refund": 32.5, "items": ["b", "c"]}, {})


def test_sum_other_union_and_untouched():
    total = {"kind": "refund", "amount": 42.5}
    assert plan.plan_verdict(total, A, [B], verify, match)["plan"] == "sum"
    about_b = {"kind": "refund", "amount": 32.5}
    assert plan.plan_verdict(about_b, A, [B], verify, match)["plan"] == "other"
    both = {"kind": "items", "items": ["c", "a", "b"]}
    assert plan.plan_verdict(both, A, [B], verify, match)["plan"] == "union"
    wrong = {"kind": "refund", "amount": 99.0}
    r = plan.plan_verdict(wrong, A, [B], verify, match)
    assert r["verdict"] == "false" and r["plan"] is None
    assert (
        plan.plan_verdict({"kind": "refund", "amount": 10.0}, A, [B], verify, match)["plan"] is None
    )
    assert plan.plan_verdict(total, A, [], verify, match)["verdict"] == "false"


def test_plan_calls_drops_self_retries_and_later_when_so_far():
    retry = ("return", {"order_id": "#W1", "refund": 10.0, "items": ["a"], "payment_id": "x"}, {})
    session = [("w1", 0, A), ("w2", 1, retry), ("w3", 2, B)]
    own = ("w1", 0, "return", A[1])
    assert plan.plan_calls(own, session, so_far=False) == [B]
    assert plan.plan_calls(own, session, so_far=True) == []
    assert plan.plan_calls(("w3", 2, "return", B[1]), session, so_far=True) == [A]
