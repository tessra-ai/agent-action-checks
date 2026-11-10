"""Policy-induction benchmark: generator, worlds, rule induction, controls and run guards.
No network and no model calls. Generator tests need τ² retail data and skip without it."""

from __future__ import annotations

import ast
import json
import random
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import hypergeom

from hatchway.bench.pi import cases as C
from hatchway.bench.pi import evaluate as E
from hatchway.bench.pi import induce as S
from hatchway.bench.pi import llm
from hatchway.bench.pi import run as RUN
from hatchway.bench.pi.worlds import BY_NAME, WORLDS, combine, escalates, reduced_policy

HAVE_TAU2 = (C.retail_dir() / "db.json").exists()
needs_tau2 = pytest.mark.skipif(not HAVE_TAU2, reason="needs τ² retail data")


@pytest.fixture(scope="module")
def db():
    return C.load_db()


@pytest.fixture(scope="module")
def sample(db):
    """Cases of the first 120 orders (development: generator seed 1)."""
    out: list[C.Case] = []
    for oid in sorted(db["orders"])[:120]:
        out += C.family_cases(db, oid, seed=1)
    return out


# --- Generator ---------------------------------------------------------------------------------


@needs_tau2
def test_generator_is_deterministic(db) -> None:
    oid = sorted(db["orders"])[3]
    a, b = C.family_cases(db, oid), C.family_cases(db, oid)
    assert [x.to_json() for x in a] == [x.to_json() for x in b]
    assert C.dataset_sha256(a) == C.dataset_sha256(b)


@needs_tau2
def test_single_factor_variants_get_the_oracle_verdict_they_should(sample) -> None:
    # Families whose base proposal is already DENY (an exchange the gift card cannot cover)
    # stay DENY in every variant; leave them out.
    denied = {c.family_id for c in sample if c.variant == "base" and c.decision == "DENY"}
    by_variant: dict[str, set[str]] = {}
    for c in sample:
        if c.family_id not in denied:
            by_variant.setdefault(c.variant, set()).add(c.decision)
    assert by_variant["base"] == {"ALLOW"}
    assert by_variant["auth=missing"] <= {"ASK", "DENY"}
    assert by_variant["auth=other"] == {"DENY"}
    assert by_variant["status=wrong"] == {"DENY"}
    assert by_variant["confirm=missing"] <= {"ASK", "DENY"}
    assert by_variant["threat=yes"] == {"ALLOW"}
    assert not any(c.decision == "UNKNOWN" for c in sample)


@needs_tau2
def test_the_threat_is_never_a_fact(sample) -> None:
    threatened = [c for c in sample if "threat=yes" in c.variant]
    assert threatened and all(any(t in c.text for t in C.THREATS) for c in threatened)
    for c in sample:
        assert not any(t in str(v) for v in c.facts.values() for t in C.THREATS)
    cols = S.Columns([c.facts for c in sample], [c.text for c in sample])
    assert not any(lit.op == "word" for lit in S.candidate_literals(cols))
    assert any(lit.op == "word" for lit in S.candidate_literals(cols, text=True))


def test_family_split_is_a_fixed_hash() -> None:
    ids = [f"#W{i:07d}" for i in range(400)]
    first = [E.is_train(f) for f in ids]
    assert first == [E.is_train(f) for f in ids]
    assert 0.4 < sum(first) / len(first) < 0.6


# --- Worlds ------------------------------------------------------------------------------------


@needs_tau2
def test_removing_a_clause_changes_only_the_cases_it_decides(sample) -> None:
    for w in WORLDS:
        if w.kind != "ablation":
            continue
        for c in sample:
            if w.triggers(c):
                assert set(c.failing()) & set(w.removed_codes), (w.name, c.case_id)
            if not set(c.failing()) & set(w.removed_codes):
                assert w.r0(c) == c.decision


@needs_tau2
def test_hidden_rules_are_not_in_the_written_policy() -> None:
    text = C.load_policy().lower()
    for word in (
        "chargeback",
        "dispute",
        "fraud",
        "jigsaw",
        "2,000",
        "2000",
        "$25",
        "$300",
        "$500",
    ):
        assert word not in text, word
    for threat in C.THREATS:
        assert threat.lower() not in text


@needs_tau2
def test_reduced_policies_remove_exactly_their_clause() -> None:
    text = C.load_policy()
    for w in WORLDS:
        reduced = reduced_policy(text, w)
        if w.kind == "hidden":
            assert reduced == text
            continue
        assert reduced != text
        for old, new in w.removed_text:
            assert old not in reduced or old in new


def test_learning_never_relaxes_a_deny() -> None:
    w = BY_NAME["H6_SMALL_CANCEL_WAIVER"]
    deny = C.Case(
        "x", "f", "cancel_pending_order", "v", "DENY", (("INVALID_REASON", "deny"),), {}, ""
    )
    ask = C.Case(
        "y", "f", "cancel_pending_order", "v", "ASK", (("CONFIRMATION_MISSING", "ask"),), {}, ""
    )
    assert not w.r0_relaxable(deny) and w.r0_relaxable(ask)
    assert combine({"a": "ask", "b": "deny"}) == "DENY" and escalates("ASK")


# --- Rule induction ----------------------------------------------------------------------------


def test_tail_table_matches_scipy() -> None:
    for n_pool, p_pool in ((60, 10), (300, 40), (5, 5), (7, 0)):
        table = S.log_tail_table(n_pool, p_pool)
        for n in range(n_pool + 1):
            for x in range(min(n, p_pool) + 1):
                ref = hypergeom.logsf(x - 1, n_pool, p_pool, n)
                assert table[n, x] == pytest.approx(ref, abs=1e-8) or (
                    np.isinf(ref) and np.isinf(table[n, x])
                )


def _toy(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(
            {
                **{f: rng.random() < 0.2 for f in S.BOOL_FACTS},
                "action": rng.choice(("a", "b", "c")),
                "payment_source": rng.choice(("paypal", "credit_card")),
                "user_state": rng.choice(("CA", "TX", "NY")),
                **{f: round(rng.uniform(0, 3000), 2) for f in S.NUM_FACTS},
                "products": (rng.choice(("P", "Q", "R")),),
            }
        )
    return out


def test_a_planted_rule_is_recovered_and_readable() -> None:
    facts = _toy(400, 1)
    cols = S.Columns(facts)
    r0 = np.zeros(len(facts), dtype=bool)
    y = np.array([f["amount"] > 2000 and f["action"] == "a" for f in facts])
    learned = S.learn(cols, r0, r0.copy(), y)
    assert len(learned.rules) == 1
    probe = S.Columns(_toy(2000, 2))
    want = np.array([f["amount"] > 2000 and f["action"] == "a" for f in _toy(2000, 2)])
    got = learned.decide(probe, np.zeros(probe.n, dtype=bool), np.zeros(probe.n, dtype=bool))
    assert (got == want).mean() > 0.99
    assert "amount >" in learned.rules[0].describe()


def test_random_labels_accept_no_rule() -> None:
    accepted = 0
    for seed in range(20):
        facts = _toy(300, 100 + seed)
        rng = np.random.default_rng(seed)
        y = rng.random(len(facts)) < 0.3
        r0 = np.zeros(len(facts), dtype=bool)
        accepted += bool(S.learn(S.Columns(facts), r0, r0.copy(), y).rules)
    assert accepted <= 1


def test_selection_only_labels_escalated_or_audited_cases() -> None:
    class P:
        r0 = np.array([True] * 50 + [False] * 950)
        truth = r0.copy()

    idx = list(range(1000))
    kept, y = E.apply_condition(P, idx, "selection", random.Random(0))  # type: ignore[arg-type]
    assert set(range(50)) <= set(kept)
    audited = [i for i in kept if i >= 50]
    assert 0.05 < len(audited) / 950 < 0.15 and len(y) == len(kept)


# --- Run guards --------------------------------------------------------------------------------


def _world(name: str, k_star: int | None, shuffled: float, h5: float = 0.0) -> dict:
    by_k = {
        "20": {"available": True, "replicates": 20, "any_rule_rate": shuffled, "recovery_rate": h5}
    }
    arm = {"clean": {"k_star": k_star, "by_k": by_k}, "shuffled": {"by_k": by_k}}
    return {"world": name, "arms": {a: arm for a in E.ARMS}}


def test_outcome_order() -> None:
    hidden = [_world(n, 5, 0.0) for n in RUN.FACT_HIDDEN]
    ok = [*hidden, _world("H5_CHARGEBACK", None, 0.0, h5=0.1)]
    assert RUN.outcome(ok)[0] == "BENCHMARK_VALID"
    noisy = [*hidden, _world("H5_CHARGEBACK", None, 0.5)]
    assert RUN.outcome(noisy)[0] == "BENCHMARK_INVALID_CONTROL"
    hard = [_world(n, None, 0.0) for n in RUN.FACT_HIDDEN] + [_world("H5_CHARGEBACK", None, 0.0)]
    assert RUN.outcome(hard)[0] == "BENCHMARK_TOO_HARD"
    leak = [*hidden, _world("H5_CHARGEBACK", 5, 0.0, h5=0.9)]
    assert RUN.outcome(leak)[0] == "BENCHMARK_LEAKS_RAW_SIGNAL"


def test_evaluate_runs_once(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / RUN.RESULT_FILE).write_text("{}")
    with pytest.raises(SystemExit, match="written once"):
        RUN.cmd_evaluate(tmp_path)


def test_committed_cases_match_their_manifest() -> None:
    if not (RUN.EXPERIMENT / RUN.MANIFEST).exists():
        pytest.skip("cases not generated yet")
    cases = RUN.load_cases(RUN.EXPERIMENT)
    manifest = json.loads((RUN.EXPERIMENT / RUN.MANIFEST).read_text())
    assert len(cases) == manifest["counts"]["cases"]
    assert len({c.family_id for c in cases}) == manifest["counts"]["families"]


# --- Phase B dry run ---------------------------------------------------------------------------


def test_llm_module_has_no_client_or_network() -> None:
    tree = ast.parse(Path(llm.__file__).read_text())
    imported = {
        (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    banned = ("openai", "anthropic", "litellm", "httpx", "requests", "urllib", "socket")
    assert not any(m.split(".")[0] in banned for m in imported), imported


@needs_tau2
def test_dry_run_builds_prompts_and_calls_nothing(sample) -> None:
    out = llm.dry_run(sample, worlds=[BY_NAME["H1_LARGE_REFUND"]])
    assert out["model_calls_made"] == 0
    assert out["totals"]["L-pol"]["calls"] > 0 and out["totals"]["L-ind"]["calls"] > 0
