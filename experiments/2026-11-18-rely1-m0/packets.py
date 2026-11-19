"""Rely-1 action packets: one loader for all 328 frozen write actions (README.md, "Packet format").

    python experiments/2026-11-18-rely1-m0/packets.py        # train + dev -> runs/packets.jsonl
    python experiments/2026-11-18-rely1-m0/packets.py --all  # all 328; M5 only

Reads the three captures, read-only:

- retail   : experiments/2026-10-25-docent-vs-oracle/data/runs.jsonl        (73)
- airline1 : experiments/2026-10-28-airline-veto/data/runs.jsonl            (133)
- airline2 : experiments/2026-11-05-airline-holdout/data/runs.jsonl         (122)

Policy text and tool descriptions come from τ²-bench at the commit the captures were made with
(`hatchway.bench.tau2.TAU2_COMMIT`), checked out at `.tau2-bench/` (git-ignored).

Nothing here is written for one kind of statement or one tool: the conversation, the proposed
call and the lookups are rendered the same way for every action.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
EXP = ROOT / "experiments"
TAU2 = ROOT / ".tau2-bench"
TAU2_COMMIT = "c5b2d228d850c59b749b93cf32c4745d3aa53967"
OUT = HERE / "runs/packets.jsonl"

CAPTURES = {
    "retail": ("retail", EXP / "2026-10-25-docent-vs-oracle"),
    "airline1": ("airline", EXP / "2026-10-28-airline-veto"),
    "airline2": ("airline", EXP / "2026-11-05-airline-holdout"),
}

# The three known wrong approvals (Goal). Located by the earlier experiments' own notes:
# claims_airline1_metrics.json "catches" and claims_retail_metrics.json "catches".
ANCHORS = {
    "01M61Q0HD0F0DNRS5WWVBVESGP": "second cheapest (airline, task 35)",
    "01M61PYGRX51BXSSZ4R86R0CQH": "certificate balance (airline, task 25)",
    "01M5JZ4FQ7N37RJXVD6FW00S14": "Gaming Mouse (retail, task 12)",
}

# v0: M0 as first measured. v1 (M0 decisions, 2026-11-18): identical repeated lookups become
# pointers to their last copy, and later calls in the same customer turn are shown as context.
# v2 (Prithvi, 2026-11-18): no consent-turn marker (agreement is a separate per-action label,
# M1 `agreement.py`), and the main text has no later calls; `text_with_later_calls` is kept
# only as a comparison, since a live check would not have them.
PACKET_VERSION = "rely1-packet-v2"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------------------------
# Tools: description and parameters, parsed from τ²'s source (no τ² import needed).


def tool_specs(domain: str) -> dict[str, dict]:
    """{tool name: {kind, description, parameters}} for every `@is_tool` method of the domain."""
    src = (TAU2 / f"src/tau2/domains/{domain}/tools.py").read_text()
    specs = {}
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef):
            continue
        kind = next(
            (
                ast.unparse(d.args[0]).split(".")[-1].lower()
                for d in node.decorator_list
                if isinstance(d, ast.Call) and ast.unparse(d.func) == "is_tool" and d.args
            ),
            None,
        )
        if kind is None:
            continue
        doc = ast.get_docstring(node) or ""
        desc, arg_docs = _split_docstring(doc)
        params = []
        for a in node.args.args[1:]:  # skip self
            params.append(
                {
                    "name": a.arg,
                    "type": ast.unparse(a.annotation) if a.annotation else None,
                    "description": arg_docs.get(a.arg, ""),
                }
            )
        specs[node.name] = {"kind": kind, "description": desc, "parameters": params}
    return specs


def _split_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Google-style docstring -> (summary text before the first section, {arg: description})."""
    lines = doc.splitlines()
    section = None
    summary: list[str] = []
    args: dict[str, str] = {}
    current = None
    for line in lines:
        head = line.strip()
        if head in ("Args:", "Returns:", "Raises:"):
            section = head[:-1]
            continue
        if section is None:
            summary.append(line)
        elif section == "Args":
            m = re.match(r"\s{4}(\w+)(?:\s*\(.*?\))?:\s*(.*)", line)
            if m and not line.startswith(" " * 8):
                current = m.group(1)
                args[current] = m.group(2).strip()
            elif current and head:
                args[current] += " " + head
    return "\n".join(summary).strip(), args


def policy_text(domain: str) -> str:
    return (TAU2 / f"data/tau2/domains/{domain}/policy.md").read_text().strip()


# --------------------------------------------------------------------------------------------
# Truth per action, rebuilt exactly as each experiment built it (no file in those folders is
# written or rerun).


def truth_airline1() -> dict[str, dict]:
    d = EXP / "2026-10-28-airline-veto"
    grades = {g["write_id"]: g for g in jsonl(d / "results/grades.jsonl")}
    key = {
        k["case"]: k["write_id"] for k in json.loads((d / "review/key.json").read_text())["cases"]
    }
    answers = json.loads((d / "review/answers.json").read_text())["answers"]
    fixes = json.loads((d / "review/corrections.json").read_text())["corrections"]
    final = {c: a["decision"] for c, a in answers.items()} | {
        f["case"]: f["corrected"] for f in fixes
    }
    out = {w: {"should_run": g["grader_run"], "source": "graders"} for w, g in grades.items()}
    for c, dec in final.items():
        out[key[c]] = {"should_run": dec == "allow", "source": "person's review"}
    return out


def truth_airline2() -> dict[str, dict]:
    d = EXP / "2026-11-05-airline-holdout"
    key = json.loads((d / "grading/key.json").read_text())
    key = key.get("cases", key)
    c2w = {k["case"]: k["write_id"] for k in key} if isinstance(key, list) else dict(key)
    out = {
        c2w[g["case"]]: {"should_run": g["grader_run"], "source": "graders"}
        for g in jsonl(d / "results/grades.jsonl")
    }
    for a in json.loads((d / "review/consistency.json").read_text())["applied"]:
        out[a["write_id"]] = {
            "should_run": a["ruling"] == "allow",
            "source": "first-capture ruling",
        }
    rkey = {k["case"]: k for k in json.loads((d / "review/key.json").read_text())["cases"]}
    answers = json.loads((d / "review/answers.json").read_text())["answers"]
    decided = {c: a["decision"] for c, a in answers.items()}
    for c in json.loads((d / "review/corrections.json").read_text())["corrections"]:
        decided[c["case"]] = c["corrected"]
    for c, dec in decided.items():
        out[rkey[c]["write_id"]] = {"should_run": dec == "allow", "source": "person's review"}
    return out


def truth_retail() -> dict[str, dict]:
    """The policy oracle (ALLOW runs; ASK/DENY do not; UNKNOWN has no truth), replaced by the
    person's review of 10 writes (`review/answers.json`), which is what fixes the Gaming Mouse."""
    d = EXP / "2026-10-25-docent-vs-oracle"
    out = {}
    for t in jsonl(d / "data/truth.jsonl"):
        if t["oracle"] != "UNKNOWN":
            out[t["write_id"]] = {"should_run": t["oracle"] == "ALLOW", "source": "oracle"}
    key = {
        k["case"]: k["write_id"] for k in json.loads((d / "review/key.json").read_text())["cases"]
    }
    for c, a in json.loads((d / "review/answers.json").read_text())["answers"].items():
        out[key[c]] = {"should_run": a["decision"] == "allow", "source": "person's review"}
    return out


TRUTH = {"retail": truth_retail, "airline1": truth_airline1, "airline2": truth_airline2}


def meta(capture: str) -> dict[str, dict]:
    d = CAPTURES[capture][1]
    if capture == "retail":
        return {
            t["write_id"]: {"task_id": t["task_id"], "session_id": None, "store": t["store"]}
            for t in jsonl(d / "data/truth.jsonl")
        }
    return {
        m["write_id"]: {"task_id": m["task_id"], "session_id": m["session_id"], "seq": m["seq"]}
        for m in jsonl(d / "data/meta.jsonl")
    }


# --------------------------------------------------------------------------------------------
# The packet.


def compact(content: str) -> str:
    """A tool result as compact JSON when it parses, else verbatim."""
    try:
        return json.dumps(json.loads(content), separators=(",", ":"), ensure_ascii=False)
    except (ValueError, TypeError):
        return content


def dedup_ledger(ledger: list[dict]) -> None:
    """A lookup repeated with the same tool, arguments, result and error flag keeps only its last
    copy; earlier copies point to it, so order is kept. A repeat whose result changed (for
    example after a write) is kept in full. Lossless and kind-agnostic."""

    def key(e: dict) -> tuple:
        return (e["tool"], json.dumps(e["arguments"], sort_keys=True), e["result"], e["error"])

    last = {key(e): e["n"] for e in ledger}
    for e in ledger:
        k = key(e)
        if last[k] != e["n"]:
            e["result"], e["same_as"] = f"(same as L{last[k]})", last[k]


def _sig(call: dict) -> tuple:
    return (call["function"], json.dumps(call["arguments"], sort_keys=True))


def plan_calls(run: dict, runs: list[dict]) -> list[dict]:
    """Later calls in the same customer turn: later write proposals in the same conversation
    (their history contains this call) with no customer message between this call and them.
    Distinct calls other than this one (a retry of this call is not another call), in the order
    proposed. They are what the agent did next, **not** calls the customer is known to have
    agreed to: the Gaming Mouse return is one of them. Whether each was agreed is part of the
    judgement (Report.md, decision 2). Read from the capture: the agent proposed them after this
    call ran, so a live gate would not have them."""
    msgs = run["messages"]
    prefix, prop = msgs[:-1], msgs[-1]["tool_calls"][-1]
    later = []
    for b in runs:
        mb = b["messages"]
        if b is run or len(mb) <= len(msgs) or mb[: len(prefix)] != prefix:
            continue
        calls = mb[len(prefix)].get("tool_calls") or []
        if not any(_sig(c) == _sig(prop) for c in calls):  # it ran, possibly in a batch
            continue
        if any(m["role"] == "user" for m in mb[len(msgs) : -1]):
            continue
        later.append((len(mb), mb[-1]["tool_calls"][-1]))
    out, seen = [], {_sig(prop)}
    for _, call in sorted(later, key=lambda x: x[0]):
        if _sig(call) not in seen:
            seen.add(_sig(call))
            out.append({"tool": call["function"], "arguments": call["arguments"]})
    return out


def build(
    capture: str,
    run: dict,
    specs: dict[str, dict],
    policy: str,
    runs: list[dict] | None = None,
) -> dict:
    """One action packet. The conversation keeps every customer and agent message in order;
    each tool call becomes a numbered ledger entry, and the conversation shows only its number,
    so no record appears twice. No turn is marked as the consent: whether and where the customer
    agreed is a per-action label, not part of the input."""
    msgs = run["messages"]
    proposed = msgs[-1]["tool_calls"][-1]
    assert proposed["id"] == "proposed", run["write_id"]

    results = {m["tool_call_id"]: m for m in msgs if m["role"] == "tool"}
    ledger: list[dict] = []
    turns: list[dict] = []
    for m in msgs:
        if m["role"] == "user":
            turns.append({"role": "customer", "text": m["content"]})
        elif m["role"] == "assistant":
            refs = []
            for call in m.get("tool_calls") or []:
                if call["id"] == "proposed":
                    continue
                res = results.get(call["id"])
                ledger.append(
                    {
                        "n": len(ledger) + 1,
                        "tool": call["function"],
                        "kind": specs.get(call["function"], {}).get("kind", "unknown"),
                        "arguments": call["arguments"],
                        "result": compact(res["content"]) if res else None,
                        "error": bool(res and res.get("error")),
                    }
                )
                refs.append(len(ledger))
            if m["content"] or refs:
                turns.append({"role": "agent", "text": m["content"] or "", "ledger_refs": refs})
    dedup_ledger(ledger)

    spec = specs[proposed["function"]]
    return {
        "packet_version": PACKET_VERSION,
        "write_id": run["write_id"],
        "capture": capture,
        "domain": CAPTURES[capture][0],
        "conversation": turns,
        "proposed_action": {
            "tool": proposed["function"],
            "arguments": proposed["arguments"],
            "description": spec["description"],
            "parameters": spec["parameters"],
        },
        "plan_calls": plan_calls(run, runs or []),
        "policy": policy,
        "ledger": ledger,
    }


def render(p: dict, later_calls: bool = False) -> str:
    """The packet as the one text document a decision model reads (Kev's `state`). The main
    version has no later calls; `later_calls=True` renders the comparison version. v0 and v1
    packets render as they were measured."""
    out = ["# Conversation up to the proposed action", ""]
    for i, t in enumerate(p["conversation"], start=1):
        tag = "customer" if t["role"] == "customer" else "agent"
        if t.get("consent"):  # v0 / v1 packets only
            tag += " [CONSENT TURN]"
        line = f"[T{i}] {tag}: {t['text']}".rstrip()
        if t.get("ledger_refs"):
            line += " (lookups " + ", ".join(f"L{n}" for n in t["ledger_refs"]) + ")"
        out.append(line)
    a = p["proposed_action"]
    out += ["", "# Proposed action", f"tool: {a['tool']}"]
    out.append("arguments: " + json.dumps(a["arguments"], ensure_ascii=False, sort_keys=True))
    out.append(f"description: {a['description']}")
    for prm in a["parameters"]:
        out.append(f"- {prm['name']} ({prm['type']}): {prm['description']}")
    if p.get("packet_version") == "rely1-packet-v0":  # v0 had no later-calls section
        out += ["", "# Policy", p["policy"], "", "# Evidence ledger (every lookup, in order)"]
        return _ledger_lines(out, p)
    if later_calls or p.get("packet_version") == "rely1-packet-v1":
        out += ["", "# Later calls in the same customer turn (agreement not verified)"]
        for c in p.get("plan_calls") or []:
            args = json.dumps(c["arguments"], ensure_ascii=False, sort_keys=True)
            out.append(f"- {c['tool']} {args}")
        if not p.get("plan_calls"):
            out.append("none")
    out += ["", "# Policy", p["policy"], "", "# Evidence ledger (every lookup, in order)"]
    return _ledger_lines(out, p)


def _ledger_lines(out: list[str], p: dict) -> str:
    for e in p["ledger"]:
        args = json.dumps(e["arguments"], ensure_ascii=False, sort_keys=True)
        err = " ERROR" if e["error"] else ""
        out.append(f"[L{e['n']}] {e['tool']} {args} ->{err} {e['result']}")
    return "\n".join(out) + "\n"


def load_all(keep: set[str] | None = None) -> list[dict]:
    """Action packets with their metadata (task, session, truth, anchor), in capture order.
    `keep`: build only these write IDs (None builds all 328, which is for M5)."""
    packets = []
    for capture, (domain, d) in CAPTURES.items():
        runs = [r for r in jsonl(d / "data/runs.jsonl") if keep is None or r["write_id"] in keep]
        if not runs:
            continue  # nothing selected from this capture: its truth is not rebuilt
        specs, policy = tool_specs(domain), policy_text(domain)
        selected = {r["write_id"] for r in runs}
        m = meta(capture)
        truth = {w: t for w, t in TRUTH[capture]().items() if w in selected}
        for run in runs:
            w = run["write_id"]
            p = build(capture, run, specs, policy, runs)  # same conversation = same split
            p["meta"] = {
                **m[w],
                "truth": truth.get(w),
                "anchor": ANCHORS.get(w),
            }
            packets.append(p)
    return packets


def main() -> None:
    head = subprocess.run(
        ["git", "-C", str(TAU2), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if head != TAU2_COMMIT:
        raise SystemExit(f".tau2-bench must be checked out at {TAU2_COMMIT}, found {head}")
    if "--all" in sys.argv:  # M5 only: the test splits are opened once, then
        keep = None
    else:
        keep = set()
        for name in ("train", "dev"):
            keep |= {r["write_id"] for r in json.loads((HERE / f"splits/{name}.json").read_text())}
    packets = load_all(keep)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for p in packets:
            p["text"] = render(p)
            p["text_with_later_calls"] = render(p, later_calls=True)
            f.write(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"{len(packets)} packets -> {OUT.relative_to(ROOT)} sha256 {digest}")


if __name__ == "__main__":
    main()
