"""Rely-1 M0 (experiments/2026-11-18-rely1-m0): packet format, frozen splits, sentence units."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parents[1] / "experiments/2026-11-18-rely1-m0"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(HERE))
packets = _load("packets")
sentences = _load("sentences")

SPECS = {
    "get_user_details": {"kind": "read", "description": "Get user.", "parameters": []},
    "cancel_reservation": {
        "kind": "write",
        "description": "Cancel the whole reservation.",
        "parameters": [{"name": "reservation_id", "type": "str", "description": "The id."}],
    },
}


def _run() -> dict:
    return {
        "write_id": "W1",
        "messages": [
            {"role": "assistant", "content": "Hi! How can I help you today?"},
            {"role": "user", "content": "Cancel ABC123 please."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "function": "get_user_details", "arguments": {"user_id": "u"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": '{"user_id": "u", "reservations": ["ABC123"]}',
            },
            {"role": "assistant", "content": "It is refundable. Shall I cancel it?"},
            {"role": "user", "content": "Yes."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "proposed",
                        "function": "cancel_reservation",
                        "arguments": {"reservation_id": "ABC123"},
                    }
                ],
            },
        ],
    }


def test_packet_moves_lookups_to_the_ledger_once():
    p = packets.build("airline1", _run(), SPECS, "POLICY")
    assert [e["tool"] for e in p["ledger"]] == ["get_user_details"]
    assert p["ledger"][0]["result"] == '{"user_id":"u","reservations":["ABC123"]}'
    assert p["proposed_action"]["tool"] == "cancel_reservation"
    text = packets.render(p)
    # the lookup result appears once, in the ledger, and the conversation points to it
    assert text.count('"reservations":["ABC123"]') == 1
    assert "(lookups L1)" in text
    # the proposed call is not in the ledger
    assert "cancel_reservation {" not in text.split("# Evidence ledger")[1]


def test_consent_turn_is_the_last_customer_message():
    p = packets.build("airline1", _run(), SPECS, "POLICY")
    assert p["conversation"][p["consent_turn"]]["text"] == "Yes."
    assert "[T5] customer [CONSENT TURN]: Yes." in packets.render(p)


def test_render_sections_in_order():
    text = packets.render(packets.build("airline1", _run(), SPECS, "# Policy heading\nRule."))
    heads = [
        "# Conversation up to the proposed action",
        "\n# Proposed action\n",
        "\n# Policy\n",
        "\n# Evidence ledger (every lookup, in order)\n",
    ]
    idx = [text.index(h) for h in heads]
    assert idx == sorted(idx)


def test_docstring_split():
    desc, args = packets._split_docstring(
        "Cancel it.\n\nArgs:\n    reservation_id: The id,\n        such as 'X'."
        "\n\nReturns:\n    Thing."
    )
    assert desc == "Cancel it."
    assert args == {"reservation_id": "The id, such as 'X'."}


def test_sentence_split_keeps_amounts_and_splits_lines():
    s = sentences.split_sentences("The total is $1,282.50. Shall I proceed?\n- Cabin: Economy")
    assert s == ["The total is $1,282.50.", "Shall I proceed?", "- Cabin: Economy"]


def test_frozen_splits_match_their_hashes():
    manifest = json.loads((HERE / "splits/manifest.json").read_text())
    for name, info in manifest["splits"].items():
        body = (HERE / f"splits/{name}.json").read_bytes()
        assert hashlib.sha256(body).hexdigest() == info["sha256"], name
        assert len(json.loads(body)) == info["actions"], name


def test_splits_are_task_disjoint_where_required():
    rows = {
        n: json.loads((HERE / f"splits/{n}.json").read_text())
        for n in ("train", "dev", "test_repeat", "test_unseen")
    }
    tasks = {n: {(r["domain"], r["task_id"]) for r in v} for n, v in rows.items()}
    for a, b in [
        ("train", "dev"),
        ("train", "test_unseen"),
        ("dev", "test_unseen"),
        ("test_repeat", "test_unseen"),
    ]:
        assert not tasks[a] & tasks[b], (a, b)
    ids = [r["write_id"] for v in rows.values() for r in v]
    assert len(ids) == len(set(ids)) == 328
    manifest = json.loads((HERE / "splits/manifest.json").read_text())
    unseen = set(manifest["unseen_task_ids"]) | set(
        manifest["unseen_task_ids_only_in_second_capture"]
    )
    assert {t for _, t in tasks["test_unseen"]} == unseen
    # every repeat task has a train or dev conversation
    assert tasks["test_repeat"] <= tasks["train"] | tasks["dev"]


def test_anchors_are_in_dev():
    dev = {r["write_id"] for r in json.loads((HERE / "splits/dev.json").read_text())}
    assert set(packets.ANCHORS) <= dev


def test_worked_cases_come_from_train():
    train = {r["write_id"] for r in json.loads((HERE / "splits/train.json").read_text())}
    cited = set(re.findall(r"`(01M[0-9A-Z]{23})`", (HERE / "label_definition.md").read_text()))
    assert cited and cited <= train, sorted(cited - train)
