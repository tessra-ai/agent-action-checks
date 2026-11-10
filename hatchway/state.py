"""Build the state text a judge sees for one proposed write.

The text is deterministic: the same action, arguments, context and earlier writes always render
to the same text, so `state_hash` can key the judge score cache. Bump `STATE_VERSION` whenever
the rendering changes; stored raw inputs let old rows be re-rendered.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

STATE_VERSION = 1


def canonical_json(value: Any) -> str:
    """JSON with sorted keys and no whitespace. Raises TypeError on non-JSON values."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def render_call(action: str, args: Mapping[str, Any]) -> str:
    return f"{action}({canonical_json(dict(args))})"


def build_state(
    action: str,
    args: Mapping[str, Any],
    context: Mapping[str, Any],
    prior_writes: Sequence[tuple[str, Mapping[str, Any]]],
) -> str:
    """Render context (keys sorted), earlier writes in this session, then the proposed call.

    String context values are included as written; other values as canonical JSON.
    """
    sections = []
    for key in sorted(context):
        value = context[key]
        body = value if isinstance(value, str) else canonical_json(value)
        sections.append(f"## Context: {key}\n{body}")
    if prior_writes:
        lines = [f"{i}. {render_call(a, w)}" for i, (a, w) in enumerate(prior_writes, start=1)]
        sections.append("## Earlier writes in this session\n" + "\n".join(lines))
    else:
        sections.append("## Earlier writes in this session\n(none)")
    sections.append(f"## Proposed action\n{render_call(action, args)}")
    return "\n\n".join(sections) + "\n"


_PRIOR_WRITES_HEADING = "\n\n## Earlier writes in this session\n"


def split_context(state_text: str, key: str) -> tuple[str, str]:
    """Split a `build_state` text into the section for context `key` and everything else.

    Returns `(section, rest)` with `section` the `## Context: <key>` heading and body, and
    `rest` the state text without it, so `section + "\\n\\n" + rest` holds exactly the same
    sections with that one moved to the front. A judge puts a long section shared by every
    write (the τ² policy) first, so the prompt starts with a byte-identical prefix that the
    API can cache; `state_text` and `state_hash` are unchanged. Returns `("", state_text)` when
    there is no such section.

    The section is found by structure, not by searching its body: it ends where the next
    section begins, and the earlier-writes heading is located from the end, because the
    sections after it are rendered on single lines (canonical JSON has no raw newlines).
    """
    end = state_text.rfind(_PRIOR_WRITES_HEADING)
    if end < 0:
        return "", state_text
    heading = f"## Context: {key}\n"
    start = 0 if state_text.startswith(heading) else state_text.rfind(f"\n\n{heading}", 0, end)
    if start < 0:
        return "", state_text
    if start:
        start += 2
    # Later context sections (keys sorted after `key`) end the section early.
    next_section = state_text.find("\n\n## Context: ", start + len(heading), end)
    stop = end if next_section < 0 else next_section
    return state_text[start:stop], state_text[:start] + state_text[stop + 2 :]


def state_hash(state_text: str) -> str:
    return hashlib.sha256(state_text.encode()).hexdigest()
