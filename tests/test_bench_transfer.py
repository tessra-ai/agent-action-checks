"""Cross-domain transfer evaluation, on synthetic two-domain stores (no API calls)."""

import json

import pytest

from hatchway.bench.replay import load_rows, main, replay
from hatchway.bench.synthetic import TWO_DOMAINS, build_store

K = (0, 10, 25, 50)
DIRECTIONS = ("retail->telecom", "telecom->retail")


def run(path, *, shifted=(), seed=3):
    build_store(path, tasks=80, seed=7, domains=TWO_DOMAINS, shifted_domains=shifted)
    rows, judges = load_rows(path)
    return replay(rows, judges, seed=seed, curve_points=(), transfer_k=K, transfer_resamples=2)


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    return run(tmp_path_factory.mktemp("transfer") / "shared.db")


@pytest.fixture(scope="module")
def shifted(tmp_path_factory):
    return run(tmp_path_factory.mktemp("transfer") / "shifted.db", shifted=("telecom",))


def ask_means(result, direction, name):
    fs = result.metrics["transfer"]["directions"][direction]["few_shot"]
    return dict(zip(fs["k"], (s["mean"] for s in fs[name]["ask_at_target"]), strict=True))


def test_report_shape(shared):
    t = shared.metrics["transfer"]
    assert t["status"] == "ok"
    assert t["domains"] == ["retail", "telecom"]
    assert set(t["directions"]) == set(DIRECTIONS)
    for entry in t["directions"].values():
        assert set(entry["zero_shot"]) == {"E", "F"}
        for arm in entry["zero_shot"].values():
            for side in ("in_domain", "zero_shot"):
                keys = {"intervention_required_recall", "safe_auto_rate", "ask_rate", "ece"}
                assert keys <= set(arm[side])
        fs = entry["few_shot"]
        assert fs["k"] == list(K)
        spread = fs["transfer"]["ask_at_target"][1]
        assert set(spread) == {"mean", "std", "min", "max", "n"} and spread["n"] == 2


def test_shared_signal_transfer_beats_scratch_at_small_k(shared):
    for direction in DIRECTIONS:
        with_prior = ask_means(shared, direction, "transfer")
        scratch = ask_means(shared, direction, "scratch")
        assert scratch[0] == 1.0  # no labels: nothing to rank with
        assert with_prior[0] < 0.6
        small = (0, 10, 25)
        assert sum(with_prior[k] for k in small) < sum(scratch[k] for k in small) - 0.2


def test_different_signal_transfer_does_not_beat_scratch(shifted):
    for direction in DIRECTIONS:
        with_prior = ask_means(shifted, direction, "transfer")
        scratch = ask_means(shifted, direction, "scratch")
        ks = (10, 25, 50)
        assert sum(with_prior[k] for k in ks) >= sum(scratch[k] for k in ks)
        zero = shifted.metrics["transfer"]["directions"][direction]["zero_shot"]["E"]
        assert zero["zero_shot"]["ece"] > zero["in_domain"]["ece"]


def test_transfer_is_deterministic(shared, tmp_path):
    again = run(tmp_path / "shared.db")
    assert again.metrics["transfer"] == shared.metrics["transfer"]


def test_single_domain_or_tiny_store_reports_insufficient_data(tmp_path):
    one = build_store(tmp_path / "one.db", tasks=6)
    rows, judges = load_rows(one)
    t = replay(rows, judges, seed=0, curve_points=(), transfer_k=K, transfer_resamples=1)
    assert t.metrics["transfer"]["status"].startswith("insufficient data")

    tiny = build_store(
        tmp_path / "tiny.db", tasks=4, sessions_per_task=1, domains=TWO_DOMAINS, seed=1
    )
    out = tmp_path / "out"
    assert (
        main([str(tiny), "--out", str(out), "--transfer-k", "0,10", "--transfer-resamples", "1"])
        == 0
    )
    m = json.loads((out / "metrics.json").read_text())
    assert m["transfer"]["domains"] == ["retail", "telecom"]
    for entry in m["transfer"]["directions"].values():
        assert entry["status"] == "ok" or entry["status"].startswith("insufficient data")
    assert (out / "transfer.png").exists()
