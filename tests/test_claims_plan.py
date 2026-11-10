"""Scope routing of the plan-aware claims verifier (experiments/2026-11-05-airline-holdout)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[1] / "experiments/2026-11-05-airline-holdout/claims_plan.py"
_spec = importlib.util.spec_from_file_location("claims_plan", _PATH)
cp = importlib.util.module_from_spec(_spec)
sys.modules["claims_plan"] = cp
_spec.loader.exec_module(cp)


def verify(claim, action, args, db):
    ok = abs(claim["amount"] - args["refund"]) <= 0.01
    return {"verdict": "true" if ok else "false", "truth": args["refund"], "why": "refund"}


def match(claim, own, union):
    return None


A = ("return", {"order_id": "#W0000001", "refund": 10.0}, {})
B = ("return", {"order_id": "#W0000002", "refund": 32.5}, {})


def v(claim, others=(B,)):
    return cp.plan_verdict(claim, A, list(others), verify, match)


def test_scopes():
    assert (
        v({"kind": "refund", "amount": 10.0, "scope": "this_call", "target": None})["verdict"]
        == "true"
    )
    other = {"kind": "refund", "amount": 32.5, "scope": "other_call", "target": "order #W0000002"}
    assert v(other)["verdict"] == "true" and v(other)["plan"] == "other_call"
    assert v(other, others=())["verdict"] == "unverifiable"
    # a this_call claim about another target is routed to that call
    assert v({**other, "scope": "this_call"})["verdict"] == "true"
    total = {"kind": "refund", "amount": 42.5, "scope": "plan", "target": None}
    assert v(total)["plan"] == "sum" and v(total)["verdict"] == "true"
    # a plan claim is never rescued by being true of one other call
    one = {"kind": "refund", "amount": 32.5, "scope": "plan", "target": None}
    assert v(one)["verdict"] == "false"


def test_schema_and_targets():
    for d in ("airline", "retail"):
        _, schema, instructions = cp.domain(d)
        item = schema["properties"]["claims"]["items"]
        assert set(item["required"]) == set(item["properties"])
        assert "scope" in item["properties"] and "scope" in instructions
    assert cp._norm_target("order #W5199551") == "#W5199551"
    assert cp._norm_target("xehm4b") == "XEHM4B"
