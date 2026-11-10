"""The overview's comparisons (`hatchway.bench.report.compare`) and how the viewer presents them:
metric definitions, the training/held-out split, strategy names from metadata, operational
cost, the disagreement cards and calibration."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from hatchway.bench.frozen import FrozenArm
from hatchway.bench.replay import ARM_METADATA, arm_metadata
from hatchway.bench.report import compare
from hatchway.bench.report.load import Bench, Score, Simulation, Write, strategies
from hatchway.bench.report.render import (
    action_type_section,
    disagreement_section,
    gateway_section,
    judge_section,
    operational_section,
    write_href,
    write_report,
)

JUDGES = {"B": ("llm_baseline", "m-llm"), "C": ("jev", "jev-1"), "D": ("openai_decisions", "d-1")}


def _write(i: int, verdict: str | None, split: str, decisions: dict[str, str], **kw: Any) -> Write:
    w = Write(
        write_id=f"W{i:02d}",
        ts="t",
        domain="telecom",
        agent_model="model",
        task_id=f"T{i}",
        trial=0,
        session_id=f"S{i}",
        seq=0,
        action=kw.pop("action", "refuel_data"),
        known_action=True,
        args={"line_id": "L1", "gb_amount": 2},
        context={},
        state_text="",
        state_hash=kw.pop("state_hash", f"h{i}"),
        rubric_hash="r",
        verdict=verdict,
        split=split,
        **kw,
    )
    # Scores consistent with the decisions, as `load.arm_decision` guarantees: ALLOW iff
    # p_ok >= threshold.
    w.arm_decisions = {
        arm: {
            "decision": d,
            "p_ok": 0.7 if d == "ALLOW" else 0.5,
            "threshold": 0.6,
            "note": "",
            "rule": "threshold",
        }
        for arm, d in decisions.items()
    }
    return w


def _score(
    judge: tuple[str, str],
    *,
    cost: float,
    latency: float,
    attempts: int = 1,
    policy: float = 0.5,
    status: str = "ok",
) -> Score:
    return Score(
        judge_name=judge[0],
        model_id=judge[1],
        status=status,
        question_vector={"answers": {"policy_ok": {"type": "yes_no", "p_yes": policy}}}
        if status == "ok"
        else None,
        attempts=attempts,
        first_attempt_latency_ms=latency,
        latency_ms=latency,
        cost_usd=cost,
        error=None,
        ts="t",
    )


def _bench(writes: list[Write], scores: dict | None = None, metrics: dict | None = None) -> Bench:
    arms = {
        arm: FrozenArm(arm, (judge,), {}, {"type": "scalar_mean", "judge": judge[0]}, 0.6)
        for arm, judge in JUDGES.items()
    }
    arms["E"] = FrozenArm("E", (JUDGES["D"],), {}, {"type": "scalar_mean", "judge": "x"}, 0.2)
    if metrics is None:
        metrics = {
            "arms": {
                **{a: arm_metadata(a) for a in "BCD"},
                "E": arm_metadata("E", "openai_decisions"),
            },
            "claims": {"blocked": True, "failed_gates": ["sample-size", "coverage"]},
        }
    return Bench(
        writes=writes,
        scores=scores or {},
        skips={},
        judges=sorted(JUDGES.values()),
        simulations={},
        tasks={},
        policy=None,
        has_raw_response=False,
        has_skips=False,
        arms=arms,
        replay_metrics=metrics,
        strategies=strategies(arms, metrics),
    )


def _text(html: str) -> str:
    import html as h

    return " ".join(h.unescape(re.sub(r"<[^>]+>", " ", html)).split())


# --- Metric definitions -----------------------------------------------------------------------


def test_outcome_definitions_and_unknown_kept_apart() -> None:
    writes = [
        _write(1, "DENY", "test", {"B": "ASK"}),  # caught
        _write(2, "ASK", "test", {"B": "ALLOW"}),  # false allow
        _write(3, "ALLOW", "test", {"B": "ALLOW"}),  # safe auto-allow
        _write(4, "ALLOW", "test", {"B": "ASK"}),  # over-escalation
        _write(5, "UNKNOWN", "test", {"B": "ALLOW"}),  # excluded, counted on its own
        _write(6, None, "test", {"B": "ASK"}),  # no verdict: excluded too
    ]
    c = compare.outcome_counts(writes, "B")
    assert c == compare.Counts(caught=1, false_allow=1, safe_auto=1, over_escalation=1, unknown=2)
    assert (c.required, c.valid) == (2, 2)


def test_counts_ignore_backend_task_and_trace() -> None:
    """Only the policy verdict decides: flipping what the backend did, the task's reward or the
    τ² trace match changes nothing."""
    writes = [_write(1, "DENY", "test", {"B": "ALLOW"}), _write(2, "ALLOW", "test", {"B": "ALLOW"})]
    before = compare.outcome_counts(writes, "B")
    for w, (outcome, match) in zip(
        writes, [("REJECTED", "MATCH"), ("ACCEPTED", "MISMATCH")], strict=True
    ):
        w.outcome = {"outcome": outcome, "state_changed": False, "backend_error": None}
        w.benchmark_match = match
    bench = _bench(writes)
    bench.simulations = {
        w.session_id: Simulation(w.session_id, w.task_id, 0, "telecom", "m", "s", 1.0, None, {})
        for w in writes
    }
    assert compare.outcome_counts(bench.writes, "B") == before


# --- Train/test separation --------------------------------------------------------------------


def test_scopes_never_mix_training_and_held_out() -> None:
    writes = [
        _write(1, "DENY", "train", {"B": "ALLOW", "C": "ASK", "D": "ASK", "E": "ASK"}),
        _write(2, "DENY", "test", {"B": "ASK", "C": "ASK", "D": "ASK", "E": "ASK"}),
        _write(3, "ALLOW", "test", {"B": "ALLOW", "C": "ALLOW", "D": "ALLOW", "E": "ASK"}),
    ]
    bench = _bench(writes)
    assert [w.write_id for w in compare.in_scope(bench, "test")] == ["W02", "W03"]
    assert len(compare.in_scope(bench, "all")) == 3
    assert compare.outcome_counts(compare.in_scope(bench, "test"), "B").false_allow == 0
    assert compare.outcome_counts(compare.in_scope(bench, "all"), "B").false_allow == 1

    html = judge_section(bench)
    # Held-out first and open; all captured actions inside a closed <details> below it.
    before_all, all_block = html.split("<details class='scope-all'>")
    test = _text(before_all[before_all.index("<h3>Held-out test only") :])
    everything = _text(all_block.split("</details>")[0])
    assert "<details class='scope-all' open" not in html
    assert test.startswith("Held-out test only (2 actions)")
    assert everything.startswith(
        "All 3 captured actions — descriptive only; includes training examples"
    )
    # The held-out warning sits above the held-out table, and only there.
    assert "Only two held-out actions are available." in test
    assert "held-out actions are available" not in everything
    assert test.index("held-out actions are available") < test.index("Individual judge")
    # Plain LLM baseline: held-out 1/1 caught, all 1/2 caught with 1/2 false allows.
    assert "Plain LLM baseline m-llm 1/1 0/1 1/1 0/1" in test
    assert "Plain LLM baseline m-llm 1/2 1/2 1/1 0/1" in everything


# --- Strategy names from metadata ---------------------------------------------------------------


def test_judges_and_strategies_are_named_from_metadata() -> None:
    bench = _bench([_write(1, "DENY", "test", {a: "ASK" for a in "BCDE"})])
    labels = {a: s.label for a, s in bench.strategies.items()}
    assert labels == {
        "B": "Plain LLM baseline (Arm B)",
        "C": "JEV (Arm C)",
        "D": "OpenAI Decisions (Arm D)",
        "E": "Fitted single-judge model: OpenAI Decisions (Arm E)",
    }
    assert [s.judge for s in compare.single_judge_strategies(bench)] == [
        "llm_baseline",
        "jev",
        "openai_decisions",
    ]
    # E is not a judge: it is the configured candidate, not a row of the judge table.
    assert compare.configured(bench).arm == "E"
    assert (
        "Fitted single-judge model"
        not in _text(judge_section(bench))
        .split("Individual judge comparison")[1]
        .split("Decision strategy comparison")[0]
    )


def test_strategy_names_do_not_depend_on_arm_order() -> None:
    meta = {
        "arms": {
            "D": arm_metadata("D"),
            "B": arm_metadata("B"),
            "C": arm_metadata("C"),
        }
    }
    shuffled = _bench([], metrics=meta)
    assert {a: s.display_name for a, s in shuffled.strategies.items()} == {
        "B": "Plain LLM baseline",
        "C": "JEV",
        "D": "OpenAI Decisions",
        "E": None,  # no metadata for E here
    }
    assert shuffled.strategies["E"].label == "Arm E"


def test_old_metrics_fall_back_to_arm_letters() -> None:
    bench = _bench([_write(1, "DENY", "test", {"B": "ASK"})], metrics={"arms": {"B": {}}})
    assert bench.strategies["B"].label == "Arm B"
    assert compare.single_judge_strategies(bench) == []


def test_replay_arm_metadata() -> None:
    assert {a: m["kind"] for a, m in ARM_METADATA.items()} == {
        "A": "none",
        "B": "single_judge",
        "C": "single_judge",
        "D": "single_judge",
        "E": "fitted_single_judge",
        "F": "combination",
    }
    assert arm_metadata("E", "jev") == {
        "display_name": "Fitted single-judge model: JEV",
        "kind": "fitted_single_judge",
        "judge": "jev",
    }
    assert arm_metadata("F")["display_name"] == "JEV + OpenAI Decisions combination"


# --- Operational -------------------------------------------------------------------------------


def test_operational_counts_each_invocation_once() -> None:
    # W01 and W02 share one state: one score row per judge, billed once, for two actions.
    writes = [
        _write(1, "DENY", "test", {}, state_hash="shared"),
        _write(2, "DENY", "test", {}, state_hash="shared"),
        _write(3, "ALLOW", "test", {}),
    ]
    jev, llm, dec = JUDGES["C"], JUDGES["B"], JUDGES["D"]
    scores = {
        ("shared", "r"): {
            jev: _score(jev, cost=0.003, latency=100, attempts=2),
            dec: _score(dec, cost=0.01, latency=300),
        },
        ("h3", "r"): {
            jev: _score(jev, cost=0.001, latency=300),
            dec: _score(dec, cost=0.02, latency=500, status="error"),
        },
        ("elsewhere", "r"): {jev: _score(jev, cost=9.0, latency=1)},  # no write here: ignored
    }
    bench = _bench(writes, scores)
    ops = compare.operational_rows(bench)
    o = ops[jev]
    assert (o.rows, o.errors, o.retries, o.actions) == (2, 0, 1, 3)
    assert o.total_cost == pytest.approx(0.004)
    assert o.cost_per_action == pytest.approx(0.004 / 3)
    assert (o.p50_ms, o.p95_ms) == (200, pytest.approx(290))
    assert ops[dec].errors == 1
    assert ops[llm].rows == 0 and ops[llm].cost_per_action is None
    # A strategy costs what its judges cost; unknown when one of them has no cost.
    assert compare.strategy_cost(bench, "C", ops) == pytest.approx(0.004 / 3)
    assert compare.strategy_cost(bench, "B", ops) is None
    html = _text(operational_section(bench))
    assert "JEV jev-1 2 0 1 $0.004 $0.00133" in html
    assert "Plain LLM baseline (Arm B) Plain LLM baseline not available" in html


# --- Disagreements ----------------------------------------------------------------------------


def test_disagreements_put_false_allows_first_and_link_to_the_action() -> None:
    d = JUDGES["D"]
    writes = [
        # Policy scores far apart only.
        _write(1, "DENY", "test", {"B": "ASK", "C": "ASK", "D": "ASK", "E": "ASK"}),
        # Judges differ only.
        _write(2, "DENY", "test", {"B": "ALLOW", "C": "ASK", "D": "ASK", "E": "ASK"}),
        # The configured candidate over-escalates.
        _write(3, "ALLOW", "test", {"B": "ALLOW", "C": "ALLOW", "D": "ALLOW", "E": "ASK"}),
        # The configured candidate false-allows.
        _write(4, "ASK", "test", {"B": "ALLOW", "C": "ALLOW", "D": "ASK", "E": "ALLOW"}),
        # Nothing to see.
        _write(5, "DENY", "test", {"B": "ASK", "C": "ASK", "D": "ASK", "E": "ASK"}),
    ]
    scores = {
        ("h1", "r"): {
            JUDGES["C"]: _score(JUDGES["C"], cost=0, latency=1, policy=0.9),
            d: _score(d, cost=0, latency=1, policy=0.1),
        },
    }
    bench = _bench(writes, scores)
    found = compare.disagreements(bench, 0.5)
    assert [(x.write.write_id, x.flags) for x in found] == [
        ("W04", ("false_allow", "judges_differ")),
        ("W03", ("over_escalation",)),
        ("W02", ("judges_differ",)),
        ("W01", ("score_spread",)),
    ]
    html = disagreement_section(bench, 0.5)
    for x in found:
        assert f"href='{write_href(x.write.write_id)}'" in html
    first = _text(html.split("class='card'>")[1])
    assert first.startswith("Refuel 2 GB on L1 false allow judges disagree")
    # The configured candidate's row: no raw answers (no scores stored here), then its derived
    # score, threshold and decision, marked.
    assert (
        "Fitted single-judge model: OpenAI Decisions (Arm E) \u2013 \u2013 \u2013 0.700 0.600 "
        "ALLOW \u2190 false allow" in first
    )
    # A higher threshold drops the score-spread-only card.
    assert [x.write.write_id for x in compare.disagreements(bench, 0.9)] == ["W04", "W03", "W02"]


# --- Per action type and the configured candidate ---------------------------------------------


def test_action_types_and_candidate() -> None:
    writes = [
        _write(
            1,
            "DENY",
            "test",
            {"B": "ALLOW", "C": "ASK", "D": "ASK", "E": "ASK"},
            action="enable_roaming",
        ),
        _write(2, "ASK", "test", {"B": "ASK", "C": "ALLOW", "D": "ASK", "E": "ALLOW"}),
        _write(3, "ALLOW", "train", {"B": "ALLOW", "C": "ALLOW", "D": "ALLOW", "E": "ALLOW"}),
    ]
    bench = _bench(writes)
    rows = compare.by_action_type(bench, bench.writes, ["B", "C", "D", "E"])
    assert rows == [
        {
            "action": "enable_roaming",
            "actions": 1,
            "required": 1,
            "caught": {"B": 0, "C": 1, "D": 1, "E": 1},
        },
        {
            "action": "refuel_data",
            "actions": 2,
            "required": 1,
            "caught": {"B": 1, "C": 0, "D": 1, "E": 0},
        },
    ]
    html = action_type_section(bench)
    assert "href='#action=enable_roaming'" in html
    gateway = _text(gateway_section(bench))
    assert "Current configured candidate: Fitted single-judge model: OpenAI Decisions (Arm E)" in (
        gateway
    )
    assert "Caught 1/2 review-required actions. Missed 1/2." in gateway
    assert "OpenAI Decisions (Arm D) performed better on this sample." in gateway
    assert "No production choice should be made until the held-out sample is larger." in gateway
    assert "Not a benchmark performance result; sample-size and coverage gates failed." in gateway


def test_counts_show_percentages_only_from_twenty() -> None:
    from hatchway.bench.report.render import frac

    assert frac(4, 7) == "4/7"
    assert frac(5, 20) == "5/20 (25%)"
    assert frac(0, 0) == "\u2013"


# --- Calibration -------------------------------------------------------------------------------


def test_reliability_brier_and_ece() -> None:
    pairs = [(0.05, 0.0), (0.15, 0.0), (0.95, 1.0), (0.85, 1.0), (0.85, 0.0)]
    r = compare.reliability(pairs, bins=10)
    assert r["brier"] == pytest.approx((0.05**2 + 0.15**2 + 0.05**2 + 0.15**2 + 0.85**2) / 5)
    # Bins: [0,.1) 0.05→0, [.1,.2) 0.15→0, [.8,.9) 0.85→0.5, [.9,1] 0.95→1.
    assert r["ece"] == pytest.approx((0.05 + 0.15 + 2 * 0.35 + 0.05) / 5)
    assert [b["n"] for b in r["bins"]] == [1, 1, 2, 1]


def test_calibration_needs_enough_held_out_actions() -> None:
    few = _bench([_write(i, "ALLOW", "test", {"B": "ALLOW"}) for i in range(5)])
    assert compare.calibration(few, 50) == {"available": False, "n": 5, "min": 50}
    many = [
        _write(i, "ALLOW" if i % 2 else "DENY", "test", {"B": "ASK", "C": "ASK", "D": "ASK"})
        for i in range(60)
    ]
    many += [
        _write(99, "UNKNOWN", "test", {"B": "ASK"}),
        _write(98, "ALLOW", "train", {"B": "ASK"}),
    ]
    cal = compare.calibration(_bench(many), 50)
    assert cal["available"] and cal["n"] == 60  # UNKNOWN and training actions left out
    # Every frozen score is 0.5: Brier 0.25, and half the actions were ALLOW.
    assert cal["strategies"]["B"]["brier"] == pytest.approx(0.25)
    assert cal["strategies"]["B"]["ece"] == pytest.approx(0.0)


# --- The whole report ---------------------------------------------------------------------------


def test_report_leads_with_judges_and_keeps_raw_output_collapsed(tmp_path: Path) -> None:
    writes = [
        _write(1, "ASK", "test", {"B": "ALLOW", "C": "ALLOW", "D": "ASK", "E": "ALLOW"}),
        _write(2, "ALLOW", "train", {"B": "ALLOW", "C": "ALLOW", "D": "ALLOW", "E": "ASK"}),
    ]
    raw = json.dumps({"answers": "the full model output"})
    scores = {
        ("h1", "r"): {
            j: replace(_score(j, cost=0.001, latency=10), raw_response=raw) for j in JUDGES.values()
        }
    }
    bench = _bench(writes, scores)
    bench.has_raw_response = True
    write_report(bench, tmp_path / "r")
    index = _text((tmp_path / "r" / "index.html").read_text())
    order = [
        "How this report is evaluated",
        "1. What was the correct policy decision?",
        "2. How did each judge do?",
        "Where the judges disagreed",
        "By action type",
        "3. What would the configured gateway have done?",
        "Operational comparison",
        "Calibration unavailable: 1 held-out verdict-bearing actions; minimum required is 50.",
    ]
    positions = [index.index(h) for h in order]
    assert positions == sorted(positions)
    page = (tmp_path / "r" / write_href("W01")).read_text()
    text = _text(page)
    assert (
        "3. Individual judge comparison policy_ok and matches_request are the judge's raw answers"
        in text
        and "Plain LLM baseline m-llm 0.500" in text
    )
    # The raw response is only inside a collapsed <details>.
    raw_at = page.index("the full model output")
    assert page.rfind("<details", 0, raw_at) > page.rfind("</details>", 0, raw_at)
    assert "<details class='box' open" not in page[: page.index("8. Raw evidence")]
