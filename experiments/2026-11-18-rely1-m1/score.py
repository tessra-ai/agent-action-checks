"""Score the M1 gate from the people's answers (README.md, "Gate"). Written and committed before
any answer exists; run once when both answer files are in review/.

    python experiments/2026-11-18-rely1-m1/score.py

Inputs: results/label_set.jsonl, review/prithvi_answers.json (exported from his sheet),
review/second_answers.json (the second labeller's download), results/agreement.jsonl.

Reports, every number with its denominator and split under / over 8,192 tokens:
1. Pre-fill vs Prithvi on the random 40: matches (gate: at least 36). "unsure" is not a match.
2. (a) Of the 14 MC pre-fills, how many Prithvi confirms as MC.
3. (b) MCs Prithvi finds in the random 40, and what that implies for the statements pre-filled
   not MC that nobody reviewed: rate with a 95% Wilson interval, times their count.
4. Prithvi vs the second labeller on the 30 main statements (gate: at least 26), and on the 5
   over-limit ones separately. "Not sure" from either side is not agreement.
5. Agreement labels: how many pre-fills Prithvi confirms or changes.

Before counting, Prithvi's agreement answers are applied: statements on an action he marks "no
agreement" leave every count; an action he moves from "no" to "yes" was never sampled, so it is
listed as needing a follow-up review and the result is marked provisional. Answer files must
match the current sheets (Prithvi's `items_sha256`, the second sheet's `fingerprint`) and be
complete; otherwise nothing is written.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).parent


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mc_of(answer: object) -> str | None:
    """'yes' / 'no' / 'unsure' from either sheet's answer format."""
    if isinstance(answer, dict):
        return answer.get("mc")
    return answer if isinstance(answer, str) else None


def split(rows: list[dict], f) -> dict:
    out = {}
    out["all"] = f(rows)
    for length in ("under_8192", "over_8192"):
        out[length] = f([r for r in rows if r["length"] == length])
    return out


def final_agreement(agreement: list[dict], prithvi: dict) -> dict[str, str]:
    """Prithvi's answer where he gave one (on a pre-fill, or an optional override of a rule or
    earlier-ruling label), otherwise the label as built."""
    out = {}
    for a in agreement:
        given = (prithvi.get("agree:" + a["write_id"]) or {}).get("agreed")
        out[a["write_id"]] = given or a["agreed"]
    return out


def score(rows: list[dict], prithvi: dict, second: dict, agreement: list[dict]) -> dict:
    final = final_agreement(agreement, prithvi)
    built = {a["write_id"]: a["agreed"] for a in agreement}
    dropped = [r for r in rows if final.get(r["write_id"], "yes") == "no"]
    rows = [r for r in rows if final.get(r["write_id"], "yes") != "no"]
    newly_agreed = sorted(w for w in final if built[w] == "no" and final[w] != "no")
    by_block = lambda b: [r for r in rows if r["review"]["prithvi_reason"] == b]  # noqa: E731
    p = lambda r: mc_of(prithvi.get(r["unit_key"]))  # noqa: E731
    s = lambda r: mc_of(second.get(r["unit_key"]))  # noqa: E731

    def prefill_match(rs: list[dict]) -> dict:
        want = {"MC": "yes", "not MC": "no"}
        answered = [r for r in rs if p(r)]
        return {
            "n": len(rs),
            "answered": len(answered),
            "match": sum(p(r) == want[r["prefill"]] for r in answered),
            "unsure": sum(p(r) == "unsure" for r in answered),
        }

    def confirmed(rs: list[dict]) -> dict:
        return {
            "n": len(rs),
            "confirmed_mc": sum(p(r) == "yes" for r in rs),
            "rejected": sum(p(r) == "no" for r in rs),
            "unsure": sum(p(r) == "unsure" for r in rs),
            "unanswered": sum(p(r) is None for r in rs),
        }

    random40 = by_block("random 40")
    found = sum(p(r) == "yes" for r in random40)
    reviewed = {r["unit_key"] for r in rows if r["review"]["prithvi"]}
    unreviewed_not_mc = [
        r for r in rows if r["prefill"] == "not MC" and r["unit_key"] not in reviewed
    ]
    lo, hi = wilson(found, len(random40))

    def by_length(length: str) -> dict:
        """The random-40 rate for one length group, applied to that group's unreviewed pool: the
        over-limit block was drawn from long packets only, so the pools differ in their mix."""
        sample = [r for r in random40 if r["length"] == length]
        pool = [r for r in unreviewed_not_mc if r["length"] == length]
        k = sum(p(r) == "yes" for r in sample)
        u = sum(p(r) == "unsure" for r in sample)
        a, b = wilson(k, len(sample))
        b_if_unsure_yes = wilson(k + u, len(sample))[1]
        return {
            "found": k,
            "unsure": u,
            "of": len(sample),
            "rate_95ci": [round(a, 3), round(b, 3)],
            "rate_high_if_unsure_were_mc": round(b_if_unsure_yes, 3),
            "implied_mc_high_if_unsure_were_mc": round(b_if_unsure_yes * len(pool)),
            "unreviewed_not_mc_statements": len(pool),
            "implied_mc_low_point_high": [
                round(a * len(pool)),
                round(k / max(1, len(sample)) * len(pool)),
                round(b * len(pool)),
            ],
        }

    def pair(rs: list[dict]) -> dict:
        both = [r for r in rs if p(r) and s(r)]
        return {
            "n": len(rs),
            "both_answered": len(both),
            "agree": sum(p(r) == s(r) and p(r) != "unsure" for r in both),
            "either_unsure": sum("unsure" in (p(r), s(r)) for r in both),
        }

    main = [r for r in rows if r["review"]["second_reason"] == "main"]
    over = [r for r in rows if r["review"]["second_reason"] == "over-limit block"]

    pre = [a for a in agreement if a["source"] == "prefill"]
    ans = {a["write_id"]: prithvi.get("agree:" + a["write_id"]) or {} for a in pre}
    given = {w: v.get("agreed") for w, v in ans.items()}
    shrunk = {
        "random 40": sum(r["review"]["prithvi_reason"] == "random 40" for r in dropped),
        "second main 30": sum(r["review"]["second_reason"] == "main" for r in dropped),
    }
    return {
        "provisional": bool(newly_agreed) or any(shrunk.values()),
        # The thresholds (36 of 40, 26 of 30) assume full samples: if Prithvi's agreement answers
        # remove statements from them, the fixed-size gate cannot be evaluated as written.
        "fixed_size_gate_evaluable": not any(shrunk.values()),
        "samples_shrunk_by_agreement": shrunk,
        "agreement_applied": {
            "statements_dropped_as_no_agreement": len(dropped),
            "dropped_by_block": {
                b: sum(r["review"]["prithvi_reason"] == b for r in dropped)
                for b in ("pre-filled MC", "random 40", "over-limit block")
            },
            "actions_moved_to_agreed_need_follow_up": newly_agreed,
        },
        "gate_prefill_vs_prithvi_random40": split(random40, prefill_match),
        "gate_threshold_prefill": "at least 36 of 40 match",
        "a_mc_prefills_confirmed": split(by_block("pre-filled MC"), confirmed),
        "b_mc_found_in_random40": {
            "found": found,
            "unsure": sum(p(r) == "unsure" for r in random40),
            "of": len(random40),
            "rate_95ci": [round(lo, 3), round(hi, 3)],
            "unreviewed_not_mc_statements": len(unreviewed_not_mc),
            "implied_mc_among_them_low_point_high": [
                round(lo * len(unreviewed_not_mc)),
                round(found / max(1, len(random40)) * len(unreviewed_not_mc)),
                round(hi * len(unreviewed_not_mc)),
            ],
            "by_length": {g: by_length(g) for g in ("under_8192", "over_8192")},
            "note": "confirmed MCs only: 'unsure' counts as not MC in the rate; the "
            "'high if unsure were MC' figures bound that. A rough extrapolation from one random "
            "sample of 40; prefer the by-length "
            "figures, since the pools differ in length mix; the label set's not-MC statements are "
            "not a random sample of all statements",
        },
        "over_limit_block_prithvi": split(by_block("over-limit block"), confirmed),
        "gate_prithvi_vs_second_main30": split(main, pair),
        "gate_threshold_people": "at least 26 of 30 agree",
        "prithvi_vs_second_over_limit5": pair(over),
        "agreement_prefills": {
            "n": len(pre),
            "answered": sum(bool(v) for v in given.values()),
            "confirmed": sum(given[a["write_id"]] == a["agreed"] for a in pre),
            "changed": sum(
                bool(given[a["write_id"]]) and given[a["write_id"]] != a["agreed"] for a in pre
            ),
        },
    }


def sheet_data(name: str) -> dict:
    html = (HERE / f"review/{name}_sheet.html").read_text()
    blob = re.search(r"const DATA = (.*?);\nconst (SHEET|KEY)", html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


TURNS = re.compile(
    "^\\s*T?\\d+(\\s*[-\u2013]\\s*T?\\d+)?(\\s*,\\s*T?\\d+(\\s*[-\u2013]\\s*T?\\d+)?)*\\s*$"
)


def parse_turns(text: str | None) -> list[int] | None:
    """'31, 34' or 'T31-T34' -> turn numbers; None when the text is not in that form."""
    if not (text or "").strip():
        return []
    if not TURNS.match(text):
        return None
    out: list[int] = []
    for part in text.split(","):
        nums = [int(n) for n in re.findall(r"\d+", part)]
        if len(nums) == 2 and nums[1] < nums[0]:
            return None  # a reversed range
        out += list(range(nums[0], nums[-1] + 1)) if len(nums) == 2 else nums
    return out


def customer_turns(sheet: dict) -> dict[str, set[int]]:
    """{write_id: the T numbers of its customer messages}, from the conversations on the sheet
    the reviewer used (already checked against its fingerprint)."""
    return {
        w: {i for i, t in enumerate(a["conversation"], start=1) if t["role"] == "customer"}
        for w, a in sheet["actions"].items()
    }


def check(rows: list[dict], agreement: list[dict], pa: dict, sa: dict) -> list[str]:
    """Problems that stop scoring: a file from another sheet or version, or missing answers."""
    problems = []
    pd, sd = sheet_data("prithvi"), sheet_data("second")
    if pa.get("sheet") != "prithvi" or pa.get("items_sha256") != pd["items_sha256"]:
        problems.append("prithvi_answers.json is not from the current Prithvi sheet")
    if sa.get("sheet") != "second" or sa.get("fingerprint") != sd["fingerprint"]:
        problems.append("second_answers.json is not from the current second sheet")
    for name, d in (("Prithvi", pd), ("second", sd)):
        for f, digest in d.get("inputs", {}).items():
            if hashlib.sha256((HERE / "results" / f).read_bytes()).hexdigest() != digest:
                problems.append(f"the {name} sheet was built from another {f}; rebuild it")
        if not d.get("inputs"):
            problems.append(f"the {name} sheet does not record its inputs; rebuild it")
    p, s = pa.get("answers", {}), sa.get("answers", {})
    three = {"yes", "no", "unsure"}
    choices = {
        "mc": three,
        "material": three,
        "records": {"supported", "contradicted", "not covered", "unsure"},
    }
    miss_p = [
        r["unit_key"]
        for r in rows
        if r["review"]["prithvi"]
        and not all((p.get(r["unit_key"]) or {}).get(f) in ok for f, ok in choices.items())
    ]
    miss_s = [
        r["unit_key"] for r in rows if r["review"]["second"] and s.get(r["unit_key"]) not in three
    ]
    given = {
        a["write_id"]: (p.get("agree:" + a["write_id"]) or {}).get("agreed") for a in agreement
    }
    miss_a = [
        a["write_id"]
        for a in agreement
        if a["source"] == "prefill" and given[a["write_id"]] not in three
    ]
    bad = [
        a["write_id"]
        for a in agreement
        if a["source"] != "prefill" and given[a["write_id"]] not in (None, *three)
    ]
    if bad:
        problems.append(f"{len(bad)} agreement overrides have an invalid value")
    cust = customer_turns(pd)
    bad_turns = []
    for a in agreement:
        ans = p.get("agree:" + a["write_id"]) or {}
        turns = parse_turns(ans.get("turns"))
        if turns is None or not set(turns) <= cust.get(a["write_id"], set()):
            bad_turns.append(a["write_id"])
        elif ans.get("agreed") == "yes" and a["agreed"] != "yes" and not turns:
            bad_turns.append(a["write_id"])  # a new yes needs the turns that carry it
    if bad_turns:
        problems.append(
            f"{len(bad_turns)} agreement answers cite turns that are not customer messages of "
            "that conversation, are not written as '31, 34' or 'T31-T34', or change an answer "
            "to yes without citing the agreeing turns"
        )
    for what, miss in (
        ("Prithvi statements (all three answers, valid choices)", miss_p),
        ("second-sheet statements (Yes / No / Not sure)", miss_s),
        ("agreement pre-fills", miss_a),
    ):
        if miss:
            problems.append(f"{len(miss)} {what} unanswered")
    return problems


def main() -> None:
    out = HERE / "results/gate.json"
    if out.exists():
        raise SystemExit("gate results exist; scored once")
    rows = [json.loads(x) for x in (HERE / "results/label_set.jsonl").read_text().splitlines()]
    agreement = [json.loads(x) for x in (HERE / "results/agreement.jsonl").read_text().splitlines()]
    pa = json.loads((HERE / "review/prithvi_answers.json").read_text())
    sa = json.loads((HERE / "review/second_answers.json").read_text())
    problems = check(rows, agreement, pa, sa)
    if problems:
        raise SystemExit("not scored: " + "; ".join(problems))
    result = score(rows, pa["answers"], sa["answers"], agreement)
    # The finalized agreement labels, with Prithvi's decision and turns where he gave them.
    final_rows = []
    for a in agreement:
        ans = pa["answers"].get("agree:" + a["write_id"]) or {}
        given = parse_turns(ans.get("turns")) or []
        decided = ans.get("agreed") or a["agreed"]
        # The pre-filled turns carry over only when the decision is unchanged: a changed answer
        # without its own turns has no cited evidence (empty), never the old decision's.
        turns = given or (a["turns"] if decided == a["agreed"] else [])
        final_rows.append(
            {
                "write_id": a["write_id"],
                "domain": a["domain"],
                "task_id": a["task_id"],
                "agreed": decided,
                "turns": turns,
                "decided_by": "Prithvi"
                if ans.get("agreed") or a["source"] == "prithvi"
                else "pre-fill",
                "reviewer_note": ans.get("note") or None,
                # what was shown to the reviewer, kept apart from the decision
                "prefill": {
                    k: a.get(k) for k in ("agreed", "turns", "reason", "note", "source", "basis")
                },
            }
        )
    (HERE / "results/agreement_final.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in final_rows)
    )
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
