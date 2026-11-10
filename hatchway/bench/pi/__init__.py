"""Policy-induction benchmark (experiment, zero spend in Phase A).

Can a learner recover an organization's rules, written or unwritten, from its decisions? Cases
are counterfactual families built from τ² retail data and labelled by the unchanged retail
oracle (`hatchway.bench.tau2.verdicts`). Each "world" either removes one clause from the policy
the learner starts from, or adds a hidden organization rule the written policy never states.
Preregistration: `experiments/2026-10-25-policy-induction/RFC.md`.
"""
