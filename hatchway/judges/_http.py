"""HTTP plumbing shared by the API-backed judge adapters."""

from __future__ import annotations

import json
import math
import os
from typing import Any

import httpx
from pydantic import ValidationError

from hatchway.judges.runner import JudgeError

OPENAI_BASE_URL = "https://api.openai.com/v1"

# Rate limits, timeouts, conflicts and server errors may succeed on a later attempt.
_RETRYABLE_STATUS = {408, 409, 429}


def api_key_from_env(var: str) -> str:
    key = os.environ.get(var)
    if not key:
        raise RuntimeError(f"{var} is not set")
    return key


async def post_json(
    client: httpx.AsyncClient, url: str, api_key: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """POST `payload` and return the decoded JSON object, or raise JudgeError.

    Error text and the error's `raw_response` keep only the status and the API's error type and
    code: error bodies can echo part of the API key.
    """
    try:
        response = await client.post(
            url, json=payload, headers={"Authorization": f"Bearer {api_key}"}
        )
    except httpx.TransportError as exc:
        raise JudgeError(f"transport error: {type(exc).__name__}", retryable=True) from None
    if response.status_code != 200:
        retryable = response.status_code in _RETRYABLE_STATUS or response.status_code >= 500
        raise JudgeError(
            f"HTTP {response.status_code}{_error_summary(response)}",
            retryable=retryable,
            raw_response=_sanitized_error_body(response),
        )
    try:
        body = response.json()
    except ValueError:
        raise JudgeError("malformed response: body is not JSON", retryable=False) from None
    if not isinstance(body, dict):
        raise JudgeError("malformed response: body is not a JSON object", retryable=False)
    return body


def dump_body(body: Any) -> str:
    """A decoded response body as JSON text, for `raw_response`."""
    return json.dumps(body, ensure_ascii=False)


def sanitize_error_body(payload: Any) -> dict[str, Any]:
    """Keep only the error type and code (OpenAI) or error type and field (TypeSafe)."""
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("error"), dict):
        return {"error": {k: payload["error"].get(k) for k in ("type", "code")}}
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return {"detail": {"error_type": detail.get("error_type")}}
    if isinstance(detail, list):
        return {
            "detail": [
                {"type": e.get("type"), "loc": e.get("loc")} for e in detail if isinstance(e, dict)
            ]
        }
    return {}


def _sanitized_error_body(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return dump_body(sanitize_error_body(payload))


def _error_summary(response: httpx.Response) -> str:
    """The error type and code, from OpenAI's `error` or TypeSafe's `detail`; never messages."""
    try:
        body = response.json()
        if isinstance(body.get("error"), dict):
            error = body["error"]
            parts = [str(error[k]) for k in ("type", "code") if error.get(k)]
        elif isinstance(body.get("detail"), dict):
            parts = [str(body["detail"]["error_type"])] if body["detail"].get("error_type") else []
        elif isinstance(body.get("detail"), list):
            parts = sorted({str(e["type"]) for e in body["detail"] if e.get("type")})
        else:
            parts = []
    except (ValueError, AttributeError, TypeError):
        return ""
    return f" ({', '.join(parts)})" if parts else ""


def finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"expected a finite number, got {value!r}")
    return float(value)


def malformed(detail: str) -> JudgeError:
    return JudgeError(f"malformed response: {detail}", retryable=False)


def short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(e["msg"] for e in exc.errors())
    if isinstance(exc, KeyError):
        return f"missing field {exc.args[0]!r}"
    return str(exc)
