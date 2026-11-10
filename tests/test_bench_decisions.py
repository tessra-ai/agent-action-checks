"""Every decision the viewer shows can be reproduced from what it shows: the derived gateway
score, the threshold, and any override that applied (fail closed, a disagreement veto).
Predicates explain a score and never veto it. Rounding never hides which side of the threshold
a score is on."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Any

from hatchway.bench.frozen import FrozenArm
from hatchway.bench.replay import arm_metadata
from hatchway.bench.report import compare
from hatchway.bench.report.load import Bench, Score, Write, arm_decision, strategies
from hatchway.bench.report.render import (
    calc_facts,
    decision_calc,
    executive_cards,
    gateway_section,
    write_href,
    write_report,
)

LLM, JEV, DEC = ("llm_baseline", "m-llm"), ("jev", "jev-1"), ("openai_decisions", "d-1")
B_THRESHOLD = 0.9998923226206666  # the smoke run's Plain LLM threshold


def _vector(judge: tuple[str, str], **p_yes: float) -> dict[str, Any]:
    return {
        "judge": judge[0],
        "model_id": judge[1],
        "answers": {q: {"type": "yes_no", "p_yes": p} for q, p in p_yes.items()},
    }


def _score(judge: tuple[str, str], **p_yes: float) -> Score:
    return Score(
        judge_name=judge[0],
        model_id=judge[1],
        status="ok",
        question_vector=_vector(judge, **p_yes),
        attempts=1,
        first_attempt_latency_ms=10.0,
        latency_ms=10.0,
        cost_usd=0.001,
        error=None,
        ts="t",
    )


def _write(i: int, verdict: str | None, split: str = "test") -> Write:
    return Write(
        write_id=f"W{i:02d}",
        ts="t",
        domain="telecom",
        agent_model="model",
        task_id=f"T{i}",
        trial=0,
        session_id=f"S{i}",
        seq=0,
        action="refuel_data",
        known_action=True,
        args={"line_id": "L1", "gb_amount": 2},
        context={},
        state_text="",
        state_hash=f"h{i}",
        rubric_hash="r",
        verdict=verdict,
        split=split,
    )


def _two_judge(p_jev: float, p_dec: float, combined: float, limit: float | None) -> FrozenArm:
    """A two-judge arm from constant calibrators: each judge's calibrated score, the combined
    score and the disagreement limit are fixed, so the veto is easy to provoke."""
    model = {
        "type": "two_judge",
        "judge_order": ["jev", "openai_decisions"],
        "judges": {
            "jev": {
                "type": "calibrated",
                "judge": "jev",
                "models": {"*": {"kind": "constant", "p": p_jev}},
            },
            "openai_decisions": {
                "type": "calibrated",
                "judge": "openai_decisions",
                "models": {"*": {"kind": "constant", "p": p_dec}},
            },
        },
        "combiner": {"kind": "constant", "p": combined},
        "disagreement_max": limit,
    }
    return FrozenArm("F", (JEV, DEC), {}, model, 0.6)


def _scalar(arm: str, judge: tuple[str, str], threshold: float) -> FrozenArm:
    return FrozenArm(arm, (judge,), {}, {"type": "scalar_mean", "judge": judge[0]}, threshold)


def _bench(cases: list[tuple[Write, dict]], arms: dict[str, FrozenArm]) -> Bench:
    metrics = {
        "arms": {a: arm_metadata(a) for a in arms if a in "BCDF"},
        "claims": {"blocked": True, "failed_gates": ["sample-size"]},
    }
    bench = Bench(
        writes=[w for w, _ in cases],
        scores={(w.state_hash, "r"): scores for w, scores in cases},
        skips={},
        judges=[LLM, JEV, DEC],
        simulations={},
        tasks={},
        policy=None,
        has_raw_response=False,
        has_skips=False,
        arms=arms,
        replay_metrics=metrics,
        strategies=strategies(arms, metrics),
    )
    for w in bench.writes:
        w.arm_decisions = {name: arm_decision(a, bench, w) for name, a in arms.items()}
    return bench


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def shown_decisions(page: str) -> list[tuple[dict[str, str], str]]:
    """Every decision display on a page: its `data-` facts and its visible text."""
    found = []
    for m in re.finditer(r"<(span|tr) class='calc' ([^>]*)>(.*?)</\1>", page, re.S):
        facts = {k: html.unescape(v) for k, v in re.findall(r"data-(\w+)='([^']*)'", m.group(2))}
        found.append((facts, _text(m.group(3))))
    return found


# --- Rounding ---------------------------------------------------------------------------------


def test_rounding_never_hides_the_side_of_the_threshold() -> None:
    # The smoke run's B1002 row: 1.000 / 1.000 at three decimals, but the score is below.
    s, op, t = compare.score_pair(0.9997846461524232, B_THRESHOLD)
    assert (s, op, t) == ("0.9998", "<", "0.9999")
    assert float(s) < float(t)
    # Three decimals when they already tell the two apart.
    assert compare.score_pair(0.655, 0.61) == ("0.655", "≥", "0.610")
    # Equal values print equal, and equal is an ALLOW.
    assert compare.score_pair(0.5, 0.5) == ("0.500", "≥", "0.500")
    # Just above the threshold: still shown above it.
    s, op, t = compare.score_pair(0.80000004, 0.8)
    assert op == "≥" and float(s) >= float(t)
    s, op, t = compare.score_pair(0.79999996, 0.8)
    assert op == "<" and float(s) < float(t)


def test_raw_answers_average_to_the_shown_side() -> None:
    # Plain LLM on B1002: policy_ok 0.99999986, matches_request 0.99956944; mean 0.99978.
    digits = compare.mean_digits(
        [0.9999998554928706, 0.9995694368119759], 0.9997846461524232, B_THRESHOLD
    )
    shown = [float(f"{v:.{digits}f}") for v in (0.9999998554928706, 0.9995694368119759)]
    _, _, t = compare.score_pair(0.9997846461524232, B_THRESHOLD, digits)
    assert sum(shown) / 2 < float(t)  # ASK, as the exact values say
    assert compare.mean_digits([0.47, 0.84], 0.655, 0.61) == 3


def test_an_unfittable_threshold_reads_as_such() -> None:
    d = {"decision": "ASK", "p_ok": 0.99, "threshold": math.inf, "rule": "threshold"}
    facts = calc_facts(d)
    assert facts["rule"] == "no_threshold" and compare.recompute(facts) == "ASK"


# --- Overrides and predicates -----------------------------------------------------------------


def test_predicates_never_veto() -> None:
    """Every predicate near 0, the core answers high: the scalar strategy allows, and the page
    calls the predicate explanatory."""
    w = _write(1, "ASK")
    bench = _bench(
        [
            (
                w,
                {
                    JEV: _score(
                        JEV, policy_ok=0.9, matches_request=0.9, line_ok=0.01, price_confirmed=0.0
                    )
                },
            )
        ],
        {"C": _scalar("C", JEV, 0.61)},
    )
    d = w.arm_decisions["C"]
    assert (d["decision"], d["rule"]) == ("ALLOW", "threshold")
    assert _text(decision_calc(bench, d)) == "Derived gateway score 0.900 ≥ threshold 0.610 → ALLOW"


def test_disagreement_veto_is_shown_and_reproduces() -> None:
    w = _write(1, "ALLOW")
    scores = {JEV: _score(JEV, policy_ok=0.9), DEC: _score(DEC, policy_ok=0.1)}
    bench = _bench([(w, scores)], {"F": _two_judge(0.9, 0.1, 0.95, 0.5)})
    d = w.arm_decisions["F"]
    # The combined score clears the threshold, yet the veto asks.
    assert (d["decision"], d["rule"]) == ("ASK", "disagreement_veto")
    assert d["p_ok"] >= d["threshold"]
    text = _text(decision_calc(bench, d))
    assert text == (
        "Derived gateway score 0.950 ≥ threshold 0.600; disagreement 0.800 > limit 0.500: "
        "veto → ASK"
    )
    assert compare.recompute(calc_facts(d)) == "ASK"
    # Below the limit, no veto: the threshold decides, and the page says so.
    w2 = _write(2, "ALLOW")
    bench = _bench([(w2, scores)], {"F": _two_judge(0.6, 0.4, 0.95, 0.5)})
    d = w2.arm_decisions["F"]
    assert (d["decision"], d["rule"]) == ("ALLOW", "threshold")
    assert "(disagreement 0.200 ≤ limit 0.500: no veto)" in _text(decision_calc(bench, d))


def test_fail_closed_is_shown() -> None:
    w = _write(1, "ASK")
    bench = _bench(
        [(w, {JEV: _score(JEV, policy_ok=0.9, matches_request=0.9)})],
        {"F": _two_judge(0.9, 0.9, 0.9, None)},
    )
    d = w.arm_decisions["F"]
    assert (d["decision"], d["rule"], d["missing"]) == ("ASK", "fail_closed", ["openai_decisions"])
    assert _text(decision_calc(bench, d)) == "fail closed: OpenAI Decisions did not score → ASK"


# --- Exact reproduction across a whole report -------------------------------------------------


def test_every_rendered_decision_reproduces(tmp_path: Path) -> None:
    near = (0.9999998554928706, 0.9995694368119759)  # the B1002 Plain LLM answers
    cases = [
        # Near the Plain LLM threshold, below it.
        (
            _write(1, "DENY"),
            {
                LLM: _score(LLM, policy_ok=near[0], matches_request=near[1], overdue_ok=0.38),
                JEV: _score(JEV, policy_ok=0.68, matches_request=0.21, overdue_ok=0.14),
                DEC: _score(DEC, policy_ok=0.0, matches_request=0.0),
            },
        ),
        # Just above it.
        (
            _write(2, "ALLOW", "train"),
            {
                LLM: _score(LLM, policy_ok=1.0, matches_request=0.99979),
                JEV: _score(JEV, policy_ok=0.94, matches_request=0.76),
                DEC: _score(DEC, policy_ok=1.0, matches_request=0.95),
            },
        ),
        # The two-judge veto.
        (
            _write(3, "ASK"),
            {
                LLM: _score(LLM, policy_ok=1.0, matches_request=1.0),
                JEV: _score(JEV, policy_ok=0.47, matches_request=0.84, price_confirmed=0.56),
                DEC: _score(DEC, policy_ok=0.02, matches_request=0.99, price_confirmed=0.0),
            },
        ),
        # A judge missing: fail closed for every arm that needs it.
        (_write(4, "ALLOW"), {LLM: _score(LLM, policy_ok=1.0, matches_request=1.0)}),
        # An UNKNOWN verdict: raw and effective decisions.
        (
            _write(5, "UNKNOWN"),
            {
                LLM: _score(LLM, policy_ok=1.0, matches_request=1.0),
                JEV: _score(JEV, policy_ok=0.9, matches_request=0.9),
                DEC: _score(DEC, policy_ok=0.9, matches_request=0.9),
            },
        ),
    ]
    arms = {
        "B": _scalar("B", LLM, B_THRESHOLD),
        "C": _scalar("C", JEV, 0.61),
        "D": _scalar("D", DEC, 0.8),
        "F": _two_judge(0.9, 0.1, 0.95, 0.5),
    }
    bench = _bench(cases, arms)
    write_report(bench, tmp_path / "r")
    seen: set[str] = set()
    total = 0
    for page_path in (tmp_path / "r").rglob("*.html"):
        page = page_path.read_text()
        for facts, text in shown_decisions(page):
            total += 1
            seen.add(facts["rule"])
            # The decision follows from the shown facts alone, and the text shows them.
            assert compare.recompute(facts) == facts["decision"], (page_path, facts, text)
            assert facts["decision"] in text
            if facts["rule"] in ("threshold", "disagreement_veto"):
                assert facts["score"] in text and facts["threshold"] in text
            if facts["rule"] == "disagreement_veto":
                assert "veto" in text
    assert total >= 5 * 4 * 3  # summary lines, tables and cards on every action page
    assert seen >= {"threshold", "fail_closed", "disagreement_veto"}
    # Every stored decision appears with its calculation on its action page.
    for w in bench.writes:
        page = (tmp_path / "r" / write_href(w.write_id)).read_text()
        shown = {(f["decision"], f["rule"]) for f, _ in shown_decisions(page)}
        for d in w.arm_decisions.values():
            assert (d["decision"], d["rule"]) in shown
    # The B1002-like row: below the threshold as shown, raw answers averaging below it too.
    w1 = _text((tmp_path / "r" / write_href("W01")).read_text())
    assert "Plain LLM baseline m-llm 1.0000 0.9996" in w1
    assert "Derived gateway score 0.9998 < threshold 0.9999 → ASK" in w1
    assert (
        "1.000 1.000" not in w1.split("3. Individual judge comparison")[1].split("4. Decision")[0]
    )


# --- Descriptions and explanations ------------------------------------------------------------


def test_descriptions_follow_the_frozen_model() -> None:
    b = compare.describe(_scalar("B", LLM, B_THRESHOLD))
    assert "mean of Plain LLM baseline's policy_ok and matches_request answers" in b
    assert "yes_no" not in b and "every" not in b
    assert "one global threshold, 0.999892 (no per-action thresholds fitted)" in b
    per_action = FrozenArm(
        "C", (JEV,), {}, {"type": "scalar_mean", "judge": "jev"}, 0.6, {"refuel_data": 0.7}
    )
    assert "per-action thresholds for refuel_data; elsewhere 0.6" in compare.describe(per_action)
    e = FrozenArm(
        "E",
        (DEC,),
        {},
        {
            "type": "calibrated",
            "judge": "openai_decisions",
            "models": {
                "*": {"kind": "logistic", "features": ["policy_ok", "confirmed"], "n_labels": 6}
            },
        },
        0.2,
    )
    assert (
        "a logistic model over 2 of OpenAI Decisions' answers (policy_ok, confirmed), fitted on "
        "6 training labels" in compare.describe(e)
    )
    assert "no disagreement veto" in compare.describe(_two_judge(0.5, 0.5, 0.5, None))
    assert "disagreement above 0.5 vetoes to ASK" in compare.describe(
        _two_judge(0.5, 0.5, 0.5, 0.5)
    )


def test_a_low_request_match_explains_and_none_is_never_bare(tmp_path: Path) -> None:
    found, low = compare.weakest_answers(
        {
            "policy_ok": {"type": "yes_no", "p_yes": 0.68},
            "matches_request": {"type": "yes_no", "p_yes": 0.21},
            "overdue_ok": {"type": "yes_no", "p_yes": 0.14},
        }
    )
    assert low and found == [("overdue_ok", 0.14), ("matches_request", 0.21)]
    found, low = compare.weakest_answers(
        {
            "matches_request": {"type": "yes_no", "p_yes": 0.95},
            "line_ok": {"type": "yes_no", "p_yes": 0.7},
        }
    )
    assert not low and found == [("line_ok", 0.7)]
    w = _write(1, "DENY")
    bench = _bench(
        [(w, {JEV: _score(JEV, policy_ok=0.68, matches_request=0.21)})],
        {"C": _scalar("C", JEV, 0.61)},
    )
    write_report(bench, tmp_path / "r")
    page = (tmp_path / "r" / write_href("W01")).read_text()
    assert "Matches the request" in _text(page)
    # No table cell is a bare "none" (the verdict badge "none" is a verdict, not a cell).
    assert not re.search(r"<td>\s*(<span class='muted'>)?\s*none\s*(</span>)?\s*</td>", page)


# --- Held-out first ---------------------------------------------------------------------------


def test_executive_cards_and_gate_by_verdict() -> None:
    cases = [
        (_write(1, "DENY"), {DEC: _score(DEC, policy_ok=0.0, matches_request=0.0)}),
        (_write(2, "ASK"), {DEC: _score(DEC, policy_ok=1.0, matches_request=1.0)}),
        (_write(3, "ALLOW"), {DEC: _score(DEC, policy_ok=0.1, matches_request=0.1)}),
        (_write(4, "ALLOW", "train"), {DEC: _score(DEC, policy_ok=1.0, matches_request=1.0)}),
    ]
    bench = _bench(cases, {"D": _scalar("D", DEC, 0.8)})
    cards = re.findall(
        r"<div class='exec-card'><h3>(.*?)</h3>(.*?)</div>", executive_cards(bench), re.S
    )
    assert [t for t, _ in cards] == [
        "Held-out sample",
        "Best individual judge",
        "Configured gate",
        "Can we conclude?",
    ]
    bodies = [_text(b) for _, b in cards]
    assert bodies[0] == "3 actions 2 must not auto-run (ASK or DENY) · 1 valid (ALLOW) · 0 UNKNOWN"
    assert bodies[1] == "OpenAI Decisions caught 1/2 · auto-allowed 0/1"
    assert bodies[2].startswith("OpenAI Decisions (Arm D) caught 1/2 · missed 1/2")
    assert f"href='{write_href('W02')}'" in cards[2][1]  # the miss links to its action
    assert bodies[3].startswith("No sample-size gates failed; oracle unaudited; 3 < 50")
    rows = compare.by_verdict(compare.in_scope(bench, "test"), "D")
    assert [(r["verdict"], r["actions"], r["allowed"], r["asked"]) for r in rows] == [
        ("ALLOW", 1, 0, 1),
        ("ASK", 1, 1, 0),
        ("DENY", 1, 0, 1),
        ("UNKNOWN", 0, 0, 0),
    ]
    gate = gateway_section(bench)
    held_out, rest = gate.split("<details class='scope-all'>")
    assert "Held-out test only (3 actions)" in _text(held_out)
    assert "ALLOW policy-valid 1 0 (safe auto-allows) 1 (over-escalations) 0/1" in _text(held_out)
    assert "ASK needs clarification 1 1 (false allows) 0 (caught) 0/1" in _text(held_out)
    assert "ALLOW policy-valid 2 1 (safe auto-allows) 1 (over-escalations) 1/2" in _text(rest)
