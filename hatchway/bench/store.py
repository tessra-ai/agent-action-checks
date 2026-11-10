"""Flat SQLite store for the week 1 benchmark path.

`captured_writes` holds one row per gated write call, duplicates included, so replay counts
every call. `scores` caches one judge result per (state_hash, rubric_hash, judge_name,
model_id), so identical writes are billed once. Raw arguments are kept: τ²-bench data is
synthetic. Week 2's production ledger imports these rows.

Two bookkeeping tables make long runs resumable: `openai_batches` (with `openai_batch_keys`)
records every OpenAI Batch API job the scorer submits, so a killed run picks the job up instead
of paying for it twice; `simulations` records every τ² simulation the harness and the gated
pass start and finish, so a killed capture run redoes only unfinished simulations. Writes
captured by a simulation that never finished are "abandoned": `abandoned_session_ids()` names
their sessions.

Schema 2 separates four things about every captured write (see
`hatchway.bench.tau2.verdicts`): the pre-action snapshot it was judged on
(`pre_action_snapshots`, databases in `db_blobs`), the policy oracle's verdict per oracle
version (`policy_verdicts`) and any manual adjudication (`manual_verdicts`), what the backend
then did (`execution_outcomes`), and how it compares with τ²'s reference trace
(`benchmark_matches`). The final task outcome stays per simulation (`simulations.reward`, read
through `simulation_outcomes()`), never per write. All of these tables are append-only. A file
from before schema 2 is refused: regenerate it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import zlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from hatchway.bench.outcomes import TaskOutcome, task_outcome
from hatchway.judges.base import QuestionVector
from hatchway.state import STATE_VERSION, build_state, canonical_json, state_hash
from hatchway.ulid import new_ulid

STORE_SCHEMA_VERSION = 2

BenchmarkMatch = Literal["MATCH", "MISMATCH", "AMBIGUOUS"]
PolicyDecision = Literal["ALLOW", "ASK", "DENY", "UNKNOWN"]
ExecutionOutcome = Literal["NOT_EXECUTED", "ACCEPTED", "REJECTED", "TECHNICAL_ERROR"]
ReviewKind = Literal["unknown_queue", "audit_sample"]

_WRITE_COLUMNS = (
    "write_id, ts, domain, agent_model, task_id, trial, session_id, seq, action, known_action, "
    "args, context, state_text, state_hash, state_version, rubric_hash"
)

# `gated` simulations are live gated passes (M7). They are not resumed, and one store may hold
# several gated runs of the same key (other arms or approver modes), so the one-done-per-key
# index leaves them out.
_SIMULATIONS_DDL = """
CREATE TABLE IF NOT EXISTS simulations (
    session_id      TEXT PRIMARY KEY,
    mode            TEXT NOT NULL CHECK (mode IN ('wrapped', 'unwrapped', 'gated')),
    domain          TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    trial           INTEGER NOT NULL,
    agent_model     TEXT NOT NULL,
    user_model      TEXT,
    seed            INTEGER,
    status          TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    reward          REAL,
    agent_cost_usd  REAL,
    user_cost_usd   REAL,
    error           TEXT,
    simulation      TEXT,
    started_ts      TEXT NOT NULL,
    finished_ts     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS simulations_one_done_per_key
    ON simulations (mode, domain, task_id, trial, agent_model, seed)
    WHERE status = 'done' AND mode != 'gated';
"""

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS captured_writes (
    write_id      TEXT PRIMARY KEY,
    ts            TEXT NOT NULL,
    domain        TEXT,
    agent_model   TEXT,
    task_id       TEXT,
    trial         INTEGER,
    session_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    action        TEXT NOT NULL,
    known_action  INTEGER NOT NULL,
    args          TEXT NOT NULL,
    context       TEXT NOT NULL,
    state_text    TEXT NOT NULL,
    state_hash    TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    rubric_hash   TEXT,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS captured_writes_score_key
    ON captured_writes (state_hash, rubric_hash);

CREATE TRIGGER IF NOT EXISTS captured_writes_no_delete
BEFORE DELETE ON captured_writes
BEGIN SELECT RAISE(ABORT, 'captured_writes is append-only'); END;

CREATE TRIGGER IF NOT EXISTS captured_writes_no_update
BEFORE UPDATE ON captured_writes
BEGIN SELECT RAISE(ABORT, 'captured_writes is append-only'); END;

CREATE TABLE IF NOT EXISTS scores (
    state_hash               TEXT NOT NULL,
    rubric_hash              TEXT NOT NULL,
    judge_name               TEXT NOT NULL,
    model_id                 TEXT NOT NULL,
    status                   TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    question_vector          TEXT,
    attempts                 INTEGER NOT NULL CHECK (attempts >= 1),
    first_attempt_latency_ms REAL,
    latency_ms               REAL,
    cost_usd                 REAL,
    error                    TEXT,
    ts                       TEXT NOT NULL,
    raw_response             TEXT,
    PRIMARY KEY (state_hash, rubric_hash, judge_name, model_id),
    CHECK ((status = 'ok') = (question_vector IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS scoring_skips (
    state_hash  TEXT,
    rubric_hash TEXT,
    reason      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    PRIMARY KEY (state_hash, rubric_hash)
);

CREATE TABLE IF NOT EXISTS openai_batches (
    batch_key          TEXT PRIMARY KEY,
    judge_name         TEXT NOT NULL,
    model_id           TEXT NOT NULL,
    n_requests         INTEGER NOT NULL,
    estimated_cost_usd REAL,
    input_file_id      TEXT,
    batch_id           TEXT UNIQUE,
    status             TEXT NOT NULL,
    ingested           INTEGER NOT NULL DEFAULT 0,
    created_ts         TEXT NOT NULL,
    updated_ts         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS openai_batch_keys (
    batch_key   TEXT NOT NULL REFERENCES openai_batches (batch_key),
    state_hash  TEXT NOT NULL,
    rubric_hash TEXT NOT NULL,
    PRIMARY KEY (batch_key, state_hash, rubric_hash)
);

{_SIMULATIONS_DDL}
CREATE VIEW IF NOT EXISTS write_scores AS
SELECT w.*, s.judge_name, s.model_id, s.status, s.question_vector, s.attempts,
       s.first_attempt_latency_ms, s.latency_ms, s.cost_usd, s.error
FROM captured_writes AS w
JOIN scores AS s USING (state_hash, rubric_hash);
"""


# Live gated pass (M7). One `gated_decisions` row per gated write, keyed by its captured write;
# one `gated_judge_calls` row per live judge call for it. Files created before M7 gain these
# tables when opened. Both tables are append-only.
_GATED_SCHEMA = """
CREATE TABLE IF NOT EXISTS gated_decisions (
    write_id           TEXT PRIMARY KEY REFERENCES captured_writes (write_id),
    ts                 TEXT NOT NULL,
    session_id         TEXT NOT NULL,
    arm                TEXT NOT NULL,
    decision           TEXT NOT NULL CHECK (decision IN ('ALLOW', 'ASK', 'DENY')),
    ask_reason         TEXT CHECK (ask_reason IN
                           ('threshold', 'judge_error', 'unknown_action', 'unverified')),
    decided_by         TEXT NOT NULL CHECK (decided_by IN ('threshold', 'approver', 'hard_rule')),
    p_ok               REAL,
    threshold          REAL,
    approver_mode      TEXT,
    approver_answer    TEXT CHECK (approver_answer IN ('approve', 'reject')),
    approver_flipped   INTEGER,
    executed           INTEGER NOT NULL,
    repeat_same_args   INTEGER NOT NULL,
    repeat_same_action INTEGER NOT NULL,
    CHECK ((decision = 'ASK') = (ask_reason IS NOT NULL)),
    CHECK ((decision = 'ALLOW') = (decided_by = 'threshold')),
    CHECK ((decision = 'DENY') = (decided_by = 'hard_rule')),
    CHECK ((decided_by = 'approver') = (approver_answer IS NOT NULL)),
    CHECK (executed = (decision = 'ALLOW' OR approver_answer = 'approve'))
);
CREATE INDEX IF NOT EXISTS gated_decisions_session ON gated_decisions (session_id);

CREATE TABLE IF NOT EXISTS gated_judge_calls (
    write_id   TEXT NOT NULL REFERENCES gated_decisions (write_id),
    judge_name TEXT NOT NULL,
    model_id   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    latency_ms REAL,
    cost_usd   REAL,
    error      TEXT,
    PRIMARY KEY (write_id, judge_name, model_id)
);

CREATE TRIGGER IF NOT EXISTS gated_decisions_append_only_update
BEFORE UPDATE ON gated_decisions
BEGIN SELECT RAISE(ABORT, 'gated_decisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS gated_decisions_append_only_delete
BEFORE DELETE ON gated_decisions
BEGIN SELECT RAISE(ABORT, 'gated_decisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS gated_judge_calls_append_only_update
BEFORE UPDATE ON gated_judge_calls
BEGIN SELECT RAISE(ABORT, 'gated_judge_calls is append-only'); END;
CREATE TRIGGER IF NOT EXISTS gated_judge_calls_append_only_delete
BEFORE DELETE ON gated_judge_calls
BEGIN SELECT RAISE(ABORT, 'gated_judge_calls is append-only'); END;
"""

# Policy verdicts (schema 2). Everything here is append-only. The pre-execution rows of a write
# (the write, its snapshot, its deterministic verdict) are committed in one transaction before
# the tool runs; an execution outcome can only be added after them.
_VERDICT_SCHEMA = """
CREATE TABLE IF NOT EXISTS db_blobs (
    hash TEXT PRIMARY KEY,
    data BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS pre_action_snapshots (
    write_id           TEXT PRIMARY KEY REFERENCES captured_writes (write_id),
    tool_call_id       TEXT,
    agent_db_hash      TEXT NOT NULL REFERENCES db_blobs (hash),
    user_db_hash       TEXT REFERENCES db_blobs (hash),
    messages           TEXT NOT NULL,
    proposing_text     TEXT NOT NULL,
    domain_policy_hash TEXT NOT NULL,
    ts                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_verdicts (
    write_id            TEXT NOT NULL REFERENCES captured_writes (write_id),
    oracle_version      TEXT NOT NULL,
    expected_decision   TEXT NOT NULL CHECK (expected_decision IN
                            ('ALLOW', 'ASK', 'DENY', 'UNKNOWN')),
    should_execute_now  INTEGER,
    reason_codes        TEXT NOT NULL,
    explanation         TEXT NOT NULL,
    evidence            TEXT NOT NULL,
    ts                  TEXT NOT NULL,
    PRIMARY KEY (write_id, oracle_version),
    CHECK ((expected_decision = 'UNKNOWN') = (should_execute_now IS NULL))
);

CREATE TABLE IF NOT EXISTS manual_verdicts (
    review_id          TEXT PRIMARY KEY,
    write_id           TEXT NOT NULL REFERENCES captured_writes (write_id),
    oracle_version     TEXT NOT NULL,
    expected_decision  TEXT NOT NULL CHECK (expected_decision IN
                           ('ALLOW', 'ASK', 'DENY', 'UNKNOWN')),
    reason_codes       TEXT NOT NULL,
    explanation        TEXT NOT NULL,
    reviewer           TEXT NOT NULL,
    adjudicated        INTEGER NOT NULL,
    review_kind        TEXT NOT NULL CHECK (review_kind IN ('unknown_queue', 'audit_sample')),
    ts                 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS manual_verdicts_write ON manual_verdicts (write_id, oracle_version);

CREATE TABLE IF NOT EXISTS execution_outcomes (
    write_id           TEXT PRIMARY KEY REFERENCES captured_writes (write_id),
    outcome            TEXT NOT NULL CHECK (outcome IN
                           ('NOT_EXECUTED', 'ACCEPTED', 'REJECTED', 'TECHNICAL_ERROR')),
    state_changed      INTEGER,
    backend_error      TEXT,
    agent_db_hash_after TEXT,
    user_db_hash_after TEXT,
    ts                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_matches (
    write_id    TEXT PRIMARY KEY REFERENCES captured_writes (write_id),
    match       TEXT NOT NULL CHECK (match IN ('MATCH', 'MISMATCH', 'AMBIGUOUS')),
    rule        TEXT NOT NULL,
    gold_index  INTEGER,
    ts          TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS execution_outcomes_after_evaluation
BEFORE INSERT ON execution_outcomes
WHEN NOT EXISTS (SELECT 1 FROM pre_action_snapshots WHERE write_id = NEW.write_id)
  OR NOT EXISTS (SELECT 1 FROM policy_verdicts WHERE write_id = NEW.write_id)
BEGIN SELECT RAISE(ABORT, 'an outcome needs the write''s snapshot and verdict first'); END;
"""

_APPEND_ONLY = (
    "db_blobs",
    "pre_action_snapshots",
    "policy_verdicts",
    "manual_verdicts",
    "execution_outcomes",
    "benchmark_matches",
)
_VERDICT_SCHEMA += "".join(
    f"""
CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;
CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;
"""
    for t in _APPEND_ONLY
)


class IncompatibleStoreError(RuntimeError):
    """The file was written by an older schema; regenerate it."""


ApproverAnswer = Literal["approve", "reject"]
AskReason = Literal["threshold", "judge_error", "unknown_action", "unverified"]


class CapturedWrite(BaseModel):
    model_config = ConfigDict(frozen=True)

    write_id: str
    ts: str
    domain: str | None
    agent_model: str | None
    task_id: str | None
    trial: int | None
    session_id: str
    seq: int
    action: str
    known_action: bool
    args: dict[str, Any]
    context: dict[str, Any]
    state_text: str
    state_hash: str
    state_version: int
    rubric_hash: str | None


class ScoreRecord(BaseModel):
    """One judge's result for one score key. `ok` rows carry a QuestionVector; `error` rows
    carry the error text instead.

    `raw_response` is the judge's JSON response body, or None when there was none (timeouts,
    transport errors). Error bodies keep only the API's error type and code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state_hash: str
    rubric_hash: str
    judge_name: str
    model_id: str
    status: Literal["ok", "error"]
    question_vector: QuestionVector | None = None
    attempts: int = 1
    first_attempt_latency_ms: float | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    error: str | None = None
    raw_response: str | None = None

    @model_validator(mode="after")
    def _check_status(self) -> ScoreRecord:
        if (self.status == "ok") != (self.question_vector is not None):
            raise ValueError("status 'ok' requires a question_vector; 'error' must not have one")
        if self.question_vector is not None and (
            self.question_vector.judge != self.judge_name
            or self.question_vector.model_id != self.model_id
        ):
            raise ValueError("question_vector judge/model_id do not match the score key")
        return self

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.state_hash, self.rubric_hash, self.judge_name, self.model_id)


class BatchJob(BaseModel):
    """One OpenAI Batch API job. `batch_id` is None until the job is known to exist."""

    model_config = ConfigDict(frozen=True)

    batch_key: str
    judge_name: str
    model_id: str
    n_requests: int
    estimated_cost_usd: float | None
    input_file_id: str | None
    batch_id: str | None
    status: str
    ingested: bool


SimulationKey = tuple[str, str, str, int, str, int | None]  # mode, domain, task, trial, agent, seed


class SimulationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    mode: Literal["wrapped", "unwrapped", "gated"]
    domain: str
    task_id: str
    trial: int
    agent_model: str
    user_model: str | None
    seed: int | None
    status: Literal["running", "done", "failed"]
    reward: float | None = None
    agent_cost_usd: float | None = None
    user_cost_usd: float | None = None
    error: str | None = None
    simulation: str | None = None  # the τ² SimulationRun as JSON, once done

    @property
    def key(self) -> SimulationKey:
        return (self.mode, self.domain, self.task_id, self.trial, self.agent_model, self.seed)


class GatedJudgeCall(BaseModel):
    """One live judge call made for one gated write (production rules: one attempt)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    judge_name: str
    model_id: str
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    cost_usd: float | None = None
    error: str | None = None


class GatedDecision(BaseModel):
    """What the live gate decided for one write, who decided it, and whether the tool ran.

    `decision` is the gate's: `ALLOW` (decided by the threshold), `ASK` (decided by the
    approver, whose answer is `approver_answer`) or `DENY` (a hard rule; none exist before M8).
    `repeat_same_args` / `repeat_same_action`: the write proposes an action (with the same
    arguments / with any arguments) that was denied earlier in the same session.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    write_id: str
    session_id: str
    arm: str
    decision: Literal["ALLOW", "ASK", "DENY"]
    ask_reason: AskReason | None = None
    decided_by: Literal["threshold", "approver", "hard_rule"]
    p_ok: float | None = None
    threshold: float | None = None
    approver_mode: str | None = None
    approver_answer: ApproverAnswer | None = None
    approver_flipped: bool | None = None
    executed: bool
    repeat_same_args: bool = False
    repeat_same_action: bool = False
    judge_calls: tuple[GatedJudgeCall, ...] = ()

    @model_validator(mode="after")
    def _check_consistent(self) -> GatedDecision:
        allow = self.decision == "ALLOW"
        if (self.decision == "ASK") != (self.ask_reason is not None):
            raise ValueError("an ASK needs an ask_reason; ALLOW and DENY must not have one")
        expected = {"ALLOW": "threshold", "ASK": "approver", "DENY": "hard_rule"}
        if self.decided_by != expected[self.decision]:
            raise ValueError(
                "ALLOW is decided by the threshold, ASK by the approver, DENY by a rule"
            )
        if (self.decided_by == "approver") != (self.approver_answer is not None):
            raise ValueError("approver_answer is set exactly when the approver decided")
        if self.executed != (allow or self.approver_answer == "approve"):
            raise ValueError("a write runs only when allowed or approved")
        return self


class PreActionSnapshot(BaseModel):
    """The state a write was judged on, taken just before the tool would run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_call_id: str | None = None
    agent_db: dict[str, Any]
    user_db: dict[str, Any] | None = None
    messages: list[dict[str, Any]]  # the conversation before the proposing message
    proposing_text: str = ""
    domain_policy_hash: str


class VerdictRecord(BaseModel):
    """The policy oracle's verdict on one write, for one oracle version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    oracle_version: str
    expected_decision: PolicyDecision
    should_execute_now: bool | None
    reason_codes: tuple[str, ...] = ()
    explanation: str = ""
    evidence: dict[str, Any] = {}

    @model_validator(mode="after")
    def _check(self) -> VerdictRecord:
        if (self.expected_decision == "UNKNOWN") != (self.should_execute_now is None):
            raise ValueError("should_execute_now is None exactly for UNKNOWN")
        return self


class ManualVerdict(BaseModel):
    """A reviewer's verdict on one write. An adjudicated one overrides the deterministic
    verdict of the same oracle version; the latest adjudicated one wins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_id: str
    write_id: str
    oracle_version: str
    expected_decision: PolicyDecision
    reason_codes: tuple[str, ...] = ()
    explanation: str = ""
    reviewer: str
    adjudicated: bool = True
    review_kind: ReviewKind


class OutcomeRecord(BaseModel):
    """What happened after the gate: whether the tool ran and what the backend said."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExecutionOutcome
    state_changed: bool | None = None
    backend_error: str | None = None
    agent_db_hash_after: str | None = None
    user_db_hash_after: str | None = None


# Called inside the write's transaction with the new write and the session's earlier writes as
# (action, args); returns the snapshot and the deterministic verdict to commit with it. It must
# not use the store.
PreExecution = Callable[
    [CapturedWrite, list[tuple[str, dict[str, Any]]]], tuple[PreActionSnapshot, VerdictRecord]
]


class ProposedActionRecord(BaseModel):
    """One proposed write with its verdicts for one oracle version, its backend outcome and its
    benchmark match. It carries no task outcome: that belongs to the simulation
    (`BenchStore.simulation_outcomes`), so per-write rows never count a task twice."""

    model_config = ConfigDict(frozen=True)

    write_id: str
    ts: str
    session_id: str
    seq: int
    domain: str | None
    task_id: str | None
    agent_model: str | None
    trial: int | None
    action: str
    args: dict[str, Any]
    state_hash: str
    rubric_hash: str | None
    oracle_version: str
    deterministic_decision: PolicyDecision
    deterministic_reason_codes: tuple[str, ...]
    deterministic_explanation: str
    manual_decision: PolicyDecision | None = None
    manual_reason_codes: tuple[str, ...] | None = None
    manual_reviewer: str | None = None
    manual_review_kind: ReviewKind | None = None
    effective_decision: PolicyDecision
    effective_source: Literal["deterministic_oracle", "manual_review"]
    benchmark_match: BenchmarkMatch | None = None
    execution_outcome: ExecutionOutcome | None = None
    state_changed: bool | None = None
    backend_error: str | None = None


class SimulationOutcome(BaseModel):
    """One simulation's final task outcome (`hatchway.bench.outcomes.task_outcome`)."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    mode: str
    domain: str
    task_id: str
    trial: int
    agent_model: str
    status: str
    reward: float | None
    final_task_outcome: TaskOutcome | None


class BenchStore:
    """Thread-safe handle on one benchmark SQLite file. Several processes may share a file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False, timeout=30.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._check_schema_version()
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_GATED_SCHEMA)
        self._conn.executescript(_VERDICT_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")

    def _check_schema_version(self) -> None:
        """Refuse a file written before schema 2: its writes have trace labels, not policy
        verdicts, and no pre-action snapshots to compute verdicts from."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'captured_writes'"
        ).fetchone()
        if has_tables and version != STORE_SCHEMA_VERSION:
            self._conn.close()
            raise IncompatibleStoreError(
                f"{self.path} has store schema {version}, not {STORE_SCHEMA_VERSION}: it "
                "predates policy verdicts. Regenerate it (capture again into a new file)."
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> BenchStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def record_write(
        self,
        *,
        session_id: str,
        action: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any],
        rubric_hash: str | None,
        known_action: bool = True,
        domain: str | None = None,
        agent_model: str | None = None,
        task_id: str | None = None,
        trial: int | None = None,
        pre_execution: PreExecution | None = None,
    ) -> CapturedWrite:
        """Append one write and commit it before returning. Errors propagate to the caller.

        With `pre_execution`, the write's pre-action snapshot and deterministic policy verdict
        are computed from the new write (its `seq` and the session's earlier writes are fixed
        inside the transaction) and committed with it, all or nothing. The caller runs the tool
        only after this returns.
        """
        args_json = canonical_json(dict(args))
        context_json = canonical_json(dict(context))
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                prior = self._conn.execute(
                    "SELECT action, args FROM captured_writes WHERE session_id = ? ORDER BY seq",
                    (session_id,),
                ).fetchall()
                prior_writes = [(r["action"], json.loads(r["args"])) for r in prior]
                text = build_state(action, args, context, prior_writes)
                write = CapturedWrite(
                    write_id=new_ulid(),
                    ts=_now(),
                    domain=domain,
                    agent_model=agent_model,
                    task_id=task_id,
                    trial=trial,
                    session_id=session_id,
                    seq=len(prior),
                    action=action,
                    known_action=known_action,
                    args=json.loads(args_json),
                    context=json.loads(context_json),
                    state_text=text,
                    state_hash=state_hash(text),
                    state_version=STATE_VERSION,
                    rubric_hash=rubric_hash,
                )
                self._conn.execute(
                    f"INSERT INTO captured_writes ({_WRITE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        write.write_id,
                        write.ts,
                        domain,
                        agent_model,
                        task_id,
                        trial,
                        session_id,
                        write.seq,
                        action,
                        int(known_action),
                        args_json,
                        context_json,
                        write.state_text,
                        write.state_hash,
                        STATE_VERSION,
                        rubric_hash,
                    ),
                )
                if pre_execution is not None:
                    snapshot, verdict = pre_execution(write, prior_writes)
                    self._insert_snapshot(write.write_id, snapshot)
                    self._insert_verdict(write.write_id, verdict)
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return write

    # --- Policy verdicts (schema 2) -----------------------------------------------------------

    def _put_blob(self, value: Mapping[str, Any]) -> str:
        text = canonical_json(dict(value))
        digest = hashlib.sha256(text.encode()).hexdigest()
        self._conn.execute(
            "INSERT INTO db_blobs (hash, data) VALUES (?, ?) ON CONFLICT (hash) DO NOTHING",
            (digest, zlib.compress(text.encode(), 6)),
        )
        return digest

    def _get_blob(self, digest: str | None) -> dict[str, Any] | None:
        if digest is None:
            return None
        row = self._conn.execute("SELECT data FROM db_blobs WHERE hash = ?", (digest,)).fetchone()
        if row is None:
            raise KeyError(f"no db blob {digest}")
        return json.loads(zlib.decompress(row["data"]))

    def _insert_snapshot(self, write_id: str, snapshot: PreActionSnapshot) -> None:
        agent = self._put_blob(snapshot.agent_db)
        user = None if snapshot.user_db is None else self._put_blob(snapshot.user_db)
        self._conn.execute(
            "INSERT INTO pre_action_snapshots (write_id, tool_call_id, agent_db_hash, "
            "user_db_hash, messages, proposing_text, domain_policy_hash, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                write_id,
                snapshot.tool_call_id,
                agent,
                user,
                canonical_json(snapshot.messages),
                snapshot.proposing_text,
                snapshot.domain_policy_hash,
                _now(),
            ),
        )

    def _insert_verdict(self, write_id: str, verdict: VerdictRecord) -> None:
        self._conn.execute(
            "INSERT INTO policy_verdicts (write_id, oracle_version, expected_decision, "
            "should_execute_now, reason_codes, explanation, evidence, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                write_id,
                verdict.oracle_version,
                verdict.expected_decision,
                None if verdict.should_execute_now is None else int(verdict.should_execute_now),
                canonical_json(list(verdict.reason_codes)),
                verdict.explanation,
                canonical_json(verdict.evidence),
                _now(),
            ),
        )

    def snapshot(self, write_id: str) -> PreActionSnapshot | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM pre_action_snapshots WHERE write_id = ?", (write_id,)
            ).fetchone()
            if row is None:
                return None
            return PreActionSnapshot(
                tool_call_id=row["tool_call_id"],
                agent_db=self._get_blob(row["agent_db_hash"]) or {},
                user_db=self._get_blob(row["user_db_hash"]),
                messages=json.loads(row["messages"]),
                proposing_text=row["proposing_text"],
                domain_policy_hash=row["domain_policy_hash"],
            )

    def record_verdict(self, write_id: str, verdict: VerdictRecord) -> bool:
        """Append a deterministic verdict for an oracle version the write has no verdict for
        yet (a new oracle version over stored snapshots). Returns False if one exists."""
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM policy_verdicts WHERE write_id = ? AND oracle_version = ?",
                (write_id, verdict.oracle_version),
            ).fetchone()
            if exists:
                return False
            self._insert_verdict(write_id, verdict)
        return True

    def verdict(self, write_id: str, oracle_version: str) -> VerdictRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM policy_verdicts WHERE write_id = ? AND oracle_version = ?",
                (write_id, oracle_version),
            ).fetchone()
        return None if row is None else _verdict_from_row(row)

    def oracle_versions(self) -> list[str]:
        """Oracle versions with verdicts in this store, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT oracle_version, MIN(rowid) AS first FROM policy_verdicts "
                "GROUP BY oracle_version ORDER BY first"
            ).fetchall()
        return [r["oracle_version"] for r in rows]

    def record_manual_verdict(
        self,
        *,
        write_id: str,
        oracle_version: str,
        expected_decision: PolicyDecision,
        reviewer: str,
        review_kind: ReviewKind,
        reason_codes: Sequence[str] = (),
        explanation: str = "",
        adjudicated: bool = True,
    ) -> ManualVerdict:
        """Append a reviewer's verdict. Earlier reviews are kept; the latest adjudicated one
        is the effective verdict for that oracle version."""
        review = ManualVerdict(
            review_id=new_ulid(),
            write_id=write_id,
            oracle_version=oracle_version,
            expected_decision=expected_decision,
            reason_codes=tuple(sorted(reason_codes)),
            explanation=explanation,
            reviewer=reviewer,
            adjudicated=adjudicated,
            review_kind=review_kind,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO manual_verdicts (review_id, write_id, oracle_version, "
                "expected_decision, reason_codes, explanation, reviewer, adjudicated, "
                "review_kind, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review.review_id,
                    write_id,
                    oracle_version,
                    expected_decision,
                    canonical_json(list(review.reason_codes)),
                    explanation,
                    reviewer,
                    int(adjudicated),
                    review_kind,
                    _now(),
                ),
            )
        return review

    def manual_verdicts(self, oracle_version: str | None = None) -> list[ManualVerdict]:
        query = "SELECT * FROM manual_verdicts"
        params: tuple[str, ...] = ()
        if oracle_version is not None:
            query += " WHERE oracle_version = ?"
            params = (oracle_version,)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY rowid", params).fetchall()
        return [
            ManualVerdict(
                review_id=r["review_id"],
                write_id=r["write_id"],
                oracle_version=r["oracle_version"],
                expected_decision=r["expected_decision"],
                reason_codes=tuple(json.loads(r["reason_codes"])),
                explanation=r["explanation"],
                reviewer=r["reviewer"],
                adjudicated=bool(r["adjudicated"]),
                review_kind=r["review_kind"],
            )
            for r in rows
        ]

    def record_outcome(self, write_id: str, outcome: OutcomeRecord) -> None:
        """Append what happened after the gate. Refused (by a trigger) unless the write's
        snapshot and verdict were committed first."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO execution_outcomes (write_id, outcome, state_changed, "
                "backend_error, agent_db_hash_after, user_db_hash_after, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    write_id,
                    outcome.outcome,
                    None if outcome.state_changed is None else int(outcome.state_changed),
                    outcome.backend_error,
                    outcome.agent_db_hash_after,
                    outcome.user_db_hash_after,
                    _now(),
                ),
            )

    def outcome(self, write_id: str) -> OutcomeRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM execution_outcomes WHERE write_id = ?", (write_id,)
            ).fetchone()
        if row is None:
            return None
        return OutcomeRecord(
            outcome=row["outcome"],
            state_changed=None if row["state_changed"] is None else bool(row["state_changed"]),
            backend_error=row["backend_error"],
            agent_db_hash_after=row["agent_db_hash_after"],
            user_db_hash_after=row["user_db_hash_after"],
        )

    def record_benchmark_match(
        self, write_id: str, match: BenchmarkMatch, rule: str, gold_index: int | None
    ) -> bool:
        """Set a write's τ² trace match once. Returns False if it already has one."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO benchmark_matches (write_id, match, rule, gold_index, ts) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (write_id) DO NOTHING",
                (write_id, match, rule, gold_index, _now()),
            )
        return cursor.rowcount == 1

    def benchmark_matches(self) -> dict[str, BenchmarkMatch]:
        with self._lock:
            rows = self._conn.execute("SELECT write_id, match FROM benchmark_matches").fetchall()
        return {r["write_id"]: r["match"] for r in rows}

    def proposed_actions(
        self, oracle_version: str, *, require_verdicts: bool = True
    ) -> list[ProposedActionRecord]:
        """Every captured write with its verdicts for `oracle_version`, in capture order.

        The effective decision is the latest adjudicated manual verdict for the same oracle
        version, else the deterministic one; both are returned for audit. With
        `require_verdicts`, a write with no deterministic verdict for the version raises
        KeyError; otherwise such writes are left out.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT w.*, v.expected_decision AS v_decision, v.reason_codes AS v_reasons,
                       v.explanation AS v_explanation,
                       b.match AS b_match, o.outcome AS o_outcome,
                       o.state_changed AS o_state_changed, o.backend_error AS o_backend_error
                FROM captured_writes AS w
                LEFT JOIN policy_verdicts AS v
                       ON v.write_id = w.write_id AND v.oracle_version = ?
                LEFT JOIN benchmark_matches AS b ON b.write_id = w.write_id
                LEFT JOIN execution_outcomes AS o ON o.write_id = w.write_id
                ORDER BY w.rowid
                """,
                (oracle_version,),
            ).fetchall()
            manual: dict[str, sqlite3.Row] = {}
            for m in self._conn.execute(
                "SELECT * FROM manual_verdicts WHERE oracle_version = ? AND adjudicated = 1 "
                "ORDER BY rowid",
                (oracle_version,),
            ):
                manual[m["write_id"]] = m  # the latest adjudication wins
        out = []
        missing = []
        for r in rows:
            if r["v_decision"] is None:
                missing.append(r["write_id"])
                continue
            m = manual.get(r["write_id"])
            out.append(
                ProposedActionRecord(
                    write_id=r["write_id"],
                    ts=r["ts"],
                    session_id=r["session_id"],
                    seq=r["seq"],
                    domain=r["domain"],
                    task_id=r["task_id"],
                    agent_model=r["agent_model"],
                    trial=r["trial"],
                    action=r["action"],
                    args=json.loads(r["args"]),
                    state_hash=r["state_hash"],
                    rubric_hash=r["rubric_hash"],
                    oracle_version=oracle_version,
                    deterministic_decision=r["v_decision"],
                    deterministic_reason_codes=tuple(json.loads(r["v_reasons"])),
                    deterministic_explanation=r["v_explanation"],
                    manual_decision=None if m is None else m["expected_decision"],
                    manual_reason_codes=None if m is None else tuple(json.loads(m["reason_codes"])),
                    manual_reviewer=None if m is None else m["reviewer"],
                    manual_review_kind=None if m is None else m["review_kind"],
                    effective_decision=r["v_decision"] if m is None else m["expected_decision"],
                    effective_source="deterministic_oracle" if m is None else "manual_review",
                    benchmark_match=r["b_match"],
                    execution_outcome=r["o_outcome"],
                    state_changed=None
                    if r["o_state_changed"] is None
                    else bool(r["o_state_changed"]),
                    backend_error=r["o_backend_error"],
                )
            )
        if missing and require_verdicts:
            raise KeyError(
                f"{len(missing)} writes have no verdict for oracle version {oracle_version!r} "
                f"(first: {missing[0]}); run `python -m hatchway.bench.tau2.verdicts --recompute`"
            )
        return out

    def simulation_outcomes(self, status: str | None = "done") -> list[SimulationOutcome]:
        """One row per simulation (not per write), with its final task outcome."""
        return [
            SimulationOutcome(
                session_id=s.session_id,
                mode=s.mode,
                domain=s.domain,
                task_id=s.task_id,
                trial=s.trial,
                agent_model=s.agent_model,
                status=s.status,
                reward=s.reward,
                final_task_outcome=task_outcome(s.reward),
            )
            for s in self.simulations(status)
        ]

    def writes(self, session_id: str | None = None) -> list[CapturedWrite]:
        query = "SELECT * FROM captured_writes"
        params: tuple[str, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY rowid", params).fetchall()
        return [_write_from_row(row) for row in rows]

    def put_score(self, record: ScoreRecord) -> bool:
        """Store a judge result. An `error` row may be replaced; an `ok` row never is.

        Returns True if the row was written.
        """
        vector = record.question_vector.model_dump_json() if record.question_vector else None
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO scores (state_hash, rubric_hash, judge_name, model_id, status,
                    question_vector, attempts, first_attempt_latency_ms, latency_ms, cost_usd,
                    error, ts, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (state_hash, rubric_hash, judge_name, model_id) DO UPDATE SET
                    status = excluded.status,
                    question_vector = excluded.question_vector,
                    attempts = excluded.attempts,
                    first_attempt_latency_ms = excluded.first_attempt_latency_ms,
                    latency_ms = excluded.latency_ms,
                    cost_usd = excluded.cost_usd,
                    error = excluded.error,
                    ts = excluded.ts,
                    raw_response = excluded.raw_response
                WHERE scores.status = 'error'
                """,
                (
                    *record.key,
                    record.status,
                    vector,
                    record.attempts,
                    record.first_attempt_latency_ms,
                    record.latency_ms,
                    record.cost_usd,
                    record.error,
                    _now(),
                    record.raw_response,
                ),
            )
        return cursor.rowcount == 1

    def get_score(
        self, state_hash: str, rubric_hash: str, judge_name: str, model_id: str
    ) -> ScoreRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scores WHERE state_hash = ? AND rubric_hash = ? "
                "AND judge_name = ? AND model_id = ?",
                (state_hash, rubric_hash, judge_name, model_id),
            ).fetchone()
        if row is None:
            return None
        fields = dict(row)
        del fields["ts"]
        if fields["question_vector"] is not None:
            fields["question_vector"] = QuestionVector.model_validate_json(
                fields["question_vector"]
            )
        return ScoreRecord(**fields)

    def ok_score_keys(self, judge_name: str, model_id: str) -> set[tuple[str, str]]:
        """The (state_hash, rubric_hash) pairs this judge and model already scored `ok`."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_hash, rubric_hash FROM scores "
                "WHERE judge_name = ? AND model_id = ? AND status = 'ok'",
                (judge_name, model_id),
            ).fetchall()
        return {(r["state_hash"], r["rubric_hash"]) for r in rows}

    def put_skip(self, state_hash: str, rubric_hash: str, reason: str) -> bool:
        """Record that a score key is not sent to judges. The first reason recorded is kept.

        Returns True if the row was written.
        """
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO scoring_skips (state_hash, rubric_hash, reason, ts) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (state_hash, rubric_hash) DO NOTHING",
                (state_hash, rubric_hash, reason, _now()),
            )
        return cursor.rowcount == 1

    def skips(self) -> dict[tuple[str, str], str]:
        """Skipped score keys and their reasons."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_hash, rubric_hash, reason FROM scoring_skips"
            ).fetchall()
        return {(r["state_hash"], r["rubric_hash"]): r["reason"] for r in rows}

    # --- Live gated pass (M7) ----------------------------------------------------------------

    def record_gated(self, decision: GatedDecision) -> None:
        """Append one gated decision and its judge calls in one transaction."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO gated_decisions (write_id, ts, session_id, arm, decision,
                        ask_reason, decided_by, p_ok, threshold, approver_mode, approver_answer,
                        approver_flipped, executed, repeat_same_args, repeat_same_action)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.write_id,
                        _now(),
                        decision.session_id,
                        decision.arm,
                        decision.decision,
                        decision.ask_reason,
                        decision.decided_by,
                        decision.p_ok,
                        decision.threshold,
                        decision.approver_mode,
                        decision.approver_answer,
                        None
                        if decision.approver_flipped is None
                        else int(decision.approver_flipped),
                        int(decision.executed),
                        int(decision.repeat_same_args),
                        int(decision.repeat_same_action),
                    ),
                )
                self._conn.executemany(
                    "INSERT INTO gated_judge_calls (write_id, judge_name, model_id, status, "
                    "latency_ms, cost_usd, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            decision.write_id,
                            c.judge_name,
                            c.model_id,
                            c.status,
                            c.latency_ms,
                            c.cost_usd,
                            c.error,
                        )
                        for c in decision.judge_calls
                    ],
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def gated_decisions(self, session_id: str | None = None) -> list[GatedDecision]:
        """Gated decisions in the order they were made, with their judge calls."""
        where = "" if session_id is None else " WHERE d.session_id = ?"
        params: tuple[str, ...] = () if session_id is None else (session_id,)
        with self._lock:
            rows = self._conn.execute(
                "SELECT d.* FROM gated_decisions AS d" + where + " ORDER BY d.rowid", params
            ).fetchall()
            calls: dict[str, list[GatedJudgeCall]] = {}
            for row in self._conn.execute(
                "SELECT c.* FROM gated_judge_calls AS c JOIN gated_decisions AS d "
                "USING (write_id)" + where + " ORDER BY c.rowid",
                params,
            ):
                fields = dict(row)
                calls.setdefault(fields.pop("write_id"), []).append(GatedJudgeCall(**fields))
        out = []
        for row in rows:
            fields = dict(row)
            del fields["ts"]
            for flag in ("executed", "repeat_same_args", "repeat_same_action"):
                fields[flag] = bool(fields[flag])
            if fields["approver_flipped"] is not None:
                fields["approver_flipped"] = bool(fields["approver_flipped"])
            fields["judge_calls"] = tuple(calls.get(fields["write_id"], ()))
            out.append(GatedDecision(**fields))
        return out

    # --- OpenAI Batch API jobs ------------------------------------------------------------

    def add_batch(
        self,
        batch_key: str,
        *,
        judge_name: str,
        model_id: str,
        keys: list[tuple[str, str]],
        n_requests: int,
        estimated_cost_usd: float | None,
    ) -> None:
        """Record a batch job and the score keys it covers, before anything is uploaded."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO openai_batches (batch_key, judge_name, model_id, n_requests, "
                    "estimated_cost_usd, status, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, ?, ?, 'preparing', ?, ?)",
                    (batch_key, judge_name, model_id, n_requests, estimated_cost_usd, now, now),
                )
                self._conn.executemany(
                    "INSERT INTO openai_batch_keys (batch_key, state_hash, rubric_hash) "
                    "VALUES (?, ?, ?)",
                    [(batch_key, s, r) for s, r in keys],
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def update_batch(
        self,
        batch_key: str,
        *,
        input_file_id: str | None = None,
        batch_id: str | None = None,
        status: str | None = None,
        ingested: bool | None = None,
    ) -> None:
        """Set the given fields of a batch job; fields left as None are kept."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE openai_batches SET input_file_id = COALESCE(?, input_file_id), "
                "batch_id = COALESCE(?, batch_id), status = COALESCE(?, status), "
                "ingested = COALESCE(?, ingested), updated_ts = ? WHERE batch_key = ?",
                (
                    input_file_id,
                    batch_id,
                    status,
                    None if ingested is None else int(ingested),
                    _now(),
                    batch_key,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"no batch {batch_key}")

    def open_batches(self, judge_name: str, model_id: str) -> list[BatchJob]:
        """Batch jobs for this judge whose results are not ingested yet, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM openai_batches WHERE judge_name = ? AND model_id = ? "
                "AND ingested = 0 ORDER BY created_ts, batch_key",
                (judge_name, model_id),
            ).fetchall()
        return [_batch_from_row(row) for row in rows]

    def batches(self) -> list[BatchJob]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM openai_batches ORDER BY created_ts, batch_key"
            ).fetchall()
        return [_batch_from_row(row) for row in rows]

    def batch_keys(self, batch_key: str) -> list[tuple[str, str]]:
        """The (state_hash, rubric_hash) keys a batch job covers."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_hash, rubric_hash FROM openai_batch_keys WHERE batch_key = ? "
                "ORDER BY rowid",
                (batch_key,),
            ).fetchall()
        return [(r["state_hash"], r["rubric_hash"]) for r in rows]

    # --- τ² simulations ----------------------------------------------------------------------

    def start_simulation(
        self,
        *,
        session_id: str,
        mode: Literal["wrapped", "unwrapped", "gated"],
        domain: str,
        task_id: str,
        trial: int,
        agent_model: str,
        user_model: str | None,
        seed: int | None,
    ) -> None:
        """Record that a simulation started; its writes are abandoned until it finishes."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO simulations (session_id, mode, domain, task_id, trial, agent_model, "
                "user_model, seed, status, started_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    mode,
                    domain,
                    task_id,
                    trial,
                    agent_model,
                    user_model,
                    seed,
                    "running",
                    _now(),
                ),
            )

    def finish_simulation(
        self,
        session_id: str,
        *,
        reward: float | None,
        agent_cost_usd: float | None,
        user_cost_usd: float | None,
        simulation: str,
    ) -> None:
        """Mark a simulation done and keep its τ² `SimulationRun` JSON, committed at once."""
        self._end_simulation(
            session_id,
            "done",
            reward=reward,
            agent_cost_usd=agent_cost_usd,
            user_cost_usd=user_cost_usd,
            simulation=simulation,
        )

    def fail_simulation(self, session_id: str, error: str) -> None:
        """Mark a simulation failed; its key runs again on the next run."""
        self._end_simulation(session_id, "failed", error=error)

    def _end_simulation(self, session_id: str, status: str, **fields: Any) -> None:
        columns = ", ".join(f"{name} = ?" for name in fields)
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE simulations SET status = ?, {columns}, finished_ts = ? "
                "WHERE session_id = ? AND status = 'running'",
                (status, *fields.values(), _now(), session_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"no running simulation {session_id}")

    def simulations(self, status: str | None = None) -> list[SimulationRecord]:
        query = "SELECT * FROM simulations"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY rowid", params).fetchall()
        return [_simulation_from_row(row) for row in rows]

    def done_simulations(self) -> dict[SimulationKey, SimulationRecord]:
        return {sim.key: sim for sim in self.simulations("done")}

    def abandoned_session_ids(self) -> set[str]:
        """Sessions of simulations that started but never finished (killed or failed runs).
        Their captured writes are partial conversations and are not scored."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id FROM simulations WHERE status != 'done'"
            ).fetchall()
        return {r["session_id"] for r in rows}


def _batch_from_row(row: sqlite3.Row) -> BatchJob:
    fields = {k: row[k] for k in BatchJob.model_fields}
    fields["ingested"] = bool(fields["ingested"])
    return BatchJob(**fields)


def _simulation_from_row(row: sqlite3.Row) -> SimulationRecord:
    return SimulationRecord(**{k: row[k] for k in SimulationRecord.model_fields})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _verdict_from_row(row: sqlite3.Row) -> VerdictRecord:
    return VerdictRecord(
        oracle_version=row["oracle_version"],
        expected_decision=row["expected_decision"],
        should_execute_now=None
        if row["should_execute_now"] is None
        else bool(row["should_execute_now"]),
        reason_codes=tuple(json.loads(row["reason_codes"])),
        explanation=row["explanation"],
        evidence=json.loads(row["evidence"]),
    )


def _write_from_row(row: sqlite3.Row) -> CapturedWrite:
    fields = dict(row)
    fields["args"] = json.loads(fields["args"])
    fields["context"] = json.loads(fields["context"])
    fields["known_action"] = bool(fields["known_action"])
    return CapturedWrite(**fields)
