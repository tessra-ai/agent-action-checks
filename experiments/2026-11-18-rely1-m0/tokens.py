"""Exact packet lengths with Kev's own encoder (README.md, "Length audit"). Train and dev only.

    /path/to/kev-venv/bin/python experiments/2026-11-18-rely1-m0/tokens.py

Needs Kev's code importable (github.com/jaredpalmer/kev, commit KEV_COMMIT) and its pinned
tokenizer. Kev serves a Hub checkpoint with the base model's tokenizer at the base revision in
the checkpoint's provenance (`kev.checkpoint.Checkpoint.load`); for Kev-4B v1.0 that is
Qwen/Qwen3.5-4B-Base @ BASE_REVISION. The tokenizer files shipped in the kev-4b repo are counted
too, as a cross-check.

The packet is Kev's `state`. Counts go through `kev.model.encode`, so they include Kev's marker
tokens (<state>, <q>, <opt>, </opt>, <decide>) and its escaping of caller text. The test splits
are not read.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path

import kev
from kev.model import SERVE_MAX_BRANCH, SERVE_MAX_STATE, encode, load_tokenizer, user_tokens

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from sentences import agent_sentences  # noqa: E402

PACKETS = HERE / "runs/packets.jsonl"
# results/token_lengths.json is the v0 measurement M0 was gated on, token_lengths_v1.json the
# v1 one; v2 (main text without later calls, plus the with-later-calls comparison) writes its own.
OUT = HERE / "results/token_lengths_v2.json"
BASE = "Qwen/Qwen3.5-4B-Base"
BASE_REVISION = "1001bb4d826a52d1f399e183466143f4da7b741b"
KEV_REPO, KEV_REVISION = "jaredpalmer/kev-4b", "v1.0"
LIMIT = 8192  # Kev-4B's validated context (state tokens)
TRAINED = 7552  # longest state Kev-4B v1.0 was trained on

# The direct question (Model spec), with one statement filled in. Only its length matters here.
QUESTION = (
    'Agent statement: "{s}"\n'
    "Is this statement a material contradiction for the proposed action: do the records "
    "contradict it, and would correcting it plausibly change the customer's yes to this "
    "exact action?"
)


def pct(xs: list[int], q: float) -> int:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))]


def summary(xs: list[int]) -> dict:
    return {
        "n": len(xs),
        "median": int(statistics.median(xs)),
        "p95": pct(xs, 0.95),
        "max": max(xs),
        "over_8192": sum(x > LIMIT for x in xs),
        "over_7552": sum(x > TRAINED for x in xs),
    }


HEADERS = {
    "conversation": "# Conversation up to the proposed action\n",
    "proposed_action": "\n# Proposed action\n",
    "plan_calls": "\n# Later calls in the same customer turn (agreement not verified)\n",
    "policy": "\n# Policy\n",
    "ledger": "\n# Evidence ledger (every lookup, in order)\n",
}


def sections(text: str) -> dict[str, str]:
    """The four sections, cut at packets.render's own headers (the policy has `#` headings too)."""
    present = {name: text.index(h) for name, h in HEADERS.items() if h in text}
    cuts = list(present.values())
    assert cuts == sorted(cuts), "headers out of order"
    ends = [*cuts[1:], len(text)]
    out = {name: text[a:b] for name, a, b in zip(present, cuts, ends, strict=True)}
    return {name: out.get(name, "") for name in HEADERS}


def frozen_train_dev() -> set[str]:
    ids: set[str] = set()
    for name in ("train", "dev"):
        ids |= {r["write_id"] for r in json.loads((HERE / f"splits/{name}.json").read_text())}
    return ids


def load_train_dev(path: Path) -> list[dict]:
    """The train and dev packets, refusing an incomplete or duplicated packet file: a gate
    statistic over a partial set would look valid."""
    keep = frozen_train_dev()
    packets = [p for p in map(json.loads, path.read_text().splitlines()) if p["write_id"] in keep]
    ids = [p["write_id"] for p in packets]
    if len(ids) != len(set(ids)) or set(ids) != keep:
        raise SystemExit(
            f"{path.name}: {len(set(ids))} of {len(keep)} train/dev packets "
            f"({len(ids) - len(set(ids))} duplicated); rebuild it with packets.py"
        )
    return packets


def main() -> None:
    splits = {
        name: {r["write_id"] for r in json.loads((HERE / f"splits/{name}.json").read_text())}
        for name in ("train", "dev")
    }
    packets = load_train_dev(PACKETS)
    if {p["packet_version"] for p in packets} != {"rely1-packet-v2"}:
        raise SystemExit("tokens.py measures packet v2; rebuild runs/packets.jsonl with packets.py")

    tok = load_tokenizer(BASE, revision=BASE_REVISION)
    tok_card = load_tokenizer(KEV_REPO, revision=KEV_REVISION)

    rows = []
    for p in packets:
        sents = agent_sentences(p)
        longest = max(sents, key=len) if sents else ""
        rec = {
            "state": p["text"],
            "questions": [
                {"instr": QUESTION.format(s=longest), "options": ["yes", "no"], "label": 0}
            ],
        }
        enc = encode(tok, rec, max_state=SERVE_MAX_STATE, max_branch=SERVE_MAX_BRANCH, strict=True)
        card_state = len(user_tokens(tok_card, p["text"])) + 1
        with_later = len(user_tokens(tok, p["text_with_later_calls"])) + 1
        rows.append(
            {
                "write_id": p["write_id"],
                "split": "train" if p["write_id"] in splits["train"] else "dev",
                "domain": p["domain"],
                "state_tokens": enc["state_tokens"],
                "row_tokens_longest_statement": len(enc["ids"]),
                "state_tokens_card_tokenizer": card_state,
                "state_tokens_with_later_calls": with_later,
                "sections": {
                    k: len(user_tokens(tok, v))
                    for k, v in sections(p["text_with_later_calls"]).items()
                },
                "ledger_entries": len(p["ledger"]),
                "agent_sentences": len(sents),
            }
        )

    state = [r["state_tokens"] for r in rows]
    result = {
        "kev_code": {
            "repo": "github.com/jaredpalmer/kev",
            "commit": KEV_COMMIT,
            "package_version": kev_version(),
        },
        "tokenizer": {
            "used": f"{BASE}@{BASE_REVISION}",
            "why": (
                "kev.checkpoint loads the base tokenizer at the provenance base_revision; "
                "kev-4b v1.0 provenance.json pins this"
            ),
            "class": type(tok).__name__,
            "cross_check": f"{KEV_REPO}@{KEV_REVISION} tokenizer files",
            "cross_check_identical_counts": all(
                r["state_tokens"] == r["state_tokens_card_tokenizer"] for r in rows
            ),
        },
        "packets_sha256": hashlib.sha256(PACKETS.read_bytes()).hexdigest(),
        "scope": "train and dev splits only; test splits not read",
        "packet_version": packets[0]["packet_version"],
        "by_split": {
            sp: summary([r["state_tokens"] for r in rows if r["split"] == sp])
            for sp in ("train", "dev")
        },
        "with_plan_calls": sum(1 for p in packets if p.get("plan_calls")),
        "state": summary(state),
        "main_text": "no later calls (the version a live check would see)",
        "state_with_later_calls": summary([r["state_tokens_with_later_calls"] for r in rows]),
        "sections_note": "sections are counted on the with-later-calls text; the main text is "
        "the same without the plan_calls section",
        "state_by_domain": {
            d: summary([r["state_tokens"] for r in rows if r["domain"] == d])
            for d in ("airline", "retail")
        },
        "row_with_longest_statement_question": summary(
            [r["row_tokens_longest_statement"] for r in rows]
        ),
        "sections": {k: summary([r["sections"][k] for r in rows]) for k in HEADERS},
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))


def kev_version() -> str:
    try:
        from importlib.metadata import version

        return version("kev")
    except Exception:
        return "unknown"


KEV_COMMIT = "2074cc44256200bb37540103fa4572901faa10f3"
_found = subprocess.run(
    ["git", "-C", str(Path(kev.__file__).resolve().parents[1]), "rev-parse", "HEAD"],
    capture_output=True,
    text=True,
).stdout.strip()
if _found != KEV_COMMIT:
    raise SystemExit(f"kev checkout is at {_found or 'no git checkout'}, expected {KEV_COMMIT}")


if __name__ == "__main__":
    main()
