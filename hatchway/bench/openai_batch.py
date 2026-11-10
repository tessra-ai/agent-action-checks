"""Score captured writes with the LLM baseline through the OpenAI Batch API (offline, half price).

Shapes follow https://developers.openai.com/api/docs/guides/batch (checked 2026-10-21): upload a
JSONL file (`purpose=batch`) with one Chat Completions request per line, create a batch on
`/v1/chat/completions` with a `24h` completion window, poll `GET /v1/batches/{id}` until it is
`completed`, `failed`, `expired` or `cancelled`, then download the output and error files. Output
lines may come back in any order; `custom_id` maps them back. A batch may hold 50,000 requests
and a 200 MB input file.

Each score key (`state_hash`, `rubric_hash`) becomes one request per question, with the same
body the real-time judge sends (`llm_baseline.build_request`), so a batch row and a real-time
row answer the same prompt. Results are stored as ordinary `scores` rows: `ok` when every
question has a usable answer, else `error` (retried, in a new batch, on the next run). Batch
rows have no latency (`first_attempt_latency_ms` is None): replay's 3 s fail-closed check needs
real-time calls.

Resumable: every job is recorded in the store before its file is uploaded, then updated with
the file id and the batch id as each exists. A killed run finds its open jobs on the next run:
a job with a batch id is polled, a job with a file but no recorded batch id is looked up in
`GET /v1/batches` by its input file (the run may have died between creating the batch and
recording it) and created only if absent, and a job with no file is uploaded afresh. Keys in an
open job are never put in a new one.

Cost: the pricing page lists Batch rates at half the standard rates and, for gpt-4.1 models, no
cached-input rate, so cached tokens are billed as ordinary batch input. Note that standard calls
with a warm cache can be cheaper than Batch: gpt-4.1-mini cached input is $0.10 per 1M tokens
against $0.20 for Batch input. The spend cap is checked before submitting, against an estimate
(prompt bytes / 3 tokens, an over-estimate for English text); stored costs come from `usage`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from hatchway.bench.store import BatchJob, BenchStore, ScoreRecord
from hatchway.judges import llm_baseline
from hatchway.judges._http import (
    OPENAI_BASE_URL,
    api_key_from_env,
    dump_body,
    sanitize_error_body,
)
from hatchway.judges.base import Question
from hatchway.judges.runner import JudgeError
from hatchway.ulid import new_ulid

log = logging.getLogger("hatchway")

ENDPOINT = "/v1/chat/completions"
COMPLETION_WINDOW = "24h"
TERMINAL = frozenset({"completed", "failed", "expired", "cancelled"})
MAX_REQUESTS = 50_000
# Well under the 200 MB limit.
MAX_FILE_BYTES = 100_000_000
# Prompt bytes per token used for the spend-cap estimate; English runs at about 4 to 4.5.
BYTES_PER_TOKEN_ESTIMATE = 3


class BatchAPIError(RuntimeError):
    """A Files or Batches API call failed. The message keeps the status and error type only."""


class BatchClient:
    """The few Files and Batches API calls batch scoring needs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = OPENAI_BASE_URL,
    ) -> None:
        self._api_key = api_key or api_key_from_env("OPENAI_API_KEY")
        self._client = client or httpx.AsyncClient(timeout=300)
        self._base = base_url.rstrip("/")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = await self._client.request(
                method, f"{self._base}{path}", headers=headers, **kwargs
            )
        except httpx.TransportError as exc:
            raise BatchAPIError(f"{method} {path}: transport error {type(exc).__name__}") from None
        if response.status_code != 200:
            try:
                detail = dump_body(sanitize_error_body(response.json()))
            except ValueError:
                detail = ""
            raise BatchAPIError(f"{method} {path}: HTTP {response.status_code} {detail}".strip())
        return response

    async def upload(self, content: bytes, filename: str) -> dict[str, Any]:
        files = {"file": (filename, content, "application/jsonl")}
        response = await self._call("POST", "/files", data={"purpose": "batch"}, files=files)
        return response.json()

    async def create(self, input_file_id: str, metadata: dict[str, str]) -> dict[str, Any]:
        body = {
            "input_file_id": input_file_id,
            "endpoint": ENDPOINT,
            "completion_window": COMPLETION_WINDOW,
            "metadata": metadata,
        }
        return (await self._call("POST", "/batches", json=body)).json()

    async def get(self, batch_id: str) -> dict[str, Any]:
        return (await self._call("GET", f"/batches/{batch_id}")).json()

    async def find_by_input_file(
        self, input_file_id: str, pages: int = 10
    ) -> dict[str, Any] | None:
        """The batch created from this input file, searching the newest `pages` x 100."""
        params: dict[str, Any] = {"limit": 100}
        for _ in range(pages):
            page = (await self._call("GET", "/batches", params=params)).json()
            for batch in page.get("data", []):
                if batch.get("input_file_id") == input_file_id:
                    return batch
            if not page.get("has_more") or not page.get("data"):
                return None
            params["after"] = page["data"][-1]["id"]
        return None

    async def content(self, file_id: str) -> str:
        return (await self._call("GET", f"/files/{file_id}/content")).text


def custom_id(state_hash: str, rubric_hash: str, question: str) -> str:
    return f"{state_hash}:{rubric_hash}:{question}"


def parse_custom_id(value: str) -> tuple[str, str, str]:
    state_hash, rubric_hash, question = value.split(":", 2)
    return state_hash, rubric_hash, question


@dataclass(frozen=True)
class BatchKey:
    """One score key to send: its questions and state text."""

    state_hash: str
    rubric_hash: str
    state_text: str
    questions: tuple[Question, ...]
    write_ids: tuple[str, ...] = ()


def request_lines(model_id: str, key: BatchKey) -> list[str]:
    """The JSONL lines for one key: one Chat Completions request per question."""
    return [
        json.dumps(
            {
                "custom_id": custom_id(key.state_hash, key.rubric_hash, q.name),
                "method": "POST",
                "url": ENDPOINT,
                "body": llm_baseline.build_request(model_id, key.state_text, q),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for q in key.questions
    ]


def estimate_cost(lines: Iterable[str], prices: llm_baseline.Prices | None) -> float | None:
    """An over-estimate of what these request lines cost: no caching, bytes / 3 tokens each."""
    if prices is None:
        return None
    total = 0.0
    for line in lines:
        tokens = math.ceil(len(line.encode()) / BYTES_PER_TOKEN_ESTIMATE)
        total += tokens * prices.input + prices.output
    return total


def parse_output(text: str) -> dict[str, dict[str, Any]]:
    """Output or error file lines keyed by `custom_id`."""
    out: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if line.strip():
            entry = json.loads(line)
            out[entry["custom_id"]] = entry
    return out


def _line_result(
    q: Question, entry: dict[str, Any] | None, prices: llm_baseline.Prices | None, why: str
) -> tuple[Any, float | None, Any] | JudgeError:
    """One question's (answer, cost, body), or the JudgeError explaining why it has none."""
    if entry is None:
        return JudgeError(f"batch: no result ({why})", retryable=True)
    response = entry.get("response")
    if isinstance(response, dict) and response.get("status_code") == 200:
        body = response.get("body")
        if not isinstance(body, dict):
            return JudgeError("malformed response: body is not a JSON object", retryable=False)
        try:
            return llm_baseline.answer_from_body(q, body, prices)
        except JudgeError as exc:
            return exc
    error = entry.get("error")
    if isinstance(response, dict) and isinstance(response.get("body"), dict):
        status = response.get("status_code")
        body = sanitize_error_body(response["body"])
        error_type = (body.get("error") or {}).get("type")
        summary = f"HTTP {status}" + (f" ({error_type})" if error_type else "")
        return JudgeError(f"batch: {summary}", retryable=True, raw_response=dump_body(body))
    if isinstance(error, dict):
        code = error.get("code") or "error"
        return JudgeError(
            f"batch: {code}", retryable=True, raw_response=dump_body({"error": {"code": code}})
        )
    return JudgeError("batch: unrecognised result line", retryable=False)


def record_for_key(
    judge_name: str,
    model_id: str,
    key: BatchKey,
    entries: dict[str, dict[str, Any]],
    prices: llm_baseline.Prices | None,
    why_missing: str,
) -> ScoreRecord:
    """Build the score row for one key from its questions' result lines."""
    outcomes = [
        _line_result(
            q, entries.get(custom_id(key.state_hash, key.rubric_hash, q.name)), prices, why_missing
        )
        for q in key.questions
    ]
    base = dict(
        state_hash=key.state_hash,
        rubric_hash=key.rubric_hash,
        judge_name=judge_name,
        model_id=model_id,
        attempts=1,
    )
    try:
        result = llm_baseline.assemble(judge_name, model_id, key.questions, outcomes)
        result.vector.check_against(key.questions)
    except JudgeError as exc:
        return ScoreRecord(
            **base,
            status="error",
            cost_usd=exc.cost_usd,
            error=str(exc),
            raw_response=exc.raw_response,
        )
    except ValueError as exc:
        return ScoreRecord(**base, status="error", error=f"malformed answers: {exc}")
    return ScoreRecord(
        **base,
        status="ok",
        question_vector=result.vector,
        cost_usd=result.cost_usd,
        raw_response=result.raw_response,
    )


@dataclass
class BatchSummary:
    judge_name: str
    model_id: str
    pending: int = 0  # keys with no ok row when the run started
    in_open_batches: int = 0  # of those, keys already in a submitted batch
    submitted_keys: int = 0
    submitted_requests: int = 0
    not_scheduled: int = 0  # keys left out by the spend cap
    batches_created: list[str] = field(default_factory=list)
    batches_resumed: list[str] = field(default_factory=list)
    batches_open: list[str] = field(default_factory=list)  # still running when the run ended
    ingested_keys: int = 0
    ok: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    estimated_cost_usd: float = 0.0  # of the batches created this run
    spend_cap_reached: bool = False
    request_counts: dict[str, dict[str, Any]] = field(default_factory=dict)


async def score_store_batch(
    store: BenchStore,
    keys: Sequence[BatchKey],
    judge_name: str,
    model_id: str,
    client: BatchClient,
    *,
    spend_cap_usd: float | None = None,
    wait: bool = True,
    poll_interval_s: float = 60.0,
    max_requests: int = MAX_REQUESTS,
    max_file_bytes: int = MAX_FILE_BYTES,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> BatchSummary:
    """Score `keys` (the planned keys without an ok row are sent) through the Batch API.

    Open jobs from earlier runs are resumed first. New jobs are cut at `max_requests` lines or
    `max_file_bytes`. Keys are submitted while this run's estimated spend stays within
    `spend_cap_usd`. With `wait`, polls until every job ends and ingests it; without, ingests
    jobs that have already ended and returns.
    """
    summary = BatchSummary(judge_name, model_id)
    prices = llm_baseline.BATCH_PRICES.get(model_id)
    by_key = {(k.state_hash, k.rubric_hash): k for k in keys}
    done = store.ok_score_keys(judge_name, model_id)
    pending = [k for k in keys if (k.state_hash, k.rubric_hash) not in done]
    summary.pending = len(pending)

    jobs: list[BatchJob] = store.open_batches(judge_name, model_id)
    in_flight = {k for job in jobs for k in store.batch_keys(job.batch_key)}
    summary.in_open_batches = sum(1 for k in pending if (k.state_hash, k.rubric_hash) in in_flight)
    summary.batches_resumed = [job.batch_key for job in jobs]

    # Cut new jobs from the remaining keys, within the spend cap.
    new_jobs: list[tuple[list[BatchKey], list[str]]] = []
    chunk: list[BatchKey] = []
    lines: list[str] = []
    size = 0
    spent = 0.0
    for key in pending:
        if (key.state_hash, key.rubric_hash) in in_flight:
            continue
        key_lines = request_lines(model_id, key)
        cost = estimate_cost(key_lines, prices) or 0.0
        if spend_cap_usd is not None and spent + cost > spend_cap_usd:
            summary.spend_cap_reached = True
            summary.not_scheduled += 1
            continue
        key_size = sum(len(line.encode()) + 1 for line in key_lines)
        if chunk and (
            len(lines) + len(key_lines) > max_requests or size + key_size > max_file_bytes
        ):
            new_jobs.append((chunk, lines))
            chunk, lines, size = [], [], 0
        chunk.append(key)
        lines.extend(key_lines)
        size += key_size
        spent += cost
    if chunk:
        new_jobs.append((chunk, lines))
    for chunk, lines in new_jobs:
        batch_key = new_ulid()
        estimate = estimate_cost(lines, prices)
        store.add_batch(
            batch_key,
            judge_name=judge_name,
            model_id=model_id,
            keys=[(k.state_hash, k.rubric_hash) for k in chunk],
            n_requests=len(lines),
            estimated_cost_usd=estimate,
        )
        summary.submitted_keys += len(chunk)
        summary.submitted_requests += len(lines)
        summary.estimated_cost_usd += estimate or 0.0
        summary.batches_created.append(batch_key)
        jobs.append(
            BatchJob(
                batch_key=batch_key,
                judge_name=judge_name,
                model_id=model_id,
                n_requests=len(lines),
                estimated_cost_usd=estimate,
                input_file_id=None,
                batch_id=None,
                status="preparing",
                ingested=False,
            )
        )

    # Make sure every job exists at OpenAI, then poll and ingest.
    for i, job in enumerate(jobs):
        jobs[i] = await _ensure_submitted(store, client, job, by_key, model_id)
    open_jobs = list(jobs)
    while open_jobs:
        still_open = []
        for job in open_jobs:
            assert job.batch_id is not None
            batch = await client.get(job.batch_id)
            status = batch.get("status", "unknown")
            if status != job.status:
                store.update_batch(job.batch_key, status=status)
            summary.request_counts[job.batch_id] = batch.get("request_counts") or {}
            if status in TERMINAL:
                await _ingest(store, client, job, batch, by_key, summary, prices)
            else:
                still_open.append(job.model_copy(update={"status": status}))
        open_jobs = still_open
        if open_jobs and wait:
            log.info(
                "%d batch job(s) still running; next poll in %gs", len(open_jobs), poll_interval_s
            )
            await sleep(poll_interval_s)
        elif open_jobs:
            break
    summary.batches_open = [job.batch_id or job.batch_key for job in open_jobs]
    return summary


async def _ensure_submitted(
    store: BenchStore,
    client: BatchClient,
    job: BatchJob,
    by_key: dict[tuple[str, str], BatchKey],
    model_id: str,
) -> BatchJob:
    """Upload and create the job at OpenAI unless that already happened; return it updated."""
    if job.batch_id is not None:
        return job
    file_id = job.input_file_id
    if file_id is not None:
        found = await client.find_by_input_file(file_id)
        if found is not None:
            store.update_batch(job.batch_key, batch_id=found["id"], status=found["status"])
            return job.model_copy(update={"batch_id": found["id"], "status": found["status"]})
    else:
        lines: list[str] = []
        for k in store.batch_keys(job.batch_key):
            if k not in by_key:
                raise RuntimeError(
                    f"batch {job.batch_key} covers a key no longer planned; it cannot be rebuilt"
                )
            lines.extend(request_lines(model_id, by_key[k]))
        uploaded = await client.upload(
            ("\n".join(lines) + "\n").encode(), f"hatchway-{job.batch_key}.jsonl"
        )
        file_id = uploaded["id"]
        store.update_batch(job.batch_key, input_file_id=file_id, status="uploaded")
    batch = await client.create(file_id, {"hatchway_batch_key": job.batch_key})
    store.update_batch(job.batch_key, batch_id=batch["id"], status=batch["status"])
    log.info("created batch %s (%d requests)", batch["id"], job.n_requests)
    return job.model_copy(
        update={"input_file_id": file_id, "batch_id": batch["id"], "status": batch["status"]}
    )


async def _ingest(
    store: BenchStore,
    client: BatchClient,
    job: BatchJob,
    batch: dict[str, Any],
    by_key: dict[tuple[str, str], BatchKey],
    summary: BatchSummary,
    prices: llm_baseline.Prices | None,
) -> None:
    entries: dict[str, dict[str, Any]] = {}
    for file_field in ("output_file_id", "error_file_id"):
        file_id = batch.get(file_field)
        if file_id:
            entries.update(parse_output(await client.content(file_id)))
    why = f"batch {batch.get('status')}"
    for k in store.batch_keys(job.batch_key):
        key = by_key.get(k)
        if key is None:  # no longer planned (e.g. its rubric changed): nothing to store
            continue
        record = record_for_key(job.judge_name, job.model_id, key, entries, prices, why)
        if store.put_score(record):
            summary.ingested_keys += 1
            if record.status == "ok":
                summary.ok += 1
            else:
                summary.errors += 1
            summary.cost_usd += record.cost_usd or 0.0
    store.update_batch(job.batch_key, status=batch.get("status"), ingested=True)
