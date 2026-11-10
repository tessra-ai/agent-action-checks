"""Week 1 benchmark path: flat capture store and score cache."""

from hatchway.bench.store import BenchmarkMatch, BenchStore, CapturedWrite, ScoreRecord

# The tool result the τ² agent gets, byte for byte, whenever the live gated pass denies a write
# (MILESTONES.md, "M7 denial result"). Who denied it is recorded in the store, never here.
DENIAL_RESULT = (
    "POLICY_DENIED: This action was reviewed and not approved under the business policy. "
    "This is a final decision, not a system error. Do not retry this action with the same "
    "arguments. Tell the customer it cannot be completed, or choose a different action."
)

__all__ = ["DENIAL_RESULT", "BenchStore", "BenchmarkMatch", "CapturedWrite", "ScoreRecord"]
