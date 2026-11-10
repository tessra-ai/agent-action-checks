"""Decision-model pilot (Phase 0): concepts, frozen arms, the sealed split, promotion, gates and
the synthetic verification of the transfer analysis. No network, no real store."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from hatchway.bench import BenchStore
from hatchway.bench.pilot import analysis as A
from hatchway.bench.pilot import arms, concepts, data, run
from hatchway.bench.pilot.arms import FittedArm, Row
from hatchway.bench.pilot.concepts import CONCEPTS, ConceptAssessment, assess
from hatchway.bench.pilot.synthetic import planted_rows
from hatchway.bench.score import score_store
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.judges.base import ChoiceAnswer
from hatchway.judges.runner import RetryPolicy
from hatchway.policy import Kind, load_policy

POLICY = load_policy(DEFAULT_POLICY)
J = arms.PRIMARY_JUDGE


def row(
    i: int,
    label: int | None,
    *,
    action: str = "a",
    domain: str = "retail",
    family: str | None = None,
    assessment: float = 0.9,
    applicable: float = 1.0,
    reasons: tuple[str, ...] = (),
) -> Row:
    vector = {
        c: ConceptAssessment(c, applicable, assessment if applicable >= 0.5 else None, 0.8)
        for c in CONCEPTS
    }
    return Row(
        write_id=f"w{i}",
        family=family or f"f{i}",
        domain=domain,
        action=action,
        order=(i,),
        label=label,
        verdict={1: "ALLOW", 0: "DENY", None: "UNKNOWN"}[label],
        impact="financial",
        reversible="partly",
        concepts={J: vector},
        baseline={J: {"policy_ok": assessment, "matches_request": assessment}},
        reason_codes=reasons,
    )


class Fixed(FittedArm):
    """An arm with set decisions per write id (ASK otherwise)."""

    def __init__(self, name: str, allow: set[str]) -> None:
        super().__init__(name, J, 0.5, f"{name}:fixed")
        self.allow = allow

    def score(self, r: Row) -> float | None:
        return 1.0 if r.write_id in self.allow else 0.0


# --- Concepts -------------------------------------------------------------------------------------


def test_one_template_per_concept_for_every_write_action() -> None:
    rubrics = concepts.rubrics(POLICY)
    writes = {n for n, a in POLICY.actions.items() if a.kind is Kind.WRITE}
    assert set(rubrics) == writes
    texts = {}
    for action, (questions, h) in rubrics.items():
        assert h.startswith("pilot-concepts-1:")
        assert [q.name for q in questions] == [
            *(concepts.PREFIX + c for c in CONCEPTS),
            "policy_ok",
            "matches_request",
        ]
        description = POLICY.actions[action].metadata.description
        for q in questions[: len(CONCEPTS)]:
            assert q.options == concepts.OPTIONS
            texts.setdefault(q.name, set()).add(q.text.replace(description, "<action>"))
    # The same words for every action, once the action's own description is taken out.
    assert all(len(t) == 1 for t in texts.values())
    # A rubric hash never collides with a policy rubric hash.
    assert not {h for _, h in rubrics.values()} & {
        a.rubric_hash for a in POLICY.actions.values() if a.kind is Kind.WRITE
    }


def test_not_applicable_is_never_satisfied() -> None:
    na = assess(ChoiceAnswer(probs={"met": 0.02, "not_met": 0.01, "not_applicable": 0.97}), "c")
    assert na.applicable == pytest.approx(0.03)
    assert na.assessment is None  # missing, not "met"
    r = row(1, 1, applicable=0.03)
    x = arms.g1_inputs(r)
    feats = dict(zip(arms.G1_FEATURES, x, strict=True))
    for c in CONCEPTS:
        assert feats[f"{c}:assessed"] == 0.0 and feats[f"{c}:missing"] == 1.0
    # DC: no applicable concept scores 0, so it escalates whatever the threshold.
    assert arms.dc_score(r) == 0.0
    dc = FittedArm("DC", J, 0.01, "DC:t")
    assert dc.decide(r) == "ASK"


def test_dc_takes_the_weakest_applicable_correctness_concept() -> None:
    r = row(1, 1)
    vec = dict(r.concepts[J])
    vec["consent_obtained"] = ConceptAssessment("consent_obtained", 1.0, 0.2, 0.9)
    vec["terms_disclosed"] = ConceptAssessment("terms_disclosed", 0.1, None, 0.9)
    vec["reversible"] = ConceptAssessment("reversible", 1.0, 0.0, 0.9)  # stakes, not correctness
    r = dataclasses.replace(r, concepts={J: vec})
    assert arms.dc_score(r) == pytest.approx(0.2)


def test_confidence_is_one_minus_normalized_entropy() -> None:
    sure = assess(ChoiceAnswer(probs={"met": 1.0, "not_met": 0.0, "not_applicable": 0.0}), "c")
    even = assess(ChoiceAnswer(probs={o: 1 / 3 for o in concepts.OPTIONS}), "c")
    assert sure.confidence == pytest.approx(1.0) and even.confidence == pytest.approx(0.0)
    assert sure.evidence is None  # no judge returns a span; never an input


# --- G1 is frozen and sees shared concepts only ---------------------------------------------------


def test_g1_inputs_are_shared_concepts_only() -> None:
    writes = [n for n, a in POLICY.actions.items() if a.kind is Kind.WRITE]
    arms.assert_g1_inputs(arms.G1_FEATURES, writes)
    assert len(arms.G1_FEATURES) == 4 * len(CONCEPTS) + 6
    for extra in ("action=refuel_data", "domain=retail", "policy_ok", "price_confirmed"):
        with pytest.raises(AssertionError):
            arms.assert_g1_inputs([*arms.G1_FEATURES, extra], writes)


def test_g1_decisions_ignore_action_and_domain_identity() -> None:
    rows = planted_rows(120, seed=3)
    g1 = arms.fit_g1(rows)
    assert g1.model is not None
    for r in rows[:30]:
        moved = dataclasses.replace(r, action="never_seen", domain="elsewhere", family="x")
        assert g1.score(moved) == g1.score(r)


def test_the_frozen_specs_are_pinned() -> None:
    """A change to D, DC or G1 changes this hash: freeze a new pilot, never edit a frozen one."""
    assert arms.spec_hash() == arms.spec_hash(json.loads(json.dumps(arms.PILOT_SPECS)))
    assert arms.G1_SPEC["inputs"] == list(arms.G1_FEATURES)
    assert arms.HARD_RULES == ()  # no deterministic prohibition exists for τ² before M8


def test_cold_start_escalates_everything() -> None:
    for a in arms.PRIMARY_ARMS:
        fitted = arms.fit_arm(a, [row(1, 1), row(2, 1)])
        assert fitted.threshold is None or a == "G1"
        assert fitted.decide(row(3, 1)) == "ASK"


# --- Split and holdout seal -----------------------------------------------------------------------


def candidates(n_families: int = 12) -> list[data.Candidate]:
    out = []
    for f in range(n_families):
        domain = "retail" if f % 2 else "telecom"
        for k in range(1 + f % 3):
            out.append(
                data.Candidate(
                    f"w{f}-{k}", "s", "sess", k, f"t{f}", domain, str(f), "a", f"fam{f}", "h"
                )
            )
    return out


def test_split_is_label_free_disjoint_deterministic_and_sealed() -> None:
    cands = candidates()
    split = data.freeze_split(cands, seed=5)
    assert split == data.freeze_split(cands, seed=5)
    revealed, promotion = set(split["revealed"]), set(split["promotion"])
    held = set(split["holdout"]["family_sha256"])
    assert not revealed & promotion
    assert not {data.family_hash(f) for f in revealed | promotion} & held
    assert len(revealed) + len(promotion) + len(held) == 12
    # The holdout is stored only as salted hashes.
    text = json.dumps(split["holdout"])
    assert not any(f'"fam{i}"' in text for i in range(12))
    for domain in ("retail", "telecom"):
        assert all(split["by_domain"][domain]["datasets"][s]["families"] >= 1 for s in data.SPLITS)
    with pytest.raises(data.HoldoutSealed):
        data.in_scope(cands, split, "holdout")
    held_rows = data.in_scope(cands, split, "holdout", final_eval=True)
    assert {data.family_hash(c.family) for c in held_rows} == held
    seen = data.in_scope(cands, split, "revealed") + data.in_scope(cands, split, "promotion")
    assert not {c.write_id for c in seen} & {c.write_id for c in held_rows}


def test_a_stale_split_is_refused() -> None:
    cands = candidates()
    split = data.freeze_split(cands, seed=5)
    extra = dataclasses.replace(cands[0], write_id="new", family="unseen")
    with pytest.raises(ValueError, match="in no dataset"):
        data.in_scope([*cands, extra], split, "revealed")


def test_final_eval_writes_once(tmp_path: Path) -> None:
    run.write_once(tmp_path / "final.json", {"a": 1})
    with pytest.raises(SystemExit, match="written once"):
        run.write_once(tmp_path / "final.json", {"a": 2})


def test_final_eval_refuses_a_second_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run, "load", lambda d: {"definition_sha256": "x"})
    (tmp_path / run.FINAL).write_text("{}")
    with pytest.raises(SystemExit, match="already run"):
        run.cmd_final_eval(tmp_path)
    # And the analyses before it are closed once it has run.
    with pytest.raises(SystemExit, match="closed"):
        run.cmd_analyze(tmp_path)


# --- Promotion ------------------------------------------------------------------------------------


def test_a_challenger_with_more_false_allows_is_never_promoted() -> None:
    promo = [row(i, 0) for i in range(5)] + [row(i, 1) for i in range(5, 15)]
    champion = Fixed("champ", {f"w{i}" for i in range(5, 10)})
    riskier = Fixed("risky", {"w0", *(f"w{i}" for i in range(5, 15))})  # 1 false allow
    ok, reason = A.should_promote(A.outcomes(riskier, promo), A.outcomes(champion, promo))
    assert not ok and "more false allows" in reason
    better = Fixed("better", {f"w{i}" for i in range(5, 13)})
    assert A.should_promote(A.outcomes(better, promo), A.outcomes(champion, promo))[0]
    same = Fixed("same", {f"w{i}" for i in range(5, 10)})
    assert not A.should_promote(A.outcomes(same, promo), A.outcomes(champion, promo))[0]


def test_promotion_run_logs_versions_and_rollback_is_exact() -> None:
    rows = planted_rows(200, seed=4)
    revealed, promo = rows[:140], rows[140:]
    log, registry = A.promotion_run(revealed, promo, every=20)
    assert len(log) == 7
    promoted = [v for v in log if v.promoted]
    assert len(registry.history) == 1 + len(promoted)
    # Every promotion was no less safe than the champion it replaced.
    champion_fa = A.outcomes(A.escalate_all(), promo).false_allows
    for v in log:
        if v.promoted:
            assert v.promotion_false_allows <= champion_fa
            champion_fa = v.promotion_false_allows
    if len(registry.history) >= 2:
        expected = [registry.history[-2].decide(r) for r in promo]
        assert [registry.rollback().decide(r) for r in promo] == expected
    with pytest.raises(ValueError):
        A.Registry(A.escalate_all()).rollback()


# --- Safety gates ---------------------------------------------------------------------------------


def test_safety_gates_are_disaggregated_with_inconclusive_groups() -> None:
    rows = (
        [row(i, 0, action="big", domain="retail") for i in range(4)]
        + [row(i, 1, action="big", domain="retail") for i in range(4, 12)]
        + [row(i, 0, action="small", domain="telecom") for i in range(12, 14)]
        + [row(i, 1, action="small", domain="telecom") for i in range(14, 16)]
    )
    safe = {f"w{i}" for i in range(4, 12)}
    d, dc = Fixed("D", safe), Fixed("DC", safe)
    # G1 is as safe overall... except one more false allow on the small action only.
    g1 = Fixed("G1", safe | {"w12"})
    gates = A.safety_gates({"D": d, "DC": dc, "G1": g1}, rows)
    g = gates["groups"]
    assert g["action:small"]["gate"] == "insufficient: inconclusive"
    assert g["domain:telecom"]["gate"] == "insufficient: inconclusive"
    assert g["action:big"]["gate"] == "pass"
    assert g["overall"]["gate"] == "fail"  # 1 false allow overall vs 0
    assert not gates["passed"]
    assert g["overall"]["G1"]["false_allow_rate"] == {"n": 1, "of": 6, "rate": 1 / 6}
    good = A.safety_gates({"D": d, "DC": dc, "G1": Fixed("G1", safe)}, rows)
    assert good["passed"]


# --- Synthetic verification (never evidence) ------------------------------------------------------


def _held_out_auc(rows: list[Row]) -> float:
    revealed = [r for r in rows if int(r.family.rsplit("-", 1)[1]) % 10 < 6]
    holdout = [r for r in rows if r not in revealed]
    t = A.transfer(revealed, holdout)
    values = [e["arms"]["G1"]["action_held_out_auc"] for e in t.values()]
    return sum(values) / len(values)


def test_transfer_is_found_when_planted() -> None:
    assert _held_out_auc(planted_rows(300, seed=1)) > 0.8


def test_transfer_is_not_found_when_absent() -> None:
    assert _held_out_auc(planted_rows(300, seed=1, effect=False)) < 0.65


def test_adaptation_marks_concepts_without_corrections_inconclusive() -> None:
    rows = planted_rows(150, seed=2)
    orders = A.family_orderings({r.family for r in rows}, 3, seed=1)
    out = A.adaptation(rows, orders, ["consent_obtained", "reversible"])
    assert out["reversible"]["status"] == "insufficient: inconclusive"
    assert out["consent_obtained"]["status"] == "measured"
    measured = out["consent_obtained"]["arms"]["G1"]
    assert {"before:should_run", "after:should_run"} <= set(measured)


def test_learning_curve_reports_a_distribution_over_orderings() -> None:
    rows = planted_rows(60, seed=5)
    orders = A.family_orderings({r.family for r in rows}, 4, seed=2)
    curve = A.learning_curve(rows, orders)
    assert curve["checkpoints"] == [10, 25, 50, 60]
    first = curve["arms"]["G1"][0]
    assert set(first["false_allows"]) == {"median", "min", "max", "p10", "p90"}


# --- Scoring the pilot rubric ---------------------------------------------------------------------


def test_pilot_rubric_scoring_is_resumable(tmp_path: Path) -> None:
    from tests.test_bench_score import REQUEST, FakeJudge

    with BenchStore(tmp_path / "b.db") as store:
        w = store.record_write(
            session_id="s1",
            action="cancel_pending_order",
            args={"order_id": "#W1", "reason": "ordered by mistake"},
            context={"conversation": REQUEST, "policy": "p"},
            rubric_hash="an-older-policy-rubric",
            domain="retail",
            task_id="0",
            trial=0,
        )
        rubrics = concepts.rubrics(POLICY)
        judge = FakeJudge("openai_decisions", "luna")
        kwargs = {"rubrics": rubrics, "write_ids": {w.write_id}, "retry": RetryPolicy(1)}
        asyncio.run(score_store(store, POLICY, [judge], **kwargs))
        assert sum(judge.calls.values()) == 1
        asyncio.run(score_store(store, POLICY, [judge], **kwargs))
        assert sum(judge.calls.values()) == 1  # a rerun makes no call
        rec = store.get_score(
            w.state_hash, rubrics["cancel_pending_order"][1], "openai_decisions", "luna"
        )
        assert rec is not None and rec.status == "ok"
        assert set(concepts.concept_vector(rec.question_vector)) == set(CONCEPTS)
