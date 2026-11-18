"""Statement units for Rely-1 (M0 decision 7): code-split agent sentences, and a list item carries
its lead-in line as context.

A unit is one sentence of an agent message before the proposed action (M0 `sentences.py`
splitting: line breaks, then sentence ends, list markers kept with their item). When a unit is a
list item ("- Total price: $255", "1. Cancel …"), its lead-in is the non-list line directly above
its list, when that line ends with a colon ("… I will use the following details:"). A non-list
line without a colon ends the lead-in; indented continuation lines and nested items keep it.
Nothing here depends on a statement kind or a tool.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

M0 = Path(__file__).parents[1] / "2026-11-18-rely1-m0"
sys.path.insert(0, str(M0))
from sentences import split_sentences  # noqa: E402

LIST_ITEM = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+")


def units(packet: dict) -> list[dict]:
    """[{id, turn, text, lead_in}] for every agent sentence, in conversation order. `turn` is the
    1-based T number of the rendered packet; `id` is "T{turn}.{k}"."""
    out = []
    for t_i, turn in enumerate(packet["conversation"], start=1):
        if turn["role"] != "agent" or not turn["text"].strip():
            continue
        lead_in = None
        k = 0
        for line in turn["text"].splitlines():
            if not line.strip():
                continue
            is_item = bool(LIST_ITEM.match(line))
            continuation = not is_item and line[:1].isspace() and lead_in is not None
            if continuation:
                is_item = True  # an indented line inside a list keeps the list's lead-in
            elif not is_item:
                # "**Flights eligible for upgrade:**" ends in a colon inside its emphasis
                lead_in = line.strip() if line.rstrip().rstrip("*_ ").endswith(":") else None
            for sent in split_sentences(line):
                k += 1
                out.append(
                    {
                        "id": f"T{t_i}.{k}",
                        "turn": t_i,
                        "text": sent,
                        "lead_in": lead_in if is_item else None,
                    }
                )
    return out
