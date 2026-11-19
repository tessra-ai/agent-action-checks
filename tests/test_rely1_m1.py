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
    blob = re.search(r"const DATA = (.*?);\nconst (SHEET|KEY)", html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


def test_second_sheet_is_blind_plain_and_drawn_from_prithvis():
    second, prithvi = _data("second"), _data("prithvi")
    assert len(second["items"]) == 35  # 30 main + 5 over-limit
    allowed = {
        "key", "domain", "request", "last_customer", "text", "lead_in", "record", "action",
        "conversation", "all_records",
    }  # fmt: skip
    for it in second["items"]:
        assert set(it) == allowed  # no pre-fill, label, ruling, reason or claims-check field
    assert set(second) == {"sheet", "items", "examples", "fingerprint", "policy", "inputs"}
    keys = {i["key"] for i in second["items"]}
    assert keys <= {i["key"] for i in prithvi["items"]}
    task = {
        r["write_id"]: (r["domain"], r["task_id"])
        for r in map(json.loads, (HERE / "results/agreement.jsonl").read_text().splitlines())
    }
    examples = {task[e["key"].split(":")[0]] for e in second["examples"]}
    on_sheets = {task[k.split(":")[0]] for k in keys | {i["key"] for i in prithvi["items"]}}
    assert len(second["examples"]) == 2 and not examples & on_sheets  # no shared task
    assert {e["answer"] for e in second["examples"]} == {"yes", "no"}


def test_no_agreement_actions_are_not_labelled():
    agreed = {
        r["write_id"]: r["agreed"]
        for r in map(json.loads, (HERE / "results/agreement.jsonl").read_text().splitlines())
    }
    assert len(agreed) == 174
    rows = [json.loads(x) for x in (HERE / "results/label_set.jsonl").read_text().splitlines()]
    assert all(agreed[r["write_id"]] != "no" for r in rows)
    blocks = {r["review"]["prithvi_reason"] for r in rows if r["review"]["prithvi"]}
    assert blocks == {"pre-filled MC", "random 40", "over-limit block"}
    over = [r for r in rows if r["review"]["prithvi_reason"] == "over-limit block"]
    assert len(over) == 10 and all(r["length"] == "over_8192" for r in over)


def test_score_counts_on_toy_answers():
    score = _load("score")

    def row(key, w, length, prefill, block, second):
        return {
            "unit_key": key,
            "write_id": w,
            "length": length,
            "prefill": prefill,
            "review": {
                "prithvi": block is not None,
                "prithvi_reason": block,
                "second_reason": second,
            },
        }

    rows = [
        row("a", "W1", "under_8192", "MC", "pre-filled MC", "main"),
        row("b", "W1", "under_8192", "not MC", "random 40", "main"),
        row("c", "W2", "over_8192", "not MC", None, None),
        row("d", "W3", "under_8192", "not MC", "random 40", None),
    ]
    agreement = [
        {"write_id": "W1", "agreed": "yes", "source": "rule"},
        {"write_id": "W2", "agreed": "yes", "source": "prefill"},
        {"write_id": "W3", "agreed": "yes", "source": "prefill"},
        {"write_id": "W4", "agreed": "no", "source": "prefill"},
    ]
    prithvi = {
        "a": {"mc": "yes"},
        "b": {"mc": "yes"},
        "d": {"mc": "no"},
        "agree:W2": {"agreed": "yes"},
        "agree:W3": {"agreed": "no"},  # Prithvi: no agreement -> d leaves every count
        "agree:W4": {"agreed": "yes"},  # was excluded, now agreed -> needs follow-up
    }
    out = score.score(rows, prithvi, {"a": "yes", "b": "no"}, agreement)
    assert out["a_mc_prefills_confirmed"]["all"]["confirmed_mc"] == 1
    assert out["gate_prefill_vs_prithvi_random40"]["all"] == {
        "n": 1, "answered": 1, "match": 0, "unsure": 0,
    }  # fmt: skip
    assert out["b_mc_found_in_random40"]["found"] == 1
    assert out["b_mc_found_in_random40"]["unreviewed_not_mc_statements"] == 1
    assert out["gate_prithvi_vs_second_main30"]["all"]["agree"] == 1
    assert out["agreement_applied"]["statements_dropped_as_no_agreement"] == 1
    assert out["agreement_applied"]["actions_moved_to_agreed_need_follow_up"] == ["W4"]
    assert out["provisional"] is True
    assert out["agreement_prefills"]["changed"] == 2


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


def test_turn_citations_parse_strictly():
    score = _load("score")
    assert score.parse_turns("31, 34") == [31, 34]
    assert score.parse_turns("T31-T34") == [31, 32, 33, 34]
    assert score.parse_turns("") == []
    assert score.parse_turns("about 31") is None
    assert score.parse_turns("T34-T31") is None
    assert score.parse_turns("T31-T34", customer={31, 33}, n_turns=40) == [31, 33]
    assert score.parse_turns("T1-T999", customer={31}, n_turns=40) is None  # past the end
    assert score.parse_turns("T5-T6", customer={31}, n_turns=40) is None  # no customer turn


def test_card_finds_digit_leading_ids_and_resolves_repeats():
    friend = _load("friend")
    assert "59XX6W" in friend.norm_tokens("cancel reservation 59XX6W now")
    assert "12345.67" in friend.norm_tokens("a refund of $12345.67")
    packet = {
        "conversation": [
            {"role": "customer", "text": "Hi"},
            {"role": "agent", "text": "", "ledger_refs": [1]},
            {"role": "agent", "text": "Your fare for ABC123 is $104."},
            {"role": "agent", "text": "", "ledger_refs": [2]},
        ],
        "ledger": [
            {"n": 1, "tool": "get", "kind": "read", "arguments": {"id": "ABC123"},
             "result": "(same as L2)", "error": False, "same_as": 2},
            {"n": 2, "tool": "get", "kind": "read", "arguments": {"id": "ABC123"},
             "result": '{"price": 104}', "error": False},
        ],
        "proposed_action": {"arguments": {"reservation_id": "ABC123"}},
    }  # fmt: skip
    best = friend.relevant(packet, "Your fare for ABC123 is $104.", None, turn=3)
    assert best[0]["n"] == 1 and best[0]["result"] == '{"price": 104}'  # made before the sentence
