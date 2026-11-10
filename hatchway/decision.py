"""The value `Gate.check()` returns for every gated call."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Result(StrEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: Result
    reason: str
    receipt_id: str | None = None
    p_ok: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None = None
