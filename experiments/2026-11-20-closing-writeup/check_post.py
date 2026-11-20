"""Check that every number in post.md comes from numbers.json (or, for figures about other papers,
from prior_work.md).

    python experiments/2026-11-20-closing-writeup/check_post.py

Every number token in the post's text is compared with the values in numbers.json: counts and
denominators as they are, rates and bounds as whole percentages, AUCs and kappas at two decimals.
Numbers that are not figures (dates, model and product names such as GPT-4.1 or Kev-4B, folder
names, the 0.5 setting and widths that name a configuration) are listed in NOT_FIGURES or
NAME_PATTERNS. A percentage must match a sourced percentage, not a bare count; selection caps match
the caps recorded in numbers.json (jev_tradeoff). Anything else that matches nothing is reported,
and the script exits non-zero.

This only proves that each number exists somewhere in numbers.json or prior_work.md. Small
integers appear in many places there, so whether a number is the right one for its sentence is
checked by reading (the Codex gate), against numbers.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# tokens that name something rather than state a result, with the reason
NOT_FIGURES = {
    "2026": "dates and folder names",
    "8192": "the packet-length threshold (Kev-4B's validated context), not a result",
}
NAME_PATTERNS = [
    r"GPT-4\.1(?:-nano|-mini)?",
    r"GPT-6\.2-sol",
    r"Kev-4B",
    r"4B",
    r"4-billion",
    r"Qwen",
    r"τ²-bench",
    r"Gemini 4 Neon",
    r"2026-11-\d\d(?:-[a-z0-9-]+)?",
    r"rely1-m\d",
    r"-m\d\b",
    r"uncaught-38",
    r"arxiv\.org/abs/\d{4}\.\d{5}",
    r"fixed 0\.5\b",
    r"first of the three",
]


def values(node, out: set[str]) -> None:
    if isinstance(node, dict):
        for v in node.values():
            values(v, out)
    elif isinstance(node, list):
        for v in node:
            values(v, out)
    elif isinstance(node, bool):
        return
    elif isinstance(node, int):
        out.add(str(node))
    elif isinstance(node, float):
        out.add(f"{node:.2f}")
        out.add(f"{node:.3f}".rstrip("0").rstrip("."))
        if 0 <= node <= 1:
            out.add(f"{round(node * 100)}%")
            out.add(str(round(node * 100)))
    elif isinstance(node, str):
        for m in re.findall(r"\d[\d,]*(?:\.\d+)?", node):
            out.add(m.replace(",", ""))


def main() -> int:
    N = json.loads((HERE / "numbers.json").read_text())
    allowed: set[str] = set()
    values({k: v for k, v in N.items() if k != "checks"}, allowed)
    # the selection caps the results were run at, recorded as jev_tradeoff keys (cap_5pct ...)
    for k in N["jev_tradeoff"]:
        m = re.fullmatch(r"cap_(\d+)pct", k)
        if m:
            allowed.add(f"{m.group(1)}%")
    for c in N["checks"]:  # the brief's figures that numbers.json reproduces
        if c["match"]:
            values(c["computed"], allowed)
    pw = (HERE / "prior_work.md").read_text()
    # figures about papers: only numbers inside the quotations check_prior_work.py verifies, not
    # years, arXiv IDs or section numbers elsewhere in the notes
    quoted = " ".join(re.findall(r'"([^"]*)"', re.sub(r"\n(?!\n)", " ", pw)))
    paper_nums = set(re.findall(r"\d+(?:\.\d+)?%?", quoted))
    text = (HERE / "post.md").read_text()
    text = (
        text.split("\n---\n", 1)[1] if text.startswith("---") else text
    )  # front matter checked too below
    front = (HERE / "post.md").read_text().split("\n---\n", 1)[0]
    body = re.sub(r"\(/blog/[^)]*\)|\(https?://[^)]*\)", "", front + "\n" + text)
    # a cascade width names a configuration: it must be one the results were run at
    widths = set()
    for k in list(N["cascade"]) + list(N["designs"]):
        widths.update(re.findall(r"width (0\.\d)", k))
    bad_widths = [w for w in re.findall(r"width (0\.\d+)", body) if w not in widths]
    body = re.sub(r"width 0\.\d+", " ", body)
    for pat in NAME_PATTERNS:
        body = re.sub(pat, " ", body)
    missing = []
    for m in re.finditer(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?", body):
        tok = m.group(0).replace(",", "")
        # a percentage must match a sourced percentage, never a bare count ("174%" is not "174")
        ok = tok in allowed or tok in paper_nums
        if not ok and tok in NOT_FIGURES:
            ok = True
        if not ok:
            ctx = body[max(0, m.start() - 40) : m.end() + 30].replace("\n", " ")
            missing.append(f"{tok!r}: ...{ctx}...")
    missing += [f"{w!r}: a cascade width with no recorded run" for w in bad_widths]
    print(f"{len(missing)} numbers in post.md not traced to numbers.json or prior_work.md")
    for x in missing:
        print("  ", x)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
