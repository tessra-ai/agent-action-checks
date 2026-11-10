"""Read a benchmark store, τ² results files and the policy into one in-memory view.

Everything is read-only: the store is opened with `mode=ro`, never through `BenchStore`, which
creates tables. Columns and tables that M5 adds (`scores.raw_response`, `scoring_skips`) are
found by introspecting the schema and are optional, as are the policy-verdict tables.

Each write carries four separate things: its effective policy verdict for one oracle version
(a manual adjudication over the deterministic oracle; both kept), each replayed arm's decision
(from M6's `frozen_*.json`, if given), its τ² benchmark trace match, and what the backend did.
The final task outcome belongs to the simulation, not the write.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hatchway.bench.frozen import FrozenArm, two_judge_parts
from hatchway.bench.outcomes import task_outcome
from hatchway.bench.provenance import git_commit
from hatchway.bench.tau2.label import Explanation, GoldAction, GroundTruth, explain_session
from hatchway.judges.base import Question, QuestionVector
from hatchway.policy import Policy, load_policy

ScoreKey = tuple[str, str]  # (state_hash, rubric_hash)
JudgeKey = tuple[str, str]  # (judge_name, model_id)
TaskKey = tuple[str, str]  # (domain, task_id); "" for a missing value


@dataclass
class Write:
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
    rubric_hash: str | None
    verdict: str | None = None  # effective policy verdict; None when no verdict is stored
    verdict_source: str | None = None  # deterministic_oracle or manual_review
    deterministic: dict[str, Any] | None = None  # decision, reason_codes, explanation, evidence
    manual: dict[str, Any] | None = None  # the latest adjudicated review, if any
    reviews: list[dict[str, Any]] = field(default_factory=list)  # every review, oldest first
    benchmark_match: str | None = None
    outcome: dict[str, Any] | None = None  # outcome, state_changed, backend_error
    arm_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    mode: str | None = None  # the simulation's mode: wrapped (shadow), gated, unwrapped
    split: str | None = None  # train or test in the replay, if one was given
    explanation: Explanation | None = None

    @property
    def score_key(self) -> ScoreKey | None:
        return None if self.rubric_hash is None else (self.state_hash, self.rubric_hash)

    @property
    def task_key(self) -> TaskKey:
        return (self.domain or "", self.task_id or "")


@dataclass
class Score:
    judge_name: str
    model_id: str
    status: str
    question_vector: dict[str, Any] | None
    attempts: int
    first_attempt_latency_ms: float | None
    latency_ms: float | None
    cost_usd: float | None
    error: str | None
    ts: str
    raw_response: str | None = None


@dataclass
class Skip:
    reason: str
    ts: str
    judge: JudgeKey | None = None  # None: the skip applies to every judge


@dataclass
class Simulation:
    id: str
    task_id: str
    trial: int | None
    domain: str
    agent_model: str
    source: str
    reward: float | None
    termination_reason: str | None
    data: dict[str, Any]

    @property
    def outcome(self) -> str | None:
        """The final task outcome (`hatchway.bench.outcomes.task_outcome`)."""
        return task_outcome(self.reward)

    @property
    def passed(self) -> bool:
        return self.outcome == "PASS"

    @property
    def task_key(self) -> TaskKey:
        return (self.domain, self.task_id)


@dataclass
class Strategy:
    """A replayed decision strategy (an M6 arm) as the report presents it. Names and kinds come
    from the replay's `metrics.json`; without them the arm letter is all there is."""

    arm: str
    display_name: str | None = None
    kind: str | None = None  # single_judge, fitted_single_judge, combination
    judge: str | None = None  # the one judge a single-judge strategy uses
    judges: tuple[str, ...] = ()
    description: str | None = None

    @property
    def label(self) -> str:
        """ "OpenAI Decisions (Arm D)"; "Arm D" without metadata."""
        return f"{self.display_name} (Arm {self.arm})" if self.display_name else f"Arm {self.arm}"


@dataclass
class Bench:
    writes: list[Write]
    scores: dict[ScoreKey, dict[JudgeKey, Score]]
    skips: dict[ScoreKey, list[Skip]]
    judges: list[JudgeKey]
    simulations: dict[str, Simulation]
    tasks: dict[TaskKey, dict[str, Any]]
    policy: Policy | None
    has_raw_response: bool
    has_skips: bool
    oracle_version: str | None = None
    oracle_versions: list[str] = field(default_factory=list)
    arms: dict[str, FrozenArm] = field(default_factory=dict)
    replay_metrics: dict[str, Any] | None = None
    strategies: dict[str, Strategy] = field(default_factory=dict)
    judge_names: dict[str, str] = field(default_factory=dict)  # judge -> display name
    provenance: dict[str, Any] = field(default_factory=dict)
    supported_actions: list[tuple[str, str]] = field(default_factory=list)
    by_session: dict[str, list[Write]] = field(default_factory=dict)
    by_score_key: dict[ScoreKey, list[Write]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        by_session: dict[str, list[Write]] = defaultdict(list)
        by_key: dict[ScoreKey, list[Write]] = defaultdict(list)
        for w in self.writes:
            by_session[w.session_id].append(w)
            if w.score_key is not None:
                by_key[w.score_key].append(w)
        for ws in by_session.values():
            ws.sort(key=lambda w: w.seq)
        self.by_session = dict(by_session)
        self.by_score_key = dict(by_key)

    def questions(self, write: Write) -> list[Question] | None:
        """The policy's questions for this write's action, or None if the policy does not
        define it or its rubric is not the one the write was captured with."""
        if self.policy is None or write.action not in self.policy.actions:
            return None
        action = self.policy.actions[write.action]
        if not action.questions or action.rubric_hash != write.rubric_hash:
            return None
        return list(action.questions.values())

    def skip_for(self, key: ScoreKey | None, judge: JudgeKey) -> Skip | None:
        if key is None:
            return None
        matches = [s for s in self.skips.get(key, []) if s.judge in (None, judge)]
        return max(matches, key=lambda s: s.ts) if matches else None

    def ground_truth(self, key: TaskKey) -> GroundTruth | None:
        task = self.tasks.get(key)
        return None if task is None else ground_truth(task)


def load(
    store: str | Path,
    results: Iterable[str | Path] = (),
    policy: str | Path | None = None,
    *,
    oracle_version: str | None = None,
    replay: str | Path | None = None,
) -> Bench:
    """`oracle_version` picks the verdicts shown (default: the current oracle's if stored, else
    the latest). `replay` is an M6 output directory; its `frozen_*.json` arms are applied to
    every write's stored scores."""
    conn = sqlite3.connect(f"{Path(store).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM captured_writes ORDER BY rowid")
        writes = [_write(row) for row in rows]
        versions, oracle_version = _verdicts(conn, writes, oracle_version)
        modes, run_models = _simulation_modes(conn)
        for w in writes:
            w.mode = modes.get(w.session_id)
        score_columns = _columns(conn, "scores")
        has_raw = "raw_response" in score_columns
        scores: dict[ScoreKey, dict[JudgeKey, Score]] = defaultdict(dict)
        for row in conn.execute("SELECT * FROM scores"):
            vector = row["question_vector"]
            scores[(row["state_hash"], row["rubric_hash"])][
                (row["judge_name"], row["model_id"])
            ] = Score(
                judge_name=row["judge_name"],
                model_id=row["model_id"],
                status=row["status"],
                question_vector=json.loads(vector) if vector is not None else None,
                attempts=row["attempts"],
                first_attempt_latency_ms=row["first_attempt_latency_ms"],
                latency_ms=row["latency_ms"],
                cost_usd=row["cost_usd"],
                error=row["error"],
                ts=row["ts"],
                raw_response=row["raw_response"] if has_raw else None,
            )
        skip_columns = _columns(conn, "scoring_skips")
        skips: dict[ScoreKey, list[Skip]] = defaultdict(list)
        if skip_columns:
            for row in conn.execute("SELECT * FROM scoring_skips"):
                judge = None
                if "judge_name" in skip_columns and row["judge_name"] is not None:
                    model = row["model_id"] if "model_id" in skip_columns else None
                    judge = (row["judge_name"], model or "")
                skips[(row["state_hash"], row["rubric_hash"])].append(
                    Skip(reason=str(row["reason"]), ts=str(row["ts"]), judge=judge)
                )
    finally:
        conn.close()

    simulations, tasks = load_results(results)
    judges = sorted({j for by_judge in scores.values() for j in by_judge})
    for skip_list in skips.values():
        for s in skip_list:
            if s.judge is not None and s.judge not in judges:
                judges.append(s.judge)
    arms = load_arms(replay) if replay is not None else {}
    replay_metrics = None
    if replay is not None and (Path(replay) / "metrics.json").is_file():
        replay_metrics = json.loads((Path(replay) / "metrics.json").read_text())
    from hatchway.bench.tau2.verdicts import VALIDATORS

    provenance = {
        **_results_summary(results),
        "oracle_version": oracle_version,
        "replay_oracle_version": (replay_metrics or {}).get("oracle_version"),
        "replay_seed": (replay_metrics or {}).get("seed"),
        "decision_rule": (replay_metrics or {}).get("decision_rule"),
        **run_models,
        "judge_models": sorted({f"{j} {m}" for by_judge in scores.values() for j, m in by_judge}),
        # Stores captured outside the harness have no simulations rows: use the writes'.
        "agent_models": run_models["agent_models"]
        or sorted({w.agent_model for w in writes if w.agent_model}),
        "report_commit": git_commit(),
    }
    bench = Bench(
        writes=writes,
        scores=dict(scores),
        skips=dict(skips),
        judges=judges,
        simulations=simulations,
        tasks=tasks,
        policy=load_policy(policy) if policy is not None else None,
        has_raw_response=has_raw,
        has_skips=bool(skip_columns),
        oracle_version=oracle_version,
        oracle_versions=versions,
        arms=arms,
        replay_metrics=replay_metrics,
        strategies=strategies(arms, replay_metrics),
        judge_names=dict((replay_metrics or {}).get("judge_display_names") or {}),
        provenance=provenance,
        supported_actions=sorted(VALIDATORS),
    )
    split = ((replay_metrics or {}).get("split") or {}).get("write_ids") or {}
    by_id = {w.write_id: w for w in bench.writes}
    for name in ("train", "test"):
        for write_id in split.get(name, []):
            if write_id in by_id:
                by_id[write_id].split = name
    for w in bench.writes:
        w.arm_decisions = {name: arm_decision(arm, bench, w) for name, arm in arms.items()}
    for session in bench.by_session.values():
        truth = bench.ground_truth(session[0].task_key)
        if truth is None or len({w.task_key for w in session}) != 1:
            continue
        for w, e in zip(
            session, explain_session([(w.action, w.args) for w in session], truth), strict=True
        ):
            w.explanation = e
    return bench


def load_results(
    paths: Iterable[str | Path],
) -> tuple[dict[str, Simulation], dict[TaskKey, dict[str, Any]]]:
    """Simulations and tasks from τ² `Results` JSON files, or directories holding them (as the
    harness writes: `wrapped.json`, `unwrapped.json`). Other JSON files are ignored."""
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob("*.json")) if p.is_dir() else [p])
    loaded = []
    for f in dict.fromkeys(f.resolve() for f in files):
        data = json.loads(f.read_text())
        if isinstance(data, dict) and isinstance(data.get("simulations"), list):
            loaded.append((f, data))
    stems = [f.stem for f, _ in loaded]
    simulations: dict[str, Simulation] = {}
    tasks: dict[TaskKey, dict[str, Any]] = {}
    for f, data in loaded:
        source = f.stem if stems.count(f.stem) == 1 else f"{f.parent.name}/{f.stem}"
        info = data.get("info") or {}
        domain = str((info.get("environment_info") or {}).get("domain_name") or "")
        model = str((info.get("agent_info") or {}).get("llm") or "")
        for task in data.get("tasks") or []:
            tasks.setdefault((domain, str(task["id"])), task)
        for sim in data["simulations"]:
            reward = (sim.get("reward_info") or {}).get("reward")
            simulations[str(sim["id"])] = Simulation(
                id=str(sim["id"]),
                task_id=str(sim["task_id"]),
                trial=sim.get("trial"),
                domain=domain,
                agent_model=model,
                source=source,
                reward=reward,
                termination_reason=sim.get("termination_reason"),
                data=sim,
            )
    return simulations, tasks


def _simulation_modes(
    conn: sqlite3.Connection,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Each session's mode, and the agent and user models the store's simulations ran."""
    if not _columns(conn, "simulations"):
        return {}, {"agent_models": [], "user_models": [], "simulation_modes": []}
    rows = conn.execute("SELECT session_id, mode, agent_model, user_model FROM simulations")
    rows = list(rows)
    return {r["session_id"]: r["mode"] for r in rows}, {
        "agent_models": sorted({r["agent_model"] for r in rows if r["agent_model"]}),
        "user_models": sorted({r["user_model"] for r in rows if r["user_model"]}),
        "simulation_modes": sorted({r["mode"] for r in rows}),
    }


def _results_summary(results: Iterable[str | Path]) -> dict[str, Any]:
    """Run facts from a results directory's `summary.json` (written by the τ² harness): the run
    config, its seed, the commit the run used, and whether the store is a converted copy."""
    for p in map(Path, results):
        path = p / "summary.json" if p.is_dir() else p.with_name("summary.json")
        if path.is_file():
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return {
                    "config": data.get("config"),
                    "seed": data.get("seed"),
                    "run_commit": data.get("hatchway_commit"),
                    "converted": data.get("converted"),
                }
    return {"config": None, "seed": None, "run_commit": None, "converted": None}


def load_arms(replay: str | Path) -> dict[str, FrozenArm]:
    """The frozen arms M6 replay wrote (`frozen_<arm>.json`), by arm."""
    return {
        p.stem.removeprefix("frozen_"): FrozenArm.load(p)
        for p in sorted(Path(replay).glob("frozen_*.json"))
    }


def strategies(
    arms: Mapping[str, FrozenArm], metrics: Mapping[str, Any] | None
) -> dict[str, Strategy]:
    """One `Strategy` per frozen arm, named from the replay metrics' arm metadata."""
    meta = (metrics or {}).get("arms") or {}
    out = {}
    for name in sorted(arms):
        m = meta.get(name) or {}
        out[name] = Strategy(
            arm=name,
            display_name=m.get("display_name"),
            kind=m.get("kind"),
            judge=m.get("judge"),
            judges=tuple(j for j, _ in arms[name].judges),
            description=m.get("description"),
        )
    return out


def arm_decision(arm: FrozenArm, bench: Bench, w: Write) -> dict[str, Any]:
    """The arm's decision on this write from its stored scores, with what produced it: `rule`
    is `threshold` (ALLOW iff `p_ok >= threshold`), `fail_closed` (a judge the arm needs did not
    score `ok`: ASK, as production does) or `disagreement_veto` (a two-judge arm whose judges
    disagree by more than its `disagreement_max`: ASK whatever `p_ok`). Two-judge arms also
    carry their `disagreement` and `disagreement_max`."""
    key = w.score_key
    scores = bench.scores.get(key, {}) if key is not None else {}
    vectors: dict[str, QuestionVector] = {}
    for judge, model in arm.judges:
        s = scores.get((judge, model))
        if s is not None and s.status == "ok" and s.question_vector is not None:
            vectors[judge] = QuestionVector.model_validate(s.question_vector)
    threshold = arm.threshold(w.action)
    if len(vectors) < len(arm.judges):
        return {
            "decision": "ASK",
            "p_ok": None,
            "threshold": threshold,
            "note": "fail closed",
            "rule": "fail_closed",
            "missing": [j for j, _ in arm.judges if j not in vectors],
        }
    out = {
        "decision": arm.decide(w.action, vectors),
        "p_ok": arm.p_ok(w.action, vectors),
        "threshold": threshold,
        "note": "",
        "rule": "threshold",
    }
    if arm.model["type"] == "two_judge":
        _, disagreement = two_judge_parts(arm.model, w.action, vectors)
        limit = arm.model.get("disagreement_max")
        out.update(disagreement=disagreement, disagreement_max=limit)
        if limit is not None and disagreement > limit:
            out.update(rule="disagreement_veto", note="disagreement veto")
    expected = (
        "ASK"
        if out["rule"] == "disagreement_veto"
        else "ALLOW"
        if out["p_ok"] >= threshold
        else "ASK"
    )
    if out["decision"] != expected:  # the viewer explains every decision by these rules
        raise ValueError(f"arm {arm.arm} on {w.write_id}: decision not explained by its rule")
    return out


def _verdicts(
    conn: sqlite3.Connection, writes: list[Write], requested: str | None
) -> tuple[list[str], str | None]:
    """Attach verdicts, reviews, benchmark matches and outcomes to `writes`. Returns the
    store's oracle versions and the one used."""
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    by_id = {w.write_id: w for w in writes}
    if "benchmark_matches" in tables:
        for r in conn.execute("SELECT write_id, match FROM benchmark_matches"):
            if r["write_id"] in by_id:
                by_id[r["write_id"]].benchmark_match = r["match"]
    if "execution_outcomes" in tables:
        for r in conn.execute("SELECT * FROM execution_outcomes"):
            if r["write_id"] in by_id:
                by_id[r["write_id"]].outcome = {
                    "outcome": r["outcome"],
                    "state_changed": None
                    if r["state_changed"] is None
                    else bool(r["state_changed"]),
                    "backend_error": r["backend_error"],
                }
    if "policy_verdicts" not in tables:
        return [], None
    from hatchway.bench.tau2.verdicts import ORACLE_VERSION

    versions = [
        r["oracle_version"]
        for r in conn.execute(
            "SELECT oracle_version, MIN(rowid) AS first FROM policy_verdicts "
            "GROUP BY oracle_version ORDER BY first"
        )
    ]
    if requested is not None:
        version: str | None = requested
    elif ORACLE_VERSION in versions:
        version = ORACLE_VERSION
    else:
        version = versions[-1] if versions else None
    if version is None:
        return versions, None
    for r in conn.execute("SELECT * FROM policy_verdicts WHERE oracle_version = ?", (version,)):
        w = by_id.get(r["write_id"])
        if w is None:
            continue
        w.deterministic = {
            "decision": r["expected_decision"],
            "reason_codes": json.loads(r["reason_codes"]),
            "explanation": r["explanation"],
            "evidence": json.loads(r["evidence"]),
        }
        w.verdict, w.verdict_source = r["expected_decision"], "deterministic_oracle"
    if "manual_verdicts" in tables:
        for r in conn.execute(
            "SELECT * FROM manual_verdicts WHERE oracle_version = ? ORDER BY rowid", (version,)
        ):
            w = by_id.get(r["write_id"])
            if w is None:
                continue
            review = {
                "decision": r["expected_decision"],
                "reason_codes": json.loads(r["reason_codes"]),
                "explanation": r["explanation"],
                "reviewer": r["reviewer"],
                "adjudicated": bool(r["adjudicated"]),
                "review_kind": r["review_kind"],
                "ts": r["ts"],
            }
            w.reviews.append(review)
            if review["adjudicated"]:
                w.manual = review
                w.verdict, w.verdict_source = review["decision"], "manual_review"
    return versions, version


def ground_truth(task: Mapping[str, Any]) -> GroundTruth:
    """`GroundTruth.from_task` for a task as saved in a results file."""
    criteria = task.get("evaluation_criteria")
    if not criteria:
        return GroundTruth(actions=(), db_scored=False)
    actions = tuple(
        GoldAction(
            name=a["name"],
            arguments=dict(a.get("arguments") or {}),
            compare_args=tuple(a["compare_args"]) if a.get("compare_args") is not None else None,
        )
        for a in criteria.get("actions") or []
        if a.get("requestor", "assistant") == "assistant"
    )
    return GroundTruth(actions=actions, db_scored="DB" in (criteria.get("reward_basis") or []))


def slug(value: str) -> str:
    """A file name for an arbitrary id: kept as is when already safe, else sanitized and
    suffixed with a short hash so distinct ids never collide."""
    if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()[:10]
    return f"{re.sub(r'[^A-Za-z0-9_-]+', '_', value)[:60]}-{digest}"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _write(row: sqlite3.Row) -> Write:
    return Write(
        write_id=row["write_id"],
        ts=row["ts"],
        domain=row["domain"],
        agent_model=row["agent_model"],
        task_id=row["task_id"],
        trial=row["trial"],
        session_id=row["session_id"],
        seq=row["seq"],
        action=row["action"],
        known_action=bool(row["known_action"]),
        args=json.loads(row["args"]),
        context=json.loads(row["context"]),
        state_text=row["state_text"],
        state_hash=row["state_hash"],
        rubric_hash=row["rubric_hash"],
    )
