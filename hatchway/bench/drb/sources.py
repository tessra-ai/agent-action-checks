"""Where a record's concepts come from.

Phase 0 uses `AuthoritativeConcepts` only: synthetic latent facts and deterministic oracle checks.
`JudgeConcepts` is the interface Phase 1 will implement, where a semantic judge reads the rendered
evidence. It makes no call, and a training run never mixes the two sources (`assert_one_source`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from hatchway.bench.drb.schema import ConceptValue, DecisionRecord


class ConceptSource(Protocol):
    name: str

    def concepts(self, record: DecisionRecord) -> Mapping[str, ConceptValue]: ...


class AuthoritativeConcepts:
    name = "authoritative"

    def concepts(self, record: DecisionRecord) -> Mapping[str, ConceptValue]:
        return record.concepts


class JudgeConcepts:
    """Phase 1 (separate approval): concept probabilities from a semantic judge."""

    name = "judge"

    def concepts(self, record: DecisionRecord) -> Mapping[str, ConceptValue]:
        raise NotImplementedError("judge-extracted concepts are Phase 1 and need separate approval")


def assert_one_source(sources: Iterable[ConceptSource]) -> str:
    names = {s.name for s in sources}
    if len(names) != 1:
        raise ValueError(f"a training run uses one concept source, not {sorted(names)}")
    return names.pop()
