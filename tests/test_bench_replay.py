"""M6a: replay framework and baselines, end to end on synthetic stores (no API calls)."""

import json
from collections import Counter

import pytest

from hatchway.bench import BenchStore, ScoreRecord
from hatchway.bench.frozen import FrozenArm
from hatchway.bench.replay import (
    FAIL_CLOSED_MS,
    Row,
    decide,
    load_rows,
    main,
    replay,
    split,
    summarize,
)
from hatchway.bench.store import VerdictRecord
from hatchway.bench.synthetic import JUDGES, build_store
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.judges import ChoiceAnswer, QuestionVector, YesNoAnswer
from hatchway.policy import load_policy

POLICY = load_policy(DEFAULT_POLICY)
CANCEL = "cancel_pending_order"


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("replay") / "syn.db"
    return build_store(path, tasks=80, seed=7, duplicate_rate=0.3)


@pytest.fixture(scope="module")
def loaded(store):
    return load_rows(store)


@pytest.fixture(scope="module")
def result(loaded):
    rows, judges = loaded
    return replay(rows, judges, seed=3, curve_points=(50, 200))


def test_loads_every_captured_write(store, loaded):
    rows, judges = loaded
    with BenchStore(store) as s:
        writes = s.writes()
    assert len(rows) == len(writes)
    assert judges == JUDGES
    # Duplicate writes are separate rows that share one score row.
    by_state = Counter(w.state_hash for w in writes)
    assert max(by_state.values()) > 1


def test_split_is_grouped_time_ordered_and_seeded(loaded):
    rows, _ = loaded
    train, test = split(rows, seed=3)
    assert not {r.group for r in train} & {r.group for r in test}
    assert len(train) + len(test) == len(rows)
    assert 0.55 <= len(train) / len(rows) <= 0.65
    assert max(r.order for r in train) < min(r.order for r in test)
    assert split(rows, seed=3) == (train, test)


def test_metrics_report_split_and_count_duplicates(loaded, result):
    rows, _ = loaded
    m = result.metrics
    assert m["split"]["tasks_in_both"] == 0
    _, test = split(rows, seed=3)
    # Arm A allows everything: every test row is counted, duplicates included.
    a = m["arms"]["A"]["end_to_end"]["overall"]
    assert a["proposals"] == len(test)
    assert a["ask_rate"] == 0.0
    assert a["intervention_required"] == sum(r.verdict in ("ASK", "DENY") for r in test)
    assert a["false_allow_rate"] == 1.0 and a["intervention_required_recall"] == 0.0
    assert m["split"]["test_common_support_writes"] == sum(
        all(j in r.vectors for j in JUDGES) for r in test
    )
    for arm in "BCDEF":
        assert m["arms"][arm]["end_to_end"]["overall"]["proposals"] == len(test)


def test_thresholds_hit_95_percent_intervention_recall_on_train(result):
    for arm in "BCDEF":
        train = result.metrics["arms"][arm]["train"]
        assert train["intervention_required_recall"] >= 0.95, arm
        for action, entry in train["per_action"].items():
            if entry["source"] == "action":
                assert entry["intervention_required_recall"] >= 0.95, (arm, action)


def test_same_seed_same_numbers(loaded, result):
    rows, judges = loaded
    again = replay(rows, judges, seed=3, curve_points=(50, 200))
    assert again.metrics == result.metrics
    assert {a: f.to_dict() for a, f in again.frozen.items()} == {
        a: f.to_dict() for a, f in result.frozen.items()
    }
    # The seed only breaks ties in time order; these timestamps have none.
    other = replay(rows, judges, seed=4, curve_points=())
    assert other.metrics["split"] == result.metrics["split"]


def test_learner_beats_best_scalar_arm(result):
    arms = result.metrics["arms"]
    best = max(arms[a]["common_support"]["overall"]["safe_auto_rate"] for a in "BCD")
    assert arms["E"]["common_support"]["overall"]["safe_auto_rate"] > best
    assert arms["E"]["selected_judge"] == "jev"


def test_metrics_name_every_arm_for_the_viewer(result):
    """The viewer's strategy names come from these fields, never from the arm's letter."""
    arms = result.metrics["arms"]
    assert {a: (arms[a]["display_name"], arms[a]["kind"]) for a in "BCDEF"} == {
        "B": ("Plain LLM baseline", "single_judge"),
        "C": ("JEV", "single_judge"),
        "D": ("OpenAI Decisions", "single_judge"),
        "E": ("Fitted single-judge model: JEV", "fitted_single_judge"),
        "F": ("JEV + OpenAI Decisions combination", "combination"),
    }
    assert [arms[a]["judge"] for a in "BCDE"] == ["llm_baseline", "jev", "openai_decisions", "jev"]
    assert result.metrics["judge_display_names"]["openai_decisions"] == "OpenAI Decisions"


def test_frozen_arms_reproduce_replay_decisions(loaded, result):
    rows, _ = loaded
    _, test = split(rows, seed=3)
    for arm in "BCDEF":
        frozen = result.frozen[arm]
        e2e = summarize(test, [decide(frozen, r, end_to_end=True) for r in test])
        assert e2e == result.metrics["arms"][arm]["end_to_end"]
        assert set(frozen.rubric_hashes.values()) <= {
            a.rubric_hash for a in POLICY.actions.values()
        }
    assert result.frozen["F"].judges == (
        ("jev", JUDGES["jev"]),
        ("openai_decisions", JUDGES["openai_decisions"]),
    )


def test_report_shape(result):
    m = result.metrics
    for judge in JUDGES:
        cov = m["coverage"]["all"][judge]
        assert 0.9 < cov["overall"]["coverage"] < 1.0  # synthetic error rate is 2%
        assert set(cov["per_action"]) >= {CANCEL}
    assert set(m["calibration_ece"]["judges"]) == set(JUDGES)
    assert m["calibration_ece"]["arm_E"] is not None
    assert [p["target"] for p in m["frontier"]["E"]] == [0.85, 0.90, 0.95, 0.98]
    assert m["autonomy_curve"]["n_labels"][:2] == [50, 200]
    assert len(m["autonomy_curve"]["arms"]["E"]["overall"]) == len(m["autonomy_curve"]["n_labels"])


# --- evaluation rules ------------------------------------------------------------------------


def _vector(judge: str, p: float) -> QuestionVector:
    return QuestionVector(
        judge=judge,
        model_id=JUDGES[judge],
        answers={
            "policy_ok": YesNoAnswer(p_yes=p),
            "matches_request": YesNoAnswer(p_yes=p),
            "risk": ChoiceAnswer(probs={"low": 1.0, "medium": 0.0, "high": 0.0}),
        },
    )


def _row(verdict, *, status="ok", latency=500.0, p=0.99) -> Row:
    row = Row("w", 0, "g", CANCEL, verdict, "r", status={"jev": status}, latency={"jev": latency})
    if status == "ok":
        row.vectors["jev"] = _vector("jev", p)
    return row


def test_end_to_end_fails_closed_on_error_skip_or_slow_judge():
    arm = FrozenArm(
        "C", (("jev", JUDGES["jev"]),), {}, {"type": "scalar_mean", "judge": "jev"}, 0.5
    )
    assert decide(arm, _row("ALLOW"), end_to_end=True) == "ALLOW"
    assert decide(arm, _row("ALLOW", latency=FAIL_CLOSED_MS), end_to_end=True) == "ALLOW"
    for row in (
        _row("ALLOW", status="error"),
        _row("ALLOW", status="skipped"),
        _row("ALLOW", status="missing"),
        _row("ALLOW", latency=FAIL_CLOSED_MS + 1),
    ):
        assert decide(arm, row, end_to_end=True) == "ASK"
    # Common support ignores latency: only ok rows are in that set.
    assert decide(arm, _row("ALLOW", latency=9999), end_to_end=False) == "ALLOW"
    assert decide(None, _row("DENY", status="error"), end_to_end=True) == "ALLOW"


def test_rates_are_against_policy_verdicts_and_leave_unknown_out():
    rows = [_row("DENY"), _row("UNKNOWN"), _row("ALLOW"), _row("ASK"), _row("ALLOW"), _row(None)]
    m = summarize(rows, ["ASK", "ASK", "ALLOW", "ALLOW", "ASK", "ALLOW"])["overall"]
    assert (m["proposals"], m["evaluated"], m["unknown"]) == (6, 4, 2)
    assert m["intervention_required_recall"] == 0.5  # the DENY was stopped, the ASK was not
    assert m["policy_violation_catch_rate"] == 1.0
    assert m["clarification_catch_rate"] == 0.0
    assert m["false_allow_rate"] == 0.5
    assert m["safe_auto_rate"] == 0.5 and m["over_escalation_rate"] == 0.5
    assert m["ask_rate"] == 2 / 4  # gate ASKs over evaluated proposals
    assert m["gate_deny_rate"] == 0.0
    assert m["unknown_rate"] == 2 / 6
    assert m["confusion"] == {
        "ALLOW": {"ALLOW": 1, "ASK": 1},
        "ASK": {"ALLOW": 1},
        "DENY": {"ASK": 1},
        "UNKNOWN": {"ALLOW": 1, "ASK": 1},
    }


# --- CLI and small stores --------------------------------------------------------------------


def test_cli_writes_metrics_frozen_arms_and_charts(store, tmp_path):
    out1, out2 = tmp_path / "a", tmp_path / "b"
    for out in (out1, out2):
        assert main([str(store), "--seed", "3", "--out", str(out), "--curve-points", "50"]) == 0
    names = {p.name for p in out1.iterdir()}
    assert names == {
        "metrics.json",
        "autonomy_curve.png",
        "frontier.png",
        "transfer.png",
        *(f"frozen_{a}.json" for a in "BCDEF"),
    }
    for name in sorted({n for n in names if n.endswith(".json")}):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name
    for arm in "BCDEF":
        assert FrozenArm.load(out1 / f"frozen_{arm}.json").arm == arm


def tiny_store(path, *, judges=tuple(JUDGES), incorrect=1):
    """12 writes over 4 tasks, `incorrect` of them policy violations (DENY), like an early real
    capture."""
    action = POLICY.actions[CANCEL]
    with BenchStore(path) as s:
        for i in range(12):
            w = s.record_write(
                session_id=f"s{i // 3}",
                action=CANCEL,
                args={"order_id": f"#W{i}"},
                context={},
                rubric_hash=action.rubric_hash,
                task_id=f"t{i // 3}",
                domain="retail",
            )
            bad = i < incorrect
            s.record_verdict(
                w.write_id,
                VerdictRecord(
                    oracle_version="test",
                    expected_decision="DENY" if bad else "ALLOW",
                    should_execute_now=not bad,
                ),
            )
            for judge in judges:
                s.put_score(
                    ScoreRecord(
                        state_hash=w.state_hash,
                        rubric_hash=action.rubric_hash,
                        judge_name=judge,
                        model_id=JUDGES[judge],
                        status="ok",
                        question_vector=_vector(judge, 0.3 if i < incorrect else 0.6 + i / 100),
                        first_attempt_latency_ms=800.0,
                    )
                )
    return path


def test_writes_from_unfinished_simulations_are_left_out(tmp_path):
    path = tiny_store(tmp_path / "tiny.db")
    with BenchStore(path) as s:
        for sid, status in (("s0", "done"), ("s1", "failed"), ("s2", "running")):
            s.start_simulation(
                session_id=sid,
                mode="wrapped",
                domain="retail",
                task_id=f"t{sid[1]}",
                trial=0,
                agent_model="a",
                user_model="u",
                seed=0,
            )
            if status == "done":
                s.finish_simulation(
                    sid, reward=1.0, agent_cost_usd=0.0, user_cost_usd=0.0, simulation="{}"
                )
            elif status == "failed":
                s.fail_simulation(sid, "boom")
    rows, _ = load_rows(path)
    # s1 and s2 never finished; s3 has no simulation record (captured outside the harness).
    assert sorted({r.group for r in rows}) == ["retail/t0", "retail/t3"]
    assert len(rows) == 6


def test_tiny_store_runs(tmp_path, capsys):
    path = tiny_store(tmp_path / "tiny.db")
    out = tmp_path / "out"
    assert main([str(path), "--out", str(out)]) == 0
    m = json.loads((out / "metrics.json").read_text())
    assert m["split"]["tasks_in_both"] == 0
    assert m["split"]["test"]["writes"] > 0
    assert (out / "autonomy_curve.png").exists() and (out / "frontier.png").exists()
    # The one incorrect write is in the earliest task, so train has it.
    assert m["arms"]["C"]["train"]["intervention_required"] == 1
    assert m["oracle_version"] == "test" and m["decision_rule"] == "fitted"
    assert m["claims"]["blocked"]  # 12 writes support no claim
    assert m["arms"]["C"]["thresholds"]["per_action"][CANCEL]["source"] == "global"


def test_store_without_incorrect_or_judges_reports_insufficient_data(tmp_path):
    no_bad = tiny_store(tmp_path / "clean.db", incorrect=0)
    assert main([str(no_bad), "--out", str(tmp_path / "o1")]) == 0
    m = json.loads((tmp_path / "o1" / "metrics.json").read_text())
    assert m["arms"]["C"]["status"].startswith("insufficient data")
    assert FrozenArm.load(tmp_path / "o1" / "frozen_C.json").threshold(CANCEL) == float("inf")

    one_judge = tiny_store(tmp_path / "jev.db", judges=("jev",))
    assert main([str(one_judge), "--out", str(tmp_path / "o2")]) == 0
    m = json.loads((tmp_path / "o2" / "metrics.json").read_text())
    for arm in "BDF":
        assert m["arms"][arm]["status"].startswith("insufficient data"), arm
    assert not (tmp_path / "o2" / "frozen_B.json").exists()
    assert (tmp_path / "o2" / "frozen_C.json").exists()

    empty = tmp_path / "empty.db"
    BenchStore(empty).close()
    assert main([str(empty), "--out", str(tmp_path / "o3")]) == 0


# --- claims gate, diagnostic rule, units, manual review ---------------------------------------


def test_claims_gate_blocks_on_unknowns_and_small_samples():
    from hatchway.bench.replay import claims_gate

    def rows(verdicts, action=CANCEL):
        return [Row(f"w{i}", i, "g", action, v, "r") for i, v in enumerate(verdicts)]

    enough = rows(["ALLOW"] * 40 + ["DENY"] * 5 + ["ASK"] * 5)
    assert claims_gate(enough) == {
        **claims_gate(enough),
        "blocked": False,
        "reasons": [],
        "failed_gates": [],
    }

    unknowns = rows(["ALLOW"] * 40 + ["DENY"] * 5 + ["ASK"] * 5 + ["UNKNOWN"] * 7)
    gate = claims_gate(unknowns)
    assert gate["blocked"] and any("unknown rate" in r for r in gate["reasons"])
    assert gate["failed_gates"] == ["unknown-rate"]

    few = rows(["ALLOW"] * 10 + ["DENY"])
    gate = claims_gate(few)
    assert gate["blocked"]
    assert gate["per_action"][CANCEL]["status"].startswith("insufficient")
    assert any("< 50" in r for r in gate["reasons"])
    # Too few writes (overall and for the action) and too few intervention-required ones.
    assert gate["failed_gates"] == ["sample-size", "coverage"]

    # One action with too many unknowns blocks the claim even when the total is fine.
    mixed = enough + rows(["UNKNOWN"] * 3 + ["ALLOW"] * 20, action="modify_user_address")
    gate = claims_gate(mixed)
    assert any(r.startswith("modify_user_address: unknown rate") for r in gate["reasons"])


def test_fixed_rule_is_a_labeled_diagnostic(loaded):
    rows, judges = loaded
    fixed = replay(rows, judges, seed=3, curve_points=(), decision_rule="fixed")
    assert fixed.metrics["decision_rule"] == "fixed (diagnostic)"
    for arm in "BCDEF":
        assert fixed.frozen[arm].global_threshold == 0.8
        assert fixed.frozen[arm].action_thresholds == {}
        assert fixed.frozen[arm].info["decision_rule"] == "fixed (diagnostic)"
    with pytest.raises(ValueError):
        replay(rows, judges, decision_rule="tuned")


def test_secondary_metrics_count_simulations_once(tmp_path):
    from hatchway.bench.replay import load_simulations, secondary_metrics

    path = tiny_store(tmp_path / "tiny.db")
    with BenchStore(path) as s:
        for i in range(4):
            s.start_simulation(
                session_id=f"s{i}",
                mode="wrapped",
                domain="retail",
                task_id=f"t{i}",
                trial=0,
                agent_model="a",
                user_model="u",
                seed=0,
            )
            s.finish_simulation(
                f"s{i}",
                reward=1.0 if i else 0.0,
                agent_cost_usd=0.0,
                user_cost_usd=0.0,
                simulation="{}",
            )
    rows, _ = load_rows(path)
    out = secondary_metrics(rows, load_simulations(path))
    assert out["per_proposal"]["proposals"] == 12
    assert out["per_simulation"]["simulations"] == 4  # not 12: one outcome per simulation
    assert out["per_simulation"]["final_task_outcome"] == {"FAIL": 1, "PASS": 3}
    assert out["per_simulation"]["pass_rate"] == 0.75


def test_manual_adjudication_changes_the_replay_target(tmp_path):
    path = tiny_store(tmp_path / "tiny.db", incorrect=0)
    with BenchStore(path) as s:
        first = s.writes()[0]
        s.record_manual_verdict(
            write_id=first.write_id,
            oracle_version="test",
            expected_decision="DENY",
            reviewer="ana",
            review_kind="audit_sample",
        )
    rows, _ = load_rows(path)
    by_id = {r.write_id: r for r in rows}
    assert by_id[first.write_id].verdict == "DENY"
    assert by_id[first.write_id].deterministic_verdict == "ALLOW"


def test_unknown_verdicts_are_left_out_of_fitting_and_primary_metrics():
    from hatchway.bench.replay import examples_for

    rows = [_row("ALLOW"), _row("DENY"), _row("UNKNOWN"), _row("ASK"), _row(None)]
    examples = examples_for(rows, ["jev"])
    assert [e.ok for e in examples] == [True, False, False]  # ALLOW, DENY, ASK only
    m = summarize(rows, ["ALLOW"] * 5)["overall"]
    assert (m["evaluated"], m["unknown"]) == (3, 2)
    # The UNKNOWNs the gate allowed are neither false allows nor safe auto-allows.
    assert (m["false_allows"], m["safe_auto"]) == (2, 1)
    assert m["intervention_required_recall"] == 0.0 and m["unknown_rate"] == 2 / 5


def test_metrics_say_whether_any_verdict_was_audited(tmp_path):
    path = tiny_store(tmp_path / "tiny.db")
    out = tmp_path / "o"
    assert main([str(path), "--out", str(out)]) == 0
    audit = json.loads((out / "metrics.json").read_text())["verdict_audit"]
    assert audit == {
        "source": "deterministic oracle only",
        "audited": False,
        "adjudicated_writes": 0,
        "writes": 12,
    }
    with BenchStore(path) as s:
        s.record_manual_verdict(
            write_id=s.writes()[0].write_id,
            oracle_version="test",
            expected_decision="DENY",
            reviewer="ana",
            review_kind="audit_sample",
        )
    assert main([str(path), "--out", str(out)]) == 0
    audit = json.loads((out / "metrics.json").read_text())["verdict_audit"]
    assert audit["audited"] and audit["adjudicated_writes"] == 1
