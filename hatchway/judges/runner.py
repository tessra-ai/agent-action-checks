"""Retry, timing and cost accounting around one judge call, producing a `ScoreRecord`.

Benchmark scoring never fails closed: a judge that keeps failing, refuses, or returns answers
that do not match the questions produces a `status='error'` row, never a score or `ASK`.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from hatchway.bench.store import ScoreRecord
from hatchway.judges.base import Judge, Question, QuestionVector


class JudgeError(Exception):
    """A judge call failed. `retryable` says whether trying again might succeed."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        cost_usd: float | None = None,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        # A failed call can still be billed, e.g. a malformed or refused answer.
        self.cost_usd = cost_usd
        # The response body behind the failure (JSON text), kept for review; None if there was
        # no body. Error bodies keep only the API's error type and code.
        self.raw_response = raw_response


@dataclass(frozen=True)
class JudgeResult:
    vector: QuestionVector
    cost_usd: float | None = None
    raw_response: str | None = None


@runtime_checkable
class CostReportingJudge(Judge, Protocol):
    """A judge that can also report what one call cost. The runner prefers this method."""

    async def score_with_cost(
        self, state_text: str, questions: Sequence[Question]
    ) -> JudgeResult: ...


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    timeout_s: float = 30.0
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0

    def delay(self, attempt: int, rng: random.Random) -> float:
        """Full-jitter exponential backoff before retry number `attempt` (1-based)."""
        return rng.uniform(0, min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1)))


async def score_with_retry(
    judge: Judge,
    state_text: str,
    questions: Sequence[Question],
    *,
    state_hash: str,
    rubric_hash: str,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.perf_counter,
    rng: random.Random | None = None,
) -> ScoreRecord:
    """Call `judge` until it returns answers matching `questions` or retries run out.

    `first_attempt_latency_ms` is the first attempt alone (replay compares it with the
    production timeout, which does not retry). `latency_ms` is wall time across all attempts,
    backoff included. `cost_usd` sums the cost of every attempt that reported one.
    `raw_response` is the response body of the last attempt, the one the record describes.
    """
    policy = policy or RetryPolicy()
    rng = rng or random.Random()
    key = dict(
        state_hash=state_hash,
        rubric_hash=rubric_hash,
        judge_name=judge.name,
        model_id=judge.model_id,
    )
    start = clock()
    first_latency_ms: float | None = None
    cost: float | None = None
    error = "no attempts made"
    raw: str | None = None
    attempt = 0
    while attempt < policy.max_attempts:
        attempt += 1
        attempt_start = clock()
        attempt_cost: float | None = None
        raw = None
        try:
            result = await asyncio.wait_for(_call(judge, state_text, questions), policy.timeout_s)
            attempt_cost, raw = result.cost_usd, result.raw_response
        except TimeoutError:
            result, error, retryable = None, f"timed out after {policy.timeout_s:g}s", True
        except JudgeError as exc:
            result, error, retryable = None, str(exc), exc.retryable
            attempt_cost, raw = exc.cost_usd, exc.raw_response
        if first_latency_ms is None:
            first_latency_ms = (clock() - attempt_start) * 1000
        if attempt_cost is not None:
            cost = (cost or 0.0) + attempt_cost
        if result is not None:
            try:
                result.vector.check_against(questions)
                if (result.vector.judge, result.vector.model_id) != (judge.name, judge.model_id):
                    raise ValueError("answers carry the wrong judge name or model id")
            except ValueError as exc:
                # Malformed answers are not retried: the same request usually fails the same way.
                error, retryable = f"malformed answers: {exc}", False
            else:
                return ScoreRecord(
                    **key,
                    status="ok",
                    question_vector=result.vector,
                    attempts=attempt,
                    first_attempt_latency_ms=first_latency_ms,
                    latency_ms=(clock() - start) * 1000,
                    cost_usd=cost,
                    raw_response=raw,
                )
        if not retryable:
            break
        if attempt < policy.max_attempts:
            await sleep(policy.delay(attempt, rng))
    return ScoreRecord(
        **key,
        status="error",
        attempts=attempt,
        first_attempt_latency_ms=first_latency_ms,
        latency_ms=(clock() - start) * 1000,
        cost_usd=cost,
        error=error,
        raw_response=raw,
    )


async def _call(judge: Judge, state_text: str, questions: Sequence[Question]) -> JudgeResult:
    if isinstance(judge, CostReportingJudge):
        return await judge.score_with_cost(state_text, questions)
    return JudgeResult(await judge.score(state_text, questions))
