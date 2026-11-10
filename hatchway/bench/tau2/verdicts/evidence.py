"""Deterministic readers over the conversation before a proposed write.

The validators use these to answer the conversational parts of a policy: was the customer
authenticated, did the agent present the details, did the customer say yes, was anything changed
after that. Each reader follows the oracle's evidence rule:

- evidence objectively absent (the details were never presented, nobody asked) → `ask`;
- evidence present but not reliably classifiable (a reply that is neither a clear yes nor a
  clear no) → `unknown`;
- an explicit contradiction (the customer changed the details after confirming) → `deny`.

Confirmation is checked per value (order id, items, payment method, price), not per message: an
agent often confirms the items in one exchange and the payment method in another, and a
customer often states the details and says "I confirm" in the same message.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hatchway.bench.tau2.verdicts.base import Check, CheckOutcome, ToolCallRef, Turn

Affirmation = Literal["yes", "no", "unclear"]
ChainStatus = Literal["CONFIRMED", "ABSENT", "NOT_AFFIRMED", "UNCLEAR", "CHANGED"]

# --- Affirmation --------------------------------------------------------------------------------

_YES = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|correct|confirm|confirmed|go ahead|proceed|please do|"
    r"do it|that's right|that is right|sounds good|that works|exactly|absolutely)\b"
)
# A refusal counts only when the reply opens with it, or says outright not to go on: "I do not
# want to change my plan" is not a refusal of the refuel the agent asked about.
_NO_START = re.compile(r"^\W*(no|nope|wait|hold on|stop|cancel|don't|do not|never ?mind)\b")
_NO_ANYWHERE = re.compile(
    r"\b(don't|do not) (do|proceed|process|go ahead|continue)\b|\bdo not want (this|that|it)\b"
)
# Words that qualify a yes: "yes, but…", "yes, except…", a question back.
_HEDGE = re.compile(r"\b(but|however|except|instead|unless|only if|actually)\b|\?")


def affirmation(text: str) -> Affirmation:
    """`yes`, `no` or `unclear` for one customer message. Only a clear yes with no hedge is
    `yes`; only an explicit refusal is `no`; everything else is `unclear`."""
    t = _normalize(text)
    says_no = bool(_NO_START.search(t) or _NO_ANYWHERE.search(t))
    # "do not proceed" is a refusal, not a "proceed".
    says_yes = bool(_YES.search(_NO_ANYWHERE.sub(" ", t)))
    if says_no and not says_yes:
        return "no"
    if says_yes and not says_no and not _HEDGE.search(t):
        return "yes"
    return "unclear"


# --- Value matchers -----------------------------------------------------------------------------

Matcher = Callable[[str], bool]


def _normalize(text: str) -> str:
    return text.lower().replace("\u2019", "'").replace("\u2018", "'")


def contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", _normalize(text)) is not None


_ORDER_ID = re.compile(r"#?\bw(\d{7})\b")


def order_ids_in(text: str) -> set[str]:
    return {f"#W{m}" for m in _ORDER_ID.findall(_normalize(text))}


_MONEY = (
    re.compile(r"\$\s?(\d+(?:,\d{3})*(?:\.\d+)?)"),
    re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)\s?(?:usd|dollars?)\b"),
)


def money_in(text: str) -> list[float]:
    t = _normalize(text)
    return [float(m.replace(",", "")) for rx in _MONEY for m in rx.findall(t)]


_GB = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(?:gb|gigabytes?)\b")


def gb_amounts_in(text: str) -> list[float]:
    return [float(m) for m in _GB.findall(_normalize(text))]


_PER_GB = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?(?:/|per|a|each)\s?(?:gb|gigabyte)\b")


def per_gb_rates_in(text: str) -> list[float]:
    return [float(m) for m in _PER_GB.findall(_normalize(text))]


def without_per_gb_rates(text: str) -> str:
    """The text with every per-GB rate ("$2.00 per GB") removed."""
    return _PER_GB.sub(" ", _normalize(text))


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def phone_numbers_in(text: str) -> set[str]:
    """Phone numbers as their last 10 digits (or all digits when shorter, from 7)."""
    found = re.findall(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)
    return {digits(n)[-10:] for n in found}


def same_amount(a: float, b: float) -> bool:
    return abs(a - b) < 0.005


# --- Conversation structure --------------------------------------------------------------------


def tool_results(turns: Sequence[Turn]) -> dict[str, Turn]:
    """Tool result turns keyed by the id of the call they answer."""
    return {t.tool_call_id: t for t in turns if t.role == "tool" and t.tool_call_id}


def successful_calls(
    turns: Sequence[Turn], names: Iterable[str], requestor: str = "assistant"
) -> list[tuple[ToolCallRef, Turn]]:
    """Calls to any of `names` by `requestor` that got a result without an error, in order."""
    wanted = set(names)
    results = tool_results(turns)
    out = []
    for t in turns:
        if t.role != requestor:
            continue
        for call in t.tool_calls:
            result = results.get(call.id)
            if call.name in wanted and result is not None and not result.error:
                out.append((call, result))
    return out


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def text_turns(turns: Sequence[Turn]) -> list[Turn]:
    return [t for t in turns if t.is_text]


# --- Confirmation chain ------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainResult:
    status: ChainStatus
    facts: Mapping[str, Any] = field(default_factory=dict)


def confirmation_chain(
    turns: Sequence[Turn], mentions: Matcher, conflicts: Matcher | None = None
) -> ChainResult:
    """Whether the customer confirmed one value before the call.

    Walks back over the text turns (tool-call-only turns and tool results are skipped) to the
    latest mention of the value that settles it:

    - a customer message naming the value: its own yes, no or unclear decides;
    - an agent message naming it: the customer's next message decides. An agent mention with no
      customer reply after it (the agent restating the details as it acts) settles nothing,
      and the walk goes on to the mention before it.

    No settling mention at all is `ABSENT`. After a confirmation, a later message naming a
    conflicting value (another order, another payment method) is `CHANGED` when the customer
    affirmed it (or stated it themselves), else `UNCLEAR`.
    """
    texts = text_turns(turns)
    for pos in range(len(texts) - 1, -1, -1):
        turn = texts[pos]
        if not mentions(turn.content):
            continue
        if turn.role == "user":
            reply_pos = pos
        else:
            reply_pos = next((j for j in range(pos + 1, len(texts)) if texts[j].role == "user"), -1)
            if reply_pos < 0:
                continue
        reply = texts[reply_pos]
        answer = affirmation(reply.content)
        facts = {"presented_in_turn": turn.index, "reply_turn": reply.index, "reply": answer}
        if answer == "no":
            return ChainResult("NOT_AFFIRMED", facts)
        if answer == "unclear":
            return ChainResult("UNCLEAR", facts)
        if conflicts is not None:
            for later_pos in range(reply_pos + 1, len(texts)):
                later = texts[later_pos]
                if not conflicts(later.content):
                    continue
                facts = {**facts, "conflict_turn": later.index}
                if later.role == "user":
                    settled = affirmation(later.content) != "no"
                else:
                    nxt = next(
                        (
                            texts[j]
                            for j in range(later_pos + 1, len(texts))
                            if texts[j].role == "user"
                        ),
                        None,
                    )
                    settled = nxt is not None and affirmation(nxt.content) == "yes"
                return ChainResult("CHANGED" if settled else "UNCLEAR", facts)
        return ChainResult("CONFIRMED", facts)
    return ChainResult("ABSENT", {})


def plan_confirmation(
    turns: Sequence[Turn],
    chains: Mapping[str, ChainResult],
    conflicts: Mapping[str, Matcher | None],
) -> dict[str, ChainResult]:
    """Resolve UNCLEAR values that the customer later confirmed as part of the plan.

    An agent often names the order early, gets a question back, and later asks to go ahead
    with a plan that names only the items and the payment method. A clear yes to that plan
    confirms its order too, when the order is the only one in play. So the one value whose
    chain is UNCLEAR becomes CONFIRMED when:

    - its own reply was unclear (not a conflict after a confirmation);
    - every other value is CONFIRMED, and the latest of their replies (the plan's yes) comes
      after the unclear reply;
    - no conflicting value (`conflicts[name]`) is named in any text turn from the value's
      presentation through the plan's yes.

    Every other status is left as it is.
    """
    out = dict(chains)
    unclear = [n for n, r in chains.items() if r.status == "UNCLEAR"]
    confirmed = [r for r in chains.values() if r.status == "CONFIRMED"]
    if len(unclear) != 1 or not confirmed or len(confirmed) != len(chains) - 1:
        return out
    name = unclear[0]
    r = chains[name]
    plan_reply = max(c.facts["reply_turn"] for c in confirmed)
    if "conflict_turn" in r.facts or r.facts["reply_turn"] >= plan_reply:
        return out
    conflict = conflicts.get(name)
    start = r.facts["presented_in_turn"]
    if conflict is not None and any(
        conflict(t.content) for t in text_turns(turns) if start <= t.index <= plan_reply
    ):
        return out
    out[name] = ChainResult("CONFIRMED", {**r.facts, "confirmed_by_plan_reply": plan_reply})
    return out


CHAIN_OUTCOMES: dict[ChainStatus, tuple[CheckOutcome, str]] = {
    "CONFIRMED": ("pass", "confirmed"),
    "ABSENT": ("ask", "never presented to the customer and confirmed"),
    "NOT_AFFIRMED": ("ask", "the customer did not agree"),
    "UNCLEAR": ("unknown", "the customer's reply is not a clear yes or no"),
    "CHANGED": ("deny", "the details changed after the customer confirmed them"),
}

_CHAIN_CODES: dict[ChainStatus, str] = {
    "CONFIRMED": "CONFIRMED",
    "ABSENT": "CONFIRMATION_MISSING",
    "NOT_AFFIRMED": "CONFIRMATION_DECLINED",
    "UNCLEAR": "CONFIRMATION_UNCLEAR",
    "CHANGED": "DETAILS_CHANGED_AFTER_CONFIRMATION",
}

_SEVERITY: dict[CheckOutcome, int] = {"pass": 0, "unknown": 1, "ask": 2, "deny": 3}


def confirmation_check(results: Mapping[str, ChainResult]) -> Check:
    """One check over the per-value chains; the worst value decides (deny, then ask, then
    unknown). The code names the worst chain status."""
    worst_name = max(results, key=lambda n: _SEVERITY[CHAIN_OUTCOMES[results[n].status][0]])
    status = results[worst_name].status
    outcome, note = CHAIN_OUTCOMES[status]
    if outcome == "pass":
        code, note = "DETAILS_CONFIRMED", "every detail was presented and confirmed"
    else:
        code, note = _CHAIN_CODES[status], f"{worst_name}: {note}"
    facts = {name: {"status": r.status, **r.facts} for name, r in results.items()}
    return Check(code, outcome, note, facts)
