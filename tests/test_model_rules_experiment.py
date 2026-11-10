"""The model-drafted rules experiment: the brief is blind, the runner survives bad drafts,
and the scoring is right on toy data."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).parents[1] / "experiments/2026-11-05-model-drafted-rules"
sys.path.insert(0, str(Path(__file__).parents[1] / "experiments/2026-10-28-airline-veto"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


brief = load("brief")
run_drafts = load("run_drafts")
evaluate = load("evaluate")


def test_brief_is_blind():
    text = brief.INSTRUCTIONS + brief.brief()
    assert "# Airline Agent Policy" in text
    for leak in (
        "FLOWN_CANCEL",
        "CANCEL_ELIGIBLE",
        "BASIC_NO_FLIGHT_CHANGE",
        "DUPLICATE_SEAT",
        "COMP_CAUSE",
        "01M6",
        "task_id",
        "benchmark",
    ):
        assert leak not in text


def test_extract_code():
    assert brief.extract_code("x\n```python\ndef check(ctx):\n    return []\n```\ny") == (
        "def check(ctx):\n    return []\n"
    )
    assert brief.extract_code("def check(ctx): return []") == "def check(ctx): return []\n"
    # a reply cut by its output limit: the fence is never closed
    assert brief.extract_code("```python\ndef check(ctx):\n    return [") == (
        "def check(ctx):\n    return [\n"
    )


def test_apply_records_errors_as_no_block():
    class Ctx:
        def __init__(self, action, args, db, messages):
            self.action, self.args = action, args

    def check(ctx):
        if ctx.action == "boom":
            raise KeyError("x")
        return [("R", "why")] if ctx.action == "cancel" else None

    writes = [("w1", "cancel", {}, [], {}), ("w2", "boom", {}, [], {}), ("w3", "ok", {}, [], {})]
    rows = run_drafts.apply(check, writes, Ctx)
    assert [r["blocks"] for r in rows] == [[{"rule": "R", "reason": "why"}], [], []]
    assert rows[1]["error"].startswith("KeyError") and rows[0]["error"] is None


def test_score_and_agreement():
    blocks = {"a": True, "b": False, "c": False, "d": True}
    truth = {"a": True, "b": True, "c": False, "d": False}  # a,b should run
    m = evaluate.score(blocks, truth)
    assert (m["ran"], m["wrong"], m["good_sent_back"], m["good_total"]) == (2, 1, 1, 2)
    assert m["false_block_ids"] == ["a"] and m["wrong_write_ids"] == ["c"]
    other = {"a": True, "b": True, "c": False, "d": False}
    assert evaluate.agreement(blocks, other, "abcd") == {
        "both_block": 1,
        "b_only": 1,
        "both_allow": 1,
        "a_only": 1,
    }
