"""LLM baseline scoring through the OpenAI Batch API, against recorded batch runs.

tests/fixtures/openai_batch/ holds two real runs made by scripts/record_batch_fixtures.py: `ok`
(two requests, both answered) and `error` (one request whose line failed with a 404).
`FakeOpenAI` plays them back through httpx.MockTransport: the upload, create, poll, list and
file-content responses are the recorded ones, and output lines are matched to uploaded lines by
question.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from hatchway.bench import BenchStore, openai_batch
from hatchway.bench.score import score_store_batch
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.judges import YesNoAnswer, llm_baseline
from hatchway.judges.llm_baseline import LLMBaselineJudge
from hatchway.policy import Policy, load_policy
from hatchway.state import split_context, state_hash

FIXTURES = Path(__file__).parent / "fixtures"
STATE = (FIXTURES / "judges" / "llm_baseline_state.txt").read_text()
ACTION = "return_delivered_order_items"
MODEL = "gpt-4.1-mini-2025-04-14"
NO_LOGPROBS_MODEL = "gpt-5-mini"
PRICES = llm_baseline.BATCH_PRICES[MODEL]


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "openai_batch" / f"{name}.json").read_text())


def _key(model: str) -> openai_batch.BatchKey:
    """The key scripts/record_batch_fixtures.py recorded. The recording predates the per-rule
    questions, so the rubric is pinned to the three questions it had then."""
    current = load_policy(DEFAULT_POLICY).actions[ACTION]
    recorded = {
        n: current.questions[n].model_dump(exclude={"name"})
        for n in ("policy_ok", "matches_request", "risk")
    }
    action = Policy.model_validate(
        {"version": 1, "actions": {ACTION: {"kind": "write", "questions": recorded}}}
    ).actions[ACTION]
    names = ("policy_ok",) if model == NO_LOGPROBS_MODEL else ("policy_ok", "risk")
    questions = tuple(action.questions[n] for n in names)
    return openai_batch.BatchKey(state_hash(STATE), action.rubric_hash, STATE, questions)


class Killed(BaseException):
    """Stands in for the process being killed."""


class FakeOpenAI:
    """Serves one recorded batch run. Every request is logged as (method, path)."""

    def __init__(
        self,
        name: str,
        *,
        polls_before_done: int = 1,
        drop: set[str] = frozenset(),
        id_suffix: str = "",
    ) -> None:
        self.f = _fixture(name)
        self.id_suffix = id_suffix  # a resubmission gets a new batch id from the real API
        self.polls_before_done = polls_before_done  # GETs answered with the first poll
        self.drop = drop  # question names whose result lines go missing
        self.calls: list[tuple[str, str]] = []
        self.uploads: list[list[dict[str, Any]]] = []
        self.creates: list[dict[str, Any]] = []
        self.polls = 0

    @property
    def client(self) -> openai_batch.BatchClient:
        transport = httpx.MockTransport(self._handle)
        return openai_batch.BatchClient(
            api_key="test-key-not-real", client=httpx.AsyncClient(transport=transport)
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        self.calls.append((request.method, path))
        assert request.headers["authorization"] == "Bearer test-key-not-real"
        if request.method == "POST" and path == "/files":
            text = request.content.decode()
            assert 'name="purpose"\r\n\r\nbatch' in text
            lines = [json.loads(m) for m in re.findall(r'^\{"custom_id".*$', text, re.M)]
            self.uploads.append(lines)
            return httpx.Response(200, json=self.f["upload"])
        if request.method == "POST" and path == "/batches":
            body = json.loads(request.content)
            self.creates.append(body)
            assert body["input_file_id"] == self.f["upload"]["id"]
            batch_id = self.f["create"]["id"] + self.id_suffix
            batch_id += "" if len(self.creates) == 1 else "-2"
            batch = {**self.f["create"], "id": batch_id, "metadata": body["metadata"]}
            return httpx.Response(200, json=batch)
        if request.method == "GET" and path == "/batches":
            return httpx.Response(200, json=self.f["list"])
        if request.method == "GET" and path.startswith(f"/batches/{self.f['create']['id']}"):
            self.polls += 1
            done = self.polls > self.polls_before_done
            poll = self.f["final_poll" if done else "first_poll"]
            return httpx.Response(200, json={**poll, "id": path.removeprefix("/batches/")})
        match = re.fullmatch(r"/files/([^/]+)/content", path)
        if request.method == "GET" and match:
            return httpx.Response(200, text=self._content(match.group(1)))
        raise AssertionError(f"unexpected {request.method} {path}")

    def _content(self, file_id: str) -> str:
        field = next(k for k, v in self.f["final_poll"].items() if v == file_id)
        recorded = {
            openai_batch.parse_custom_id(e["custom_id"])[2]: e for e in self.f["contents"][field]
        }
        lines = []
        for line in self.uploads[-1] if self.uploads else self.f["lines"]:
            question = openai_batch.parse_custom_id(line["custom_id"])[2]
            if question in recorded and question not in self.drop:
                lines.append(json.dumps({**recorded[question], "custom_id": line["custom_id"]}))
        return "\n".join(lines) + "\n"


async def _no_sleep(_: float) -> None:
    return None


async def _kill(_: float) -> None:
    raise Killed


def _score(
    store: BenchStore,
    fake: FakeOpenAI,
    model: str = MODEL,
    sleep: Any = _no_sleep,
    **kwargs: Any,
) -> openai_batch.BatchSummary:
    async def run() -> openai_batch.BatchSummary:
        client = fake.client
        try:
            return await openai_batch.score_store_batch(
                store, [_key(model)], "llm_baseline", model, client, sleep=sleep, **kwargs
            )
        finally:
            await client.aclose()

    return asyncio.run(run())


@pytest.fixture
def store(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as s:
        yield s


def _expected_cost(fixture: dict[str, Any]) -> float:
    total = 0.0
    for entry in fixture["contents"]["output_file_id"]:
        usage = entry["response"]["body"]["usage"]
        cached = usage["prompt_tokens_details"]["cached_tokens"]
        total += (
            (usage["prompt_tokens"] - cached) * PRICES.input
            + cached * PRICES.cached_input
            + usage["completion_tokens"] * PRICES.output
        )
    return total


def test_recorded_batch_is_submitted_polled_and_ingested(store: BenchStore) -> None:
    f = _fixture("ok")
    fake = FakeOpenAI("ok")
    summary = _score(store, fake)

    # The uploaded lines are exactly the recorded ones; the batch targets Chat Completions.
    assert fake.uploads == [f["lines"]]
    assert {k: v for k, v in fake.creates[0].items() if k != "metadata"} == {
        k: v for k, v in f["create_request"].items() if k != "metadata"
    }
    assert [line["body"] for line in f["lines"]] == [
        llm_baseline.build_request(MODEL, STATE, q) for q in _key(MODEL).questions
    ]
    assert (summary.submitted_keys, summary.submitted_requests, summary.ok) == (1, 2, 1)

    key = _key(MODEL)
    record = store.get_score(key.state_hash, key.rubric_hash, "llm_baseline", MODEL)
    assert record is not None and record.status == "ok"
    bodies = {
        openai_batch.parse_custom_id(e["custom_id"])[2]: e["response"]["body"]
        for e in f["contents"]["output_file_id"]
    }
    for q in key.questions:
        assert record.question_vector.answers[q.name] == llm_baseline.parse_answer(  # type: ignore[union-attr]
            q, bodies[q.name]
        )
    assert isinstance(record.question_vector.answers["policy_ok"], YesNoAnswer)  # type: ignore[union-attr]
    assert json.loads(record.raw_response or "") == bodies
    # Billed at the Batch rates, half the standard ones; batch rows carry no latency.
    assert record.cost_usd == pytest.approx(_expected_cost(f))
    assert summary.cost_usd == pytest.approx(record.cost_usd)
    assert record.first_attempt_latency_ms is None and record.attempts == 1
    # The pre-submission estimate is an over-estimate.
    assert summary.estimated_cost_usd > record.cost_usd

    (job,) = store.batches()
    assert (job.batch_id, job.status, job.ingested) == (f["create"]["id"], "completed", True)
    assert store.batch_keys(job.batch_key) == [(key.state_hash, key.rubric_hash)]


def test_second_run_makes_no_calls(store: BenchStore) -> None:
    _score(store, FakeOpenAI("ok"))
    again = FakeOpenAI("ok")
    summary = _score(store, again)
    assert again.calls == [] and summary.pending == 0 and summary.batches_created == []


def test_killed_while_polling_resumes_the_submitted_batch(store: BenchStore) -> None:
    first = FakeOpenAI("ok", polls_before_done=5)
    with pytest.raises(Killed):
        _score(store, first, sleep=_kill)
    assert len(first.creates) == 1
    (job,) = store.open_batches("llm_baseline", MODEL)
    assert job.batch_id == first.f["create"]["id"] and not job.ingested

    resumed = FakeOpenAI("ok", polls_before_done=0)
    summary = _score(store, resumed)
    assert ("POST", "/files") not in resumed.calls and ("POST", "/batches") not in resumed.calls
    assert summary.batches_resumed == [job.batch_key] and summary.ok == 1
    assert store.open_batches("llm_baseline", MODEL) == []


def test_killed_between_creating_and_recording_the_batch_finds_it(
    store: BenchStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = store.update_batch

    def die_on_batch_id(batch_key: str, **fields: Any) -> None:
        if fields.get("batch_id"):
            raise Killed
        update(batch_key, **fields)

    monkeypatch.setattr(store, "update_batch", die_on_batch_id)
    first = FakeOpenAI("ok")
    with pytest.raises(Killed):
        _score(store, first)
    monkeypatch.undo()
    (job,) = store.open_batches("llm_baseline", MODEL)
    assert job.batch_id is None and job.input_file_id == first.f["upload"]["id"]

    resumed = FakeOpenAI("ok", polls_before_done=0)
    summary = _score(store, resumed)
    # Looked up by its input file, not created again.
    assert ("GET", "/batches") in resumed.calls
    assert resumed.creates == [] and resumed.uploads == []
    assert summary.ok == 1


def test_killed_before_the_upload_was_recorded_uploads_again(
    store: BenchStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = store.update_batch

    def die_on_file_id(batch_key: str, **fields: Any) -> None:
        if fields.get("input_file_id"):
            raise Killed
        update(batch_key, **fields)

    monkeypatch.setattr(store, "update_batch", die_on_file_id)
    with pytest.raises(Killed):
        _score(store, FakeOpenAI("ok"))
    monkeypatch.undo()
    (job,) = store.open_batches("llm_baseline", MODEL)
    assert job.input_file_id is None

    # The unrecorded file is never used; only one batch is ever created.
    resumed = FakeOpenAI("ok", polls_before_done=0)
    summary = _score(store, resumed)
    assert len(resumed.uploads) == 1 and len(resumed.creates) == 1
    assert summary.batches_created == [] and summary.batches_resumed == [job.batch_key]
    assert summary.ok == 1


def test_failed_line_is_an_error_row_and_is_resubmitted_next_run(store: BenchStore) -> None:
    f = _fixture("error")
    summary = _score(store, FakeOpenAI("error"), model=NO_LOGPROBS_MODEL)
    assert (summary.ok, summary.errors) == (0, 1)
    key = _key(NO_LOGPROBS_MODEL)
    record = store.get_score(key.state_hash, key.rubric_hash, "llm_baseline", NO_LOGPROBS_MODEL)
    assert record is not None and record.status == "error"
    assert record.error == "batch: HTTP 404 (invalid_request_error)"
    raw = json.loads(record.raw_response or "")
    assert raw == {"policy_ok": f["contents"]["error_file_id"][0]["response"]["body"]}
    assert "message" not in (record.raw_response or "")

    again = FakeOpenAI("error", id_suffix="-retry")
    summary = _score(store, again, model=NO_LOGPROBS_MODEL)
    assert len(again.creates) == 1 and summary.submitted_keys == 1


def test_missing_result_line_fails_the_key(store: BenchStore) -> None:
    summary = _score(store, FakeOpenAI("ok", drop={"risk"}))
    assert summary.errors == 1
    key = _key(MODEL)
    record = store.get_score(key.state_hash, key.rubric_hash, "llm_baseline", MODEL)
    assert record is not None and record.status == "error"
    assert record.error == "batch: no result (batch completed)"
    # The answered question is still billed.
    assert record.cost_usd is not None and record.cost_usd > 0


def test_spend_cap_is_checked_against_the_estimate_before_submitting(store: BenchStore) -> None:
    fake = FakeOpenAI("ok")
    summary = _score(store, fake, spend_cap_usd=0.0001)
    assert fake.calls == [] and summary.not_scheduled == 1 and summary.spend_cap_reached
    assert store.batches() == []


def test_no_wait_submits_and_returns_then_a_rerun_ingests(store: BenchStore) -> None:
    fake = FakeOpenAI("ok", polls_before_done=1)
    summary = _score(store, fake, wait=False)
    assert summary.batches_open == [fake.f["create"]["id"]] and summary.ok == 0
    resumed = FakeOpenAI("ok", polls_before_done=0)
    summary = _score(store, resumed, wait=False)
    assert summary.ok == 1 and summary.batches_open == []


def test_batches_split_at_the_request_limit(store: BenchStore) -> None:
    key = _key(MODEL)
    other = openai_batch.BatchKey("0" * 64, key.rubric_hash, STATE + " ", key.questions)

    fake = FakeOpenAI("ok", polls_before_done=10)

    async def plan() -> openai_batch.BatchSummary:
        client = fake.client
        try:
            return await openai_batch.score_store_batch(
                store, [key, other], "llm_baseline", MODEL, client, wait=False, max_requests=3
            )
        finally:
            await client.aclose()

    summary = asyncio.run(plan())
    assert len(summary.batches_created) == 2 and len(summary.batches_open) == 2
    assert [len(lines) for lines in fake.uploads] == [2, 2]
    jobs = store.batches()
    assert [store.batch_keys(j.batch_key) for j in jobs] == [
        [(key.state_hash, key.rubric_hash)],
        [(other.state_hash, other.rubric_hash)],
    ]
    assert [j.n_requests for j in jobs] == [2, 2]


# --- Through the scorer ------------------------------------------------------------------------


def _policy_with_two_questions() -> Policy:
    action = load_policy(DEFAULT_POLICY).actions[ACTION]
    questions = {n: action.questions[n].model_dump(exclude={"name"}) for n in ("policy_ok", "risk")}
    return Policy.model_validate(
        {"version": 1, "actions": {ACTION: {"kind": "write", "questions": questions}}}
    )


def test_scorer_batch_mode_plans_from_captured_writes(store: BenchStore) -> None:
    policy = _policy_with_two_questions()
    conversation = split_context(STATE, "conversation")[0].removeprefix(
        "## Context: conversation\n"
    )
    shared = split_context(STATE, "policy")[0].removeprefix("## Context: policy\n")
    args = json.loads(STATE.split("## Proposed action\n")[1].removeprefix(ACTION + "(")[:-2])
    for session in ("s1", "s2"):  # two identical writes share one score key
        write = store.record_write(
            session_id=session,
            action=ACTION,
            args=args,
            context={"conversation": conversation, "policy": shared},
            rubric_hash=policy.actions[ACTION].rubric_hash,
        )
    assert write.state_text == STATE

    fake = FakeOpenAI("ok", polls_before_done=0)

    async def run() -> Any:
        client = fake.client
        try:
            judge = LLMBaselineJudge(model_id=MODEL, api_key="test-key-not-real")
            return await score_store_batch(
                store, policy, [judge], client, sleep=_no_sleep, spend_cap_usd=1.0
            )
        finally:
            await client.aclose()

    summary = asyncio.run(run())
    assert summary.score_keys == 1 and len(fake.uploads[0]) == 2
    (batch,) = summary.batches
    assert batch["ok"] == 1 and summary.spent_usd == pytest.approx(batch["cost_usd"])
    record = store.get_score(write.state_hash, write.rubric_hash, "llm_baseline", MODEL)
    assert record is not None and record.status == "ok"
