"""Addendum 3A: build the blind human-review pack for the judge/oracle disagreements.

Writes `review/cases.json` (what the reviewer sees: conversations, proposed calls and policy;
no verdicts, reason codes, task numbers, backend answers or rewards) and `review/key.json`
(which write each case is, and both graders' verdicts). Refuses to overwrite either.

    python experiments/2026-10-25-docent-vs-oracle/make_review_pack.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "review"
POLICY = Path(".tau2-bench/data/tau2/domains/retail/policy.md")
SEED = 20261028
ACTION_SECTION = {
    "cancel_pending_order": "Cancel pending order",
    "modify_pending_order_items": "Modify pending order",
    "modify_pending_order_payment": "Modify pending order",
    "modify_pending_order_address": "Modify pending order",
    "return_delivered_order_items": "Return delivered order",
    "exchange_delivered_order_items": "Exchange delivered order",
    "modify_user_address": "Generic action rules",
}
ACTION_LABEL = {
    "cancel_pending_order": "Cancel a pending order",
    "modify_pending_order_items": "Change items in a pending order",
    "modify_pending_order_payment": "Change a pending order's payment method",
    "modify_pending_order_address": "Change a pending order's address",
    "return_delivered_order_items": "Return items from a delivered order",
    "exchange_delivered_order_items": "Exchange items in a delivered order",
    "modify_user_address": "Change the customer's default address",
}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def policy_sections() -> tuple[str, dict[str, str]]:
    text = POLICY.read_text()
    parts = re.split(r"(?m)^## ", text)
    intro = parts[0].strip()
    return intro, {p.split("\n", 1)[0].strip(): "## " + p.strip() for p in parts[1:]}


def summarize(content: str) -> dict:
    """A readable view of one tool result; the raw text is always kept."""
    out: dict = {"raw": content}
    try:
        data = json.loads(content)
    except ValueError:
        return out
    if isinstance(data, dict) and "order_id" in data and "items" in data:
        out["order"] = {
            "order_id": data["order_id"],
            "user_id": data.get("user_id"),
            "status": data.get("status"),
            "items": [
                {k: i.get(k) for k in ("name", "item_id", "price", "options")}
                for i in data["items"]
            ],
            "payments": data.get("payment_history", []),
        }
    elif isinstance(data, dict) and "payment_methods" in data:
        out["user"] = {
            "user_id": data.get("user_id"),
            "name": data.get("name"),
            "payment_methods": {
                k: v.get("source") + (f" (balance {v['balance']})" if "balance" in v else "")
                for k, v in data["payment_methods"].items()
            },
            "orders": data.get("orders", []),
        }
    elif isinstance(data, dict) and "variants" in data:
        out["product"] = {
            "name": data.get("name"),
            "variants": [
                {k: v.get(k) for k in ("item_id", "options", "available", "price")}
                for v in data["variants"].values()
            ],
        }
    return out


def describe(name: str, options: dict | None) -> str:
    opts = ", ".join(f"{k} {v}" for k, v in (options or {}).items())
    return f"{name} ({opts})" if opts else name


def case_view(run: dict) -> dict:
    names: dict[str, str] = {}
    methods: dict[str, str] = {}
    turns = []
    calls_by_id: dict[str, dict] = {}
    msgs = run["messages"]
    for m in msgs[:-1]:
        if m["role"] == "user":
            turns.append({"who": "customer", "text": m["content"] or ""})
        elif m["role"] == "assistant":
            calls = [
                {"name": c["function"], "args": c["arguments"]} for c in m.get("tool_calls") or []
            ]
            for c, raw in zip(calls, m.get("tool_calls") or [], strict=True):
                calls_by_id[raw["id"]] = c
            turns.append({"who": "agent", "text": m["content"] or "", "calls": calls})
        else:
            view = summarize(m["content"] or "")
            for item in (view.get("order") or {}).get("items", []):
                names[item["item_id"]] = describe(item["name"], item["options"])
            product = view.get("product") or {}
            for v in product.get("variants", []):
                names.setdefault(v["item_id"], describe(product["name"], v["options"]))
            methods.update((view.get("user") or {}).get("payment_methods", {}))
            call = calls_by_id.get(m.get("tool_call_id"), {})
            turns.append({"who": "system", "tool": call.get("name"), **view})
    last = msgs[-1]
    proposed = next(c for c in last["tool_calls"] if c["id"] == "proposed")
    args = proposed["arguments"]
    notes = {}
    for key in ("item_ids", "new_item_ids"):
        if key in args:
            notes[key] = [names.get(i, "not shown earlier") for i in args[key]]
    if "payment_method_id" in args:
        notes["payment_method_id"] = methods.get(args["payment_method_id"], "not shown earlier")
    return {
        "action": proposed["function"],
        "action_label": ACTION_LABEL.get(proposed["function"], proposed["function"]),
        "turns": turns,
        "final_text": last["content"] or "",
        "proposed": {"name": proposed["function"], "args": args, "notes": notes},
    }


def main() -> None:
    if (OUT / "cases.json").exists() or (OUT / "key.json").exists():
        sys.exit("review pack exists; written once")
    runs = {r["write_id"]: r for r in jsonl(HERE / "data/runs.jsonl")}
    truth = {r["write_id"]: r for r in jsonl(HERE / "data/truth.jsonl")}
    docent = {
        r["write_id"]: r["judge"]
        for r in json.loads((HERE / "results/comparison.json").read_text())["rows"]
    }
    disagreements = [
        c["write_id"] for c in json.loads((HERE / "adjudication.json").read_text())["cases"]
    ]
    rng = random.Random(SEED)
    controls = []
    for label in ("ALLOW", "ASK", "DENY"):
        pool = sorted(w for w in runs if truth[w]["oracle"] == label and docent.get(w) == label)
        controls.append(rng.choice(pool))
    chosen = [(w, "disagreement") for w in disagreements] + [(w, "control") for w in controls]
    rng.shuffle(chosen)
    intro, sections = policy_sections()
    cases, key = [], []
    for n, (w, role) in enumerate(chosen, 1):
        cid = f"case-{n:02d}"
        view = case_view(runs[w])
        view["policy_section"] = sections[ACTION_SECTION[view["action"]]]
        cases.append({"id": cid, **view})
        key.append(
            {
                "case": cid,
                "write_id": w,
                "role": role,
                "store": truth[w]["store"],
                "task_id": truth[w]["task_id"],
                "oracle": truth[w]["oracle"],
                "docent": docent[w],
            }
        )
    general = "\n\n".join(sections[s] for s in ("Generic action rules",))
    OUT.mkdir(exist_ok=True)
    pack = {
        "policy_intro": intro,
        "policy_general": general,
        "policy_full": POLICY.read_text(),
        "cases": cases,
    }
    (OUT / "cases.json").write_text(json.dumps(pack, indent=1) + "\n")
    (OUT / "key.json").write_text(json.dumps({"seed": SEED, "cases": key}, indent=1) + "\n")
    print(f"{len(cases)} cases ({len(disagreements)} disagreements, {len(controls)} controls)")


if __name__ == "__main__":
    main()
