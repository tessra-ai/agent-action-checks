"""Arms S and S-text: symbolic rule induction from decisions, with a significance gate.

The learner starts from the world's starting policy and adds readable rules of two kinds:

- **escalation rules**, learned on the cases the starting policy allows; a rule escalates the
  cases it covers;
- **exceptions**, learned on the cases the starting policy escalates for `ask` reasons only; an
  exception allows the cases it covers. Learning never relaxes a DENY or an UNKNOWN.

A rule is a conjunction of at most `MAX_LITERALS` literals:

- a boolean fact is true, or false;
- a categorical fact (action, payment source, customer state) equals a value seen in training;
- a product is among the affected items;
- a numeric fact is above, or at most, a midpoint between two consecutive distinct training
  values;
- S-text only: a word (four letters or more) occurs in the customer's messages.

Rules are grown greedily (sequential covering). Each step adds the literal that most lowers the
rule's adjusted p-value: the one-sided hypergeometric probability of covering at least that many
positives among the covered cases, given the pool's base rate, multiplied by L^d for L candidate
literals and d literals in the rule (a Bonferroni bound over every rule of that length). Growth
stops when no literal lowers it. A rule is accepted only when its adjusted p-value is below
`ALPHA` and it covers at least `MIN_POSITIVES` positives; its covered cases then leave the pool
and the next rule is grown, up to `MAX_RULES` of each kind.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
from scipy.special import gammaln

ALPHA = 0.05
MAX_LITERALS = 3
MAX_RULES = 5
MIN_POSITIVES = 2

BOOL_FACTS = (
    "auth_missing",
    "owner_mismatch",
    "status_wrong",
    "items_invalid",
    "refund_method_invalid",
    "payment_invalid",
    "reason_invalid",
    "confirmation_missing",
)
CAT_FACTS = ("action", "payment_source", "user_state")
NUM_FACTS = (
    "amount",
    "price_difference",
    "n_items",
    "order_total",
    "user_orders",
    "user_cancelled",
)
_WORD = re.compile(r"[a-z]{4,}")


@dataclass(frozen=True)
class Schema:
    """The fact vocabulary: boolean, categorical and numeric facts, and an optional set fact
    (a literal says a value is in the set)."""

    bools: tuple[str, ...]
    cats: tuple[str, ...]
    nums: tuple[str, ...]
    set_fact: str | None = None


RETAIL = Schema(BOOL_FACTS, CAT_FACTS, NUM_FACTS, "products")


def customer_words(text: str) -> frozenset[str]:
    """Lowercase words of four letters or more in the customer's messages."""
    out: set[str] = set()
    for line in text.splitlines():
        if line.startswith("user: "):
            out.update(_WORD.findall(line[6:].lower()))
    return frozenset(out)


class Columns:
    """Facts of a set of cases as arrays, for vectorized literal masks."""

    def __init__(
        self,
        facts: Sequence[Mapping[str, Any]],
        texts: Sequence[str] | None = None,
        schema: Schema = RETAIL,
    ):
        self.n = len(facts)
        self.schema = schema
        self.arr: dict[str, np.ndarray] = {}
        for f in schema.bools:
            self.arr[f] = np.array([bool(x[f]) for x in facts], dtype=bool)
        for f in schema.cats:
            self.arr[f] = np.array([str(x[f]) for x in facts], dtype=object)
        for f in schema.nums:
            self.arr[f] = np.array([float(x[f]) for x in facts], dtype=float)
        sf = schema.set_fact
        self.products = [frozenset(x[sf]) if sf else frozenset() for x in facts]
        self.words = [customer_words(t) for t in texts] if texts is not None else None
        self._cache: dict[tuple[str, str], np.ndarray] = {}

    def member(self, kind: str, value: str) -> np.ndarray:
        key = (kind, value)
        if key not in self._cache:
            sets = self.products if kind == "has" else self.words
            if sets is None:
                raise ValueError("these columns carry no text")
            self._cache[key] = np.fromiter((value in s for s in sets), dtype=bool, count=self.n)
        return self._cache[key]


@dataclass(frozen=True, order=True)
class Literal:
    fact: str
    op: str  # "is", "eq", "has", "word", "gt" or "le"
    value: Any

    def mask(self, cols: Columns) -> np.ndarray:
        if self.op in ("has", "word"):
            return cols.member(self.op, self.value)
        x = cols.arr[self.fact]
        if self.op in ("is", "eq"):
            return x == self.value
        if self.op == "gt":
            return x > self.value
        return x <= self.value

    def describe(self) -> str:
        if self.op == "is":
            return self.fact if self.value else f"not {self.fact}"
        if self.op == "eq":
            return f"{self.fact} = {self.value}"
        if self.op == "has":
            return f"items include {self.value}"
        if self.op == "word":
            return f"customer says '{self.value}'"
        return f"{self.fact} {'>' if self.op == 'gt' else '<='} {self.value:g}"

    def to_json(self) -> list[Any]:
        return [self.fact, self.op, self.value]


@dataclass(frozen=True)
class Rule:
    kind: str  # "escalate" or "allow"
    literals: tuple[Literal, ...]
    positives: int
    covered: int
    log_p_adjusted: float

    def mask(self, cols: Columns) -> np.ndarray:
        out = np.ones(cols.n, dtype=bool)
        for lit in self.literals:
            out &= lit.mask(cols)
        return out

    def describe(self) -> str:
        verb = "escalate" if self.kind == "escalate" else "allow"
        return f"{verb} if " + " and ".join(lit.describe() for lit in self.literals)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rule": self.describe(),
            "literals": [lit.to_json() for lit in self.literals],
            "positives": self.positives,
            "covered": self.covered,
            "p_adjusted": math.exp(self.log_p_adjusted),
        }


def candidate_literals(cols: Columns, text: bool = False) -> list[Literal]:
    lits: list[Literal] = []
    schema = cols.schema
    for f in schema.bools:
        lits += [Literal(f, "is", True), Literal(f, "is", False)]
    for f in schema.cats:
        lits += [Literal(f, "eq", v) for v in sorted(set(cols.arr[f].tolist()))]
    if schema.set_fact:
        values = sorted(set().union(*cols.products))
        lits += [Literal(schema.set_fact, "has", p) for p in values]
    for f in schema.nums:
        values = np.unique(cols.arr[f])
        for t in (values[:-1] + values[1:]) / 2:
            t = round(float(t), 4)
            lits += [Literal(f, "gt", t), Literal(f, "le", t)]
    if text:
        if cols.words is None:
            raise ValueError("S-text needs the case texts")
        lits += [Literal("text", "word", w) for w in sorted(set().union(*cols.words))]
    return lits


@dataclass
class Learned:
    rules: list[Rule]
    n_literals: int

    @cached_property
    def escalate_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.kind == "escalate"]

    @cached_property
    def allow_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.kind == "allow"]

    def decide(
        self, cols: Columns, r0_escalates: np.ndarray, r0_relaxable: np.ndarray
    ) -> np.ndarray:
        """Escalate (True) or allow (False) for each case."""
        out = r0_escalates.copy()
        for r in self.escalate_rules:
            out |= ~r0_escalates & r.mask(cols)
        for r in self.allow_rules:
            out &= ~(r0_relaxable & r.mask(cols))
        return out


def _log_comb(n: np.ndarray, k: np.ndarray) -> np.ndarray:
    return gammaln(n + 1) - gammaln(k + 1) - gammaln(n - k + 1)


def log_tail_table(n_pool: int, p_pool: int) -> np.ndarray:
    """T[n, x] = log P(X >= x) for X hypergeometric: x positives among n cases drawn from a pool
    of `n_pool` cases holding `p_pool` positives (exact; -inf where impossible)."""
    n = np.arange(n_pool + 1)[:, None]
    x = np.arange(p_pool + 2)[None, :]
    with np.errstate(invalid="ignore"):
        log_pmf = (
            _log_comb(np.float64(p_pool), x.astype(float))
            + _log_comb(np.float64(n_pool - p_pool), (n - x).astype(float))
            - _log_comb(np.float64(n_pool), n.astype(float))
        )
    possible = (x <= p_pool) & (x <= n) & (n - x <= n_pool - p_pool)
    log_pmf = np.where(possible, log_pmf, -np.inf)
    tail = np.logaddexp.accumulate(log_pmf[:, ::-1], axis=1)[:, ::-1]
    tail[:, 0] = 0.0  # P(X >= 0) = 1 exactly
    return tail


def _grow(
    matrix: np.ndarray, pool: np.ndarray, positive: np.ndarray, log_l: float
) -> tuple[list[int], float, int, int]:
    """Greedy growth of one rule on the pool. Returns literal indexes, the rule's log adjusted
    p-value, positives covered and cases covered."""
    n_pool = int(pool.sum())
    p_pool = int((pool & positive).sum())
    tail = log_tail_table(n_pool, p_pool)
    cover = pool.copy()
    chosen: list[int] = []
    best = 0.0  # log of an adjusted p-value of 1: no rule
    covered_pos = covered = 0
    for depth in range(1, MAX_LITERALS + 1):
        sub = matrix[cover]
        n = sub.sum(axis=0)
        p = matrix[cover & positive].sum(axis=0)
        log_p = tail[n, p] + depth * log_l
        log_p[n == 0] = np.inf
        j = int(np.argmin(log_p))
        if not log_p[j] < best - 1e-12:
            break
        best = float(log_p[j])
        chosen.append(j)
        cover &= matrix[:, j]
        covered_pos, covered = int(p[j]), int(n[j])
    return chosen, best, covered_pos, covered


def _learn_kind(
    kind: str,
    lits: Sequence[Literal],
    matrix: np.ndarray,
    pool: np.ndarray,
    positive: np.ndarray,
) -> list[Rule]:
    rules: list[Rule] = []
    log_l = math.log(len(lits))
    pool = pool.copy()
    while len(rules) < MAX_RULES and int((pool & positive).sum()) >= MIN_POSITIVES:
        chosen, log_p, pos, cov = _grow(matrix, pool, positive, log_l)
        if not chosen or pos < MIN_POSITIVES or log_p >= math.log(ALPHA):
            break
        rule_mask = np.all(matrix[:, chosen], axis=1)
        rules.append(Rule(kind, tuple(lits[j] for j in chosen), pos, cov, log_p))
        pool &= ~rule_mask
    return rules


def learn(
    cols: Columns,
    r0_escalates: np.ndarray,
    r0_relaxable: np.ndarray,
    y_escalates: np.ndarray,
    text: bool = False,
) -> Learned:
    """Escalation rules on the cases the starting policy allows (positives: labelled escalate),
    then exceptions on the cases it escalates for ask reasons only (positives: labelled allow)."""
    lits = candidate_literals(cols, text)
    matrix = np.column_stack([lit.mask(cols) for lit in lits])
    rules = _learn_kind("escalate", lits, matrix, ~r0_escalates, y_escalates)
    rules += _learn_kind("allow", lits, matrix, r0_relaxable, ~y_escalates)
    return Learned(rules, len(lits))
