"""The gate. Week 1 runs it in shadow mode only: it captures writes and always allows.

Judges, thresholds, `ask`/`auto` modes and fail-closed handling arrive in later milestones
(M7 for the live benchmark pass, M10 for production).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hatchway.bench.store import BenchStore, PreExecution
from hatchway.decision import Decision, Result
from hatchway.policy import Kind, Policy, load_policy

log = logging.getLogger("hatchway")


class Gate:
    def __init__(
        self,
        policy: Policy | str | Path,
        *,
        store: BenchStore,
        domain: str | None = None,
        agent_model: str | None = None,
    ) -> None:
        self.policy = policy if isinstance(policy, Policy) else load_policy(policy)
        self.store = store
        self.domain = domain
        self.agent_model = agent_model
        self._warned_unknown: set[str] = set()

    def check(
        self,
        action: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        *,
        session_id: str,
        task_id: str | None = None,
        trial: int | None = None,
        pre_execution: PreExecution | None = None,
    ) -> Decision:
        """Shadow check: reads pass untouched; every write is captured, then allowed.

        A tool missing from the policy is captured as an unscored write and allowed, with a
        warning. Store errors are raised, not turned into a decision: a benchmark run must
        stop rather than silently lose data. `pre_execution` (the τ² harness's snapshot and
        policy verdict) is committed with the write; see `BenchStore.record_write`.
        """
        spec = self.policy.actions.get(action)
        if spec is not None and spec.kind is Kind.READ:
            return Decision(result=Result.ALLOW, reason="read action")

        if spec is None and action not in self._warned_unknown:
            self._warned_unknown.add(action)
            log.warning("action %r is not in the policy; capturing it unscored", action)

        write = self.store.record_write(
            session_id=session_id,
            action=action,
            args=args,
            context=context or {},
            rubric_hash=spec.rubric_hash if spec is not None else None,
            known_action=spec is not None,
            domain=self.domain,
            agent_model=self.agent_model,
            task_id=task_id,
            trial=trial,
            pre_execution=pre_execution,
        )
        reason = "shadow: captured" if spec is not None else "shadow: captured unknown action"
        return Decision(result=Result.ALLOW, reason=reason, receipt_id=write.write_id)
