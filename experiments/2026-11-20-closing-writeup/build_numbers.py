# ruff: noqa: E501
"""Every figure for the closing post, from committed result files only.

    python experiments/2026-11-20-closing-writeup/build_numbers.py   # -> numbers.json

Train and dev only; the two frozen test splits are counted from the split manifest and never read.
Inputs are committed files in this repository: results/actions.json here (built by actions.py),
the M0 and M1 result files, the earlier experiments' result files, and two files of the 38-actions
read, copied unchanged into results/ from branch rely/uncaught-38 at commit 1453956
(results/uncaught_38_table.json, results/uncaught_38_types.json).

Each figure is stored as a count with its denominator, a rate, and where the first post gave one,
an exact 95% Clopper-Pearson interval. `brief` holds what the handover brief states for the same
figure, and `checks` lists every comparison; a mismatch is recorded, never corrected silently.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
REPO = EXP.parent
M0 = EXP / "2026-11-18-rely1-m0"
M1 = EXP / "2026-11-18-rely1-m1"
# the stock_agreement.json configuration behind the same-data 51 / 5
SAME_DATA_KEY = "stmt>=0.5, P(agreed)<0.5"
UNCAUGHT_COMMIT = "1453956"  # rely/uncaught-38: where results/uncaught_38_*.json were copied from


def load(p: Path):
    return json.loads(p.read_text())


# --- exact binomial intervals ------------------------------------------------------------------


def _cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> list[float]:
    """Exact two-sided interval; the upper end is what the first post reported as the 95% upper
    bound."""

    def solve(f, lo=0.0, hi=1.0):
        for _ in range(100):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _cdf(k - 1, n, p) >= alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: _cdf(k, n, p) <= alpha / 2)
    return [round(lower, 4), round(upper, 4)]


def upper95(k: int, n: int) -> float:
    """One-sided exact 95% upper bound (Clopper-Pearson), the method of the first post
    (experiments/2026-10-28-airline-veto/analyze.py, upper95): 27 of 60 -> 0.564, 0 of 33 -> 0.087."""
    return clopper_pearson(k, n, alpha=0.10)[1]


def frac(k: int, n: int, ci: bool = False) -> dict:
    d = {"count": k, "of": n, "rate": round(k / n, 4) if n else None}
    if ci:
        d["upper95"] = upper95(k, n)
    return d


def caught(k: int, n: int) -> dict:
    """Bad actions caught, with the missed share and its upper bound (the first post bounded the
    share of wrong actions let through)."""
    return frac(k, n) | {"missed": frac(n - k, n, True)}


CHECKS: list[dict] = []


def check(name: str, ours, brief) -> None:
    CHECKS.append({"figure": name, "computed": ours, "brief": brief, "match": ours == brief})


def kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n**2
    return (po - pe) / (1 - pe)


# --- figures -------------------------------------------------------------------------------


def main() -> None:
    acts = load(HERE / "results/actions.json")
    graded = {p: x for p, x in acts.items() if x["ruling"] != "ungraded"}
    bad = [p for p, x in acts.items() if x["ruling"] == "bad"]
    good = [p for p, x in acts.items() if x["ruling"] == "good"]
    N: dict = {}

    # data
    man = load(M0 / "splits/manifest.json")["splits"]
    tl = load(M0 / "results/token_lengths_v2.json")
    N["data"] = {
        "actions_train_dev": len(acts),
        "train": man["train"]["actions"],
        "dev": man["dev"]["actions"],
        "graded": len(graded),
        "bad": len(bad),
        "good": len(good),
        "ungraded": len(acts) - len(graded),
        "test_unseen_sealed": man["test_unseen"]["actions"],
        "test_repeat_sealed": man["test_repeat"]["actions"],
        "by_domain": {
            d: {
                r: sum(x["domain"] == d and x["ruling"] == r for x in acts.values())
                for r in ("bad", "good", "ungraded")
            }
            for d in ("airline", "retail")
        },
        "packet_tokens_p95": tl["state"]["p95"],
        "packets_over_8192": frac(tl["state"]["over_8192"], tl["state"]["n"]),
        "conversation_tokens_p95": tl["sections"]["conversation"]["p95"],
        "lookups_tokens_p95": tl["sections"]["ledger"]["p95"],
        "packets_sha256": tl["packets_sha256"],
    }
    check("actions train+dev", len(acts), 174)
    check(
        "graded / bad / good / ungraded",
        [len(graded), len(bad), len(good), len(acts) - len(graded)],
        [147, 91, 56, 27],
    )
    check(
        "sealed test sets (unseen, repeat)",
        [man["test_unseen"]["actions"], man["test_repeat"]["actions"]],
        [64, 90],
    )
    check("packet tokens p95", tl["state"]["p95"], 8996)
    check("packets over 8,192 tokens", tl["state"]["over_8192"], 14)
    check(
        "conversation tokens p95 (advisor-mistakes section)",
        tl["sections"]["conversation"]["p95"],
        2552,
    )

    # labels
    stm = [(p, q, s) for p, x in acts.items() for q, s in x["statements"].items()]
    cmpf = load(M1 / "results/labeller_comparison.json")
    ab = cmpf["A_vs_B"]
    a_yes = sum(s["A"] == "yes" for _, _, s in stm)
    b_yes = sum(s["B"] == "yes" for _, _, s in stm)
    a_na = sum(x["agreement"]["A"] == "not_agreed" for x in acts.values())
    b_na = sum(x["agreement"]["B"] == "not_agreed" for x in acts.values())
    both_yes = [(p, q) for p, q, s in stm if s["consensus"] == "yes"]
    either_yes = sum("yes" in (s["A"], s["B"]) for _, _, s in stm)
    st_agree = sum(s["A"] == s["B"] for _, _, s in stm)
    ag_agree = sum(x["agreement"]["A"] == x["agreement"]["B"] for x in acts.values())
    both_na = sum(x["agreement"]["consensus"] == "not_agreed" for x in acts.values())
    k_st = kappa([(s["A"], s["B"]) for _, _, s in stm])
    k_ag = kappa([(x["agreement"]["A"], x["agreement"]["B"]) for x in acts.values()])
    N["labels"] = {
        "statements": len(stm),
        "agreement_questions": len(acts),
        "labeller_A": {
            "statements_yes": a_yes,
            "not_agreed": a_na,
            "setup": cmpf["labellers"]["A"],
        },
        "labeller_B": {
            "statements_yes": b_yes,
            "not_agreed": b_na,
            "setup": cmpf["labellers"]["B"],
        },
        "statement_agreement": frac(st_agree, len(stm)),
        "statement_kappa": round(k_st, 2),
        "both_yes": len(both_yes),
        "either_yes": either_yes,
        "agreement_question_agreement": frac(ag_agree, len(acts)),
        "agreement_kappa": round(k_ag, 2),
        "both_not_agreed": both_na,
        "reasoning_off_kappa_vs_on": round(
            cmpf["A_vs_A_noreasoning"]["statements"]["cohen_kappa"], 2
        ),
        "anchors": cmpf["anchors"],
    }
    check("labeller A yes / not agreed", [a_yes, a_na], [29, 58])
    check("labeller B yes / not agreed", [b_yes, b_na], [26, 50])
    check("statements agreed / kappa", [st_agree, round(k_st, 2)], [366, 0.74])
    check(
        "statement kappa equals the comparison file",
        round(k_st, 3),
        round(ab["statements"]["cohen_kappa"], 3),
    )
    check("both yes / either yes", [len(both_yes), either_yes], [21, 34])
    check("agreement question agreed / kappa", [ag_agree, round(k_ag, 2)], [158, 0.79])
    check("both not agreed", both_na, 46)
    check("reasoning off vs on kappa", N["labels"]["reasoning_off_kappa_vs_on"], 0.89)

    # coverage and consensus gate
    def cat(x) -> str:
        by = any(s["consensus"] == "yes" for s in x["statements"].values())
        ag = x["agreement"]["consensus"]
        if by and ag == "agreed":
            return "contradiction_in_agreed"
        if by and ag == "not_agreed":
            return "both"
        if by:
            return "contradiction_agreement_split"
        if ag == "not_agreed":
            return "no_agreement_only"
        return "neither"

    cov = {r: Counter(cat(acts[p]) for p in (bad if r == "bad" else good)) for r in ("bad", "good")}
    prov = load(M1 / "results/provisional_checks.json")["coverage"]["bad"]["train+dev"]
    N["coverage_bad"] = dict(cov["bad"]) | {"n": len(bad)}
    N["coverage_bad_by_backend"] = {
        be: dict(Counter(cat(acts[p]) for p in bad if acts[p]["backend"] == be))
        | {"n": sum(acts[p]["backend"] == be for p in bad)}
        for be in ("ACCEPTED", "REJECTED")
    }
    N["coverage_good"] = dict(cov["good"]) | {"n": len(good)}
    check(
        "coverage of bad: no agreement / contradiction in agreed / both or split / neither",
        [
            cov["bad"]["no_agreement_only"],
            cov["bad"]["contradiction_in_agreed"],
            cov["bad"]["both"] + cov["bad"]["contradiction_agreement_split"],
            cov["bad"]["neither"],
        ],
        [38, 11, 4, 38],
    )
    check(
        "coverage of bad equals provisional_checks.json",
        [cov["bad"]["no_agreement_only"], cov["bad"]["neither"]],
        [prov["no agreement only"], prov["neither"]],
    )
    good_flags = sum(
        cat(acts[p]) != "neither" and cat(acts[p]) != "no_agreement_only" for p in good
    )
    good_na = sum(acts[p]["agreement"]["consensus"] == "not_agreed" for p in good)
    check("flags on good: contradiction / not agreed", [good_flags, good_na], [1, 0])

    def consensus_stop(x) -> bool:
        return (
            any(s["consensus"] == "yes" for s in x["statements"].values())
            or x["agreement"]["consensus"] == "not_agreed"
        )

    cons_bad = sum(consensus_stop(acts[p]) for p in bad)
    cons_good = sum(consensus_stop(acts[p]) for p in good)
    N["consensus_gate"] = {
        "bad_caught": caught(cons_bad, len(bad)),
        "good_stopped": frac(cons_good, len(good), True),
    }
    check("consensus gate", [cons_bad, cons_good], [53, 1])

    # stock models and the Kev pilot
    sm = load(M1 / "results/stock_models.json")["models"]
    sa = load(M1 / "results/stock_agreement.json")
    kp = load(M1 / "results/kev_pilot.json")
    N["stock"] = {
        "jev_statement_auc": round(sm["jev"]["auc_both_yes_vs_both_no"], 3),
        "jev_agreement_auc": round(sa["agreement_vs_consensus"]["auc_not_agreed"], 3),
        "kev4b_statement_auc": round(sm["kev4b"]["auc_both_yes_vs_both_no"], 3),
        "jev_cutoffs_tuned_on_same_data": {
            "bad_caught": sa["both_questions_per_action"]["jev"][SAME_DATA_KEY]["bad_caught"],
            "good_stopped": sa["both_questions_per_action"]["jev"][SAME_DATA_KEY]["good_stopped"],
        },
    }
    check(
        "stock Jev AUC statement / agreement (2 dp)",
        [round(N["stock"]["jev_statement_auc"], 2), round(N["stock"]["jev_agreement_auc"], 2)],
        [0.93, 0.97],
    )
    check("stock Kev-4B statement AUC", round(N["stock"]["kev4b_statement_auc"], 2), 0.43)
    check(
        "Jev on same-data cut-offs (advisor-mistakes section)",
        [
            N["stock"]["jev_cutoffs_tuned_on_same_data"]["bad_caught"],
            N["stock"]["jev_cutoffs_tuned_on_same_data"]["good_stopped"],
        ],
        [51, 5],
    )
    folds = [load(f) for f in sorted((M1 / "results/kev_pilot_folds").glob("fold*.json"))]
    N["kev_pilot"] = {
        "verdict": "improved over stock, clearly below Jev, not pursued",
        "statement_auc": round(kp["kev"]["a"]["auc"], 3),
        "agreement_auc": round(kp["kev"]["b"]["auc"], 3),
        "bad_caught": frac(kp["kev"]["c"]["bad"]["stopped"], kp["kev"]["c"]["bad"]["n"]),
        "good_stopped": frac(kp["kev"]["c"]["good"]["stopped"], kp["kev"]["c"]["good"]["n"]),
        "jev_same_protocol": {
            "bad_caught": kp["jev"]["c"]["bad"]["stopped"],
            "good_stopped": kp["jev"]["c"]["good"]["stopped"],
        },
        "training_records_per_fold": [f["data"]["train"][0] for f in folds],
        "gpu_wall_seconds_final_runs": sum(f["wall_seconds"] for f in folds),
        "planted_checks": kp["planted"],
        "planted_contradictions_kept": kp["planted"]["value swap"]["kept"]
        + kp["planted"]["flip"]["kept"],
        "cost_note": "no committed file records the Modal bill; the brief's $30 to $35 is an estimate from run times",
    }
    check(
        "Kev pilot AUCs (2 dp)",
        [round(kp["kev"]["a"]["auc"], 2), round(kp["kev"]["b"]["auc"], 2)],
        [0.81, 0.89],
    )
    check(
        "Kev pilot bad caught / good stopped",
        [kp["kev"]["c"]["bad"]["stopped"], kp["kev"]["c"]["good"]["stopped"]],
        [55, 19],
    )

    # Jev trade-off and cascade
    jc = load(M1 / "results/jev_cascade.json")
    trade = {}
    for name, v in jc["jev_tradeoff"].items():
        m = re.search(r"<= (\d+)%", name)
        key = f"cap_{m.group(1)}pct" if m else "pilot_rule"
        trade[key] = {
            "bad_caught": caught(v["bad"]["stopped"], v["bad"]["n"]),
            "good_stopped": frac(v["good"]["stopped"], v["good"]["n"], True),
        }
    N["jev_tradeoff"] = trade
    check(
        "Jev at 5% cap",
        [trade["cap_5pct"]["bad_caught"]["count"], trade["cap_5pct"]["good_stopped"]["count"]],
        [43, 4],
    )
    check(
        "Jev at 20% cap",
        [trade["cap_20pct"]["bad_caught"]["count"], trade["cap_20pct"]["good_stopped"]["count"]],
        [60, 11],
    )
    casc = {}
    for name, v in jc["cascade"].items():
        sent_a = [int(t) for t in v["actions_sent"].split(" of ")]
        sent_s = [int(t) for t in v["statements_sent"].split(" of ")]
        casc[name] = {
            "bad_caught": caught(v["bad"]["stopped"], v["bad"]["n"]),
            "good_stopped": frac(v["good"]["stopped"], v["good"]["n"], True),
            "actions_sent": frac(*sent_a),
            "statements_sent": frac(*sent_s),
        }
    N["cascade"] = casc
    c5 = casc["selection cap 5%, width 0.2"]
    check(
        "cascade 5% cap width 0.2: bad / good / share of actions sent",
        [
            c5["bad_caught"]["count"],
            c5["good_stopped"]["count"],
            round(100 * c5["actions_sent"]["rate"]),
        ],
        [55, 3, 36],
    )
    N["consensus_alone"] = {
        "bad_caught": jc["frontier_consensus_alone"]["bad"]["stopped"],
        "good_stopped": jc["frontier_consensus_alone"]["good"]["stopped"],
    }

    # the 38 uncaught
    table = load(HERE / "results/uncaught_38_table.json")
    types = load(HERE / "results/uncaught_38_types.json")
    air = [r for r in table if r["airline"]]
    blocked = sum(int(r["rules_block"].split(" of ")[0]) for r in air)
    air_n = sum(int(r["rules_block"].split(" of ")[1]) for r in air)
    N["uncaught_38"] = {
        "n": sum(r["n"] for r in table),
        "types": {
            r["type"]: {"name": r["name"], "n": r["n"], "rules_block": r["rules_block"]}
            for r in table
        },
        "rules_block_airline": frac(blocked, air_n),
        "note": "a model's read, not reviewed by a person",
    }
    check(
        "38 uncaught: n / refund-method / rules block airline",
        [
            N["uncaught_38"]["n"],
            N["uncaught_38"]["types"]["refund_not_original"]["n"],
            blocked,
            air_n,
        ],
        [38, 10, 20, 26],
    )

    # designs
    ds = load(M1 / "results/designs.json")
    refund_ids = {p for p, (ty, _) in types["actions"].items() if ty == "refund_not_original"}

    def design(v) -> dict:
        b = v["both"]
        bc = [int(t) for t in b["bad_caught"].split(" of ")]
        gs = [int(t) for t in b["good_stopped"].split(" of ")]
        rf = [int(t) for t in b["reach_frontier"].split(" of ")]
        missed = sorted(v["airline"]["bad_missed"] + v["retail"]["bad_missed"])
        executed_bad = [p for p in bad if acts[p]["backend"] == "ACCEPTED"]
        out = {
            "bad_caught": caught(*bc),
            "bad_missed": frac(bc[1] - bc[0], bc[1], True),
            "good_stopped": frac(*gs, ci=True),
            "reach_frontier": frac(*rf),
            "by_domain": {
                d: {k: v[d][k] for k in ("bad_caught", "good_stopped", "reach_frontier")}
                for d in ("airline", "retail")
            },
            "bad_missed_ids": missed,
            # the types cover only the 38 actions the consensus gate missed; a design can also miss
            # bad actions outside them, which have no type
            "missed_refund_method": sum(p in refund_ids for p in missed),
            "missed_untyped": sorted(p for p in missed if p not in types["actions"]),
            "executed_bad_caught": frac(
                sum(p not in missed for p in executed_bad), len(executed_bad)
            ),
        }
        return out

    N["designs"] = {
        name: design(v) for name, v in ds.items() if isinstance(v, dict) and "both" in v
    }
    ro = ds["rules_alone"]
    rb = sum(int(ro[d]["bad_caught"].split(" of ")[0]) for d in ro)
    rg = sum(int(ro[d]["good_stopped"].split(" of ")[0]) for d in ro)
    N["designs"]["rules alone"] = {
        "bad_caught": caught(rb, len(bad)),
        "good_stopped": frac(rg, len(good), True),
    }
    # the broad judge's effect: design C (A's stages, then the judge) minus design A, at width 0.2
    a_ = N["designs"]["A: rules -> cascade (width 0.2)"]
    N["judge_added_to_A"] = {
        f"run {r}": {
            "more_bad_caught": N["designs"][f"C: rules -> cascade (width 0.2) -> judge run {r}"][
                "bad_caught"
            ]["count"]
            - a_["bad_caught"]["count"],
            "more_good_stopped": N["designs"][f"C: rules -> cascade (width 0.2) -> judge run {r}"][
                "good_stopped"
            ]["count"]
            - a_["good_stopped"]["count"],
        }
        for r in (1, 2)
    }
    dA = N["designs"]["A: rules -> cascade (width 0.2)"]
    check("rules alone", [rb, rg], [33, 1])
    check(
        "design A: bad / good / % reaching frontier / missed / refund-method among missed",
        [
            dA["bad_caught"]["count"],
            dA["good_stopped"]["count"],
            round(100 * dA["reach_frontier"]["rate"]),
            dA["bad_missed"]["count"],
            dA["missed_refund_method"],
        ],
        [76, 3, 22, 15, 9],
    )
    bs = [N["designs"][f"B: rules -> Jev (5% cap) -> judge run {r}"] for r in (1, 2)]
    check(
        "design B: bad range / good / % frontier",
        [
            sorted(x["bad_caught"]["count"] for x in bs),
            sorted({x["good_stopped"]["count"] for x in bs}),
            round(100 * bs[0]["reach_frontier"]["rate"]),
        ],
        [[86, 88], [12], 50],
    )
    cs = [v for k, v in N["designs"].items() if k.startswith("C:")]
    check(
        "design C: bad range / good range over both widths (0.2 and 0.4) and both judge runs, as the brief states it; % frontier at width 0.2",
        [
            [min(x["bad_caught"]["count"] for x in cs), max(x["bad_caught"]["count"] for x in cs)],
            [
                min(x["good_stopped"]["count"] for x in cs),
                max(x["good_stopped"]["count"] for x in cs),
            ],
            round(
                100
                * N["designs"]["C: rules -> cascade (width 0.2) -> judge run 1"]["reach_frontier"][
                    "rate"
                ]
            ),
        ],
        [[87, 89], [10, 11], 56],
    )
    c02 = [N["designs"][f"C: rules -> cascade (width 0.2) -> judge run {r}"] for r in (1, 2)]
    check(
        "design C at width 0.2 only: bad range / good range (the brief's ranges span both widths)",
        [
            sorted(x["bad_caught"]["count"] for x in c02),
            sorted({x["good_stopped"]["count"] for x in c02}),
        ],
        [[87, 89], [10, 11]],
    )
    check(
        "design B misses the 'second cheapest' anchor (P033); A and C catch it",
        [
            all("P033" in b["bad_missed_ids"] for b in bs),
            "P033" in dA["bad_missed_ids"],
            any("P033" in x["bad_missed_ids"] for x in cs),
        ],
        [True, False, False],
    )

    # three cuts an outside review reported
    na_bad = [p for p in bad if acts[p]["agreement"]["consensus"] == "not_agreed"]
    by_model = Counter(acts[p]["agent_model"] for p in na_bad)
    nano_all = [p for p, x in acts.items() if x["agent_model"].startswith("gpt-4.1-nano")]
    N["cut_a_never_agreed_by_agent_model"] = {
        "bad_never_agreed": len(na_bad),
        "by_agent_model": dict(by_model),
        "nano_share": frac(by_model.get("gpt-4.1-nano-2025-04-14", 0), len(na_bad)),
        "nano_actions_domains": dict(Counter(acts[p]["domain"] for p in nano_all)),
        "never_agreed_by_domain": dict(Counter(acts[p]["domain"] for p in na_bad)),
        "never_agreed_backend_rejected": frac(
            sum(acts[p]["backend"] == "REJECTED" for p in na_bad), len(na_bad)
        ),
        "note": "gpt-4.1-nano ran only in the retail capture, so agent model and domain are confounded",
    }
    check(
        "cut a: never-agreed bad actions from gpt-4.1-nano",
        [by_model.get("gpt-4.1-nano-2025-04-14", 0), len(na_bad)],
        [31, 39],
    )
    rejected = [p for p in bad if acts[p]["backend"] == "REJECTED"]
    N["cut_b_backend_rejected"] = {
        "bad_rejected_anyway": frac(len(rejected), len(bad)),
        "by_domain": dict(Counter(acts[p]["domain"] for p in rejected)),
        "good_rejected": frac(sum(acts[p]["backend"] == "REJECTED" for p in good), len(good)),
        "executed_bad": len(bad) - len(rejected),
        "designs_on_executed_bad": {
            k: v["executed_bad_caught"]
            for k, v in N["designs"].items()
            if "executed_bad_caught" in v
        },
        "consensus_on_executed_bad": frac(
            sum(consensus_stop(acts[p]) for p in bad if acts[p]["backend"] == "ACCEPTED"),
            len(bad) - len(rejected),
        ),
    }
    check("cut b: bad actions the backend rejected", [len(rejected), len(bad)], [47, 91])

    def stype(text: str) -> str:
        t = text.lower()
        if re.search(r"cheapest|fastest|pricier|priciest|most expensive|second cheapest", t):
            return "ranking"
        if re.search(r"eligib|can be cancel|not been flown|within (the last )?24 hours", t):
            return "eligibility"
        return "other"

    typed = {
        f"{p}:{q}": {
            "type": stype(acts[p]["statements"][q]["text"]),
            "text": acts[p]["statements"][q]["text"],
        }
        for p, q in both_yes
    }
    tc = Counter(v["type"] for v in typed.values())
    N["cut_c_both_yes_by_type"] = {
        "rule": "ranking if the sentence names a price or speed order (cheapest, fastest, pricier, most expensive); else eligibility if it states eligibility, cancellability, flown status or the 24-hour window; else other. Keyword rule written for this check, applied to the sentence text",
        "counts": dict(tc),
        "statements": typed,
    }
    check(
        "cut c: both-yes statements by type (eligibility, ranking, other)",
        [tc["eligibility"], tc["ranking"], tc["other"]],
        [12, 3, 6],
    )

    def stype_alt(text: str) -> str:
        """The reading that gives the reported 12 / 3 / 6: a booking-time fact that decides the
        24-hour window counts as eligibility; "the pricier one" names an item, so it is other."""
        t = text.lower()
        if re.search(r"cheapest|fastest|most expensive", t):
            return "ranking"
        if re.search(
            r"eligib|can be cancel|not been flown|within (the last )?24 hours|hours ago", t
        ):
            return "eligibility"
        return "other"

    alt = Counter(stype_alt(v["text"]) for v in typed.values())
    N["cut_c_both_yes_by_type"]["alternative_reading"] = {
        "rule": stype_alt.__doc__.strip(),
        "counts": dict(alt),
        "differs_on": sorted(k for k, v in typed.items() if stype_alt(v["text"]) != v["type"]),
    }
    check(
        "cut c, alternative reading (eligibility, ranking, other)",
        [alt["eligibility"], alt["ranking"], alt["other"]],
        [12, 3, 6],
    )

    # the first post's figures the brief repeats
    veto = load(EXP / "2026-10-28-airline-veto/results/metrics_adjudicated.json")["metrics"]
    gates = load(EXP / "2026-10-28-claims-check/results/gates.json")["metrics"]["adjudicated"]
    hold = load(EXP / "2026-11-05-airline-holdout/results/adjudicated.json")["metrics"]
    other = load(EXP / "2026-11-05-judges-other-providers/results/metrics.json")["blocks"][
        "claude"
    ]["metrics"]["adjudicated"]
    drafted = load(EXP / "2026-11-05-model-drafted-rules/results/metrics.json")[
        "agreement_with_hand_blocks"
    ]["claude_sonnet55_b"]
    rcas = load(EXP / "2026-10-25-docent-vs-oracle/results/cascade.json")
    prim = next(c for c in rcas["curve"] if c["w"] == rcas["primary_w"])
    judge_wrong = veto["docent_1"]["wrong"] + veto["docent_2"]["wrong"]
    judge_ran = veto["docent_1"]["ran"] + veto["docent_2"]["ran"]
    stack1 = [gates[f"rules_claims_docent_{r}"] for r in (1, 2)]
    stack2 = [hold[f"hand_rules_claims_docent_{r}"] for r in (1, 2)]
    N["first_post"] = {
        "jev_alone_wrong_run": frac(veto["jev"]["wrong"], veto["jev"]["ran"], True),
        # two judge runs score the same writes, so they are not independent trials: pooled
        # counts are descriptive only; bounds are per run
        "judge_alone_wrong_run": frac(judge_wrong, judge_ran)
        | {
            "per_run": [
                frac(veto[f"docent_{r}"]["wrong"], veto[f"docent_{r}"]["ran"], True) for r in (1, 2)
            ]
        },
        "full_stack_first_capture": {
            "wrong_run": frac(sum(s["wrong"] for s in stack1), sum(s["ran"] for s in stack1))
            | {"per_run": [frac(s["wrong"], s["ran"], True) for s in stack1]},
            "good_sent_back": frac(
                sum(s["good_sent_back"] for s in stack1), sum(s["good_total"] for s in stack1)
            ),
        },
        "full_stack_held_out": {
            "wrong_run": frac(sum(s["wrong"] for s in stack2), sum(s["ran"] for s in stack2))
            | {"per_run": [frac(s["wrong"], s["ran"], True) for s in stack2]},
            "good_sent_back": frac(
                sum(s["good_sent_back"] for s in stack2), sum(s["good_total"] for s in stack2)
            ),
        },
        "judge_model_good_approved_of_26": {
            m: other[m]["good_total"] - other[m]["good_sent_back"]
            for m in ("claude", "docent_1", "docent_2", "gemini")
        },
        "drafted_rules_agree": frac(
            drafted["both_block"] + drafted["both_allow"],
            drafted["both_block"] + drafted["both_allow"] + drafted["a_only"] + drafted["b_only"],
        ),
        "retail_cascade_primary": {
            "sent_to_judge": frac(prim["sent_to_docent"], prim["n"]),
            "agree_with_checker": frac(prim["agree"], prim["n"]),
        },
    }
    fp = N["first_post"]
    check(
        "first post: Jev alone wrong run",
        [fp["jev_alone_wrong_run"]["count"], fp["jev_alone_wrong_run"]["of"]],
        [27, 60],
    )
    check("first post: judge alone wrong run", [judge_wrong, judge_ran], [9, 62])
    check(
        "first post: full stack good sent back, % (held-out, first)",
        [
            round(100 * fp["full_stack_held_out"]["good_sent_back"]["rate"]),
            round(100 * fp["full_stack_first_capture"]["good_sent_back"]["rate"]),
        ],
        [51, 62],
    )
    ga = fp["judge_model_good_approved_of_26"]
    check(
        "first post: judge models' good approved, tenths (Claude, OpenAI mean of two runs, Gemini)",
        [
            round(10 * ga["claude"] / 26),
            round(10 * (ga["docent_1"] + ga["docent_2"]) / 2 / 26),
            round(10 * ga["gemini"] / 26),
        ],
        [9, 6, 5],
    )
    check(
        "first post: drafted rules agree",
        [fp["drafted_rules_agree"]["count"], fp["drafted_rules_agree"]["of"]],
        [125, 133],
    )
    check(
        "first post: retail cascade sends about half to the judge",
        round(100 * fp["retail_cascade_primary"]["sent_to_judge"]["rate"]),
        51,
    )

    check(
        "first post: full stack wrong run, first capture and held-out (count, of)",
        [
            [
                fp["full_stack_first_capture"]["wrong_run"]["count"],
                fp["full_stack_first_capture"]["wrong_run"]["of"],
            ],
            [
                fp["full_stack_held_out"]["wrong_run"]["count"],
                fp["full_stack_held_out"]["wrong_run"]["of"],
            ],
        ],
        [[0, 33], [6, 41]],
    )
    check(
        "upper-bound method reproduces the first post (27/60, 0/33, 6/41)",
        [round(upper95(27, 60), 2), round(upper95(0, 33), 2), round(upper95(6, 41), 2)],
        [0.56, 0.09, 0.27],
    )
    # packet length: M0's gate decision asks for results on either side of 8,192 tokens
    rows = {r["write_id"]: r["state_tokens"] for r in tl["rows"]}
    over = {p for p, x in acts.items() if rows[x["write_id"]] > 8192}
    by_len = {}
    for name, pids in (
        ("within_8192", [p for p in acts if p not in over]),
        ("over_8192", sorted(over)),
    ):
        b_ = [p for p in pids if acts[p]["ruling"] == "bad"]
        g_ = [p for p in pids if acts[p]["ruling"] == "good"]
        entry = {
            "actions": len(pids),
            "by_domain": dict(Counter(acts[p]["domain"] for p in pids)),
            "consensus_gate": {
                "bad_caught": frac(sum(consensus_stop(acts[p]) for p in b_), len(b_)),
                "good_stopped": frac(sum(consensus_stop(acts[p]) for p in g_), len(g_)),
            },
            "designs": {},
        }
        for dname, v in ds.items():
            if not (isinstance(v, dict) and "both" in v):
                continue
            missed = set(v["airline"]["bad_missed"] + v["retail"]["bad_missed"])
            stopped_good = set(v["airline"]["good_stopped_ids"] + v["retail"]["good_stopped_ids"])
            entry["designs"][dname] = {
                "bad_caught": frac(sum(p not in missed for p in b_), len(b_)),
                "good_stopped": frac(sum(p in stopped_good for p in g_), len(g_)),
            }
        by_len[name] = entry
    N["by_packet_length"] = by_len
    check("packets over 8,192 tokens (from per-action rows)", len(over), tl["state"]["over_8192"])
    # figures about other papers, read from prior_work.md's verified quotations (check_prior_work.py
    # checks each quotation against the paper's text), so the post takes them from this file too
    pw = (HERE / "prior_work.md").read_text()
    sec = lambda n: pw.split(f"\n## {n}. ", 1)[1].split("\n## ", 1)[0]  # noqa: E731
    ak = re.search(r'"before (\d+)% of (\d+) policy-violating writes"', sec(2))
    fs_judge = re.search(r'"exceeds AUROC ([\d.]+)"', sec(7))
    fs_det = re.search(r'"task-disjoint AUROC ([\d.]+)"', sec(7))
    N["papers"] = {
        "read_in_full": len(re.findall(r"^## \d+\. ", pw, re.M)),
        "agent_knew_false_statement_before_violating_writes": {
            "percent": int(ak.group(1)),
            "of_writes": int(ak.group(2)),
        },
        "false_success_broad_judges_max_auroc": float(fs_judge.group(1)),
        "false_success_tfidf_detector_auroc": float(fs_det.group(1)),
        "source": "prior_work.md (quotations verified by check_prior_work.py)",
    }
    # Jev's spend this week, from the run summaries
    sa_cost = sa["cost"]["agreement_usd"]
    N["jev_cost_usd"] = {
        "statements": sm["jev"]["cost_usd"],
        "agreement": sa_cost,
        "total": round(sm["jev"]["cost_usd"] + sa_cost, 2),
    }
    # the cut-offs behind the same-data 51 / 5, from the key that records them
    N["stock"]["jev_cutoffs_tuned_on_same_data"]["cutoffs"] = (
        SAME_DATA_KEY  # the result file's own key
    )
    N["sources"] = {
        "actions": "experiments/2026-11-20-closing-writeup/results/actions.json (actions.py)",
        "labels": "experiments/2026-11-18-rely1-m1/results/labels_a.jsonl, labels_b.jsonl, labeller_comparison.json",
        "jev_and_cascade": "experiments/2026-11-18-rely1-m1/results/stock_models.json, stock_agreement.json, jev_cascade.json",
        "kev_pilot": "experiments/2026-11-18-rely1-m1/results/kev_pilot.json and kev_pilot_folds/",
        "designs": "experiments/2026-11-18-rely1-m1/results/designs.json",
        "uncaught_38": f"results/uncaught_38_table.json and _types.json, copied from branch rely/uncaught-38 at {UNCAUGHT_COMMIT}",
        "first_post": "experiments/2026-10-28-airline-veto, 2026-10-28-claims-check, 2026-11-05-airline-holdout, 2026-11-05-judges-other-providers, 2026-11-05-model-drafted-rules, 2026-10-25-docent-vs-oracle (results/)",
    }
    N["status"] = (
        "PROVISIONAL, MODEL-LABELLED. This week's figures are train and dev only; the two test splits are sealed and "
        "only counted. Exception: first_post holds the first post's published aggregates over both airline captures; "
        "M0 later drew the sealed test actions from those captures (unseen-task from both, repeat-task from the "
        "second), so these figures are not independent of the sealed sets. No per-action test result is read here."
    )
    N["checks"] = CHECKS
    (HERE / "numbers.json").write_text(json.dumps(N, indent=1, ensure_ascii=False) + "\n")
    bad_checks = [c for c in CHECKS if not c["match"]]
    print(f"{len(CHECKS)} checks, {len(bad_checks)} mismatches")
    for c in bad_checks:
        print("  MISMATCH", c["figure"], "computed", c["computed"], "brief", c["brief"])


if __name__ == "__main__":
    main()
