from pathlib import Path

import pytest

from hatchway.judges.base import QuestionType
from hatchway.policy import Kind, Policy, PolicyError, load_policy

SPEC_POLICY = Path(__file__).parent / "fixtures" / "spec_policy.yaml"

MINIMAL = """
version: 1
actions:
  refund_order:
    kind: write
    questions:
      policy_ok: {type: yes_no, text: 'Follows the refund policy.'}
      risk: {type: choice, options: [low, medium, high]}
"""


def test_spec_example_policy_loads() -> None:
    policy = load_policy(SPEC_POLICY)

    assert policy.judges == ["jev", "openai_decisions"]
    assert policy.actions["get_order"].kind is Kind.READ
    refund = policy.actions["refund_order"]
    assert refund.kind is Kind.WRITE
    assert list(refund.questions) == ["policy_ok", "matches_request", "risk"]
    assert refund.questions["policy_ok"].name == "policy_ok"
    assert refund.questions["risk"].type is QuestionType.CHOICE
    assert refund.questions["risk"].options == ("low", "medium", "high")


@pytest.mark.parametrize(
    ("yaml_text", "field", "message"),
    [
        ("version: 2\nactions: {a: {kind: read}}", "version", "Input should be 1"),
        ("version: 1\nactions: {}", "actions", "at least 1 item"),
        ("version: 1\nactions: {a: {kind: delete}}", "actions.a.kind", "'read' or 'write'"),
        ("version: 1\nactions: {a: {kind: read, colour: red}}", "actions.a.colour", "Extra"),
        ("version: 1\nactons: {a: {kind: read}}", "actons", "Extra"),
        (
            "version: 1\nactions: {a: {kind: write}}",
            "actions.a",
            "write actions need at least one question",
        ),
        (
            "version: 1\nactions: {a: {kind: read, questions: {q: {type: yes_no, text: t}}}}",
            "actions.a",
            "read actions are never judged",
        ),
        (
            "version: 1\nactions: {a: {kind: write, questions: {q: {type: maybe, text: t}}}}",
            "actions.a.questions.q.type",
            "'yes_no', 'choice' or 'score'",
        ),
        (
            "version: 1\nactions: {a: {kind: write, questions: {q: {type: yes_no}}}}",
            "actions.a.questions.q",
            "yes_no questions need text",
        ),
        (
            "version: 1\nactions: {a: {kind: write, questions: {q: {type: choice, options: [x]}}}}",
            "actions.a.questions.q",
            "at least two options",
        ),
        (
            "version: 1\nactions: {a: {kind: write, questions: "
            "{q: {type: choice, options: [x, x]}}}}",
            "actions.a.questions.q",
            "options must be unique",
        ),
        (
            "version: 1\nactions: {a: {kind: write, questions: "
            "{q: {type: score, text: t, options: [x, y]}}}}",
            "actions.a.questions.q",
            "score questions do not take options",
        ),
        (
            "version: 1\nactions: {a: {kind: write, questions: "
            "{q: {type: yes_no, text: t, name: other}}}}",
            "actions.a",
            "questions.q: remove 'name'",
        ),
    ],
)
def test_invalid_policy_names_the_field(yaml_text: str, field: str, message: str) -> None:
    with pytest.raises(PolicyError) as excinfo:
        Policy.from_yaml(yaml_text, source="bad.yaml")

    text = str(excinfo.value)
    assert text.startswith("bad.yaml: invalid policy")
    lines = text.splitlines()[1:]
    assert any(line.strip().startswith(f"{field}: ") and message in line for line in lines), text


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("", "policy file is empty"),
        ("- just\n- a list", "top level must be a mapping"),
        ("version: [1", "invalid YAML"),
    ],
)
def test_unparseable_policy_is_rejected(yaml_text: str, message: str) -> None:
    with pytest.raises(PolicyError, match=message):
        Policy.from_yaml(yaml_text)


def test_missing_policy_file_is_a_policy_error(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="cannot read policy file"):
        load_policy(tmp_path / "nope.yaml")


def _rubric_hash(yaml_text: str) -> str:
    return Policy.from_yaml(yaml_text).actions["refund_order"].rubric_hash


def test_rubric_hash_is_stable_across_formatting_and_question_order() -> None:
    reordered = """
version: 1
judges: [jev]   # unrelated settings do not affect the rubric
actions:
  refund_order:
    kind: write
    mode: ask
    questions:
      risk:
        type: choice
        options: [low, medium, high]
      policy_ok:
        type: yes_no
        text: "Follows the refund policy."
"""
    assert _rubric_hash(MINIMAL) == _rubric_hash(reordered)
    assert len(_rubric_hash(MINIMAL)) == 64


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("'Follows the refund policy.'", "'Follows the refund policy!'"),
        ("type: yes_no, text: 'Follows", "type: score, text: 'Follows"),
        ("[low, medium, high]", "[low, high]"),
        ("[low, medium, high]", "[high, medium, low]"),
        ("policy_ok:", "policy_fine:"),
    ],
)
def test_rubric_hash_changes_when_a_question_changes(old: str, new: str) -> None:
    assert old in MINIMAL
    assert _rubric_hash(MINIMAL) != _rubric_hash(MINIMAL.replace(old, new))
