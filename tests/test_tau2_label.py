from collections import Counter
from pathlib import Path

import pytest

from hatchway.bench import BenchStore
from hatchway.bench.tau2.label import GoldAction, GroundTruth, match_session, match_store

EXCHANGE = {
    "order_id": "#W1",
    "item_ids": ["a", "b"],
    "new_item_ids": ["x", "y"],
    "payment_method_id": "card_1",
}
RETAIL = GroundTruth(
    actions=(
        GoldAction("get_order_details", {"order_id": "#W1"}),
        GoldAction("exchange_delivered_order_items", EXCHANGE),
    ),
    db_scored=True,
)


def test_exact_match_is_correct_and_repeat_is_ambiguous() -> None:
    writes = [("exchange_delivered_order_items", EXCHANGE)] * 2
    assert match_session(writes, RETAIL) == ["MATCH", "AMBIGUOUS"]


def test_ground_truth_needing_a_call_twice_matches_it_twice() -> None:
    call = {"order_id": "#W1", "reason": "no longer needed"}
    truth = GroundTruth((GoldAction("cancel_pending_order", call),) * 2, db_scored=True)
    writes = [("cancel_pending_order", call)] * 3
    assert match_session(writes, truth) == ["MATCH", "MATCH", "AMBIGUOUS"]


@pytest.mark.parametrize(
    "args",
    [
        {**EXCHANGE, "payment_method_id": "gift_card_2"},  # wrong argument
        {k: v for k, v in EXCHANGE.items() if k != "payment_method_id"},  # missing argument
        {**EXCHANGE, "note": "extra"},  # extra argument
        {**EXCHANGE, "item_ids": ["a"], "new_item_ids": ["x"]},  # one item left out
    ],
)
def test_ground_truth_tool_with_other_arguments_is_incorrect(args: dict) -> None:
    assert match_session([("exchange_delivered_order_items", args)], RETAIL) == ["MISMATCH"]


def test_list_order_only_difference_is_ambiguous() -> None:
    reordered = {**EXCHANGE, "item_ids": ["b", "a"]}
    assert match_session([("exchange_delivered_order_items", reordered)], RETAIL) == ["AMBIGUOUS"]


def test_numbers_compare_by_value() -> None:
    truth = GroundTruth((GoldAction("refuel_data", {"line_id": "L1", "gb_amount": 2.0}),), False)
    assert match_session([("refuel_data", {"line_id": "L1", "gb_amount": 2})], truth) == ["MATCH"]


def test_compare_args_limit_the_comparison() -> None:
    truth = GroundTruth(
        (GoldAction("transfer_to_human_agents", {"summary": "gold text"}, compare_args=()),),
        db_scored=False,
    )
    assert match_session([("transfer_to_human_agents", {"summary": "other"})], truth) == ["MATCH"]

    truth = GroundTruth(
        (GoldAction("cancel_pending_order", {"order_id": "#W1", "reason": "x"}, ("order_id",)),),
        db_scored=True,
    )
    writes = [("cancel_pending_order", {"order_id": "#W1", "reason": "y"})]
    assert match_session(writes, truth) == ["MATCH"]


def test_other_write_in_db_scored_task_is_incorrect() -> None:
    writes = [("cancel_pending_order", {"order_id": "#W1", "reason": "ordered by mistake"})]
    assert match_session(writes, RETAIL) == ["MISMATCH"]
    refuse = GroundTruth((GoldAction("get_order_details", {"order_id": "#W1"}),), db_scored=True)
    assert match_session(writes, refuse) == ["MISMATCH"]


def test_assertion_scored_task_tolerates_extra_tools_but_not_wrong_arguments() -> None:
    truth = GroundTruth((GoldAction("refuel_data", {"line_id": "L1", "gb_amount": 2}),), False)
    writes = [
        ("enable_roaming", {"line_id": "L1"}),
        ("refuel_data", {"line_id": "L2", "gb_amount": 2}),
        ("refuel_data", {"line_id": "L1", "gb_amount": 2}),
    ]
    assert match_session(writes, truth) == ["AMBIGUOUS", "MISMATCH", "MATCH"]


class _Action:
    def __init__(self, name: str, requestor: str = "assistant", compare_args=None) -> None:
        self.name, self.requestor, self.compare_args = name, requestor, compare_args
        self.arguments = {"line_id": "L1"}


class _Criteria:
    def __init__(self, actions: list, reward_basis: list) -> None:
        self.actions, self.reward_basis = actions, reward_basis


class _Task:
    def __init__(self, criteria: _Criteria | None) -> None:
        self.evaluation_criteria = criteria


def test_ground_truth_from_task_drops_user_actions() -> None:
    task = _Task(
        _Criteria(
            [_Action("toggle_data", requestor="user"), _Action("refuel_data", compare_args=[])],
            ["ENV_ASSERTION"],
        )
    )
    truth = GroundTruth.from_task(task)
    assert truth == GroundTruth((GoldAction("refuel_data", {"line_id": "L1"}, ()),), False)
    assert GroundTruth.from_task(_Task(_Criteria([], ["DB", "COMMUNICATE"]))).db_scored
    assert GroundTruth.from_task(_Task(None)) == GroundTruth((), False)


def _record(store: BenchStore, session: str, task: str, action: str, args: dict) -> None:
    store.record_write(
        session_id=session,
        action=action,
        args=args,
        context={},
        rubric_hash=None,
        domain="retail",
        task_id=task,
    )


def test_match_store_matches_every_write_once(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "bench.db") as store:
        _record(store, "s1", "t1", "exchange_delivered_order_items", EXCHANGE)
        _record(store, "s1", "t1", "exchange_delivered_order_items", EXCHANGE)
        _record(store, "s2", "t1", "modify_user_address", {"user_id": "u"})
        truths = {("retail", "t1"): RETAIL}

        counts = match_store(store, truths)
        assert counts == Counter({"MATCH": 1, "AMBIGUOUS": 1, "MISMATCH": 1})
        matches = store.benchmark_matches()
        assert [matches[w.write_id] for w in store.writes()] == ["MATCH", "AMBIGUOUS", "MISMATCH"]

        # New writes in a matched session are matched in context; matched rows are left alone.
        _record(store, "s1", "t1", "exchange_delivered_order_items", EXCHANGE)
        assert match_store(store, truths) == Counter({"AMBIGUOUS": 1})
        assert match_store(store, truths) == Counter()


def test_match_store_refuses_writes_without_ground_truth(tmp_path: Path) -> None:
    with BenchStore(tmp_path / "bench.db") as store:
        _record(store, "s1", "t1", "exchange_delivered_order_items", EXCHANGE)
        _record(store, "s2", "t2", "exchange_delivered_order_items", EXCHANGE)
        with pytest.raises(KeyError, match="t2"):
            match_store(store, {("retail", "t1"): RETAIL})
        assert store.benchmark_matches() == {}
