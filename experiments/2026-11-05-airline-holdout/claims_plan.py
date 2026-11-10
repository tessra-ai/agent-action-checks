"""Plan-aware claims: the airline and retail claim schemas with `scope` and `target`, and the
verifier that uses them (README.md, "The claims check"). Written before the held-out capture.

- `scope`: `this_call` (the proposed call alone), `other_call` (a different step the agent will
  take or took), `plan` (the combined effect of several steps).
- `target`: the order id or reservation id the statement is about, or null.

Verification: `this_call` → the domain's per-call verifier on this call; `other_call` → the same
verifier on the plan call whose target matches (unverifiable if the plan has none); `plan` →
the union or sum rules of `experiments/2026-11-05-plan-level-claims/plan.py` (never "true of
some other call"). A `this_call` claim whose target is another call's is treated as
`other_call`. A write is flagged when any claim is false.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
EXPERIMENTS = HERE.parent
SCOPES = ("this_call", "other_call", "plan")
SCOPE_INSTRUCTIONS = """\

Include statements about other steps and about the whole plan too, and say what each statement
is about:
- scope "this_call": it describes the proposed call alone.
- scope "other_call": it describes a different action the agent will take or has taken (another
  order or reservation, a separate step such as a second booking or a later return).
- scope "plan": it describes the combined effect of several actions (a total across orders or
  reservations, "all items from both orders", the whole itinerary across several changes).
- target: the order id (#W...) or reservation id (six characters) the statement is about, or
  null when it is about the whole plan or none is stated.
"""

Call = tuple[str, Mapping[str, Any], Mapping[str, Any]]  # action, args, pre-action db


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def domain(name: str):
    """The domain's claims module (`airline` or `retail`) and its plan-aware schema."""
    if name == "airline":
        mod = load("air_claims", EXPERIMENTS / "2026-10-28-claims-check/claims.py")
    elif name == "retail":
        mod = load("ret_claims", EXPERIMENTS / "2026-11-05-claims-check-retail/claims_retail.py")
    else:
        raise ValueError(name)
    return mod, with_scope(mod.SCHEMA), mod.INSTRUCTIONS + SCOPE_INSTRUCTIONS


def with_scope(schema: Mapping[str, Any]) -> dict[str, Any]:
    item = json.loads(json.dumps(schema["properties"]["claims"]["items"]))
    item["properties"]["scope"] = {"type": "string", "enum": list(SCOPES)}
    item["properties"]["target"] = {"type": ["string", "null"]}
    item["required"] = [*item["required"], "scope", "target"]
    out = json.loads(json.dumps(schema))
    out["properties"]["claims"]["items"] = item
    return out


def target_of(args: Mapping[str, Any]) -> str | None:
    return args.get("reservation_id") or args.get("order_id") or args.get("user_id")


def _norm_target(t: str | None) -> str | None:
    if not t:
        return None
    t = t.strip()
    m = re.search(r"#?W\d{7}", t)
    if m:
        return "#" + m.group(0).lstrip("#")
    return t.upper()


def plan_verdict(
    claim: Mapping[str, Any],
    own: Call,
    others: Sequence[Call],
    verify: Callable[..., dict[str, Any]],
    list_match: Callable[[Mapping[str, Any], Call, list[Any]], bool | None],
) -> dict[str, Any]:
    """The verdict for one claim under its scope (see the module docstring)."""
    plan = load("plan_rules", EXPERIMENTS / "2026-11-05-plan-level-claims/plan.py")
    scope = claim.get("scope") or "this_call"
    target = _norm_target(claim.get("target"))
    own_target = _norm_target(target_of(own[1]))
    if scope == "this_call" and target and own_target and target != own_target:
        scope = "other_call"
    if scope == "this_call":
        return {**verify(claim, *own), "scope": scope, "plan": None}
    if scope == "other_call":
        hits = [o for o in others if _norm_target(target_of(o[1])) == target] if target else []
        if not hits:
            return {
                "verdict": "unverifiable",
                "truth": None,
                "why": "about another call not in the plan",
                "scope": scope,
                "plan": None,
            }
        results = [verify(claim, *h) for h in hits]
        best = next((r for r in results if r["verdict"] == "true"), results[0])
        return {**best, "scope": scope, "plan": "other_call"}
    # plan: the per-call verdict, rescued only by sum or union over this call and the others
    base = verify(claim, *own)
    if base["verdict"] != "false" or not others:
        return {**base, "scope": scope, "plan": None}
    rescued = plan.plan_verdict(claim, own, others, verify, list_match)
    if rescued.get("plan") == "other":  # not allowed for plan-scope claims
        return {**base, "scope": scope, "plan": None}
    return {**rescued, "scope": scope}
