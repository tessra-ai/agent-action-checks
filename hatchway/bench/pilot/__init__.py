"""Decision-model pilot (Phases 0-1): shared decision concepts vs learning vs the fixed baseline.

Three primary arms, all on the same judge (OpenAI Decisions):

- **D**: the existing fixed baseline, the mean of `policy_ok` and `matches_request`;
- **DC**: a fixed, non-learning rule over the shared concept assessments (`concepts`);
- **G1**: a learned model over exactly DC's inputs, frozen before any result is examined
  (`arms.G1_SPEC`).

D vs DC measures the value of shared concepts; DC vs G1 the value of learning. The data, the
three-way family split with its sealed holdout, and the analyses are in `data` and `analysis`;
`python -m hatchway.bench.pilot` runs them. Results are a directional pilot on the deterministic
oracle only, unaudited.
"""
