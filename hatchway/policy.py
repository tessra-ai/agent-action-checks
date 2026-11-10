"""Load and validate the policy file (`hatchway.yaml`).

Week 1 validates what the benchmark path uses: each action's `kind` and rubric `questions`.
Keys the full v0 policy defines but week 1 does not use (`defaults`, `mode`, `hard_rules`,
`promotion`) are accepted as written and validated in week 2 (M8). Unknown keys are errors, so a
typo never silently drops a setting.

A write may carry `metadata`: a plain description and coarse, judge-free facts about the action
(`impact`, `reversible`) that are known when the call is intercepted. The decision-model pilot
renders its shared concept questions with the description and feeds the two coarse facts to its
model. Metadata is not part of `rubric_hash`.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hatchway.judges.base import Question


class PolicyError(ValueError):
    """The policy file is unreadable or invalid. The message names the offending field."""


class Kind(StrEnum):
    READ = "read"
    WRITE = "write"


class ActionMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1)
    # What a wrong call costs: nothing, service to the customer, or money.
    impact: Literal["none", "service", "financial"]
    # Whether a wrong call can be undone: fully, in part, or not at all.
    reversible: Literal["yes", "partly", "no"]


class Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Kind
    questions: dict[str, Question] = Field(default_factory=dict)
    metadata: ActionMetadata | None = None

    # Validated in week 2 (M8).
    mode: Any = None
    hard_rules: Any = None
    promotion: Any = None

    @model_validator(mode="before")
    @classmethod
    def _name_questions(cls, data: Any) -> Any:
        # In YAML the mapping key is the question's name; copy it into each Question.
        if isinstance(data, dict) and isinstance(data.get("questions"), dict):
            questions = {}
            for name, spec in data["questions"].items():
                if isinstance(spec, dict):
                    if "name" in spec:
                        raise ValueError(f"questions.{name}: remove 'name'; the key is the name")
                    spec = {**spec, "name": name}
                questions[name] = spec
            data = {**data, "questions": questions}
        return data

    @model_validator(mode="after")
    def _check_questions(self) -> Action:
        if self.kind is Kind.READ and self.questions:
            raise ValueError("read actions are never judged; remove 'questions'")
        if self.kind is Kind.READ and self.metadata is not None:
            raise ValueError("read actions carry no metadata; remove 'metadata'")
        if self.kind is Kind.WRITE and not self.questions:
            raise ValueError("write actions need at least one question")
        return self

    @cached_property
    def rubric_hash(self) -> str:
        """SHA-256 over the questions' names, types, text and options.

        Question order in the file does not matter; option order does, because it is part of
        what the judge is asked.
        """
        rubric = [q.model_dump(mode="json") for _, q in sorted(self.questions.items())]
        canonical = json.dumps(rubric, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    judges: list[str] = Field(default_factory=list)
    store: str | None = None
    actions: dict[str, Action] = Field(min_length=1)

    # Validated in week 2 (M8).
    defaults: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, text: str, source: str = "<string>") -> Policy:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise PolicyError(f"{source}: invalid YAML: {exc}") from exc
        if data is None:
            raise PolicyError(f"{source}: policy file is empty")
        if not isinstance(data, dict):
            raise PolicyError(f"{source}: top level must be a mapping")
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise PolicyError(_format_errors(source, exc)) from exc


def load_policy(path: str | Path) -> Policy:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"{path}: cannot read policy file: {exc.strerror}") from exc
    return Policy.from_yaml(text, source=str(path))


def _format_errors(source: str, exc: ValidationError) -> str:
    lines = [f"{source}: invalid policy"]
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"]) or "(top level)"
        message = err["msg"].removeprefix("Value error, ")
        lines.append(f"  {field}: {message}")
    return "\n".join(lines)
