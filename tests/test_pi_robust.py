"""Policy-induction robustness pack: split, rule grammar, audits, specific certified exceptions,
perception noise and run guards. No network, no model calls."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from hatchway.bench.pi import cases as C
from hatchway.bench.pi import evaluate as E
from hatchway.bench.pi import induce as S
from hatchway.bench.pi import robust as R
from hatchway.bench.pi.worlds import BY_NAME

needs_tau2 = pytest.mark.skipif(
    not (C.retail_dir() / "db.json").exists(), reason="needs τ² retail data"
)


@pytest.fixture(scope="module")
def sample():
    db = C.load_db()
    out: list[C.Case] = []
    for oid in sorted(db["orders"])[:300]:
        out += C.family_cases(db, oid, seed=1)
    return out


def test_three_way_split_is_fixed_and_proportioned() -> None:
    ids = [f"#W{i:07d}" for i in range(2000)]
    parts = [R.split3(f) for f in ids]
    assert parts == [R.split3(f) for f in ids]
    share = {p: parts.count(p) / len(parts) for p in ("train", "cert", "test")}
    assert (
        0.35 < share["train"] < 0.45 and 0.15 < share["cert"] < 0.25 and 0.35 < share["test"] < 0.45
    )


def test_rule_specs_round_trip_into_worlds() -> None:
    spec = {
        "name": "x",
        "kind": "escalate",
        "action": R.RETURN,
        "conds": [{"fact": "amount", "op": "gt", "value": 100.0}],
    }
    w = R.rule_world(spec)
    allow = C.Case("a", "f", R.RETURN, "v", "ALLOW", (), {"amount": 150.0, "products": ()}, "")
    small = C.Case("b", "f", R.RETURN, "v", "ALLOW", (), {"amount": 50.0, "products": ()}, "")
    other = C.Case("c", "f", R.CANCEL, "v", "ALLOW", (), {"amount": 150.0, "products": ()}, "")
    assert w.truth(allow) == "ASK" and w.truth(small) == "ALLOW" and w.truth(other) == "ALLOW"
    relax = {**spec, "kind": "relax"}
    ask = C.Case(
        "d",
        "f",
        R.RETURN,
        "v",
        "ASK",
        (("CONFIRMATION_MISSING", "ask"),),
        {"amount": 150.0, "products": ()},
        "",
    )
    assert R.rule_world(relax).truth(ask) == "ALLOW"
    assert "amount > 100.0" in R.describe_spec(spec)


@needs_tau2
def test_sampled_rules_pass_the_preregistered_filter(sample) -> None:
    rules = R.sample_rules(sample)
    assert rules and rules == R.sample_rules(sample)
    for spec in rules:
        assert spec["train_families"] >= R.MIN_TRAIN_FAMILIES
        assert spec["trigger_share"] <= R.MAX_TRIGGER_SHARE
    assert len({spec["name"] for spec in rules}) == len(rules)


def test_specialized_exception_covers_only_what_its_positives_share() -> None:
    facts = []
    rng = random.Random(0)
    for i in range(200):
        facts.append(
            {
                **{f: False for f in S.BOOL_FACTS},
                "confirmation_missing": True,
                "action": "cancel_pending_order",
                "payment_source": rng.choice(("paypal", "credit_card")),
                "user_state": rng.choice(("CA", "TX")),
                **{f: round(rng.uniform(0, 1000), 2) for f in S.NUM_FACTS},
                "products": (),
            }
        )
        facts[-1]["auth_missing"] = i % 4 == 0
    cols = S.Columns(facts)
    positives = np.array([f["order_total"] < 300 and not f["auth_missing"] for f in facts])
    broad = S.Rule("allow", (S.Literal("order_total", "le", 300.0),), 0, 0, -10.0)
    spec = R.specialize(broad, cols, positives)
    assert S.Literal("auth_missing", "is", False) in spec.literals
    assert not (spec.mask(cols) & ~positives).any()


def test_certification_needs_enough_clean_families() -> None:
    n = 40
    cols = S.Columns(
        [
            {
                **{f: False for f in S.BOOL_FACTS},
                "action": "a",
                "payment_source": "x",
                "user_state": "s",
                **{f: 1.0 for f in S.NUM_FACTS},
                "products": (),
            }
            for _ in range(n)
        ]
    )
    rule = S.Rule("allow", (S.Literal("action", "eq", "a"),), 0, 0, -10.0)
    yes = np.ones(n, dtype=bool)
    fam = np.array([f"f{i}" for i in range(n)], dtype=object)
    ok, info = R.certify(rule, cols, yes, yes, np.zeros(n, dtype=bool), fam)
    assert ok and info["eligible_families"] == n
    one_family = np.array(["f0"] * n, dtype=object)
    few, _ = R.certify(rule, cols, yes, yes, np.zeros(n, dtype=bool), one_family)
    assert not few
    bad = np.zeros(n, dtype=bool)
    bad[0] = True
    failed, _ = R.certify(rule, cols, yes, yes, bad, fam)
    assert not failed


@needs_tau2
def test_audits_always_include_escalated_cases_and_respect_the_budget(sample) -> None:
    p = E.Prepared(BY_NAME["H1_LARGE_REFUND"], sample)
    m = R.masks(p)
    rng = random.Random(0)
    s = E.training_sample(p, m["train"], 5, rng)
    assert s is not None
    y = p.truth[np.array(s)]
    allowed = sum(not p.r0[i] for i in s)
    for strategy in ("random", "targeted"):
        seen = R.audited(p, s, 0.25, strategy, random.Random(1), y)
        assert {j for j, i in enumerate(s) if p.r0[i]} <= set(seen)
        assert len(seen) - sum(p.r0[i] for i in s) == round(0.25 * allowed)


@needs_tau2
def test_noise_changes_only_learner_facts(sample) -> None:
    noisy = R.noisy_facts(sample, 0.10)
    assert noisy == R.noisy_facts(sample, 0.10)
    changed = sum(n != dict(c.facts) for n, c in zip(noisy, sample, strict=True))
    assert 0 < changed < len(sample)
    assert R.noisy_facts(sample, 0.0) == [dict(c.facts) for c in sample]
    p = R.NoisyPrepared(BY_NAME["C_AUTH"], sample, noisy)
    assert (p.truth == E.Prepared(BY_NAME["C_AUTH"], sample).truth).all()


def test_evaluate_runs_once(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / R.RESULT_FILE).write_text("{}")
    with pytest.raises(SystemExit, match="written once"):
        R.cmd_evaluate(tmp_path)


def test_phase_a_files_are_untouched() -> None:
    """The robustness pack must not change any file whose hash Phase A froze."""
    import json

    from hatchway.bench.pi import run as RUN

    manifest = json.loads((RUN.EXPERIMENT / RUN.MANIFEST).read_text())
    now = RUN.code_hashes()
    assert {f: now[f] for f in manifest["code_sha256"]} == manifest["code_sha256"]
