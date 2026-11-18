"""How far generic ledger trimming goes, for the M0 gate's options (Report.md). Train and dev only.

    /path/to/kev-venv/bin/python experiments/2026-11-18-rely1-m0/trim_options.py

Measures state tokens (Kev's encoder and tokenizer, as tokens.py) under trims that know nothing
about any tool or statement kind. None of them is adopted here: choosing one is a decision for the
person (README.md, "Gate").

- dedup: a lookup repeated with identical tool, arguments and result keeps only its last copy;
  the earlier entries stay in the ledger as a pointer to the later one, so the order is kept.
  Lossless: a repeat whose result differs (for example after a write) is kept in full.
- dedup_reads_only: dedup, and only `read` lookups are deduplicated (writes and `generic` kept).
- cap_N: dedup, then every result longer than N tokens is cut to its first N tokens, with a marker.
  Lossy: what is cut may be what a statement contradicts.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from kev.model import user_tokens

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from packets import render  # noqa: E402
from tokens import (  # noqa: E402
    BASE,
    BASE_REVISION,
    LIMIT,
    PACKETS,
    load_tokenizer,
    load_train_dev,
    summary,
)


def dedup(p: dict, reads_only: bool = False) -> dict:
    p = copy.deepcopy(p)
    last = {}
    for e in p["ledger"]:
        if reads_only and e["kind"] != "read":
            continue
        last[_key(e)] = e["n"]
    for e in p["ledger"]:
        k = _key(e)
        if k in last and last[k] != e["n"]:
            e["result"] = f"(same as L{last[k]})"
    return p


def _key(e: dict) -> tuple:
    """Same tool, same arguments and the same result: a lookup repeated after a write can return
    something different, and then both copies are kept."""
    return (e["tool"], json.dumps(e["arguments"], sort_keys=True), e["result"], e["error"])


def cap(p: dict, tok, n: int) -> dict:
    p = copy.deepcopy(p)
    for e in p["ledger"]:
        ids = user_tokens(tok, e["result"] or "")
        if len(ids) > n:
            e["result"] = tok.decode(ids[:n]) + f" …[cut: {len(ids) - n} more tokens]"
    return p


def main() -> None:
    packets = load_train_dev(PACKETS)
    if {p["packet_version"] for p in packets} != {"rely1-packet-v0"}:
        raise SystemExit(
            "trim_options.py is the v0 record (results/trim_options.json); it measures v0 packets "
            "only and is not rerun on v1"
        )
    tok = load_tokenizer(BASE, revision=BASE_REVISION)

    def state(p: dict) -> int:
        return len(user_tokens(tok, render(p))) + 1

    variants = {
        "none": lambda p: p,
        "dedup": dedup,
        "dedup_reads_only": lambda p: dedup(p, reads_only=True),
        "dedup_cap_1000": lambda p: cap(dedup(p), tok, 1000),
        "dedup_cap_500": lambda p: cap(dedup(p), tok, 500),
    }
    out = {"scope": "train and dev (174 actions)", "limit": LIMIT}
    for name, f in variants.items():
        lens = [state(f(p)) for p in packets]
        out[name] = summary(lens)
        print(name, out[name])
    (HERE / "results/trim_options.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
