"""Rely-1 M1 (experiments/2026-11-18-rely1-m1): units, pre-fill citations, review sheets."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parents[1] / "experiments/2026-11-18-rely1-m1"
sys.path.insert(0, str(HERE))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


units = _load("units")
build = _load("build")


def _packet(text: str) -> dict:
    return {
        "conversation": [
            {"role": "customer", "text": "Book it."},
            {"role": "agent", "text": text},
        ]
    }


def test_list_items_carry_their_lead_in():
    us = units.units(
        _packet(
            "To proceed, I will use the following details:\n- Total price: $255\n- Bags: 3\n"
            "Shall I go ahead?"
        )
    )
    assert [u["text"] for u in us] == [
        "To proceed, I will use the following details:",
        "- Total price: $255",
        "- Bags: 3",
        "Shall I go ahead?",
    ]
    assert us[1]["lead_in"] == us[2]["lead_in"] == "To proceed, I will use the following details:"
    assert us[0]["lead_in"] is None and us[3]["lead_in"] is None
    assert us[1]["id"] == "T2.2"


def test_quotes_in_reasons():
    reason = "The yes rested on it; the agent wrongly claimed it was 'booked within 24 hours'."
    assert build.quoted_spans(reason) == ["booked within 24 hours"]
    assert build.cited_as_false(reason, "booked within 24 hours")
    support = 'The agent listed "3 checked bags (all free)" and the user said yes.'
    assert not build.cited_as_false(support, build.quoted_spans(support)[0])


def test_claim_spanning_two_units_goes_to_both():
    us = units.units(_packet("Your fare is $174. Upgrading costs $136 more."))
    claim = {"quote": "Your fare is $174. Upgrading costs $136 more.", "verdict": "false"}
    ids, how = build.locate(claim, us, "")
    assert how == "one unit" or (how == "spans units" and ids == ["T2.1", "T2.2"])


def _data(name: str) -> dict:
    html = (HERE / f"review/{name}_sheet.html").read_text()
    blob = re.search(r"const DATA = (.*?);\nconst SHEET", html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


def test_second_sheet_is_blind_and_drawn_from_prithvis():
    second, prithvi = _data("second"), _data("prithvi")
    assert len(second["items"]) == 30
    for it in second["items"]:
        assert not {"prefill", "prefill_source", "cited_by", "prefill_records"} & set(it)
    assert not any("rulings" in a or "truth" in a for a in second["actions"].values())
    assert {i["key"] for i in second["items"]} <= {i["key"] for i in prithvi["items"]}


def test_label_set_is_train_and_dev_only():
    m0 = HERE.parent / "2026-11-18-rely1-m0/splits"
    allowed = {
        r["write_id"] for n in ("train", "dev") for r in json.loads((m0 / f"{n}.json").read_text())
    }
    rows = [json.loads(x) for x in (HERE / "results/label_set.jsonl").read_text().splitlines()]
    assert {r["write_id"] for r in rows} <= allowed
    assert all(r["prefill"] != "MC" or any(c["as_false"] for c in r["cited_by"]) for r in rows)


def test_bold_heading_is_a_lead_in():
    us = units.units(_packet("**Flights eligible for upgrade:**\n- MSP to EWR (HAT300): 3 hours"))
    assert us[1]["lead_in"] == "**Flights eligible for upgrade:**"


def test_falsity_is_read_in_the_quotes_own_clause():
    reason = (
        "The reason is 'change of plan', so no condition holds, and the agent's claim that it was "
        "'booked within 24 hours' is false."
    )
    assert not build.cited_as_false(reason, "change of plan")
    assert build.cited_as_false(reason, "booked within 24 hours")
    assert build.cited_as_false(
        "Upgrading does not help, despite the agent claiming 'XEHM4B will then be eligible'.",
        "XEHM4B will then be eligible",
    )


def test_indented_continuation_keeps_the_lead_in():
    us = units.units(
        _packet(
            "To confirm, you want to:\n1. Return the boots\n   via PayPal\n2. Exchange the rest"
        )
    )
    assert [u["lead_in"] for u in us[1:]] == ["To confirm, you want to:"] * 3
