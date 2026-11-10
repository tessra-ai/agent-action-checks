"""Decision-record benchmark, Phase 0: generator, answer key, partitions, mapping, models,
controls and the telecom seal. No network, no judge, no store needed (committed experiment files
are read when present)."""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pytest

from hatchway.bench.drb import evaluate as E
from hatchway.bench.drb import model as M
from hatchway.bench.drb import partitions as P
from hatchway.bench.drb import realmap
from hatchway.bench.drb import seal as S
from hatchway.bench.drb import synthetic as G
from hatchway.bench.drb.schema import (
    CONCEPTS,
    NOT_APPLICABLE,
    ConceptValue,
    dataset_hash,
    from_json,
)
from hatchway.bench.drb.sources import AuthoritativeConcepts, JudgeConcepts, assert_one_source

EXP = Path(__file__).parents[1] / "experiments/2026-10-23-decision-record-benchmark"


@pytest.fixture(scope="module")
def syn():
    return P.assign_synthetic(G.generate(G.SEED), G.SEED)


@pytest.fixture(scope="module")
def fitted(syn):
    return E.fit_all(syn, [])


def valid(**over):
    base = {
        "actor_verified": True,
        "requested": True,
        "terms_disclosed": True,
        "consent": True,
        "owner_correct": True,
        "prerequisite_met": True,
        "impact": "low",
        "reversible": True,
        "evidence_clear": True,
        "prohibited": False,
        "channel": "chat",
        "tier": "gold",
        "weekday": "Monday",
    }
    return {**base, **over}


SPEC = G.spec_of("issue_refund")
NO_CONSENT_SPEC = G.spec_of("pause_campaign")


# --- Generation and hashes ---------------------------------------------------------------------


def test_regeneration_from_the_seed_is_identical(syn) -> None:
    again = P.assign_synthetic(G.generate(G.SEED), G.SEED)
    assert [r.record_hash for r in again] == [r.record_hash for r in syn]
    assert dataset_hash(again) == dataset_hash(syn)
    other = P.assign_synthetic(G.generate(G.SEED + 1), G.SEED + 1)
    assert dataset_hash(other) != dataset_hash(syn)


def test_record_hashes_round_trip_and_catch_edits(syn) -> None:
    r = syn[0]
    assert from_json(r.to_json()) == r
    edited = r.to_json()
    edited["verdict"] = "ALLOW" if r.verdict != "ALLOW" else "ASK"
    with pytest.raises(ValueError, match="hash"):
        from_json(edited)


def test_committed_synthetic_records_match_the_generator(syn) -> None:
    path = EXP / "synthetic-records.jsonl.gz"
    if not path.exists():
        pytest.skip("synthetic records not generated yet")
    from hatchway.bench.drb.run import read_records

    assert dataset_hash(read_records(path)) == dataset_hash(syn)
    manifest = json.loads((EXP / "synthetic-manifest.json").read_text())
    assert manifest["dataset_sha256"] == dataset_hash(syn)


# --- Answer key --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("latent", "profile", "verdict", "reason"),
    [
        (valid(prohibited=True), "P1", "DENY", "HARD_PROHIBITION"),
        (valid(owner_correct=False), "P1", "DENY", "OWNER_MISMATCH"),
        (valid(prerequisite_met=False), "P2", "DENY", "PREREQUISITE_MISSING"),
        (valid(requested=False), "P3", "DENY", "NOT_REQUESTED"),
        (valid(actor_verified=False), "P1", "ASK", "ACTOR_UNVERIFIED"),
        (valid(evidence_clear=False), "P1", "ASK", "EVIDENCE_CONTRADICTORY"),
        (valid(terms_disclosed=False), "P2", "ASK", "TERMS_NOT_DISCLOSED"),
        (valid(consent=False), "P1", "ASK", "CONSENT_MISSING"),
        (valid(consent=False, impact="high"), "P2", "ASK", "CONSENT_MISSING"),
        (valid(impact="high"), "P1", "ASK", "PROFILE_P1_ESCALATES"),
        (valid(reversible=False), "P2", "ASK", "PROFILE_P2_ESCALATES"),
        (valid(impact="high", reversible=False), "P3", "ASK", "PROFILE_P3_ESCALATES"),
    ],
)
def test_answer_key_branches(latent, profile, verdict, reason) -> None:
    v, reasons, hard = G.answer_key(latent, SPEC, profile)
    assert v == verdict and reason in reasons
    assert (hard is not None) == (reason == "HARD_PROHIBITION")


@pytest.mark.parametrize(
    ("latent", "profile"),
    [
        (valid(), "P1"),
        (valid(), "P2"),
        (valid(impact="high"), "P2"),  # reversible: P2 lets it run
        (valid(reversible=False), "P1"),  # low impact: P1 lets it run
        (valid(impact="high"), "P3"),
        (valid(consent=False), "P2"),  # waived: low impact, reversible
        (valid(consent=False), "P3"),
    ],
)
def test_answer_key_allows(latent, profile) -> None:
    assert G.answer_key(latent, SPEC, profile)[0] == "ALLOW"


def test_consent_does_not_apply_where_the_action_needs_none() -> None:
    assert G.answer_key(valid(consent=False, terms_disclosed=False), NO_CONSENT_SPEC, "P1")[0] == (
        "ALLOW"
    )


def test_profiles_cross() -> None:
    """The same grey-area case is decided differently by different organizations, both ways."""
    hi_rev = valid(impact="high", reversible=True)
    lo_irr = valid(impact="low", reversible=False)
    assert G.answer_key(hi_rev, SPEC, "P1")[0] == "ASK"
    assert G.answer_key(hi_rev, SPEC, "P2")[0] == "ALLOW"
    assert G.answer_key(lo_irr, SPEC, "P1")[0] == "ALLOW"
    assert G.answer_key(lo_irr, SPEC, "P2")[0] == "ASK"


def test_crossed_families_carry_different_labels(syn) -> None:
    crossed = [r for r in syn if "/x0/" in r.record_id and r.record_id.split("/")[-2] == "base"]
    by_family: dict[str, set[str]] = {}
    for r in crossed:
        by_family.setdefault(r.family_id, set()).add(r.verdict)
    assert by_family and all(len(v) == 2 for v in by_family.values())


def test_profiles_are_versioned_data() -> None:
    data = G.profiles()
    assert data["version"] == "drb-profiles-1"
    assert set(data["profiles"]) == {"P1", "P2", "P3"}


# --- Counterfactuals and rendering -------------------------------------------------------------


def test_counterfactuals_change_exactly_one_fact(syn) -> None:
    decision = set(G.FLIPS)
    by_key = {(r.family_id, r.record_id.split("/")[-2], r.org_profile): r for r in syn}
    seen = 0
    for (fam, variant, prof), r in by_key.items():
        if not variant.startswith("cf-"):
            continue
        base = by_key[(fam, "base", prof)]
        changed = {k for k in base.latent if base.latent[k] != r.latent[k]}
        assert changed == {variant[3:]} and changed <= decision
        seen += 1
        para = by_key[(fam, "paraphrase", prof)]
        assert para.latent == base.latent and para.evidence != base.evidence
        irr = by_key[(fam, "irrelevant", prof)]
        changed = {k for k in base.latent if base.latent[k] != irr.latent[k]}
        assert changed and changed <= {"channel", "tier", "weekday"}
        assert irr.verdict == base.verdict and irr.concepts == base.concepts
    assert seen >= 100


def test_rendered_evidence_matches_the_latent_facts(syn) -> None:
    for r in syn:
        assert G.validate_rendering(r, G.spec_of(r.action)) == [], r.record_id
    r = next(x for x in syn if x.latent["owner_correct"])
    wrong = dataclasses.replace(r, latent={**r.latent, "owner_correct": False})
    assert "owner_correct" in G.validate_rendering(wrong, G.spec_of(r.action))


def test_no_telecom_in_the_synthetic_world(syn) -> None:
    text = json.dumps(G.policy()["domains"]).lower()
    for word in ("telecom", "roaming", "refuel", "line", "phone"):
        assert word not in text
    assert {r.domain for r in syn} <= set(G.policy()["domains"])


# --- Coverage and partitions -------------------------------------------------------------------


def test_minimum_class_coverage(syn) -> None:
    main = [r for r in syn if r.split not in ("syn_hard", "syn_p3_adapt", "syn_p3_eval")]
    for _, action, _ in G.actions():
        rs = [r for r in main if r.action == action]
        assert sum(r.should_run for r in rs) >= 10, action
        assert sum(not r.should_run for r in rs) >= 10, action
        assert len({r.org_profile for r in rs}) > 1
        assert len({r.family_id for r in rs}) > 1
    for domain in G.policy()["domains"]:
        rs = [r for r in main if r.domain == domain]
        assert sum(r.should_run for r in rs) >= 10 and sum(not r.should_run for r in rs) >= 10
    for split in ("syn_final", "syn_holdout_action", "syn_holdout_domain", "syn_p3_eval"):
        rs = E.by_split(syn, split)
        assert sum(r.should_run for r in rs) >= 10, split
        assert sum(not r.should_run for r in rs) >= 10, split


def test_families_never_cross_partitions(syn) -> None:
    P.assert_family_isolation(syn)
    assert {r.split for r in syn} == set(P.SYNTHETIC_PARTITIONS)
    assert all(r.action == P.HELD_OUT_ACTION for r in E.by_split(syn, "syn_holdout_action"))
    assert all(r.domain == P.HELD_OUT_DOMAIN for r in E.by_split(syn, "syn_holdout_domain"))
    train = E.by_split(syn, "syn_pretrain", "syn_promotion")
    assert not {r.action for r in train} & {P.HELD_OUT_ACTION}
    assert not {r.domain for r in train} & {P.HELD_OUT_DOMAIN}
    assert not any(E.profile_of(r) == "P3" for r in train)
    assert all(r.hard_rule is not None for r in E.by_split(syn, "syn_hard"))
    assert not any(r.hard_rule for r in syn if r.split != "syn_hard")


def test_adaptation_subsets_are_nested(syn) -> None:
    subs = {k: P.adaptation_subset(syn, k) for k in P.ADAPT_K}
    assert [len(s) for s in subs.values()] == list(P.ADAPT_K)
    assert subs[5] == subs[10][:5] == subs[25][:5]


# --- Concepts and inputs -----------------------------------------------------------------------


def test_concepts_come_from_latent_facts_not_the_verdict(syn) -> None:
    r = next(x for x in syn if x.verdict == "ALLOW")
    relabelled = dataclasses.replace(r, verdict="DENY", reason_codes=("ANYTHING",))
    assert G.concepts_of(relabelled.latent, G.spec_of(r.action)) == r.concepts
    assert M.features(relabelled).tolist() == M.features(r).tolist()


def test_real_concepts_come_from_checks_not_the_verdict() -> None:
    checks = {
        "AUTHENTICATED": {"outcome": "pass"},
        "ORDER_DELIVERED": {"outcome": "pass"},
        "DETAILS_CONFIRMED": {"outcome": "pass"},
    }
    meta = {"impact": "financial", "reversible": "partly"}
    c = realmap.concepts_from_checks("return_delivered_order_items", checks, meta)
    assert c["consent_obtained"].state == "satisfied"
    assert c["ownership_authority"].evidence_ref == "check:ORDER_NOT_OWNED(not raised)"
    assert c["action_requested"].state == "unknown"  # no check establishes it
    assert c["potential_harm"].state == "not_satisfied"
    assert c["reversibility"].state == "not_satisfied" and c["reversibility"].confidence == 0.5
    roaming = realmap.concepts_from_checks(
        "enable_roaming", {}, {"impact": "service", "reversible": "yes"}
    )
    assert not roaming["consent_obtained"].applicable and not roaming["terms_disclosed"].applicable
    abroad = realmap.concepts_from_checks(
        "disable_roaming",
        {"CUSTOMER_ABROAD": {"outcome": "deny"}},
        {"impact": "service", "reversible": "yes"},
    )
    assert abroad["potential_harm"].state == "not_satisfied"
    assert realmap.hard_rule_of({"AMOUNT_OVER_LIMIT": {"outcome": "deny"}}) == "AMOUNT_OVER_LIMIT"
    assert realmap.hard_rule_of({"WRONG_LINE": {"outcome": "deny"}}) is None


def test_not_applicable_is_never_satisfied_and_differs_from_unknown() -> None:
    with pytest.raises(ValueError):
        ConceptValue(False, "satisfied", 1.0)
    rec = next(r for r in G.generate(G.SEED) if r.action == "pause_campaign")
    x = dict(zip(M.FEATURE_NAMES, M.features(rec), strict=True))
    assert rec.concepts["consent_obtained"] == NOT_APPLICABLE
    assert all(x[f"consent_obtained:{p}"] == 0 for p in ("satisfied", "not_satisfied", "unknown"))
    unknown = dataclasses.replace(
        rec, concepts={**rec.concepts, "actor_identified": ConceptValue(True, "unknown", 0.0)}
    )
    xu = dict(zip(M.FEATURE_NAMES, M.features(unknown), strict=True))
    assert xu["actor_identified:unknown"] == 1 and xu["actor_identified:satisfied"] == 0
    # DC never treats an unknown or an inapplicable concept as satisfied.
    assert not M.dc_allows(unknown)


def test_primary_inputs_carry_no_identity(syn) -> None:
    for name in M.FEATURE_NAMES:
        concept, part = name.split(":")
        assert concept in CONCEPTS
        assert part in ("satisfied", "not_satisfied", "unknown", "signed_confidence")
    r = syn[0]
    moved = dataclasses.replace(
        r,
        action="some_other_action",
        domain="elsewhere",
        family_id="other",
        org_profile="P9@x",
        record_id="other",
        reason_codes=("X",),
        verdict="DENY",
    )
    assert M.features(moved).tolist() == M.features(r).tolist()


def test_one_concept_source_per_run() -> None:
    assert assert_one_source([AuthoritativeConcepts(), AuthoritativeConcepts()]) == "authoritative"
    with pytest.raises(ValueError):
        assert_one_source([AuthoritativeConcepts(), JudgeConcepts()])
    with pytest.raises(NotImplementedError):
        JudgeConcepts().concepts(G.generate(G.SEED)[0])


# --- Models ------------------------------------------------------------------------------------


def test_pretraining_and_adaptation_are_reproducible(syn) -> None:
    a, b = E.fit_all(syn, []), E.fit_all(syn, [])
    assert a.g_syn.version == b.g_syn.version
    assert a.p3[25]["G-combined"].version == b.p3[25]["G-combined"].version


def test_retail_adaptation_is_reproducible() -> None:
    path = EXP / "retail-records.jsonl.gz"
    if not path.exists():
        pytest.skip("retail records not mapped yet")
    from hatchway.bench.drb.run import read_records

    retail = read_records(path)
    syn = P.assign_synthetic(G.generate(G.SEED), G.SEED)
    a, b = E.fit_all(syn, retail), E.fit_all(syn, retail)
    assert a.g_comb_retail.version == b.g_comb_retail.version
    assert a.g_retail.version == b.g_retail.version
    assert not {r.record_id for r in retail} & S.sealed_ids(S.load_seal(EXP / "telecom-seal.json"))


def test_thresholds_ignore_final_holdouts(syn, fitted) -> None:
    """Flipping every label in the final, held-out action and held-out domain partitions
    changes no fitted model."""
    flipped = [
        dataclasses.replace(r, verdict="ALLOW" if r.verdict != "ALLOW" else "ASK").sealed()
        if r.split in ("syn_final", "syn_holdout_action", "syn_holdout_domain", "syn_p3_eval")
        and r.hard_rule is None
        else r
        for r in syn
    ]
    again = E.fit_all(flipped, [])
    assert again.g_syn.version == fitted.g_syn.version
    assert {k: m.version for k, m in again.g_comb.items()} == {
        k: m.version for k, m in fitted.g_comb.items()
    }


def test_threshold_rule() -> None:
    assert M.select_threshold([(0.9, True), (0.8, True), (0.7, False), (0.6, True)]) == 0.8
    assert math.isinf(M.select_threshold([(0.9, False), (0.8, True)]))
    assert math.isinf(M.select_threshold([]))


def test_hard_deny_is_never_overridden(syn) -> None:
    allow_all = M.Model("allow-all", "g", M.Coefficients.zero(), threshold=-1.0)
    hard = E.by_split(syn, "syn_hard")
    assert hard
    for r in hard:
        assert allow_all.allows(r)  # the model would run it...
        assert M.decide(allow_all, r) == (
            "ESCALATE",
            f"hard_rule:{r.hard_rule}",
        )  # ...the rule wins


# --- Controls ----------------------------------------------------------------------------------


def test_negative_controls_show_no_apparent_transfer(syn) -> None:
    for relabel in (G.shuffled_labels, G.no_shared_effect):
        world = relabel(syn, 99)
        gate = E.internal_gate(world, E.fit_all(world, []))
        assert not gate["apparent_transfer"], relabel.__name__


def test_no_shared_effect_world_has_no_shared_rule(syn) -> None:
    world = G.no_shared_effect(syn, 99)
    assert [r.hard_rule for r in world] == [r.hard_rule for r in syn]
    assert any(a.verdict != b.verdict for a, b in zip(world, syn, strict=True))


def test_structural_controls(syn, fitted) -> None:
    out = E.controls_structural(syn, fitted)
    assert out["paraphrase"]["same_decision"] == out["paraphrase"]["pairs"] > 0
    assert out["irrelevant_context"]["same_decision"] == out["irrelevant_context"]["pairs"]


# --- Telecom stays sealed ----------------------------------------------------------------------


def test_telecom_loads_only_in_final_eval() -> None:
    from hatchway.bench.drb.realdata import real_records

    seal = S.load_seal(EXP / "telecom-seal.json")
    with pytest.raises(S.TelecomSealed):
        real_records("telecom", {}, None, "x", "o", {}, lambda d, t: "f", seal)  # type: ignore[arg-type]


def test_final_eval_refuses_when_the_gate_failed(tmp_path: Path, monkeypatch) -> None:
    from hatchway.bench.drb import run as R

    monkeypatch.setattr(R, "load_frozen", lambda d: {})
    (tmp_path / "results").mkdir()
    (tmp_path / R.DEVELOP_FILE).write_text(
        json.dumps({"gate": {"passed": False}, "outcome_so_far": "STOP_MECHANISM_FAILED"})
    )
    with pytest.raises(SystemExit, match="telecom stays sealed"):
        R.cmd_final_eval(tmp_path)
    assert not (tmp_path / "results" / S.OPENED_FILE).exists()
