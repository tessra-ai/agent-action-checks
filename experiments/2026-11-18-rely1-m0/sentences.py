"""Agent statements as code-split sentences, and the mixing audit (README.md, "Sentence audit").

    python experiments/2026-11-18-rely1-m0/sentences.py        # train split only

A statement unit is a sentence of an agent message before the proposed action, split by code:
line breaks first (lists and paragraphs), then sentence-ending punctuation followed by space.

The audit asks how often one sentence mixes a statement that matters with an unrelated one.
There are no materiality labels yet (M1), so it reports two things and says which is which:

1. A proxy over every train sentence, from the existing claims check (claims_*_verified.jsonl):
   a sentence that carries one claim scoped to the proposed call (`this_call`) and another
   scoped elsewhere (`other_call`) mixes the two. Claims whose quote crosses a sentence boundary
   are counted too, since splitting would cut that statement.
2. A random sample of train sentences that carry a claim, written out for a reader to judge
   (review/sentence_sample.json). The reader's judgement goes in the report.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from packets import EXP  # noqa: E402

PACKETS = HERE / "runs/packets.jsonl"
CLAIMS = {
    "airline1": EXP / "2026-11-05-airline-holdout/results/claims_airline1_verified.jsonl",
    "retail": EXP / "2026-11-05-airline-holdout/results/claims_retail_verified.jsonl",
}
SEED = 20261118
SAMPLE = 40

# Split after sentence-ending punctuation (and a closing quote or bracket, which stays with the
# sentence) when whitespace and a sentence-like start follow.
_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+(?=[\"'(\[]?[A-Z0-9#$*-])")


_MARKER = re.compile(r"^((?:[-•*]|\d+[.)])\s+)")


def split_sentences(text: str) -> list[str]:
    """Line breaks, then sentence ends. A list marker ("1. ", "- ") stays with its item."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _MARKER.match(line)
        marker, rest = (m.group(1), line[m.end() :]) if m else ("", line)
        parts = [s.strip() for s in _END.split(rest) if s.strip()]
        if parts:
            parts[0] = marker + parts[0]
        out += parts
    return out


def agent_sentences(packet: dict) -> list[str]:
    return [
        s
        for t in packet["conversation"]
        if t["role"] == "agent"
        for s in split_sentences(t["text"])
    ]


def _norm(s: str) -> str:
    """Lowercase, markdown emphasis and list markers dropped, whitespace collapsed: extracted quotes
    drop the agent's `**bold**` and `- ` list markers."""
    s = re.sub(r"[*`_]", "", s)
    s = re.sub(r"(^|\n)\s*(?:[-•]|\d+\.)\s+", r"\1", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def audit() -> dict:
    train = {r["write_id"] for r in json.loads((HERE / "splits/train.json").read_text())}
    rows = [p for p in map(json.loads, PACKETS.read_text().splitlines()) if p["write_id"] in train]
    ids = [p["write_id"] for p in rows]
    if len(ids) != len(set(ids)) or set(ids) != train:
        raise SystemExit(
            f"{PACKETS.name}: {len(set(ids))} of {len(train)} train packets "
            f"({len(ids) - len(set(ids))} duplicated); rebuild it with packets.py"
        )
    packets = {p["write_id"]: p for p in rows}
    claims = {}
    for path in CLAIMS.values():
        for r in map(json.loads, path.read_text().splitlines()):
            if r["write_id"] in packets:
                claims[r["write_id"]] = r["claims"]

    sentences = 0
    with_claim = 0
    mixed = []
    where = {
        "one_sentence": 0,
        "spans_sentences": 0,
        "stitched_from_parts": 0,
        "customer_text": 0,
        "tool_call_text": 0,
        "ambiguous_several_sentences": 0,
    }
    stitched_examples = []
    claim_rows = []
    for w, p in packets.items():
        sents = agent_sentences(p)
        sentences += len(sents)
        normed = [_norm(s) for s in sents]
        conv = p["conversation"]
        agent_text = _norm(" ".join(t["text"] for t in conv if t["role"] == "agent"))
        customer_text = _norm(" ".join(t["text"] for t in conv if t["role"] == "customer"))
        per_sentence: dict[int, list[dict]] = {}
        for c in claims.get(w, []):
            q = _norm(c["quote"])
            hits = [i for i, s in enumerate(normed) if q and q in s]
            if len({sents[i] for i in hits}) > 1:
                # The same words in two different sentences: which one the claim is about cannot be
                # read from the quote, so it is counted and not attached.
                where["ambiguous_several_sentences"] += 1
            elif hits:
                where["one_sentence"] += 1
                per_sentence.setdefault(hits[0], []).append(c)
            elif q in agent_text:
                where["spans_sentences"] += 1  # contiguous agent text that code splits in two
            elif q in customer_text:
                where["customer_text"] += 1  # the extractor quoted the customer
            elif re.match(r"^\w+\(\{", c["quote"].strip()):
                where["tool_call_text"] += 1  # the extractor quoted a tool call, not agent text
            else:
                # The extractor joined pieces of agent text, typically a list's lead-in and one item
                where["stitched_from_parts"] += 1
                if len(stitched_examples) < 8:
                    stitched_examples.append(c["quote"])
        for i, cs in per_sentence.items():
            with_claim += 1
            scopes = {c["scope"] for c in cs}
            row = {
                "write_id": w,
                "sentence": sents[i],
                "claims": [
                    {
                        "kind": c["kind"],
                        "scope": c["scope"],
                        "verdict": c["verdict"],
                        "quote": c["quote"],
                    }
                    for c in cs
                ],
            }
            claim_rows.append(row)
            if "this_call" in scopes and "other_call" in scopes:
                mixed.append(row)

    rng = random.Random(SEED)
    sample = rng.sample(claim_rows, min(SAMPLE, len(claim_rows)))
    review = HERE / "review/sentence_sample.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text(json.dumps({"seed": SEED, "split": "train", "rows": sample}, indent=1) + "\n")

    return {
        "split": "train",
        "actions": len(packets),
        "agent_sentences": sentences,
        "claims_in_train": sum(len(v) for v in claims.values()),
        "claims_by_location": where,
        "stitched_examples": stitched_examples,
        "sentences_with_a_claim": with_claim,
        "sentences_mixing_this_call_and_other_call_claims": len(mixed),
        "mixed_examples": mixed[:10],
        "sample_for_reading": str(review.relative_to(HERE)),
    }


def main() -> None:
    result = audit()
    out = HERE / "results/sentence_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "mixed_examples"}, indent=1))


if __name__ == "__main__":
    main()
