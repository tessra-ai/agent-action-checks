"""Record real judge API responses as test fixtures.

Usage: OPENAI_API_KEY=... TYPESAFE_API_KEY=... \
    python scripts/record_judge_fixtures.py [--only llm_baseline] [--llm-model MODEL] \
        [--policy-file .tau2-bench/data/tau2/domains/retail/policy.md]

Writes one JSON file per call to tests/fixtures/judges/: the endpoint, the request body, the
HTTP status and the response body. Headers are never written, so the Authorization header cannot
leak into a fixture. Error bodies keep only their type and code: messages can echo part of the
key. The error cases are real calls too: a made-up key, a model that refuses logprobs, and
requests the API rejects. The recorded state is synthetic.

The LLM baseline fixtures use a state with a `policy` context section (the τ² retail policy,
from `--policy-file`), long enough for OpenAI prompt caching; it is written to
`llm_baseline_state.txt` so tests replay the same text. Its calls run one after another, then
the yes/no question is asked again (`llm_baseline_yes_no_repeat`), so later calls show cached
prompt tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from hatchway.judges import Question, QuestionType, jev, llm_baseline, openai_decisions
from hatchway.judges._http import sanitize_error_body
from hatchway.state import build_state

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "judges"
OPENAI = "https://api.openai.com/v1"
TYPESAFE = "https://api.typesafe.ai/v1"
FAKE_KEY = "not-a-real-key"
# A reasoning model: Chat Completions refuses `logprobs` for it.
NO_LOGPROBS_MODEL = "gpt-5-mini"

STATE = (
    "## Context: conversation\n"
    "Customer: I was charged twice for order #W123. Please refund the duplicate $20 charge.\n\n"
    "## Earlier writes in this session\n(none)\n\n"
    '## Proposed action\nrefund_order({"amount":20,"method":"card","order_id":"W123"})\n'
)

LLM_STATE_FILE = OUT / "llm_baseline_state.txt"
LLM_CONVERSATION = (
    "assistant: Hi! How can I help you today?\n"
    "user: Hi, I'm Yusuf Rossi, zip 19122. I'd like to return the water bottle from order "
    "#W2378156.\n"
    "assistant -> find_user_id_by_name_zip("
    '{"first_name":"Yusuf","last_name":"Rossi","zip":"19122"})\n'
    "tool (assistant): yusuf_rossi_9620\n"
    'assistant -> get_order_details({"order_id":"#W2378156"})\n'
    'tool (assistant): {"order_id": "#W2378156", "user_id": "yusuf_rossi_9620", "status": '
    '"delivered", "items": [{"name": "Water Bottle", "item_id": "4579334072", "price": 54.85}], '
    '"payment_history": [{"transaction_type": "payment", "amount": 54.85, '
    '"payment_method_id": "credit_card_9513926"}]}\n'
    "assistant: I can return the Water Bottle (item 4579334072) from delivered order #W2378156 "
    "and refund $54.85 to your original credit card ending 9513926. Shall I go ahead?\n"
    "user: Yes, please go ahead."
)
LLM_ACTION = (
    "return_delivered_order_items",
    {
        "order_id": "#W2378156",
        "item_ids": ["4579334072"],
        "payment_method_id": "credit_card_9513926",
    },
)


def llm_state(policy: str) -> str:
    context = {"conversation": LLM_CONVERSATION, "policy": policy}
    return build_state(*LLM_ACTION, context, [])


QUESTIONS = (
    Question(name="policy_ok", type=QuestionType.YES_NO, text="This refund follows policy."),
    Question(name="risk", type=QuestionType.CHOICE, options=("low", "medium", "high")),
    Question(
        name="matches_request",
        type=QuestionType.SCORE,
        text="This action matches what the customer asked for.",
    ),
)


def _record(client: httpx.Client, name: str, url: str, key: str, body: dict) -> None:
    response = client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    try:
        payload = response.json()
    except ValueError:
        payload = {"_raw_text": response.text}
    if response.status_code != 200:
        payload = sanitize_error_body(payload)
    path = url.removeprefix(OPENAI).removeprefix(TYPESAFE)
    fixture = {"path": path, "request": body, "status": response.status_code, "response": payload}
    (OUT / f"{name}.json").write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    print(f"{name}: HTTP {response.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only", choices=["decisions", "jev", "llm_baseline"], action="append", help="repeatable"
    )
    parser.add_argument("--llm-model", help="chat model for the LLM baseline (needs logprobs)")
    parser.add_argument("--policy-file", type=Path, help="policy text for the LLM baseline state")
    args = parser.parse_args()
    only = set(args.only or ["decisions", "jev", "llm_baseline"])
    openai_key = os.environ.get("OPENAI_API_KEY")
    typesafe_key = os.environ.get("TYPESAFE_API_KEY")
    if not openai_key or ("jev" in only and not typesafe_key):
        print("OPENAI_API_KEY (and TYPESAFE_API_KEY for jev) must be set", file=sys.stderr)
        return 1
    if "llm_baseline" in only and args.policy_file is None:
        print("--policy-file is needed to record the LLM baseline", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60) as client:
        if "decisions" in only:
            _record_decisions(client, openai_key)
        if "jev" in only:
            _record_jev(client, typesafe_key or "")
        if "llm_baseline" in only:
            state = llm_state(args.policy_file.read_text())
            LLM_STATE_FILE.write_text(state)
            _record_llm_baseline(client, openai_key, state, args.llm_model)
    return 0


def _record_decisions(client: httpx.Client, openai_key: str) -> None:
    decisions = f"{OPENAI}/decisions"
    model = openai_decisions.DEFAULT_MODEL
    all_types = openai_decisions.build_request(model, STATE, QUESTIONS)
    _record(client, "decisions_all_types", decisions, openai_key, all_types)
    for q in QUESTIONS:
        body = openai_decisions.build_request(model, STATE, [q])
        _record(client, f"decisions_{q.type.value}", decisions, openai_key, body)
    _record(client, "decisions_error_unauthorized", decisions, FAKE_KEY, all_types)


def _record_jev(client: httpx.Client, typesafe_key: str) -> None:
    systemone = f"{TYPESAFE}/systemone"
    all_types = jev.build_request(jev.DEFAULT_MODEL, STATE, QUESTIONS)
    _record(client, "jev_all_types", systemone, typesafe_key, all_types)
    for q in QUESTIONS:
        body = jev.build_request(jev.DEFAULT_MODEL, STATE, [q])
        _record(client, f"jev_{q.type.value}", systemone, typesafe_key, body)
    _record(client, "jev_error_unauthorized", systemone, FAKE_KEY, all_types)
    unknown_model = jev.build_request("no-such-model", STATE, QUESTIONS)
    _record(client, "jev_error_unknown_model", systemone, typesafe_key, unknown_model)
    # A score question without levels: rejected by request validation (HTTP 422).
    invalid = jev.build_request(jev.DEFAULT_MODEL, STATE, QUESTIONS[2:])
    invalid["questions"]["matches_request"]["criteria"] = []
    _record(client, "jev_error_validation", systemone, typesafe_key, invalid)


def _record_llm_baseline(
    client: httpx.Client, openai_key: str, state: str, model: str | None
) -> None:
    chat = f"{OPENAI}/chat/completions"
    if model:
        for q in QUESTIONS:
            body = llm_baseline.build_request(model, state, q)
            _record(client, f"llm_baseline_{q.type.value}", chat, openai_key, body)
        body = llm_baseline.build_request(model, state, QUESTIONS[0])
        _record(client, "llm_baseline_yes_no_repeat", chat, openai_key, body)
    body = llm_baseline.build_request(NO_LOGPROBS_MODEL, state, QUESTIONS[0])
    _record(client, "llm_baseline_error_no_logprobs", chat, openai_key, body)


if __name__ == "__main__":
    sys.exit(main())
