"""The final task outcome of a simulation, computed in one place.

τ² rewards a simulation in [0, 1]; it passes only at a reward of 1, whatever the domain's reward
basis (database state, environment assertions, communicated info). Every consumer (the harness,
the viewer, the metrics) calls `task_outcome` so the definition cannot drift.

The task outcome belongs to the simulation. Per-write metrics never carry it: a conversation
with three writes is one task outcome, not three.
"""

from __future__ import annotations

import math
from typing import Literal

TaskOutcome = Literal["PASS", "FAIL"]


def task_outcome(reward: float | None) -> TaskOutcome | None:
    """`PASS` at reward 1, `FAIL` below it, None when the simulation has no reward."""
    if reward is None:
        return None
    return "PASS" if math.isclose(reward, 1) else "FAIL"


def task_passed(reward: float | None) -> bool:
    return task_outcome(reward) == "PASS"
