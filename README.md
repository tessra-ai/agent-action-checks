# Hatchway

Research code for checking an AI agent's actions before they run: a τ²-bench capture harness that
freezes each proposed write before it executes, a deterministic policy checker for τ²-bench
retail and telecom, judge adapters (Jev, OpenAI Decisions, an LLM baseline), and the experiments
that compare them.

**Start here:** [experiments/README.md](experiments/README.md) indexes every experiment, with
its preregistration, report and per-action results. The write-up of the main findings is
[Three questions before an AI agent acts](https://tessra.ai/blog/three-questions-before-an-ai-agent-acts).

**Status:** research code, not a product. [SPEC.md](SPEC.md) is the original design (a gate that
learns when to ask a human, with a hash-chained receipt ledger); [MILESTONES.md](MILESTONES.md)
tracks what was built. The ledger, promotion and the agent-framework adapters were not built: the
experiments moved the work toward checking actions against policy and records instead.

**About this repository.** It is a snapshot of the development repository (commit `015e852`,
2026-11-09). Branch names and commit hashes in the experiment records, including the
preregistration and freeze commits, refer to that development history, which is not published;
they are kept as written. The experiment records themselves (preregistrations, reports, code and
per-action results) are complete here.

## Development

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check . && ruff format --check .
```

Tests never make network calls; `pytest-socket` blocks sockets for the whole suite.

### τ²-bench harness (week 1 benchmark)

The capture harness runs against τ²-bench at the commit pinned in
`hatchway/bench/tau2/__init__.py`. Install a checkout of it in editable mode so it finds its task
data:

```bash
git init -q .tau2-bench
git -C .tau2-bench fetch --depth 1 https://github.com/sierra-research/tau2-bench c5b2d228d850c59b749b93cf32c4745d3aa53967
git -C .tau2-bench checkout -q FETCH_HEAD
pip install -e '.[dev]' -e ./.tau2-bench 'litellm>=1.80.15,<1.82.7'

# Wrapped and unwrapped runs (calls the agent and user models; needs OPENAI_API_KEY).
# Models default to the dated snapshots in hatchway/bench/models.py. Resumable: rerun the same
# command after a crash and finished simulations are kept.
python -m hatchway.bench.tau2.harness --domain retail --task-ids 0 1 2 3 4 --trials 2 \
    --spend-cap 1 --store runs/m4.db --out runs/m4
# A committed run config (wrapped capture only): smoke.yaml, then pilot.yaml
python -m hatchway.bench.tau2.harness --config hatchway/bench/tau2/configs/smoke.yaml \
    --store runs/smoke.db --out runs/smoke
# Each captured write gets its policy verdict (ALLOW/ASK/DENY/UNKNOWN) before the tool runs.
# Review queue (UNKNOWNs plus an audit sample), adjudications, and agreement with the oracle:
python -m hatchway.bench.tau2.verdicts runs/smoke.db --queue review.yaml
python -m hatchway.bench.tau2.verdicts runs/smoke.db --import review.yaml --report
# Record each write's tau2 trace match (tau2 analysis only, not the safety label)
python -m hatchway.bench.tau2.label runs/m4.db

# Live gated pass with a frozen arm from replay (M7; calls the agent, user and judge models).
# --approver perfect|noisy; --spend-cap covers judges, agent and user together
python -m hatchway.bench.tau2.gated --arm runs/m6/frozen_E.json --approver noisy \
    --domain retail --task-ids 0 1 2 3 4 --trials 2 --agent-llm gpt-4.1-mini-2025-04-14 \
    --spend-cap 20 --store runs/m7.db --out runs/m7/retail-noisy
```

### Replay (arms A–F)

Replay fits arms B–F on a 60% train split of a scored store and evaluates them on the rest,
against each write's policy verdict (rules in `hatchway/bench/replay.py`). It writes `metrics.json`, one `frozen_<arm>.json` per arm
for the live gated pass, `autonomy_curve.png`, `frontier.png`, and `transfer.png` (how a model fit
on one domain carries over to another, `hatchway/bench/transfer.py`):

```bash
pip install -e '.[bench]'
# Score a captured store first (calls the judges; resumable, capped by --spend-cap)
python -m hatchway.bench.score runs/m4.db --judge jev --judge llm_baseline:gpt-4.1-mini-2025-04-14 \
    --spend-cap 2
python -m hatchway.bench.replay runs/m4.db --seed 0 --out runs/m6
# No scored store yet? Try it on a synthetic one.
python -m hatchway.bench.synthetic runs/synthetic.db --tasks 120 --two-domains
python -m hatchway.bench.replay runs/synthetic.db --seed 0 --out runs/synthetic
```

## License

Apache 2.0. See [LICENSE](LICENSE).
