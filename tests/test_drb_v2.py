"""Decision-record benchmark v2: family-level risk, choose / refit / certify, bounded local
adaptation, pools and the once-only evaluation. No network, no judge, no store."""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pytest

from hatchway.bench.drb import model as M
from hatchway.bench.drb import partitions as PART
from hatchway.bench.drb import synthetic as G
from hatchway.bench.drb.schema import ConceptValue
from hatchway.bench.drb.v2 import adapt as A
from hatchway.bench.drb.v2 import evaluate as E
from hatchway.bench.drb.v2 import pools as P
from hatchway.bench.drb.v2 import risk as R
from hatchway.bench.drb.v2 import run as RUN

V1 = Path(__file__).parents[1] / "experiments/2026-10-23-decision-record-benchmark"


@pytest.fixture(scope="module")
def v1():
    return PART.assign_synthetic(G.generate(G.SEED), G.SEED)


@pytest.fixture(scope="module")
def dev(v1):
    return RUN.development_pool(v1)


@pytest.fixture(scope="module")
def cal():
    return P.calibration_pools()


# --- Family risk -------------------------------------------------------------------------------


def test_clopper_pearson_values() -> None:
    assert R.cp_ucb(0, 29) == pytest.approx(1 - 0.05 ** (1 / 29))
    assert R.cp_ucb(0, 29) < R.ALPHA < R.cp_ucb(0, 28)
    assert R.cp_ucb(0, 0) == 1.0 and R.cp_ucb(3, 3) == 1.0
    assert R.cp_ucb(1, 32) > R.ALPHA  # one failing family breaks the bound at 32


def test_one_false_allow_fails_the_whole_family(dev) -> None:
    fam = next(f for f, rs in R.by_family(dev).items() if sum(not r.should_run for r in rs) >= 2)
    recs = R.by_family(dev)[fam]
    one = next(r for r in recs if not r.should_run)
    risk = R.family_risk(recs, lambda r: r.record_id == one.record_id)
    assert (risk.eligible, risk.failing) == (1, 1)
    assert R.family_risk(recs, lambda r: r.should_run).failing == 0


def test_dc_score_never_counts_unknown_or_inapplicable(dev) -> None:
    r = next(
        x for x in dev if all(v.state == "satisfied" for v in x.concepts.values() if v.applicable)
    )
    assert R.dc_score(r) == 1.0
    unk = dataclasses.replace(
        r, concepts={**r.concepts, "actor_identified": ConceptValue(True, "unknown", 0.0)}
    )
    assert R.dc_score(unk) < 1.0
    na = next(x for x in G.generate(G.SEED) if x.action == "pause_campaign")
    assert not na.concepts["consent_obtained"].applicable
    assert R.dc_score(na) == (
        sum(v.state == "satisfied" for v in na.concepts.values() if v.applicable)
        / sum(v.applicable for v in na.concepts.values())
    )


# --- Choose / refit / certify ------------------------------------------------------------------


def test_crossfit_never_scores_a_record_with_its_own_family(dev, monkeypatch) -> None:
    seen: list[set[str]] = []
    real = M.fit_logistic

    def spy(records, prior=None):
        seen.append({r.family_id for r in records})
        return real(records, prior)

    monkeypatch.setattr(R.M, "fit_logistic", spy)
    folds = R.family_folds(dev)
    scores = R.crossfit_scores(dev)
    assert scores is not None and len(scores) == len(dev)
    for fold, fams in enumerate(seen):
        held = {f for f, k in folds.items() if k == fold}
        assert not held & fams


def test_candidate_walks_the_grid_strictest_first() -> None:
    assert tuple(sorted(R.G_GRID, reverse=True)) == R.G_GRID
    assert R.DC_GRID == (1.0, 0.875, 0.75)


def test_failed_certification_escalates_everything(dev, cal) -> None:
    tiny = cal["cal_P1"][:10]  # far too few families to certify
    s = R.fit_certified_g("x", dev, tiny)
    assert math.isinf(s.threshold)
    assert s.info["certificate"] in ("failed: escalate everything", "no candidate")
    assert not any(s.allows(r) for r in dev)


def test_certification_uses_only_the_pool_scored_by_the_final_model(dev, cal) -> None:
    pool = [*cal["cal_P1"], *cal["cal_P2"]]
    s = R.fit_certified_g("G-synthetic", dev, pool)
    if s.info.get("candidate") is not None:
        risk = R.family_risk(pool, lambda r: s.allows_at(r, s.info["candidate"]))
        assert s.info["pool"]["eligible_families"] == risk.eligible
        assert s.info["pool"]["failing_families"] == risk.failing


def test_pools_reach_the_eligible_family_minimum(cal) -> None:
    for name, rs in cal.items():
        assert R.eligible_families(rs) >= R.POOL_ELIGIBLE, name
    fresh = P.fresh_pools(12345)
    for name in (
        "fresh_final",
        "fresh_action",
        "fresh_domain",
        "fresh_p3_promotion",
        "fresh_p3_eval",
    ):
        assert R.eligible_families(fresh[name]) >= R.POOL_ELIGIBLE, name
    assert len({r.family_id for r in fresh["fresh_p3_corrections"]}) == 5


def test_pools_are_disjoint_and_new(v1, cal) -> None:
    fresh = P.fresh_pools(12345)
    seen: dict[str, str] = {}
    for name, rs in {**cal, **fresh}.items():
        for r in rs:
            assert seen.setdefault(r.family_id, name) == name
    assert not set(seen) & {r.family_id for r in v1}
    assert {r.action for r in fresh["fresh_action"]} == {PART.HELD_OUT_ACTION}
    assert {r.domain for r in fresh["fresh_domain"]} == {PART.HELD_OUT_DOMAIN}
    assert not any(
        r.action == PART.HELD_OUT_ACTION or r.domain == PART.HELD_OUT_DOMAIN
        for rs in (cal["cal_P1"], cal["cal_P2"], fresh["fresh_final"])
        for r in rs
    )


def test_development_pool_excludes_v1_held_out_records(v1, dev) -> None:
    assert {r.split for r in dev} == set(RUN.DEV_SPLITS)
    assert not any(
        r.action == PART.HELD_OUT_ACTION or r.domain == PART.HELD_OUT_DOMAIN for r in dev
    )
    assert not any(E.profile_of(r) == "P3" for r in dev)


# --- Adaptation --------------------------------------------------------------------------------


def _pretrained(dev, cal) -> R.Scorer:
    return R.fit_certified_g("G-synthetic", dev, [*cal["cal_P1"], *cal["cal_P2"]])


def test_updates_are_local_bounded_and_anchored(dev, cal) -> None:
    g = _pretrained(dev, cal)
    batch = [r for r in dev if r.concepts["reversibility"].state == "not_satisfied"][:5]
    new = A.update(g.coef, g.coef, batch)
    moved = {
        M.FEATURE_NAMES[i] for i, (a, b) in enumerate(zip(g.coef.w, new.w, strict=True)) if a != b
    }
    allowed = {f"{c}:{s}" for c in A.exhibited(batch) for s in ("not_satisfied", "unknown")}
    assert moved <= allowed
    assert new.b == g.coef.b
    assert all(abs(a - b) <= A.DELTA + 1e-9 for a, b in zip(g.coef.w, new.w, strict=True))
    # A record whose corrected concepts are satisfied or not applicable keeps its exact score.
    scope = A.exhibited(batch)
    for r in dev:
        if A.untouched_by(r, scope):
            assert M.score(new, r) == M.score(g.coef, r)


def test_cumulative_bound_from_the_pretrained_model(dev, cal) -> None:
    g = _pretrained(dev, cal)
    coef = g.coef
    batch = [r for r in dev if r.concepts["potential_harm"].state == "not_satisfied"][:5]
    for _ in range(6):
        coef = A.update(coef, g.coef, batch)
    assert all(abs(a - b) <= A.CUMULATIVE + 1e-9 for a, b in zip(g.coef.w, coef.w, strict=True))


def test_promotion_never_reads_corrections_and_rejects_more_failures(dev, cal) -> None:
    g = _pretrained(dev, cal)
    corrections = [r for r in dev if E.profile_of(r) == "P2"]
    pool = cal["cal_P2"]
    adapted = A.adapt("G-combined(P2)", g, A.batches(corrections), pool)
    for look in adapted.looks:
        if look.promoted:
            assert (
                look.challenger_pool["failing_families"] <= look.champion_pool["failing_families"]
            )
            assert look.challenger_pool["over_escalations"] < look.champion_pool["over_escalations"]
            assert look.challenger_pool["ucb"] <= R.ALPHA
    # Promotion is judged on pool families only, never on the corrections.
    assert not {r.family_id for r in corrections} & {r.family_id for r in pool}


def test_adaptation_is_cumulative(dev, cal) -> None:
    g = _pretrained(dev, cal)
    corr = P.draw("t_corr", 5, P.in_distribution(), ("P3",), n_families=5)
    promo = P.draw("t_promo", 5, P.in_distribution(), ("P3",))
    steps = E.p3_steps(corr)
    assert [len(s) for s in steps] == [5, 5, 15]
    full = A.adapt("x", g, steps, promo)
    first_two = A.adapt("x", g, steps[:2], promo)
    # k = 10 extends k = 5: the same champions, step by step.
    assert [c.coef for c in full.champions[:3]] == [c.coef for c in first_two.champions]


def test_hard_deny_is_never_overridden(dev, cal) -> None:
    allow_all = R.Scorer("allow-all", "dc", None, -1.0)
    hard = P.hard("h", 1)
    assert hard and not any(allow_all.allows(r) for r in hard)


# --- Controls and evaluation -------------------------------------------------------------------


def test_negative_controls_show_no_apparent_transfer(v1, dev, cal) -> None:
    world = {"dev": dev, **cal, **P.fresh_pools(777)}
    for control in ("shuffled_labels", "no_shared_effect"):
        _, gate = E.run_world(E.relabel_world(world, control, 99))
        assert not gate["apparent_transfer"], control


def test_the_fresh_seed_derives_from_the_freeze() -> None:
    assert RUN.fresh_seed({"freeze_sha256": "0000002a" + "f" * 56}) == 42


def test_evaluate_runs_once_and_needs_the_freeze(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(RUN, "load_frozen", lambda d: {"freeze_sha256": "ab" * 32})
    (tmp_path / "results").mkdir()
    (tmp_path / RUN.RESULT_FILE).write_text("{}")
    with pytest.raises(SystemExit, match="evaluated once"):
        RUN.cmd_evaluate(tmp_path)


def test_outcome_order() -> None:
    ok = {
        k: True
        for k in (
            "V1",
            "V4_over_escalations_down_20pct_overall",
            "V5_over_escalations_down_20pct_action_or_domain",
            "V8_beats_target_only_on_a_transfer_measure",
        )
    }
    assert RUN.outcome(ok, "favorable") == "GATE_PASSED_AWAITING_TELECOM_APPROVAL"
    assert RUN.outcome(ok, "inconclusive") == "INCONCLUSIVE_NEEDS_REAL_DATA"
    assert RUN.outcome(ok, "clear_regression") == "NO_SYNTHETIC_VALUE_OVER_RETAIL"
    assert RUN.outcome({**ok, "V1": False}, "favorable") == "STOP_MECHANISM_FAILED"
    assert RUN.outcome(
        {**ok, "V8_beats_target_only_on_a_transfer_measure": False}, "favorable"
    ) == ("STOP_LEARNED_ORG_MODEL_PATH")


def test_no_telecom_anywhere_in_v2() -> None:
    src = (Path(RUN.__file__).parent).glob("*.py")
    for path in src:
        text = path.read_text()
        assert "real_records" not in text and "final_eval=True" not in text, path.name
    seal = json.loads((V1 / "telecom-seal.json").read_text())
    assert not (V1 / "results" / "telecom-opened.json").exists()
    assert seal["counts"]["records"] == 35


def test_v1_freeze_still_verifies() -> None:
    if not (Path("runs/targeted.db").exists() and (V1 / "freeze.json").exists()):
        pytest.skip("needs the v1 stores and freeze")
    from hatchway.bench.drb.run import load_frozen

    load_frozen(V1)
