"""Unit tests for the policy oracle's building blocks (no τ² needed)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hatchway.bench.tau2.verdicts.base import Check, ProposalEvidence, ToolCallRef, Turn, combine
from hatchway.bench.tau2.verdicts.evidence import (
    ChainResult,
    affirmation,
    confirmation_chain,
    gb_amounts_in,
    money_in,
    order_ids_in,
    per_gb_rates_in,
    plan_confirmation,
)
from hatchway.bench.tau2.verdicts.registry import (
    ORACLE_VERSION,
    VALIDATORS,
    build_registry,
    evaluate,
    oracle_version,
)
from hatchway.bench.tau2.verdicts.retail import (
    RETAIL_POLICY_HASHES,
    ReturnDeliveredOrderItems,
    original_payment_method,
)
from hatchway.bench.tau2.verdicts.telecom import TELECOM_POLICY_HASHES


def chat(*messages: tuple[str, str]) -> tuple[Turn, ...]:
    return tuple(Turn(index=i, role=role, content=text) for i, (role, text) in enumerate(messages))


# --- affirmation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes. Do it now.", "yes"),
        ("Yes, that's correct. Please go ahead.", "yes"),
        ("I understand. Please go ahead and process it. I confirm.", "yes"),
        ("No, don't do that.", "no"),
        ("Wait, hold on.", "no"),
        ("Please do not proceed.", "no"),
        ("Sure, but also check my other order.", "unclear"),
        ("Yes? What does that cost?", "unclear"),
        ("I would like to add 2.0 GB of data to my line now, please.", "unclear"),
        ("I do not want to change my plan. I would like 2 GB.", "unclear"),
        ("Yes, actually, no.", "unclear"),
    ],
)
def test_affirmation(text: str, expected: str) -> None:
    assert affirmation(text) == expected


def test_value_readers() -> None:
    assert order_ids_in("Order #W5490111 and w7387996") == {"#W5490111", "#W7387996"}
    assert money_in("That is $4.00, or 4 dollars, not $1,023.16") == [4.0, 1023.16, 4.0]
    assert gb_amounts_in("refuel 2.0 GB or 2GB or 1 gigabyte") == [2.0, 2.0, 1.0]
    assert per_gb_rates_in("at a cost of $2.00 per GB, or $5/GB") == [2.0, 5.0]


# --- confirmation chain ------------------------------------------------------------------------


def mentions_w1(text: str) -> bool:
    return "#W1111111" in text


def other_order(text: str) -> bool:
    found = order_ids_in(text)
    return bool(found) and "#W1111111" not in found


def test_chain_skips_tool_call_only_turns() -> None:
    turns = (
        *chat(("assistant", "Return order #W1111111 to your card. Confirm?"), ("user", "Yes.")),
        Turn(index=2, role="assistant", tool_calls=(ToolCallRef("c1", "get_order_details", {}),)),
        Turn(index=3, role="tool", content="{}", tool_call_id="c1", requestor="assistant"),
    )
    result = confirmation_chain(turns, mentions_w1, other_order)
    assert result.status == "CONFIRMED"
    assert result.facts["presented_in_turn"] == 0 and result.facts["reply_turn"] == 1


def test_chain_customer_states_and_confirms() -> None:
    turns = chat(("user", "I confirm: return order #W1111111, please go ahead."))
    assert confirmation_chain(turns, mentions_w1).status == "CONFIRMED"


def test_chain_agent_restatement_without_reply_falls_back() -> None:
    turns = chat(
        ("assistant", "Return order #W1111111. Shall I?"),
        ("user", "Yes."),
        ("assistant", "Processing the return of #W1111111 now."),
    )
    assert confirmation_chain(turns, mentions_w1).status == "CONFIRMED"


def test_chain_absent_when_never_presented() -> None:
    turns = chat(("assistant", "I can help with returns."), ("user", "Great, thanks."))
    assert confirmation_chain(turns, mentions_w1).status == "ABSENT"


def test_chain_absent_when_agent_never_waits() -> None:
    turns = chat(("user", "Hi"), ("assistant", "Returning order #W1111111 now."))
    assert confirmation_chain(turns, mentions_w1).status == "ABSENT"


def test_chain_declined_and_unclear() -> None:
    declined = chat(("assistant", "Return order #W1111111?"), ("user", "No, stop."))
    unclear = chat(("assistant", "Return order #W1111111?"), ("user", "Sure, but which card?"))
    assert confirmation_chain(declined, mentions_w1).status == "NOT_AFFIRMED"
    assert confirmation_chain(unclear, mentions_w1).status == "UNCLEAR"


def test_chain_changed_after_confirmation() -> None:
    changed = chat(
        ("assistant", "Return order #W1111111?"),
        ("user", "Yes."),
        ("user", "Actually make it order #W2222222 please, go ahead."),
    )
    result = confirmation_chain(changed, mentions_w1, other_order)
    assert result.status == "CHANGED"
    assert result.facts["conflict_turn"] == 2


# --- plan confirmation -------------------------------------------------------------------------

PLAN = chat(
    ("assistant", "Order #W1111111 has a lamp and a mug."),
    ("user", "Which one is cheaper?"),
    ("assistant", "Return the lamp to your card?"),
    ("user", "Yes, return the lamp to my card."),
)
UNCLEAR_ORDER = ChainResult("UNCLEAR", {"presented_in_turn": 0, "reply_turn": 1})
CONFIRMED_AT_3 = ChainResult("CONFIRMED", {"presented_in_turn": 3, "reply_turn": 3})


def test_plan_yes_confirms_the_unclear_order() -> None:
    chains = {"order": UNCLEAR_ORDER, "items": CONFIRMED_AT_3, "payment_method": CONFIRMED_AT_3}
    out = plan_confirmation(PLAN, chains, {"order": other_order})
    assert out["order"].status == "CONFIRMED"
    assert out["order"].facts["confirmed_by_plan_reply"] == 3
    assert out["items"] == CONFIRMED_AT_3


@pytest.mark.parametrize(
    ("chains", "turns"),
    [
        # another order named between the presentation and the plan's yes
        (
            {"order": UNCLEAR_ORDER, "items": CONFIRMED_AT_3},
            (*PLAN[:2], replace(PLAN[2], content="Or order #W2222222? Return the lamp?"), PLAN[3]),
        ),
        # the plan's yes came before the unclear reply
        (
            {
                "order": ChainResult("UNCLEAR", {"presented_in_turn": 0, "reply_turn": 3}),
                "items": ChainResult("CONFIRMED", {"presented_in_turn": 0, "reply_turn": 1}),
            },
            PLAN,
        ),
        # unclear because of a conflict after a confirmation
        (
            {
                "order": ChainResult(
                    "UNCLEAR", {"presented_in_turn": 0, "reply_turn": 1, "conflict_turn": 2}
                ),
                "items": CONFIRMED_AT_3,
            },
            PLAN,
        ),
        # another value is not confirmed
        (
            {
                "order": UNCLEAR_ORDER,
                "items": CONFIRMED_AT_3,
                "payment_method": ChainResult("ABSENT"),
            },
            PLAN,
        ),
        # two unclear values
        ({"order": UNCLEAR_ORDER, "items": UNCLEAR_ORDER, "payment_method": CONFIRMED_AT_3}, PLAN),
        # nothing confirmed
        ({"order": UNCLEAR_ORDER}, PLAN),
    ],
)
def test_plan_confirmation_leaves_other_cases_alone(chains, turns) -> None:
    assert plan_confirmation(turns, chains, {"order": other_order}) == chains


# --- retail helpers ----------------------------------------------------------------------------


def test_original_payment_method_ignores_refunds() -> None:
    def order(*history: tuple[str, str]) -> dict:
        return {
            "payment_history": [
                {"transaction_type": kind, "payment_method_id": pm} for kind, pm in history
            ]
        }

    assert original_payment_method(order(("payment", "cc_1"))) == "cc_1"
    assert original_payment_method(order(("payment", "cc_1"), ("refund", "gift_1"))) == "cc_1"
    assert original_payment_method(order(("payment", "cc_1"), ("payment", "pp_1"))) is None
    assert original_payment_method(order()) is None


def retail_evidence(**changes) -> ProposalEvidence:
    """A minimal valid return: authenticated, delivered, confirmed, original card."""
    find = ToolCallRef("c1", "find_user_id_by_email", {"email": "a@b.c"})
    turns = (
        Turn(0, "assistant", tool_calls=(find,)),
        Turn(1, "tool", "u1", tool_call_id="c1", requestor="assistant"),
        Turn(
            2,
            "assistant",
            "Return the Lamp from order #W1111111 to your credit card ending in 1234. Confirm?",
        ),
        Turn(3, "user", "Yes, go ahead."),
    )
    db = {
        "users": {
            "u1": {
                "payment_methods": {
                    "cc_1": {"source": "credit_card", "id": "cc_1", "last_four": "1234"},
                    "gift_1": {"source": "gift_card", "id": "gift_1"},
                    "pp_1": {"source": "paypal", "id": "pp_1"},
                },
                "orders": ["#W1111111"],
            }
        },
        "orders": {
            "#W1111111": {
                "order_id": "#W1111111",
                "user_id": "u1",
                "status": "delivered",
                "items": [{"item_id": "i1", "name": "Lamp"}, {"item_id": "i2", "name": "Desk"}],
                "payment_history": [{"transaction_type": "payment", "payment_method_id": "cc_1"}],
            }
        },
    }
    base = ProposalEvidence(
        domain="retail",
        task_id="t",
        session_id="s",
        seq=0,
        action="return_delivered_order_items",
        args={"order_id": "#W1111111", "item_ids": ["i1"], "payment_method_id": "cc_1"},
        agent_db=db,
        user_db=None,
        turns=turns,
        domain_policy_hash=next(iter(RETAIL_POLICY_HASHES)),
    )
    return replace(base, **changes)


def test_retail_allow_and_each_violation() -> None:
    ev = retail_evidence()
    assert evaluate(ev).expected_decision == "ALLOW"

    def decide(**args) -> tuple[str, tuple[str, ...]]:
        v = evaluate(replace(ev, args={**ev.args, **args}))
        return v.expected_decision, v.reason_codes

    assert decide(payment_method_id="pp_1")[1] == ("CONFIRMATION_MISSING", "INVALID_REFUND_METHOD")
    assert decide(payment_method_id="pp_1")[0] == "DENY"
    assert decide(payment_method_id="gift_1") == ("ASK", ("CONFIRMATION_MISSING",))
    assert decide(item_ids=["i9"])[0] == "DENY"
    assert decide(order_id="#W9999999") == ("DENY", ("ORDER_NOT_FOUND",))


def test_retail_missing_confirmation_is_ask_and_missing_auth_is_ask() -> None:
    ev = retail_evidence()
    no_confirm = replace(ev, turns=ev.turns[:3])
    assert evaluate(no_confirm).reason_codes == ("CONFIRMATION_MISSING",)
    assert evaluate(no_confirm).expected_decision == "ASK"
    no_auth = replace(ev, turns=ev.turns[2:])
    assert evaluate(no_auth).reason_codes == ("NOT_AUTHENTICATED",)


def test_retail_not_delivered_is_deny() -> None:
    ev = retail_evidence()
    db = {
        **ev.agent_db,
        "orders": {"#W1111111": {**ev.agent_db["orders"]["#W1111111"], "status": "pending"}},
    }
    assert evaluate(replace(ev, agent_db=db)).reason_codes == ("ORDER_NOT_DELIVERED",)


# --- combine and versioning --------------------------------------------------------------------


def test_combine_precedence() -> None:
    def outcome(*kinds: str) -> str:
        checks = [Check(f"C{i}", k) for i, k in enumerate(kinds)]  # type: ignore[arg-type]
        return combine(checks, "v").expected_decision

    assert outcome("pass", "pass") == "ALLOW"
    assert outcome("pass", "unknown") == "UNKNOWN"
    assert outcome("unknown", "ask") == "ASK"
    assert outcome("unknown", "ask", "deny") == "DENY"


def test_verdict_is_deterministic_and_sorted() -> None:
    ev = retail_evidence(
        args={"order_id": "#W1111111", "item_ids": ["i1"], "payment_method_id": "pp_1"}
    )
    a, b = evaluate(ev), evaluate(ev)
    assert a.to_json() == b.to_json()
    assert list(a.reason_codes) == sorted(a.reason_codes)
    assert a.oracle_version == ORACLE_VERSION


def test_oracle_version_tracks_validator_and_policy_versions() -> None:
    class Bumped(ReturnDeliveredOrderItems):
        version = "bumped"

    class OtherPolicy(ReturnDeliveredOrderItems):
        supported_policy_hashes = frozenset({"f" * 64})

    others = [v for k, v in VALIDATORS.items() if k != ("retail", "return_delivered_order_items")]
    assert oracle_version(VALIDATORS) == ORACLE_VERSION
    assert oracle_version(build_registry([Bumped(), *others])) != ORACLE_VERSION
    assert oracle_version(build_registry([OtherPolicy(), *others])) != ORACLE_VERSION
    with pytest.raises(ValueError, match="two validators"):
        build_registry([Bumped(), ReturnDeliveredOrderItems()])


def test_registered_validators() -> None:
    assert set(VALIDATORS) == {
        ("retail", "return_delivered_order_items"),
        ("retail", "exchange_delivered_order_items"),
        ("retail", "modify_pending_order_items"),
        ("retail", "cancel_pending_order"),
        ("retail", "modify_user_address"),
        ("telecom", "enable_roaming"),
        ("telecom", "refuel_data"),
        ("telecom", "send_payment_request"),
        ("telecom", "resume_line"),
        ("telecom", "disable_roaming"),
    }
    for (domain, _), v in VALIDATORS.items():
        hashes = RETAIL_POLICY_HASHES if domain == "retail" else TELECOM_POLICY_HASHES
        assert v.supported_policy_hashes == hashes
