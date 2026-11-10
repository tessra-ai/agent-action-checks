"""Record a tiny real OpenAI Batch API run as test fixtures for `hatchway.bench.openai_batch`.

Usage: OPENAI_API_KEY=... python scripts/record_batch_fixtures.py [--poll 20]

Two batches, each recorded to tests/fixtures/openai_batch/<name>.json:

- `ok`: the LLM baseline's two requests (policy_ok and risk for `return_delivered_order_items`)
  on the state in tests/fixtures/judges/llm_baseline_state.txt.
- `error`: one request to `gpt-5-mini` (a reasoning model). Its line fails: on 2026-10-21 the
  Batch API answered `404 model_not_found` for it, a real per-request failure.

Each fixture holds the uploaded JSONL lines, the create-batch request body, and the responses
of every call: upload, create, the first poll, the final poll, a `GET /v1/batches` page (only
this batch kept), and the output and error file contents. Headers are never written. Error
bodies keep only their type and code. Costs a fraction of a cent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from hatchway.bench import openai_batch
from hatchway.bench.models import LLM_BASELINE_MODEL
from hatchway.bench.tau2 import DEFAULT_POLICY
from hatchway.judges._http import sanitize_error_body
from hatchway.policy import load_policy
from hatchway.state import state_hash

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "openai_batch"
STATE_FILE = ROOT / "tests" / "fixtures" / "judges" / "llm_baseline_state.txt"
OPENAI = "https://api.openai.com/v1"
NO_LOGPROBS_MODEL = "gpt-5-mini"
ACTION = "return_delivered_order_items"
QUESTIONS = ("policy_ok", "risk")


def batch_key(model: str) -> tuple[str, openai_batch.BatchKey]:
    """The model and key to record; tests rebuild the same key."""
    action = load_policy(DEFAULT_POLICY).actions[ACTION]
    state = STATE_FILE.read_text()
    questions = tuple(action.questions[name] for name in QUESTIONS)
    if model == NO_LOGPROBS_MODEL:
        questions = questions[:1]
    return model, openai_batch.BatchKey(state_hash(state), action.rubric_hash, state, questions)


def _sanitize_lines(text: str) -> list[dict[str, Any]]:
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        response = entry.get("response") or {}
        if response.get("status_code") != 200 and isinstance(response.get("body"), dict):
            response["body"] = sanitize_error_body(response["body"])
        if isinstance(entry.get("error"), dict):
            entry["error"] = {"code": entry["error"].get("code")}
        lines.append(entry)
    return lines


def _check(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        sys.exit(f"HTTP {response.status_code}: {sanitize_error_body(response.json())}")
    return response.json()


def record(client: httpx.Client, name: str, model: str, poll: float) -> None:
    model, key = batch_key(model)
    lines = openai_batch.request_lines(model, key)
    files = {
        "file": (f"hatchway-{name}.jsonl", ("\n".join(lines) + "\n").encode(), "application/jsonl")
    }
    uploaded = _check(client.post(f"{OPENAI}/files", data={"purpose": "batch"}, files=files))
    create_body = {
        "input_file_id": uploaded["id"],
        "endpoint": openai_batch.ENDPOINT,
        "completion_window": openai_batch.COMPLETION_WINDOW,
        "metadata": {"hatchway_batch_key": f"fixture-{name}"},
    }
    created = _check(client.post(f"{OPENAI}/batches", json=create_body))
    listed = _check(client.get(f"{OPENAI}/batches", params={"limit": 100}))
    listed["data"] = [b for b in listed["data"] if b["id"] == created["id"]]
    listed["first_id"] = listed["last_id"] = created["id"]
    listed["has_more"] = False
    first_poll = _check(client.get(f"{OPENAI}/batches/{created['id']}"))
    final = first_poll
    started = time.monotonic()
    while final["status"] not in openai_batch.TERMINAL:
        time.sleep(poll)
        final = _check(client.get(f"{OPENAI}/batches/{created['id']}"))
        print(f"{name}: {final['status']} after {time.monotonic() - started:.0f}s", flush=True)
    contents = {}
    for field in ("output_file_id", "error_file_id"):
        if final.get(field):
            text = client.get(f"{OPENAI}/files/{final[field]}/content").text
            contents[field] = _sanitize_lines(text)
    fixture = {
        "model": model,
        "lines": [json.loads(line) for line in lines],
        "create_request": create_body,
        "upload": uploaded,
        "create": created,
        "list": listed,
        "first_poll": first_poll,
        "final_poll": final,
        "contents": contents,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    print(f"{name}: {final['status']} {final.get('request_counts')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=float, default=20.0, help="seconds between polls")
    parser.add_argument("--only", choices=["ok", "error"], action="append")
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY must be set", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bearer {key}"}
    only = args.only or ["ok", "error"]
    with httpx.Client(timeout=120, headers=headers) as client:
        if "ok" in only:
            record(client, "ok", LLM_BASELINE_MODEL, args.poll)
        if "error" in only:
            record(client, "error", NO_LOGPROBS_MODEL, args.poll)
    return 0


if __name__ == "__main__":
    sys.exit(main())
