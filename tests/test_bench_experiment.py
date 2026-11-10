"""The targeted experiment (`hatchway.bench.experiment`): the frozen definition, completed
simulations only, the label-free family split, the gates, the three-way decision with
per-action safety, family bootstrap, and the replay's action and split filters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hatchway.bench import experiment as ex
from hatchway.bench.experiment import EligibleWrite, HeldOut
from hatchway.bench.store import BenchStore

R, ROAM, FUEL = ex.PRIMARY_ACTIONS


# --- The frozen definition -----------------------------------------------------------------------

STATE = {
    "hatchway_commit": "abc",
    "tree_clean": True,
    "tau2_commit_pinned": "t1",
    "tau2_commit_installed": "t1",
    "oracle_version": "o1",
    "policy_sha256": "p1",
    "rubric_hashes": {"refuel_data": "r1"},
    "stage_config_sha256": ["c1", "c2"],
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hatchway_commit", "def"),
        ("oracle_version", "o2"),
        ("policy_sha256", "p2"),
        ("rubric_hashes", {"refuel_data": "r2"}),
        ("stage_config_sha256", ["c1", "c3"]),
        ("tau2_commit_installed", "t2"),
    ],
)
def test_any_pinned_change_is_named(field: str, value: object) -> None:
    assert ex.differences(STATE, STATE) == []
    diffs = ex.differences(STATE, {**STATE, field: value})
    assert any(d.startswith(field) for d in diffs)


def test_a_dirty_tree_is_a_difference() -> None:
    assert ex.differences(STATE, {**STATE, "tree_clean": False}) == [
        "tree_clean (uncommitted changes)"
    ]


def test_the_definition_is_written_once_and_cannot_be_edited(tmp_path: Path) -> None:
    definition = {**STATE, "stages": [], "store": str(tmp_path / "x.db")}
    ex.write_definition(tmp_path, definition)
    with pytest.raises(SystemExit, match="frozen once"):
        ex.write_definition(tmp_path, definition)
    loaded = ex.load_experiment(tmp_path, check=False)
    assert (
        loaded.sha256
        == json.loads((tmp_path / ex.DEFINITION_FILE).read_text())["definition_sha256"]
    )
    edited = json.loads((tmp_path / ex.DEFINITION_FILE).read_text())
    edited["oracle_version"] = "o9"
    (tmp_path / ex.DEFINITION_FILE).write_text(json.dumps(edited))
    with pytest.raises(ex.DefinitionChanged, match="edited"):
        ex.load_experiment(tmp_path, check=False)


def test_freezing_refuses_a_dirty_tree(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="uncommitted"):
        ex.write_definition(tmp_path, {**STATE, "tree_clean": False})


def test_every_command_refuses_a_changed_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ex.write_definition(tmp_path, {**STATE, "stages": [], "store": str(tmp_path / "x.db")})
    monkeypatch.setattr(ex, "current_state", lambda configs: {**STATE, "oracle_version": "o2"})
    for command in ("dry-run", "count", "split", "gate", "score", "replay", "decide"):
        with pytest.raises(ex.DefinitionChanged, match="oracle_version"):
            ex.main([command, "--dir", str(tmp_path)])
    with pytest.raises(ex.DefinitionChanged, match="oracle_version"):
        ex.main(["capture", "--dir", str(tmp_path), "--stage", "1"])


# --- Completed simulations only ------------------------------------------------------------------


def test_only_writes_of_completed_simulations_are_eligible(tmp_path: Path) -> None:
    from hatchway.bench.store import PreActionSnapshot, VerdictRecord

    snap = PreActionSnapshot(agent_db={}, messages=[], domain_policy_hash="p" * 64)

    def verdict(_w: object, _p: object) -> tuple:
        return snap, VerdictRecord(
            oracle_version="o1",
            expected_decision="ALLOW",
            should_execute_now=True,
            reason_codes=(),
            explanation="ok",
            evidence={},
        )

    with BenchStore(tmp_path / "s.db") as store:
        for sid, status, reward in [
            ("done", "done", 1.0),
            ("budget", "failed", None),  # a budget refusal mid-simulation
            ("killed", "running", None),  # an interruption
            ("noreward", "done", None),
        ]:
            store.start_simulation(
                session_id=sid,
                mode="wrapped",
                domain="telecom",
                task_id="T",
                trial=0 if sid != "noreward" else 1,
                agent_model="m",
                user_model="u",
                seed=1 if sid != "done" else 2,
            )
            store.record_write(
                session_id=sid,
                action=FUEL,
                args={"line_id": sid},
                context={},
                rubric_hash="r",
                domain="telecom",
                task_id="T",
                agent_model="m",
                trial=0,
                pre_execution=verdict,
            )
            if status == "done":
                store.finish_simulation(
                    sid, reward=reward, agent_cost_usd=0, user_cost_usd=0, simulation="{}"
                )
            elif status == "failed":
                store.fail_simulation(sid, "BudgetRefused: capture cap")
        writes = ex.eligible_writes(store, "o1")
    assert [w.session_id for w in writes] == ["done"]
    assert writes[0].verdict == "ALLOW"


# --- The split -----------------------------------------------------------------------------------


def _tasks() -> dict[str, dict]:
    tasks = {}
    for i in range(12):  # retail: 6 users, two tasks each
        tasks[f"retail/{i}"] = {"family": f"retail/user:{i // 2}", "incidence": [R]}
    for i in range(16):
        inc = [[ROAM, FUEL], [FUEL], [ROAM]][i % 3]
        tasks[f"telecom/t{i}"] = {"family": f"telecom/t{i}", "incidence": inc}
    return tasks


def _writes(tasks: dict) -> list[tuple[str, str, str]]:
    out = []
    for key in tasks:
        domain, task_id = key.split("/", 1)
        for m in range(3):
            out.append((f"w-{key}-{m}", domain, task_id))
    return out


def test_split_keeps_families_together_and_is_deterministic() -> None:
    tasks = _tasks()
    writes = _writes(tasks)
    a = ex.freeze_split(writes, tasks, seed=0)
    b = ex.freeze_split(list(reversed(writes)), tasks, seed=0)
    assert a == b  # deterministic, whatever the write order
    assert a["overlap"] == 0
    assert not set(a["families"]["train"]) & set(a["families"]["test"])
    family = {w: tasks[f"{d}/{t}"]["family"] for w, d, t in writes}
    for side in ("train", "test"):
        other = "test" if side == "train" else "train"
        assert not {family[w] for w in a["write_ids"][side]} & {
            family[w] for w in a["write_ids"][other]
        }
    # Every stratum keeps families on both sides, and train holds about 60% of the writes.
    for stratum in a["strata"].values():
        assert 0 < stratum["train_families"] < stratum["families"]
    share = len(a["write_ids"]["train"]) / len(writes)
    assert 0.5 <= share <= 0.75
    assert ex.freeze_split(writes, tasks, seed=1) != a  # the seed matters


def test_split_never_sees_labels() -> None:
    """The split takes (write id, domain, task) only; verdicts cannot change it."""
    import inspect

    params = list(inspect.signature(ex.freeze_split).parameters)
    assert params == ["writes", "tasks", "seed", "train_share"]
    with pytest.raises(ValueError, match="not in the definition"):
        ex.freeze_split([("w", "retail", "999")], _tasks(), seed=0)


# --- Gates ---------------------------------------------------------------------------------------


def _ew(i: int, action: str, verdict: str | None) -> EligibleWrite:
    return EligibleWrite(f"w{i}-{action}", "s", "d", "t", action, "m", verdict)


def _side(n_allow: int, n_int: int, n_unknown: int = 0) -> list[EligibleWrite]:
    out = []
    for action in ex.PRIMARY_ACTIONS:
        out += [_ew(i, action, "ALLOW") for i in range(n_allow)]
        out += [_ew(100 + i, action, "DENY" if i % 2 else "ASK") for i in range(n_int)]
        out += [_ew(200 + i, action, "UNKNOWN") for i in range(n_unknown)]
    return out


def test_gates_pass_at_their_edges() -> None:
    # Held-out: 7 ALLOW + 7 ASK/DENY per action -> 42 overall... below 70: fails overall.
    assert not ex.gate(_side(5, 5), _side(7, 7)).passed
    # 12 + 12 per action: 72 verdict-bearing, 36 ALLOW, 36 ASK/DENY; train 5 + 5 per action.
    result = ex.gate(_side(5, 5), _side(12, 12))
    assert result.passed, [c for c in result.checks if not c["ok"]]


@pytest.mark.parametrize(
    ("train", "test", "failing"),
    [
        (_side(4, 5), _side(12, 12), "train"),  # 4 ALLOW per action in train
        (_side(5, 4), _side(12, 12), "train"),  # 4 ASK/DENY per action in train
        (_side(5, 5), _side(12, 12, n_unknown=3), "UNKNOWN"),  # 3/27 = 11% UNKNOWN
        (_side(5, 5), _side(2, 22), "ALLOW"),  # 2 ALLOW per action, 6 overall
    ],
)
def test_gates_fail_just_past_their_edges(train, test, failing) -> None:
    result = ex.gate(train, test)
    assert not result.passed
    failed = [c for c in result.checks if not c["ok"]]
    assert any(failing in c["scope"] or failing in c["rule"] for c in failed), failed


def test_unknown_at_exactly_ten_percent_passes() -> None:
    # 9 verdict-bearing + 1 UNKNOWN per action-sized block: 10% exactly.
    test = _side(12, 15, n_unknown=3)  # 3 / 30 = 10%
    result = ex.gate(_side(5, 5), test)
    assert all(c["ok"] for c in result.checks if "UNKNOWN" in c["rule"])


# --- The decision -----------------------------------------------------------------------------


def _row(i: int, action: str, verdict: str, family: str | None = None, **d: str) -> HeldOut:
    return HeldOut(
        f"w{i}",
        family or f"f{i}",
        action,
        verdict,
        {arm: (dec, "threshold") for arm, dec in d.items()},
    )


def _block(action: str, d_asks_valid: int, e_asks_valid: int, start: int = 0) -> list[HeldOut]:
    """Per action: 4 interventions (all caught by D, E and F) and 10 valid actions, of which D
    asks on `d_asks_valid` and E on `e_asks_valid`; F asks on all."""
    rows = [_row(start + i, action, "DENY", D="ASK", E="ASK", F="ASK") for i in range(4)]
    for i in range(10):
        rows.append(
            _row(
                start + 10 + i,
                action,
                "ALLOW",
                D="ASK" if i < d_asks_valid else "ALLOW",
                E="ASK" if i < e_asks_valid else "ALLOW",
                F="ASK",
            )
        )
    return rows


def _rows(d_asks: int, e_asks: int) -> list[HeldOut]:
    return [r for k, a in enumerate(ex.PRIMARY_ACTIONS) for r in _block(a, d_asks, e_asks, 100 * k)]


def test_strong_win() -> None:
    # D asks 4 + 6 = 10 of 14 per action; E asks 4 + 2 = 6: a 40% reduction.
    result = ex.decide(_rows(6, 2), gate_passed=True)
    assert result["outcome"] == "FULL_RUN_RECOMMENDED" and result["strength"] == "strong"
    assert result["best_arm"] == "E" and result["best_reduction"] == pytest.approx(0.4)


def test_directional_win() -> None:
    # D asks 10, E asks 8: 20%.
    result = ex.decide(_rows(6, 4), gate_passed=True)
    assert result["outcome"] == "FULL_RUN_RECOMMENDED" and result["strength"] == "directional"


def test_below_ten_percent_is_no_full_run() -> None:
    # D asks 10, E asks 9.5 on average... use 10 vs 10: 0%.
    result = ex.decide(_rows(6, 6), gate_passed=True)
    assert result["outcome"] == "NO_FULL_RUN" and "< 10%" in result["reason"]


def test_d_pareto_perfect_stops() -> None:
    result = ex.decide(_rows(0, 0), gate_passed=True)
    assert result["outcome"] == "NO_FULL_RUN"
    assert result["reason"] == "D already leaves no safe autonomy to recover"


def test_worse_on_one_action_is_ineligible_even_if_better_overall() -> None:
    rows = _rows(6, 1)
    # On refuel, E lets one intervention through that D caught.
    rows = [
        HeldOut(
            r.write_id, r.family, r.action, r.verdict, {**r.decisions, "E": ("ALLOW", "threshold")}
        )
        if (r.action == FUEL and r.verdict == "DENY" and r.write_id == "w200")
        else r
        for r in rows
    ]
    result = ex.decide(rows, gate_passed=True)
    assert not result["candidates"]["E"]["eligible"]
    assert any(FUEL in p for p in result["candidates"]["E"]["problems"])
    assert result["outcome"] == "NO_FULL_RUN"  # F asks everything: 0% reduction... see below
    assert result["candidates"]["F"]["eligible"]


def test_incomplete_decisions_make_a_candidate_ineligible_and_d_inconclusive() -> None:
    rows = _rows(6, 2)
    fail = HeldOut(
        "x",
        "fx",
        R,
        "ALLOW",
        {"D": ("ALLOW", "threshold"), "E": ("ASK", "fail_closed"), "F": ("ASK", "threshold")},
    )
    result = ex.decide([*rows, fail], gate_passed=True)
    assert not result["candidates"]["E"]["eligible"]
    missing_d = HeldOut(
        "y", "fy", R, "ALLOW", {"E": ("ALLOW", "threshold"), "F": ("ASK", "threshold")}
    )
    result = ex.decide([*rows, missing_d], gate_passed=True)
    assert result["outcome"] == "INCONCLUSIVE" and "incomplete" in result["reason"]


def test_inconclusive_cases() -> None:
    assert ex.decide(_rows(6, 2), gate_passed=False)["outcome"] == "INCONCLUSIVE"
    no_allow = [r for r in _rows(6, 2) if not (r.action == ROAM and r.verdict == "ALLOW")]
    result = ex.decide(no_allow, gate_passed=True)
    assert result["outcome"] == "INCONCLUSIVE" and ROAM in result["reason"]
    # D never asks: no denominator for the reduction (and D misses every intervention).
    never = [
        HeldOut(
            r.write_id, r.family, r.action, r.verdict, {**r.decisions, "D": ("ALLOW", "threshold")}
        )
        for r in _rows(6, 2)
    ]
    result = ex.decide(never, gate_passed=True)
    assert result["outcome"] == "INCONCLUSIVE" and "zero" in result["reason"]


# --- Bootstrap ------------------------------------------------------------------------------


def test_bootstrap_resamples_families_not_writes() -> None:
    # Two families: in one D catches both writes, in the other neither. Resampling families can
    # only give catch rates 0, 0.5 or 1; resampling writes would give quarters too.
    rows = [
        _row(1, R, "DENY", "fa", D="ASK", E="ASK"),
        _row(2, R, "DENY", "fa", D="ASK", E="ASK"),
        _row(3, R, "DENY", "fb", D="ALLOW", E="ASK"),
        _row(4, R, "DENY", "fb", D="ALLOW", E="ASK"),
    ]
    a = ex.bootstrap(rows, ["D", "E"], "D", seed=0, resamples=500)
    b = ex.bootstrap(rows, ["D", "E"], "D", seed=0, resamples=500)
    assert a == b and a["families"] == 2
    interval = a["intervals"]["D"]["catch_rate"]
    assert interval["low"] == 0.0 and interval["high"] == 1.0

    seen = set()
    import random

    rng = random.Random(0)
    fams = {"fa": rows[:2], "fb": rows[2:]}
    for _ in range(200):
        drawn = [r for _f in range(2) for r in fams[rng.choice(sorted(fams))]]
        seen.add(ex.stats(drawn, "D").catch_rate)
    assert seen <= {0.0, 0.5, 1.0}


# --- Dry run --------------------------------------------------------------------------------------


def test_dry_run_counts_only_new_simulations_per_stage() -> None:
    definition = {
        "agent_models": ["gpt-4.1-nano-2025-04-14", "gpt-4.1-2025-04-14"],
        "trials": 1,
        "stages": [
            {"name": "s1", "tasks": ["retail/1"]},
            {"name": "s2", "tasks": ["retail/1", "telecom/2"]},
        ],
        "tasks": {
            "retail/1": {"domain": "retail", "incidence": [R]},
            "telecom/2": {"domain": "telecom", "incidence": []},
        },
    }
    s1, s2 = ex.dry_run(definition)
    assert (s1["new_simulations"], s2["new_simulations"]) == (2, 2)
    assert s1["central_usd"] == pytest.approx(0.00325 + 0.0362, abs=0.01)
    assert s2["expected_primary_writes"] == 0  # a payment-only task adds no primary writes
    assert s2["cumulative_upper_usd"] >= s2["cumulative_central_usd"]


# --- Replay filters -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    from hatchway.bench.synthetic import build_store

    path = tmp_path_factory.mktemp("exp") / "syn.db"
    return build_store(path, tasks=60, seed=5, duplicate_rate=0.0)


def test_replay_action_filter_and_frozen_split(synthetic) -> None:
    from hatchway.bench.replay import load_rows, replay

    rows, judges = load_rows(synthetic)
    actions = sorted({r.action for r in rows})
    keep = actions[0]
    only, _ = load_rows(synthetic, judges, actions={keep})
    assert only and {r.action for r in only} == {keep}

    ids = [r.write_id for r in rows]
    frozen = {"train": ids[: int(0.6 * len(ids))], "test": ids[int(0.6 * len(ids)) :]}
    result = replay(rows, judges, seed=0, curve_points=(), frozen_split=frozen)
    assert result.metrics["split"]["test"]["writes"] == len(frozen["test"])
    with pytest.raises(ValueError, match="neither or both"):
        replay(
            rows,
            judges,
            seed=0,
            curve_points=(),
            frozen_split={**frozen, "test": frozen["test"][1:]},
        )
    with pytest.raises(ValueError, match="no own threshold"):
        replay(rows, judges, seed=0, curve_points=(), require_thresholds_for={"no_such_action"})
