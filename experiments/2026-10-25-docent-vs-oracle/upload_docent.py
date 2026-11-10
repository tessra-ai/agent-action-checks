"""Upload the 73 retail runs to hosted Docent as a private collection, for viewing (separate
venv with `docent==0.1.88`, `DOCENT_API_KEY` in the environment).

Each run is built by `judge_runs.agent_run` (taken from that file's source, which cannot be
imported here: it reads the τ² policy at import time). Attached per run, as metadata and as
label sets: Docent's verdict, explanation and citations (`results/judge.jsonl`), our checker's
verdict (`data/truth.jsonl`), and the 7 adjudicated disagreements (`adjudication.json`), also
tagged `disagreement`. No rubric is created and no judge runs on the hosted service: $0.

    <docent-venv>/bin/python experiments/2026-10-25-docent-vs-oracle/upload_docent.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from docent import Docent
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, ToolMessage, UserMessage
from docent.data_models.chat.tool import ToolCall
from docent.data_models.judge import Label
from docent.data_models.transcript import Transcript

HERE = Path(__file__).parent
NAME = "Hatchway: Docent judge vs policy checker (τ² retail, 73 writes)"
DESCRIPTION = (
    "73 real retail writes from τ²-bench, each cut at the agent's proposed tool call (id "
    "`proposed`, not executed). Labels: Docent's rubric judge (docent 0.1.88, run locally, "
    "majority of 3) and Hatchway's deterministic policy checker (unaudited). Metadata "
    "`disagreement` / tag `disagreement` marks the 7 cases where they differ."
)


def load_agent_run():
    """`agent_run` from judge_runs.py, so runs are built exactly as they were judged."""
    source = (HERE / "judge_runs.py").read_text()
    (fn,) = [
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == "agent_run"
    ]
    namespace = {
        "AgentRun": AgentRun,
        "AssistantMessage": AssistantMessage,
        "ToolCall": ToolCall,
        "ToolMessage": ToolMessage,
        "Transcript": Transcript,
        "UserMessage": UserMessage,
    }
    exec(compile(ast.Module([fn], []), "judge_runs.py", "exec"), namespace)
    return namespace["agent_run"]


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build() -> list[AgentRun]:
    rows = jsonl(HERE / "data/runs.jsonl")
    truth = {t["write_id"]: t for t in jsonl(HERE / "data/truth.jsonl")}
    judge = {j["write_id"]: j for j in jsonl(HERE / "results/judge.jsonl")}
    cases = {
        c["write_id"]: c for c in json.loads((HERE / "adjudication.json").read_text())["cases"]
    }
    if len(rows) != 73 or {r["write_id"] for r in rows} != set(truth) or set(judge) != set(truth):
        sys.exit("runs, truth and judge results do not cover the same 73 writes")
    if not set(cases) <= set(truth) or len(cases) != 7:
        sys.exit("adjudication.json does not list 7 of these writes")

    agent_run = load_agent_run()
    runs = []
    for i, row in enumerate(rows):
        run = agent_run(i, row)
        t, j, case = truth[row["write_id"]], judge[row["write_id"]], cases.get(row["write_id"])
        run.metadata = {
            "write_id": row["write_id"],
            "action": row["action"],
            "store": row["store"],
            "task_id": t["task_id"],
            "agent_model": t["agent_model"],
            "docent_label": j["label"],
            "docent_rollout_labels": ", ".join(str(x) for x in j["rollout_labels"]),
            "docent_explanation": j["explanation"],
            "checker_verdict": t["oracle"].lower(),
            "checker_reason_codes": ", ".join(t["reason_codes"]),
            "checker_explanation": t["explanation"],
            "disagreement": case is not None,
            "adjudication_class": case["class"] if case else "",
            "adjudication_reading": case["reading"] if case else "",
        }
        runs.append(run)
    return runs


LABELS = ["allow", "ask", "deny", "unknown"]
LABEL_SETS = {
    "docent": (
        "Docent judge (local run, majority of 3)",
        {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": LABELS},
                "explanation": {"type": "string", "citations": True},
            },
            "required": ["label", "explanation"],
        },
        "Docent's rubric judge, run locally with docent 0.1.88 (results/judge.jsonl).",
    ),
    "checker": (
        "Hatchway policy checker",
        {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": LABELS},
                "explanation": {"type": "string"},
                "disagrees_with_docent": {"type": "boolean"},
            },
            "required": ["label", "explanation", "disagrees_with_docent"],
        },
        "Deterministic policy checker verdict (data/truth.jsonl); unaudited.",
    ),
}


def label_values(m: dict) -> dict[str, dict]:
    return {
        "docent": {"label": m["docent_label"], "explanation": m["docent_explanation"]},
        "checker": {
            "label": m["checker_verdict"],
            "explanation": m["checker_explanation"],
            "disagrees_with_docent": m["disagreement"],
        },
    }


def main() -> None:
    """Without arguments, create the collection and upload. `--collection ID` finishes an
    upload whose runs are already there (labels, tags), matching runs by `write_id`."""
    runs = build()
    if "--dry-run" in sys.argv:
        print(len(runs), "runs;", sum(r.metadata["disagreement"] for r in runs), "disagreements")
        return
    client = Docent()
    if "--collection" in sys.argv:
        cid = sys.argv[sys.argv.index("--collection") + 1]
        ids = {}
        for run_id in client.list_agent_run_ids(cid):
            uploaded = client.get_agent_run(cid, run_id)
            ids[uploaded.metadata["write_id"]] = run_id
        if set(ids) != {r.metadata["write_id"] for r in runs}:
            sys.exit("the collection does not hold exactly these 73 runs")
        run_ids = [ids[r.metadata["write_id"]] for r in runs]
    else:
        cid = client.create_collection(name=NAME, description=DESCRIPTION)
        print("created collection", cid, flush=True)
        client.add_agent_runs(cid, runs)
        run_ids = [r.id for r in runs]

    existing = {s["name"]: s["id"] for s in client.get_label_sets(cid)}
    for key, (name, schema, description) in LABEL_SETS.items():
        set_id = existing.get(name) or client.create_label_set(cid, name, schema, description)
        if client.get_labels(cid, set_id):
            continue
        labels = [
            Label(
                label_set_id=set_id, agent_run_id=run_id, label_value=label_values(r.metadata)[key]
            )
            for r, run_id in zip(runs, run_ids, strict=True)
        ]
        result = client.add_labels(cid, labels)
        if result.get("errors"):
            sys.exit(f"label errors: {result['errors'][:3]}")
    if not client.get_tags(cid, "disagreement"):
        for r, run_id in zip(runs, run_ids, strict=True):
            if r.metadata["disagreement"]:
                client.tag_transcript(cid, run_id, "disagreement")

    public = [c for c in client.get_collection_collaborators(cid) if "public" in json.dumps(c)]
    print("collection", cid, "private" if not public else f"NOT PRIVATE: {public}")
    print(client.frontend_url + f"/dashboard/{cid}")


if __name__ == "__main__":
    main()
