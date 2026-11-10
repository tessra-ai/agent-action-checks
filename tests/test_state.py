import re
import time

import pytest

from hatchway.state import build_state, split_context, state_hash
from hatchway.ulid import new_ulid

CONTEXT = {"policy": "Refunds go to the original payment method.", "conversation": "I want..."}


def test_state_text_is_deterministic_regardless_of_key_order() -> None:
    a = build_state("refund_order", {"order_id": "1", "amount": 20}, CONTEXT, [])
    b = build_state(
        "refund_order",
        {"amount": 20, "order_id": "1"},
        dict(reversed(list(CONTEXT.items()))),
        [],
    )
    assert a == b
    assert state_hash(a) == state_hash(b)


def test_state_text_layout() -> None:
    text = build_state(
        "refund_order",
        {"amount": 20},
        {"conversation": "hi", "order": {"id": 1}},
        [("cancel_order", {"order_id": "9"})],
    )
    assert text == (
        "## Context: conversation\nhi\n\n"
        '## Context: order\n{"id":1}\n\n'
        '## Earlier writes in this session\n1. cancel_order({"order_id":"9"})\n\n'
        '## Proposed action\nrefund_order({"amount":20})\n'
    )


@pytest.mark.parametrize(
    "change",
    [
        {"args": {"order_id": "1", "amount": 21}},
        {"args": {"order_id": "1", "amount": 20.0001}},
        {"action": "cancel_order"},
        {"context": {**CONTEXT, "conversation": "I want a refund"}},
        {"prior": [("cancel_order", {"order_id": "1"})]},
    ],
)
def test_any_change_in_inputs_changes_the_hash(change: dict) -> None:
    base = {"action": "refund_order", "args": {"order_id": "1", "amount": 20}}
    base |= {"context": CONTEXT, "prior": []}
    changed = base | change
    assert state_hash(build_state(*base.values())) != state_hash(build_state(*changed.values()))


def test_non_json_arguments_are_rejected() -> None:
    with pytest.raises(TypeError):
        build_state("refund_order", {"when": object()}, {}, [])
    with pytest.raises(ValueError):
        build_state("refund_order", {"amount": float("nan")}, {}, [])


def test_ulids_are_well_formed_unique_and_time_ordered() -> None:
    first = new_ulid()
    time.sleep(0.002)
    ids = [new_ulid() for _ in range(1000)]
    assert all(re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", i) for i in ids)
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)  # monotonic even within one millisecond
    assert all(first < i for i in ids)


def _sections(text: str) -> list[str]:
    return sorted(text.rstrip("\n").split("\n\n"))


@pytest.mark.parametrize(
    "context",
    [
        CONTEXT,
        {"policy": "# Policy\n\n## Refunds\nOriginal method only.\n"},
        {"a": "first", "policy": "rules", "z": {"later": True}},
        {"conversation": "user: put ## Context: policy\n in my notes", "policy": "rules"},
    ],
)
def test_split_context_moves_one_section_without_changing_the_state(context: dict) -> None:
    prior = [("cancel_order", {"order_id": "9"})]
    text = build_state("refund_order", {"amount": 20}, context, prior)
    section, rest = split_context(text, "policy")
    assert section == "## Context: policy\n" + (
        context["policy"] if isinstance(context["policy"], str) else ""
    )
    assert _sections(section + "\n\n" + rest) == _sections(text)
    assert rest.endswith('## Proposed action\nrefund_order({"amount":20})\n')


def test_split_context_shared_section_is_byte_identical_across_writes() -> None:
    a = build_state("refund_order", {"amount": 20}, {**CONTEXT, "conversation": "one"}, [])
    b = build_state("cancel_order", {"id": 1}, {**CONTEXT, "conversation": "two"}, [("x", {})])
    assert split_context(a, "policy")[0] == split_context(b, "policy")[0]


def test_split_context_without_the_section_returns_the_state_unchanged() -> None:
    text = build_state("refund_order", {}, {"conversation": "hi"}, [])
    assert split_context(text, "policy") == ("", text)
    assert split_context("not a state", "policy") == ("", "not a state")
