"""Resumable batch scoring of captured writes (M5).

Every captured write is scored by every configured judge. Writes join to scores on
`(state_hash, rubric_hash, judge_name, model_id)`, so the job calls a judge once per distinct key
that has no `ok` row: duplicate writes are billed once, a second run makes no calls, and a run
that is killed midway resumes where it stopped (each result is committed as it arrives). `error`
rows are retried on the next run; `ok` rows never are.

Before scoring, each write's conversation (`context["conversation"]`, from the τ² harness) is
checked for a real customer request: at least one user message before the write that is not
just filler ("please go ahead", "ok", "hi"). A write without one comes from a broken
simulation, not an agent mistake, so its key is recorded in `scoring_skips` and never sent to
a judge. A customer who asked but never confirmed still made a request: acting without
confirmation is a real mistake the judges must see.

Writes that cannot be scored are counted, not called: actions missing from the policy, writes
whose `rubric_hash` no longer matches the policy (captured under older questions), and writes
from abandoned simulations (started by the τ² harness but never finished, so their
conversations are partial).

`--batch` sends the LLM baseline through the OpenAI Batch API instead (`openai_batch`): half
price, results within 24 hours, no latency measurements. The other judges have no batch
endpoint (Decisions and Jev, checked 2026-10-21) and are scored in real time first, in the
same run; the spend cap covers both.

Judges given without a model id use the pinned ids in `hatchway.bench.models`.

Usage (needs OPENAI_API_KEY and TYPESAFE_API_KEY):

    python -m hatchway.bench.score runs/m5.db --judge openai_decisions --judge jev \\
        --judge llm_baseline --concurrency 8 --spend-cap 5 --out runs/m5/score.json
    python -m hatchway.bench.score runs/m5.db --judge llm_baseline --batch --spend-cap 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hatchway.bench import models
from hatchway.bench.budget import BudgetRefused, Ledger, chars_to_tokens, llm_call_max_usd
from hatchway.bench.store import BenchStore, CapturedWrite, ScoreRecord
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.judges.base import Judge, Question, QuestionVector
from hatchway.judges.runner import (
    CostReportingJudge,
    JudgeError,
    JudgeResult,
    RetryPolicy,
    score_with_retry,
)
from hatchway.policy import Kind, Policy, load_policy

log = logging.getLogger("hatchway")

SKIP_NO_REQUEST = "no customer request before the write"

# A user message made only of these words carries no request.
_FILLER = """
    please go ahead ok okay k hi hello hey yes yeah yep yup sure thanks thank you thx ty
    great good fine sounds alright all right cool perfect proceed continue do it that thats
    correct confirm confirmed so much very and then now no stop
"""
FILLER_WORDS = frozenset(_FILLER.split())

# Line prefixes `hatchway.bench.tau2.harness.render_transcript` writes; any other line continues
# the message above it.
_LINE_START = re.compile(r"^(user|assistant)(: | -> )|^tool \(")


def user_messages(conversation: str) -> list[str]:
    """The text of each user message in a rendered τ² transcript, in order."""
    messages: list[list[str]] = []
    current: list[str] | None = None
    for line in conversation.splitlines():
        match = _LINE_START.match(line)
        if match:
            current = None
            if line.startswith("user: "):
                current = [line.removeprefix("user: ")]
                messages.append(current)
        elif current is not None:
            current.append(line)
    return ["\n".join(lines) for lines in messages]


def is_filler(text: str) -> bool:
    words = re.sub(r"[^a-z]+", " ", text.lower().replace("'", "")).split()
    return all(word in FILLER_WORDS for word in words)


def has_customer_request(conversation: str) -> bool:
    return any(not is_filler(message) for message in user_messages(conversation))


def skip_reason(write: CapturedWrite) -> str | None:
    """Why this write is not sent to judges, or None to score it. Writes without a stored
    conversation (captured outside the τ² harness) are always scored."""
    conversation = write.context.get("conversation")
    if isinstance(conversation, str) and not has_customer_request(conversation):
        return SKIP_NO_REQUEST
    return None


@dataclass
class JudgeSummary:
    judge_name: str
    model_id: str
    pending: int = 0  # keys with no ok row when the run started
    calls: int = 0  # keys scored this run (each may take several attempts)
    attempts: int = 0
    ok: int = 0
    errors: int = 0
    skipped: int = 0  # keys that already had an ok row
    not_scheduled: int = 0  # keys left unscored by the spend cap
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    p50_first_attempt_latency_ms: float | None = None
    p95_first_attempt_latency_ms: float | None = None
    refused_write_ids: list[str] = field(default_factory=list)
    _latencies: list[float] = field(default_factory=list, repr=False)

    def add(self, record: ScoreRecord, write_ids: Sequence[str]) -> None:
        self.calls += 1
        self.attempts += record.attempts
        if record.status == "ok":
            self.ok += 1
        else:
            self.errors += 1
            if (record.error or "").startswith("refusal"):
                self.refused_write_ids.extend(write_ids)
        if record.cost_usd is None:
            self.unpriced_calls += 1
        else:
            self.cost_usd += record.cost_usd
        if record.first_attempt_latency_ms is not None:
            self._latencies.append(record.first_attempt_latency_ms)
            self.p50_first_attempt_latency_ms = percentile(self._latencies, 0.50)
            self.p95_first_attempt_latency_ms = percentile(self._latencies, 0.95)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        del out["_latencies"]
        return out


@dataclass
class ScoringSummary:
    writes: int = 0
    score_keys: int = 0  # distinct (state_hash, rubric_hash) keys sent to judges
    unknown_action_writes: int = 0
    rubric_mismatch_writes: int = 0
    abandoned_writes: int = 0  # from simulations that never finished
    filtered_writes: int = 0  # actions left out by `actions`
    skipped_writes: int = 0
    skipped_keys: int = 0
    skipped_by_task: list[dict[str, Any]] = field(default_factory=list)
    spend_cap_usd: float | None = None
    spent_usd: float = 0.0
    spend_cap_reached: bool = False
    dry_run: bool = False
    judges: list[JudgeSummary] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)  # `--batch` jobs, per judge

    @property
    def calls(self) -> int:
        return sum(j.calls for j in self.judges)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["calls"] = self.calls
        out["judges"] = [j.to_dict() for j in self.judges]
        return out


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 1]); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


@dataclass(frozen=True)
class _Key:
    state_hash: str
    rubric_hash: str
    action: str
    state_text: str
    write_ids: list[str]


Rubrics = Mapping[str, tuple[Sequence[Question], str]]


def plan_keys(
    store: BenchStore,
    policy: Policy,
    summary: ScoringSummary,
    actions: Collection[str] | None = None,
    rubrics: Rubrics | None = None,
    write_ids: Collection[str] | None = None,
) -> dict[tuple[str, str], _Key]:
    """The distinct score keys to send to judges, counting what is left out in `summary` and
    recording skipped keys in the store. With `actions`, only writes of those actions; with
    `write_ids`, only those writes.

    `rubrics` (action -> (questions, rubric hash)) asks other questions than the policy's about
    the same captured states, such as the decision-model pilot's concept rubric: keys use its
    hash, and a write captured under an older policy rubric is still scored."""
    keys: dict[tuple[str, str], _Key] = {}
    skipped: set[tuple[str, str]] = set()
    skips_by_task: Counter[tuple[str | None, str | None]] = Counter()
    abandoned = store.abandoned_session_ids()
    for write in store.writes():
        summary.writes += 1
        if write.session_id in abandoned:
            summary.abandoned_writes += 1
            continue
        if (actions is not None and write.action not in actions) or (
            write_ids is not None and write.write_id not in write_ids
        ):
            summary.filtered_writes += 1
            continue
        spec = policy.actions.get(write.action)
        if write.rubric_hash is None or spec is None or spec.kind is not Kind.WRITE:
            summary.unknown_action_writes += 1
            continue
        if rubrics is not None:
            if write.action not in rubrics:
                summary.unknown_action_writes += 1
                continue
            rubric_hash = rubrics[write.action][1]
        elif spec.rubric_hash != write.rubric_hash:
            summary.rubric_mismatch_writes += 1
            continue
        else:
            rubric_hash = write.rubric_hash
        key = (write.state_hash, rubric_hash)
        reason = skip_reason(write)
        if reason is not None:
            store.put_skip(*key, reason)
            skipped.add(key)
            summary.skipped_writes += 1
            skips_by_task[(write.task_id, write.agent_model)] += 1
            continue
        if key not in keys:
            keys[key] = _Key(*key, write.action, write.state_text, [])
        keys[key].write_ids.append(write.write_id)
    summary.score_keys = len(keys)
    summary.skipped_keys = len(skipped)
    summary.skipped_by_task = [
        {"task_id": task_id, "agent_model": agent_model, "writes": n}
        for (task_id, agent_model), n in sorted(skips_by_task.items(), key=str)
    ]
    return keys


async def score_store(
    store: BenchStore,
    policy: Policy,
    judges: Sequence[Judge],
    *,
    concurrency: int = 8,
    spend_cap_usd: float | None = None,
    retry: RetryPolicy | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    dry_run: bool = False,
    actions: Collection[str] | None = None,
    ledger: Ledger | None = None,
    rubrics: Rubrics | None = None,
    write_ids: Collection[str] | None = None,
) -> ScoringSummary:
    """Score every captured write in `store` with every judge; see the module docstring.

    At most `concurrency` judge calls run at once. Once this run's spend reaches
    `spend_cap_usd`, no new calls start; calls already running finish and are stored, so the
    cap can be exceeded by up to `concurrency - 1` calls. Calls whose cost is unknown count as
    free. `dry_run` plans the calls and records skips but calls nothing. `actions` and
    `write_ids` limit scoring to those writes; `rubrics` replaces the policy's questions (see
    `plan_keys`).

    With a `ledger` the cap is hard instead: every attempt reserves its maximum cost first
    (`judge_call_max_usd`) and is refused if that could exceed the `scoring` cap; the first
    refusal stops the run, and the refused key stays unscored for a later run.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    names = [(j.name, j.model_id) for j in judges]
    if len(set(names)) != len(names):
        raise ValueError("each judge name and model id may be configured once")
    summary = ScoringSummary(spend_cap_usd=spend_cap_usd, dry_run=dry_run)
    keys = plan_keys(store, policy, summary, actions, rubrics, write_ids)
    if ledger is not None:
        judges = [BudgetedJudge(j, ledger) for j in judges]

    jobs: list[tuple[_Key, Judge, JudgeSummary]] = []
    per_judge = []
    for judge in judges:
        js = JudgeSummary(judge.name, judge.model_id)
        done = store.ok_score_keys(judge.name, judge.model_id)
        js.skipped = sum(1 for k in keys if k in done)
        js.pending = len(keys) - js.skipped
        per_judge.append((judge, js, done))
        summary.judges.append(js)
    # Key-major order, so a capped or killed run leaves whole keys scored by every judge.
    for k, key in keys.items():
        for judge, js, done in per_judge:
            if k not in done:
                jobs.append((key, judge, js))
    if dry_run or not jobs:
        return summary

    queue: Iterator[tuple[_Key, Judge, JudgeSummary]] = iter(jobs)
    refused: list[tuple[_Key, Judge, JudgeSummary]] = []

    async def worker() -> None:
        while True:
            if spend_cap_usd is not None and summary.spent_usd >= spend_cap_usd:
                summary.spend_cap_reached = True
                return
            if refused:
                return
            job = next(queue, None)
            if job is None:
                return
            key, judge, js = job
            try:
                record = await score_with_retry(
                    judge,
                    key.state_text,
                    list(
                        rubrics[key.action][0]
                        if rubrics is not None
                        else policy.actions[key.action].questions.values()
                    ),
                    state_hash=key.state_hash,
                    rubric_hash=key.rubric_hash,
                    policy=retry,
                    sleep=sleep,
                )
            except BudgetRefused as exc:
                log.warning("stopping: %s", exc)
                summary.spend_cap_reached = True
                refused.append(job)
                return
            store.put_score(record)
            js.add(record, key.write_ids)
            summary.spent_usd += record.cost_usd or 0.0
            if summary.calls % 50 == 0:
                log.info(
                    "scored %d of %d; spent $%.4f", summary.calls, len(jobs), summary.spent_usd
                )

    async with asyncio.TaskGroup() as group:
        for _ in range(min(concurrency, len(jobs))):
            group.create_task(worker())
    for _key, _judge, js in [*refused, *queue]:
        js.not_scheduled += 1
    return summary


def judge_call_max_usd(judge: Judge, state_text: str, questions: Sequence[Question]) -> float:
    """The most one attempt of `judge` on this state can cost: the request's characters as
    tokens (`budget.chars_to_tokens`, about twice the real count), every token uncached, the
    whole output allowance. Raises `BudgetRefused` for a judge with no known price."""
    from hatchway.judges import jev, llm_baseline, openai_decisions

    if judge.name == "llm_baseline":
        prices = getattr(judge, "prices", None)
        if prices is None:
            raise BudgetRefused(f"llm_baseline {judge.model_id}: no price")
        return sum(
            llm_call_max_usd(
                chars_to_tokens(
                    len(json.dumps(llm_baseline.build_request(judge.model_id, state_text, q)))
                ),
                1,  # `max_completion_tokens` in every request
                prices.input,
                prices.output,
            )
            for q in questions
        )
    modules = {"jev": jev, "openai_decisions": openai_decisions}
    module = modules.get(judge.name)
    rate = module.USD_PER_INPUT_TOKEN.get(judge.model_id) if module is not None else None
    if module is None or rate is None:
        raise BudgetRefused(f"{judge.name} {judge.model_id}: no price")
    request = module.build_request(judge.model_id, state_text, questions)
    return chars_to_tokens(len(json.dumps(request))) * rate


class BudgetedJudge:
    """A judge whose every call reserves its maximum cost in a ledger first and settles at its
    reported cost (an unknown cost settles at the reservation)."""

    def __init__(self, judge: Judge, ledger: Ledger) -> None:
        self.inner = judge
        self.ledger = ledger
        self.name = judge.name
        self.model_id = judge.model_id

    async def score(self, state_text: str, questions: Sequence[Question]) -> QuestionVector:
        return (await self.score_with_cost(state_text, questions)).vector

    async def score_with_cost(self, state_text: str, questions: Sequence[Question]) -> JudgeResult:
        max_usd = judge_call_max_usd(self.inner, state_text, questions)
        reservation = self.ledger.reserve(
            f"scoring:{self.name}:{self.model_id}", "scoring", max_usd
        )
        try:
            if isinstance(self.inner, CostReportingJudge):
                result = await self.inner.score_with_cost(state_text, questions)
            else:
                result = JudgeResult(await self.inner.score(state_text, questions))
        except JudgeError as exc:
            self.ledger.settle(reservation, exc.cost_usd, note="judge error")
            raise
        except BaseException:
            self.ledger.settle(reservation, None, note="failed: counted at its reservation")
            raise
        self.ledger.settle(reservation, result.cost_usd)
        return result

    async def aclose(self) -> None:
        aclose = getattr(self.inner, "aclose", None)
        if aclose is not None:
            await aclose()


async def score_store_batch(
    store: BenchStore,
    policy: Policy,
    judges: Sequence[Any],
    client: Any,
    *,
    spend_cap_usd: float | None = None,
    wait: bool = True,
    poll_interval_s: float = 60.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    summary: ScoringSummary | None = None,
) -> ScoringSummary:
    """Score with LLM baseline judges through the Batch API (see `openai_batch`).

    `judges` are `LLMBaselineJudge`s (only their name and model id are used); `client` is an
    `openai_batch.BatchClient`. With `summary`, adds to it (a run that scored other judges
    in real time first) and counts that run's spend against the cap.
    """
    from hatchway.bench.openai_batch import BatchKey
    from hatchway.bench.openai_batch import score_store_batch as run_batches

    if summary is None:
        summary = ScoringSummary(spend_cap_usd=spend_cap_usd)
        keys = plan_keys(store, policy, summary)
    else:
        keys = plan_keys(store, policy, ScoringSummary())
    batch_keys = [
        BatchKey(
            k.state_hash,
            k.rubric_hash,
            k.state_text,
            tuple(policy.actions[k.action].questions.values()),
            tuple(k.write_ids),
        )
        for k in keys.values()
    ]
    for judge in judges:
        remaining = None if spend_cap_usd is None else max(0.0, spend_cap_usd - summary.spent_usd)
        result = await run_batches(
            store,
            batch_keys,
            judge.name,
            judge.model_id,
            client,
            spend_cap_usd=remaining,
            wait=wait,
            poll_interval_s=poll_interval_s,
            sleep=sleep,
        )
        summary.spent_usd += result.cost_usd
        summary.spend_cap_reached = summary.spend_cap_reached or result.spend_cap_reached
        summary.batches.append(asdict(result))
    return summary


def make_judge(spec: str, store: BenchStore) -> Judge:
    """Build a judge from `name[:model_id]`: openai_decisions, jev, llm_baseline:<model>, or
    oracle (answers from the store's effective policy verdicts; free, for checks)."""
    from hatchway.judges.jev import JevJudge
    from hatchway.judges.llm_baseline import LLMBaselineJudge
    from hatchway.judges.openai_decisions import OpenAIDecisionsJudge
    from hatchway.judges.oracle import OracleJudge

    name, _, model = spec.partition(":")
    if name == "openai_decisions":
        return OpenAIDecisionsJudge(model_id=model or models.DECISIONS_MODEL)
    if name == "jev":
        return JevJudge(model_id=model or models.JEV_MODEL)
    if name == "llm_baseline":
        return LLMBaselineJudge(model_id=model or models.LLM_BASELINE_MODEL)
    if name == "oracle":
        from hatchway.bench.replay import resolve_oracle_version

        version = resolve_oracle_version(store)
        verdicts = {
            p.state_hash: p.effective_decision
            for p in store.proposed_actions(version, require_verdicts=False)
        }
        return OracleJudge(verdicts)
    raise ValueError(f"unknown judge {name!r}")


async def _run(args: argparse.Namespace) -> ScoringSummary:
    policy = load_policy(args.policy)
    with BenchStore(args.store) as store:
        judges = [make_judge(spec, store) for spec in args.judge]
        batched = [j for j in judges if args.batch and j.name == "llm_baseline"]
        realtime = [j for j in judges if j not in batched]
        if args.batch and not batched:
            raise SystemExit("--batch applies to llm_baseline judges only; none configured")
        try:
            summary = await score_store(
                store,
                policy,
                realtime,
                concurrency=args.concurrency,
                spend_cap_usd=args.spend_cap,
                retry=RetryPolicy(max_attempts=args.max_attempts, timeout_s=args.timeout),
                dry_run=args.dry_run,
                actions=args.actions,
            )
            if batched and not args.dry_run:
                from hatchway.bench.openai_batch import BatchClient

                client = BatchClient()
                try:
                    await score_store_batch(
                        store,
                        policy,
                        batched,
                        client,
                        spend_cap_usd=args.spend_cap,
                        wait=not args.no_wait,
                        poll_interval_s=args.poll_interval,
                        summary=summary,
                    )
                finally:
                    await client.aclose()
            return summary
        finally:
            for judge in judges:
                aclose = getattr(judge, "aclose", None)
                if aclose is not None:
                    await aclose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("store", type=Path, help="benchmark SQLite file")
    parser.add_argument(
        "--judge",
        action="append",
        required=True,
        help="name[:model_id]; repeat for each judge; pinned ids by default",
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--spend-cap", type=float, default=None, help="USD for this run")
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds per attempt")
    parser.add_argument("--dry-run", action="store_true", help="plan the calls; call nothing")
    parser.add_argument(
        "--actions",
        type=lambda v: frozenset(a for a in v.split(",") if a),
        default=None,
        help="score only writes of these actions (comma-separated)",
    )
    parser.add_argument(
        "--batch", action="store_true", help="score llm_baseline through the OpenAI Batch API"
    )
    parser.add_argument(
        "--no-wait", action="store_true", help="with --batch: submit, then exit; rerun to ingest"
    )
    parser.add_argument("--poll-interval", type=float, default=60.0, help="seconds, --batch")
    parser.add_argument("--out", type=Path, help="also write the summary JSON here")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(message)s")

    summary = asyncio.run(_run(args)).to_dict()
    text = json.dumps(summary, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
