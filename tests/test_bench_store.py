import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from hatchway.bench import BenchStore, ScoreRecord
from hatchway.bench.store import STORE_SCHEMA_VERSION, IncompatibleStoreError
from hatchway.judges import QuestionVector, YesNoAnswer


@pytest.fixture
def store(tmp_path: Path):
    with BenchStore(tmp_path / "bench.db") as s:
        yield s


def _record(store: BenchStore, session_id: str = "s1", **overrides):
    fields = dict(
        session_id=session_id,
        action="refund_order",
        args={"order_id": "1", "amount": 20},
        context={"conversation": "refund please"},
        rubric_hash="r" * 64,
        task_id="t1",
        trial=0,
    )
    return store.record_write(**(fields | overrides))


def _ok_score(state_hash: str, judge: str = "jev", p_yes: float = 0.9) -> ScoreRecord:
    return ScoreRecord(
        state_hash=state_hash,
        rubric_hash="r" * 64,
        judge_name=judge,
        model_id=f"{judge}-1",
        status="ok",
        question_vector=QuestionVector(
            judge=judge, model_id=f"{judge}-1", answers={"policy_ok": YesNoAnswer(p_yes=p_yes)}
        ),
        first_attempt_latency_ms=120.0,
        latency_ms=120.0,
        cost_usd=0.001,
    )


def test_identical_writes_in_one_session_get_two_rows_and_share_one_score(store) -> None:
    # Reset the session between writes so both calls render the same state text.
    first = _record(store, session_id="loop-a")
    second = _record(store, session_id="loop-b")
    assert first.state_hash == second.state_hash

    # Same session, same call twice: two rows; the second sees the first as prior history.
    a = _record(store, session_id="s1")
    b = _record(store, session_id="s1")
    assert (a.seq, b.seq) == (0, 1)
    assert a.write_id != b.write_id
    assert len(store.writes("s1")) == 2

    assert store.put_score(_ok_score(first.state_hash))
    for write in (first, second):
        score = store.get_score(write.state_hash, "r" * 64, "jev", "jev-1")
        assert score is not None and score.status == "ok"

    # The first write in s1 has no history either, so it shares the state and the score too.
    assert a.state_hash == first.state_hash and b.state_hash != first.state_hash
    rows = store._conn.execute(
        "SELECT write_id FROM write_scores WHERE state_hash = ?", (first.state_hash,)
    ).fetchall()
    assert {r[0] for r in rows} == {first.write_id, second.write_id, a.write_id}
    assert store._conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 1


def test_seq_and_prior_writes_are_tracked_per_session(store) -> None:
    _record(store, "s1", args={"n": 1})
    _record(store, "s2", args={"n": 1})
    third = _record(store, "s1", action="cancel_order", args={"n": 2})
    assert third.seq == 1
    assert 'refund_order({"n":1})' in third.state_text
    assert [w.seq for w in store.writes("s2")] == [0]


def test_rows_survive_a_hard_crash(tmp_path: Path) -> None:
    db = tmp_path / "crash.db"
    script = textwrap.dedent(
        f"""
        import os
        from hatchway.bench import BenchStore
        store = BenchStore({str(db)!r})
        for i in range(25):
            store.record_write(session_id="s", action="a", args={{"i": i}}, context={{}},
                               rubric_hash=None)
        os._exit(1)  # no close, no cleanup
        """
    )
    result = subprocess.run([sys.executable, "-c", script], check=False)
    assert result.returncode == 1

    with BenchStore(db) as reopened:
        assert [w.args["i"] for w in reopened.writes("s")] == list(range(25))


def test_captured_writes_are_append_only(store) -> None:
    _record(store)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("DELETE FROM captured_writes")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("UPDATE captured_writes SET args = '{}'")


def test_error_scores_can_be_replaced_but_ok_scores_cannot(store) -> None:
    key = "h" * 64
    error = ScoreRecord(
        state_hash=key,
        rubric_hash="r" * 64,
        judge_name="jev",
        model_id="jev-1",
        status="error",
        attempts=3,
        error="timeout",
    )
    assert store.put_score(error)
    assert store.put_score(_ok_score(key, p_yes=0.8))
    assert not store.put_score(_ok_score(key, p_yes=0.1))
    assert not store.put_score(error)

    stored = store.get_score(key, "r" * 64, "jev", "jev-1")
    assert stored is not None
    assert stored.status == "ok" and stored.error is None
    assert stored.question_vector.answers["policy_ok"].p_yes == 0.8
    assert store.get_score(key, "r" * 64, "openai_decisions", "x") is None


def test_score_records_are_consistent() -> None:
    with pytest.raises(ValidationError, match="requires a question_vector"):
        ScoreRecord(state_hash="h", rubric_hash="r", judge_name="j", model_id="m", status="ok")
    with pytest.raises(ValidationError, match="do not match"):
        ScoreRecord(
            state_hash="h",
            rubric_hash="r",
            judge_name="jev",
            model_id="other",
            status="ok",
            question_vector=_ok_score("h").question_vector,
        )


def test_concurrent_sessions_from_threads_and_a_second_handle(tmp_path: Path) -> None:
    db = tmp_path / "shared.db"
    with BenchStore(db) as one, BenchStore(db) as two:

        def run(store: BenchStore, session: str) -> None:
            for i in range(50):
                _record(store, session, args={"i": i})

        threads = [
            threading.Thread(target=run, args=(one if n % 2 else two, f"s{n}")) for n in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for n in range(6):
            assert [w.seq for w in one.writes(f"s{n}")] == list(range(50))


def test_simulations_are_recorded_as_they_start_and_finish(tmp_path) -> None:
    with BenchStore(tmp_path / "sims.db") as store:
        common = dict(
            mode="wrapped",
            domain="retail",
            task_id="0",
            trial=0,
            agent_model="m",
            user_model="u",
            seed=7,
        )
        store.start_simulation(session_id="a", **common)
        assert store.abandoned_session_ids() == {"a"} and store.done_simulations() == {}
        store.fail_simulation("a", "RuntimeError: boom")
        store.start_simulation(session_id="b", **common)
        store.finish_simulation(
            "b", reward=1.0, agent_cost_usd=0.01, user_cost_usd=0.002, simulation="{}"
        )
        assert store.abandoned_session_ids() == {"a"}
        (done,) = store.done_simulations().values()
        assert (done.session_id, done.key) == ("b", ("wrapped", "retail", "0", 0, "m", 7))
        with pytest.raises(KeyError):
            store.finish_simulation(
                "b", reward=1.0, agent_cost_usd=0.0, user_cost_usd=0.0, simulation="{}"
            )
        # A key is done at most once.
        store.start_simulation(session_id="c", **common)
        with pytest.raises(sqlite3.IntegrityError):
            store.finish_simulation(
                "c", reward=0.0, agent_cost_usd=0.0, user_cost_usd=0.0, simulation="{}"
            )


_SCHEMA_1_FILE = """
CREATE TABLE captured_writes (write_id TEXT PRIMARY KEY, label TEXT);
INSERT INTO captured_writes VALUES ('w', 'correct');
"""


def test_a_store_from_before_policy_verdicts_is_refused(tmp_path) -> None:
    path = tmp_path / "schema1.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA_1_FILE)
    with pytest.raises(IncompatibleStoreError, match="predates policy verdicts"):
        BenchStore(path)
    with BenchStore(tmp_path / "new.db") as store:  # a new file gets the current version
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == STORE_SCHEMA_VERSION
    with BenchStore(tmp_path / "new.db"):  # and opens again
        pass
