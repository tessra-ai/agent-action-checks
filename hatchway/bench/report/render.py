"""Render a `Bench` as static HTML pages: an overview, then one page per write, simulation
and task, and a review page for policy verdicts. Pages link with relative paths so the report
opens from file://. Every string from the store or results files goes through `esc`.

The pages keep five things apart and answer them in order: the policy verdict on a proposed write
(may it execute? the answer key), each judge's scores and its own decision, each decision
strategy's decision (the replayed arms), what the backend did with it, and the simulation's final
task outcome. Judges and strategies are compared against the policy verdict only
(`report.compare`); the backend outcome, the task outcome and the τ² trace match are context."""

from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hatchway.bench.report.compare import (
    DEFINITIONS,
    ESTABLISHED,
    INTERVENE,
    by_action_type,
    by_verdict,
    calibration,
    configured,
    describe,
    disagreements,
    distinguish,
    effective_decision,
    in_scope,
    mean_digits,
    operational_rows,
    outcome_counts,
    result_kind,
    score_pair,
    single_judge_strategies,
    strategy_cost,
    strongest,
    takeaway,
    weakest_answers,
)
from hatchway.bench.report.labels import (
    SCORE_SPREAD_THRESHOLD,
    action_title,
    judge_label,
    question_label,
    reason_text,
)
from hatchway.bench.report.load import (
    Bench,
    JudgeKey,
    Score,
    Simulation,
    Strategy,
    TaskKey,
    Write,
    slug,
)
from hatchway.bench.tau2.label import GoldAction
from hatchway.judges.base import Question
from hatchway.state import canonical_json

VERDICTS = ("ALLOW", "ASK", "DENY", "UNKNOWN", "none")
VERDICT_NAMES = {
    "ALLOW": "policy-valid",
    "ASK": "needs clarification",
    "DENY": "policy violation",
    "UNKNOWN": "unknown verdict",
    "none": "no verdict",
}
LEGEND = (
    ("ALLOW", "Safe and complete enough to execute now"),
    ("ASK", "Missing required information or confirmation"),
    ("DENY", "Current proposal violates policy"),
    ("UNKNOWN", "Evaluator could not establish the correct verdict"),
)
RESULT_NAMES = {
    "caught": "Caught",
    "false_allow": "False allow",
    "safe_auto": "Safe auto-allow",
    "over_escalation": "Over-escalation",
    "not_evaluated": "Not evaluated (UNKNOWN verdict; blocked at runtime)",
}
LONG_TEXT = 800
LONG_LINES = 14

RULES = {
    "3": "matches reference action #{n}, which no earlier write in this session matched.",
    "4a": "repeats reference action #{n}, which an earlier write in this session already "
    "matched (a retry or a duplicate).",
    "4b": "matches reference action #{n} only after sorting list arguments.",
    "4c": "the tool is not in this task's reference trace, and the task is not scored on the "
    "final database, so the trace is one valid path, not the only one.",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def write_href(write_id: str) -> str:
    return f"w/{slug(write_id)}.html"


def sim_href(sim_id: str) -> str:
    return f"s/{slug(sim_id)}.html"


def task_href(key: TaskKey) -> str:
    return f"t/{slug(f'{key[0]}/{key[1]}')}.html"


# --- Shared pieces ---------------------------------------------------------------------------


def page(title: str, body: str, *, depth: int) -> str:
    up = "../" * depth
    return (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title)}</title><link rel='stylesheet' href='{up}report.css'></head>"
        f"<body><nav><a href='{up}index.html'>Benchmark viewer</a>"
        f"<span class='crumb'>{esc(title)}</span></nav><main>{body}</main></body></html>\n"
    )


def badge(verdict: str | None) -> str:
    """A policy verdict badge: `ALLOW`, `ASK`, `DENY`, `UNKNOWN`, or `none` (not evaluated)."""
    name = verdict if verdict in VERDICT_NAMES else "none"
    return (
        f"<span class='badge v-{esc(name)}' title='{esc(VERDICT_NAMES[name])}'>"
        f"{esc(name)} <span class='bname'>{esc(VERDICT_NAMES[name])}</span></span>"
    )


def mode_badge(mode: str | None) -> str:
    """Shadow unless the write came from a gated (enforced) run."""
    if mode == "gated":
        return "<div class='mode gated'>GATED: Hatchway's decision was enforced</div>"
    return "<div class='mode shadow'>SHADOW MODE: Hatchway did not block backend calls</div>"


LAYERS = (
    ("Policy oracle", "benchmark answer key"),
    ("Judge", "produces scores from pre-execution evidence"),
    ("Decision strategy", "converts scores into ALLOW or ASK"),
    ("Backend outcome", "what happened in shadow mode"),
    ("Task outcome", "whether the entire conversation eventually passed"),
)


def reading_box(bench: Bench) -> str:
    """How the report is evaluated: the five layers, for readers new to all of them."""
    gated = "gated" in (bench.provenance.get("simulation_modes") or [])
    lead = (
        "<p><b>This is a shadow run.</b> The agent proposed each business action normally; "
        "Hatchway observed the proposal before execution but did not block it.</p>"
        if not gated
        else "<p><b>This report holds shadow runs and gated runs</b>; the GATED badge marks "
        "actions where Hatchway's decision was enforced.</p>"
    )
    layers = "".join(
        f"<li><b>{esc(name)}</b> \u2192 {esc(meaning)}</li>" for name, meaning in LAYERS
    )
    return (
        "<div class='box reading' id='how-to-read'><h2>How this report is evaluated</h2>"
        + lead
        + f"<ol class='layers'>{layers}</ol>"
        "<p><b>Judge quality and gateway quality are different:</b> a judge may identify a "
        "problem, but a poor threshold or combination strategy can still make the wrong gateway "
        "decision.</p>"
        "<p class='muted'>Judges and decision strategies are scored only against the policy "
        "oracle's verdict, made before the action ran; never against backend acceptance, the "
        "final task reward or the \u03c4\u00b2 trace.</p></div>"
    )


def legend() -> str:
    rows = "".join(f"<tr><td>{badge(v)}</td><td>{esc(text)}</td></tr>" for v, text in LEGEND)
    return (
        f"<table class='legend'><tbody>{rows}</tbody></table>"
        "<p><b>ASK and DENY both mean the action must not execute automatically.</b> An oracle "
        "DENY that the replayed gate turned into ASK is a catch.</p>"
    )


def primary_arm(bench: Bench) -> str | None:
    """The configured candidate's arm (`compare.configured`)."""
    candidate = configured(bench)
    return None if candidate is None else candidate.arm


def strategy_label(bench: Bench, arm: str) -> str:
    """ "OpenAI Decisions (Arm D)": the name from the replay's metadata, the letter in
    parentheses."""
    s = bench.strategies.get(arm)
    return s.label if s is not None else f"Arm {arm}"


def judge_of(bench: Bench, strategy: Strategy) -> JudgeKey | None:
    """The (judge, model) a single-judge strategy calls, from its frozen arm."""
    arm = bench.arms.get(strategy.arm)
    return tuple(arm.judges[0]) if arm is not None and len(arm.judges) == 1 else None


def judge_cell(bench: Bench, judge: JudgeKey) -> str:
    """A judge's display name with its model or version beneath."""
    return (
        f"{esc(judge_label(judge[0], bench.judge_names))}"
        f"<div class='muted small'>{esc(judge[1])}</div>"
    )


def gate_span(decision: str | None) -> str:
    return f"<span class='gate {esc(decision)}'>{esc(decision)}</span>"


def frac(n: int, d: int) -> str:
    """A count with its denominator; a percentage only once the denominator reaches 20."""
    if not d:
        return "\u2013"
    return f"{n}/{d}" + (f" ({100 * n / d:.0f}%)" if d >= 20 else "")


def diagnostic(bench: Bench) -> bool:
    """True when the claims gate failed or never ran: results diagnose, they do not claim."""
    metrics = bench.replay_metrics
    return metrics is None or bool((metrics.get("claims") or {}).get("blocked"))


def run_word(bench: Bench) -> str:
    return "smoke run" if "smoke" in str(bench.provenance.get("config") or "").lower() else "run"


def reasons_text(w: Write) -> str:
    """The oracle's reason codes in plain words."""
    d = w.deterministic or {}
    return "; ".join(reason_text(c, d.get("evidence")) for c in d.get("reason_codes", []))


def call_text(action: str, args: Mapping[str, Any]) -> str:
    """`action(arg=value, ...)`, shortened for the summary."""
    parts = []
    for k, v in args.items():
        shown = v if not isinstance(v, list) else f"[{len(v)} items]"
        parts.append(f"{k}={shown}")
    text = f"{action}({', '.join(parts)})"
    return text if len(text) <= 140 else text[:137] + "..."


def text_block(text: str | None, *, summary: str = "") -> str:
    """Preformatted text, collapsed behind a preview when long."""
    if text is None:
        return "<span class='muted'>(none)</span>"
    if len(text) <= LONG_TEXT and text.count("\n") < LONG_LINES:
        return f"<pre>{esc(text)}</pre>"
    preview = text[:160].replace("\n", " ")
    label = summary or f"{esc(preview)}… <span class='muted'>({len(text):,} chars)</span>"
    return f"<details><summary>{label}</summary><pre>{esc(text)}</pre></details>"


def json_block(value: Any) -> str:
    return text_block(json.dumps(value, indent=2, ensure_ascii=False))


def table(headers: Sequence[str], rows: Iterable[Sequence[str]], cls: str = "") -> str:
    """`rows` cells are already-escaped HTML; headers are escaped here."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table class='{cls}'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def kv(pairs: Iterable[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><th>{esc(k)}</th><td>{v}</td></tr>" for k, v in pairs)
    return f"<table class='kv'>{rows}</table>"


def fmt_ms(value: float | None) -> str:
    return "\u2013" if value is None else f"{value:,.0f} ms"


def fmt_usd(value: float | None) -> str:
    return "\u2013" if value is None else f"${value:,.6f}".rstrip("0").rstrip(".")


def fmt_cost(value: float | None) -> str:
    """A cost to five decimals ($0.00524), for comparing judges."""
    if value is None:
        return "\u2013"
    if 0 < value < 0.00001:
        return f"${value:.2g}"
    return f"${value:.5f}".rstrip("0").rstrip(".")


def fmt_reward(sim: Simulation) -> str:
    """The simulation's final task outcome, with its τ² reward."""
    if sim.outcome is None:
        return "<span class='muted'>no final task outcome (no reward)</span>"
    cls = "pass" if sim.passed else "fail"
    word = "pass" if sim.passed else "fail"
    return (
        f"<span class='{cls}'>final task outcome {word}</span> "
        f"<span class='muted'>(reward {sim.reward:g})</span>"
    )


def task_link(bench: Bench, key: TaskKey, up: str) -> str:
    domain, task_id = key
    text = f"{domain}/{task_id}" if domain else task_id or "(no task)"
    return f"<a href='{up}{task_href(key)}'>{esc(text)}</a>"


def write_chip(write: Write, up: str) -> str:
    v = write.verdict or "none"
    return (
        f"<a class='chip v-{esc(v)}' href='{up}{write_href(write.write_id)}'"
        f" title='{esc(v)}: {esc(VERDICT_NAMES.get(v, v))}'>{write.seq}. {esc(write.action)}</a>"
    )


def session_link(bench: Bench, session_id: str, up: str) -> str:
    if session_id in bench.simulations:
        return f"<a href='{up}{sim_href(session_id)}'>{esc(session_id)}</a>"
    return f"{esc(session_id)} <span class='muted'>(not in the results files)</span>"


# --- Write page ------------------------------------------------------------------------------


def _write_header(bench: Bench, w: Write) -> str:
    return (
        f"<h1>{esc(action_title(w.action, w.args))} {badge(w.verdict)}</h1>"
        + mode_badge(w.mode)
        + "<p class='muted'><a href='../index.html#how-to-read'>How this report is evaluated</a>"
        "</p>" + "<details class='box'><summary>Verdict legend</summary>" + legend() + "</details>"
    )


def calc_facts(d: Mapping[str, Any], min_digits: int = 3) -> dict[str, str]:
    """What a decision line shows, as strings: the rule, the decision, and (for a threshold
    decision) the score and threshold rounded so that they compare as the exact values do.
    `compare.recompute` gets the decision back from these alone."""
    rule = d.get("rule") or ("fail_closed" if d["p_ok"] is None else "threshold")
    facts = {"rule": rule, "decision": d["decision"]}
    if rule == "fail_closed":
        return facts
    if d["threshold"] is None or math.isinf(d["threshold"]):
        return {**facts, "rule": "no_threshold", "score": f"{d['p_ok']:.3f}"}
    score, op, threshold = score_pair(d["p_ok"], d["threshold"], min_digits)
    facts.update(score=score, op=op, threshold=threshold)
    if d.get("disagreement_max") is not None:
        dis, limit = distinguish(d["disagreement"], d["disagreement_max"])
        facts.update(disagreement=dis, limit=limit)
    return facts


def calc_attrs(facts: Mapping[str, str]) -> str:
    return " ".join(f"data-{k}='{esc(v)}'" for k, v in facts.items())


def decision_calc(bench: Bench, d: Mapping[str, Any] | None, min_digits: int = 3) -> str:
    """A decision with everything needed to reproduce it: the derived gateway score, the
    threshold and the comparison, or the override that applied (fail closed, a disagreement
    veto). Predicates never override a decision."""
    if d is None:
        return "<span class='muted'>no replay given</span>"
    f = calc_facts(d, min_digits)
    gate = gate_span(d["decision"])
    if f["rule"] == "fail_closed":
        who = ", ".join(judge_label(j, bench.judge_names) for j in d.get("missing") or [])
        text = f"fail closed: {esc(who or 'a judge it needs')} did not score \u2192 {gate}"
    elif f["rule"] == "no_threshold":
        text = (
            f"Derived gateway score {f['score']}; no threshold could be fit (asks for "
            f"everything) \u2192 {gate}"
        )
    else:
        # Every value goes through esc: "<" is the comparison, not the start of a tag.
        text = (
            f"Derived gateway score {esc(f['score'])} {esc(f['op'])} threshold "
            f"{esc(f['threshold'])}"
        )
        if f["rule"] == "disagreement_veto":
            text += (
                f"; disagreement {esc(f['disagreement'])} &gt; limit {esc(f['limit'])}: veto "
                f"\u2192 {gate}"
            )
        else:
            text += f" \u2192 {gate}"
            if "limit" in f:
                text += (
                    f" <span class='muted'>(disagreement {esc(f['disagreement'])} \u2264 limit "
                    f"{esc(f['limit'])}: no veto)</span>"
                )
    return f"<span class='calc' {calc_attrs(f)}>{text}</span>"


def strategy_description(bench: Bench, arm: str) -> str:
    """What the strategy computes, read from its frozen file (`compare.describe`)."""
    frozen = bench.arms.get(arm)
    return describe(frozen, bench.judge_names) if frozen is not None else ""


def configured_line(bench: Bench, w: Write) -> tuple[str, str | None]:
    """The configured candidate's decision on `w` with its calculation, raw and effective, as
    one line; and the effective decision (None without a replay)."""
    arm = primary_arm(bench)
    d = w.arm_decisions.get(arm) if arm else None
    if d is None:
        return "<span class='muted'>no replay given</span>", None
    effective = effective_decision(w.verdict, d["decision"])
    effect = (
        "automatic execution prevented"
        if d["decision"] != "ALLOW"
        else "would have executed automatically"
    )
    raw = f"{decision_calc(bench, d)}: {effect}"
    if w.verdict in ESTABLISHED:
        line = raw
    else:
        line = (
            f"raw replay: {raw} \u2192 effective runtime: {gate_span(effective)}, blocked "
            "(UNKNOWN verdict, unverified: never runs automatically)"
        )
    where = ", in-sample: training split" if w.split == "train" else ""
    return line + f" <span class='muted'>({esc(strategy_label(bench, arm))}{esc(where)})</span>", (
        effective
    )


def _summary_section(bench: Bench, w: Write) -> str:
    """The whole story in seven lines, in the order of the sections below, then the result."""
    reasons = reasons_text(w)
    verdict_line = (
        f"{badge(w.verdict)} {esc(reasons)}" if w.deterministic else "no verdict for this write"
    )
    judges = [
        (s, w.arm_decisions[s.arm])
        for s in single_judge_strategies(bench)
        if s.arm in w.arm_decisions
    ]
    judges_line = (
        "<ul>"
        + "".join(
            f"<li>{esc(s.display_name or s.label)}: {decision_calc(bench, d)}</li>"
            for s, d in judges
        )
        + "</ul>"
        if judges
        else "<span class='muted'>no replay given</span>"
    )
    strategies_line = (
        "<ul>"
        + "".join(
            f"<li>{esc(strategy_label(bench, arm))}: {decision_calc(bench, d)}</li>"
            for arm, d in sorted(w.arm_decisions.items())
        )
        + "</ul>"
        if w.arm_decisions
        else "<span class='muted'>no replay given</span>"
    )
    gateway_line, effective = configured_line(bench, w)
    o = (w.outcome or {}).get("outcome")
    backend_label = "Backend in shadow mode" if w.mode != "gated" else "Backend (gated run)"
    backend_line = (
        f"<span class='outcome {esc(o)}'>{esc(o)}</span>"
        if o
        else "<span class='muted'>not recorded</span>"
    )
    sim = bench.simulations.get(w.session_id)
    task_line = (
        f"<b>{esc(sim.outcome)}</b> <span class='muted'>(the whole conversation, not this "
        "action)</span>"
        if sim is not None and sim.outcome is not None
        else "<span class='muted'>not in the results files given</span>"
    )
    steps = [
        ("Agent proposed", f"<code>{esc(call_text(w.action, w.args))}</code>"),
        ("Policy verdict", verdict_line),
        ("Individual judges", judges_line),
        ("Decision strategies", strategies_line),
        ("Configured gateway decision", gateway_line),
        (backend_label, backend_line),
        ("Final task outcome", task_line),
    ]
    items = "".join(f"<li><b>{esc(label)}:</b> {value}</li>" for label, value in steps)
    arm = primary_arm(bench)
    d = w.arm_decisions.get(arm) if arm else None
    kind = result_kind(w.verdict, d["decision"] if d else None)
    if w.verdict in INTERVENE:
        required = "yes"
    elif w.verdict == "ALLOW":
        required = "no"
    else:
        required = "unknown"
    prevented = "\u2013" if effective is None else ("yes" if effective != "ALLOW" else "no")
    result = (
        f"<span class='result {esc(kind)}'>{esc(RESULT_NAMES[kind])}</span>"
        if kind
        else "<span class='muted'>no replayed gate decision</span>"
    )
    return f"<ol class='steps'>{items}</ol>" + kv(
        [
            ("Required intervention", esc(required)),
            ("Gateway prevented automatic execution", esc(prevented)),
            ("Result", result),
        ]
    )


def _proposal_section(bench: Bench, w: Write) -> str:
    return (
        "<h2>1. Proposed action</h2>"
        f"<p>{esc(action_title(w.action, w.args))}</p>"
        f"<p><code>{esc(call_text(w.action, w.args))}</code></p>"
    )


def answers_of(score: Score | None) -> Mapping[str, Any]:
    return ((score.question_vector if score else None) or {}).get("answers") or {}


def weakest_cell(score: Score | None) -> str:
    """The answers that explain a low score (`compare.weakest_answers`); never a bare "none"."""
    found, low = weakest_answers(answers_of(score))
    if not found:
        return "<span class='muted'>no yes/no answers beyond policy_ok</span>"
    items = "<br>".join(
        f"{esc(question_label(q))} <span class='muted'>({p:.2f})</span>" for q, p in found
    )
    return items if low else f"<span class='muted'>no answer below 0.5; lowest:</span> {items}"


def yes_score(score: Score | None, question: str, digits: int = 3) -> str:
    answer = answers_of(score).get(question)
    if not answer or answer.get("p_yes") is None:
        return "<span class='muted'>\u2013</span>"
    return f"{answer['p_yes']:.{digits}f}"


def shown_digits(
    bench: Bench, arm: str | None, score: Score | None, d: Mapping[str, Any] | None
) -> int:
    """For a strategy whose derived score is the mean of `policy_ok` and `matches_request`
    (`frozen.scalar_score`), enough digits that the raw answers as shown average to a score on
    the same side of the threshold as shown (`compare.mean_digits`). Otherwise 3."""
    frozen = bench.arms.get(arm) if arm else None
    if (
        frozen is None
        or frozen.model.get("type") != "scalar_mean"
        or d is None
        or d.get("rule") != "threshold"
        or math.isinf(d["threshold"])
    ):
        return 3
    answers = answers_of(score)
    values = [
        answers[q]["p_yes"]
        for q in ("policy_ok", "matches_request")
        if (answers.get(q) or {}).get("p_yes") is not None
    ]
    return mean_digits(values, d["p_ok"], d["threshold"]) if values else 3


RAW_FIELDS_NOTE = (
    "<code>policy_ok</code> and <code>matches_request</code> are the judge's raw answers "
    "(p_yes). The <b>derived gateway score</b> is the value the strategy thresholds. The relevant "
    "predicate explains a score; it never vetoes a decision."
)


def _judge_compare_section(bench: Bench, w: Write) -> str:
    out = [
        "<h2>3. Individual judge comparison</h2>",
        f"<p class='muted'>{RAW_FIELDS_NOTE}</p>",
    ]
    if w.score_key is None:
        out.append("<p>No rubric: the action is not a known write, so no judge scores it.</p>")
        return "".join(out)
    scores = bench.scores.get(w.score_key, {})
    own = {judge_of(bench, s): s for s in single_judge_strategies(bench)}
    rows = []
    # The judges in the overview's order (by their strategies), then any without one.
    judges = [j for j in own if j in bench.judges] + [j for j in bench.judges if j not in own]
    for judge in judges:
        score = scores.get(judge)
        strategy = own.get(judge)
        d = w.arm_decisions.get(strategy.arm) if strategy is not None else None
        digits = shown_digits(bench, strategy.arm if strategy else None, score, d)
        decision = (
            decision_calc(bench, d, digits)
            if strategy is not None
            else "<span class='muted'>no single-judge strategy in the replay</span>"
        )
        if score is None or score.status != "ok":
            skip = bench.skip_for(w.score_key, judge)
            status = (
                "<span class='status error'>error</span>"
                if score is not None
                else f"<span class='muted'>skipped: {esc(skip.reason)}</span>"
                if skip
                else "<span class='muted'>not scored</span>"
            )
            rows.append([judge_cell(bench, judge), status, "", "", decision])
            continue
        rows.append(
            [
                judge_cell(bench, judge),
                yes_score(score, "policy_ok", digits),
                yes_score(score, "matches_request", digits),
                weakest_cell(score),
                decision,
            ]
        )
    out.append(
        table(
            [
                "Judge",
                "policy_ok",
                "matches_request",
                "Relevant predicate (explanatory, never a veto)",
                "Judge's own strategy: derived gateway score vs threshold",
            ],
            rows,
        )
    )
    return "".join(out)


def _strategy_section(bench: Bench, w: Write) -> str:
    out = ["<h2>4. Decision strategy comparison</h2>"]
    if not bench.arms:
        out.append(
            "<p class='muted'>No replay given (build the report with <code>--replay</code> and "
            "M6's output directory).</p>"
        )
        return "".join(out)
    where = (
        "This action is in the training split: the thresholds were fitted on it (in-sample)."
        if w.split == "train"
        else "This action is in the held-out test split."
        if w.split == "test"
        else "This action is in neither replay split."
    )
    out.append(f"<p class='muted'>Computed offline from the stored judge scores. {esc(where)}</p>")
    rows = []
    for arm, d in sorted(w.arm_decisions.items()):
        description = strategy_description(bench, arm)
        rows.append(
            [
                esc(strategy_label(bench, arm))
                + (f"<div class='muted small'>{esc(description)}</div>" if description else ""),
                decision_calc(bench, d),
                gate_span(effective_decision(w.verdict, d["decision"])),
                esc(gate_result(w.verdict, d["decision"])),
            ]
        )
    out.append(
        table(
            [
                "Decision strategy (what it computes)",
                "Derived gateway score vs threshold",
                "Effective runtime decision",
                "Against the policy verdict",
            ],
            rows,
        )
    )
    return "".join(out)


def _gateway_section(bench: Bench, w: Write) -> str:
    out = ["<h2>5. Effective configured gateway decision</h2>"]
    line, _ = configured_line(bench, w)
    out.append(f"<p>{line}</p>")
    out.append(
        "<p class='muted'>The configured candidate's decision, as it would take effect at "
        "runtime. In shadow mode nothing was blocked.</p>"
    )
    return "".join(out)


def _details_section(bench: Bench, w: Write) -> str:
    """Identifiers and hashes, collapsed."""
    up = "../"
    return (
        "<details class='box'><summary>Write details and hashes</summary>"
        + kv(
            [
                ("write", f"<code>{esc(w.write_id)}</code>"),
                ("task", task_link(bench, w.task_key, up)),
                ("trial", esc(w.trial)),
                ("agent model", esc(w.agent_model)),
                ("simulation", session_link(bench, w.session_id, up)),
                ("seq", esc(w.seq)),
                ("captured", esc(w.ts)),
                ("known action", "yes" if w.known_action else "<b>no</b> (not in the policy)"),
                ("state_hash", f"<code>{esc(w.state_hash)}</code>"),
                ("rubric_hash", f"<code>{esc(w.rubric_hash)}</code>"),
                ("replay split", esc(w.split or "\u2013")),
            ]
        )
        + "<h3>Arguments</h3>"
        + json_block(w.args)
        + "</details>"
    )


def _verdict_section(bench: Bench, w: Write) -> str:
    out = ["<h2>2. Oracle verdict and reasons (before execution)</h2>"]
    if w.deterministic is None:
        why = (
            "this store has no policy verdicts"
            if bench.oracle_version is None
            else f"no verdict for oracle version {bench.oracle_version}"
        )
        out.append(f"<p>{badge(None)} <span class='muted'>{esc(why)}.</span></p>")
        return "".join(out)
    source = "manual review" if w.verdict_source == "manual_review" else "deterministic oracle"
    out.append(
        f"<p>{badge(w.verdict)} <span class='muted'>from the {esc(source)}, oracle version "
        f"<code>{esc(bench.oracle_version)}</code></span></p>"
    )
    d = w.deterministic
    if d["reason_codes"]:
        out.append(
            "<ul class='reasons'>"
            + "".join(
                f"<li>{esc(reason_text(c, d.get('evidence')))} <code>{esc(c)}</code></li>"
                for c in d["reason_codes"]
            )
            + "</ul>"
        )
    rows = [
        (
            "deterministic oracle",
            f"{badge(d['decision'])} "
            + " ".join(f"<code>{esc(c)}</code>" for c in d["reason_codes"]),
        )
    ]
    for r in w.reviews:
        kind = "adjudication" if r["adjudicated"] else "note (not adjudicated)"
        rows.append(
            (
                f"review by {r['reviewer']}",
                f"{badge(r['decision'])} {esc(kind)}, {esc(r['review_kind'])} "
                + " ".join(f"<code>{esc(c)}</code>" for c in r["reason_codes"])
                + (f"<div>{esc(r['explanation'])}</div>" if r["explanation"] else ""),
            )
        )
    out.append(kv(rows))
    if w.manual is not None and w.manual["decision"] != d["decision"]:
        out.append(
            "<p class='warn'>The reviewer overrode the deterministic oracle; the review is the "
            "effective verdict.</p>"
        )
    return "".join(out)


def _evidence_section(bench: Bench, w: Write) -> str:
    out = ["<details class='box'><summary>Detailed evidence (every check)</summary>"]
    if w.deterministic is None:
        out.append("<p class='muted'>No verdict, so no evidence.</p></details>")
        return "".join(out)
    out.append(f"<p>{esc(w.deterministic['explanation'])}</p>")
    rows = []
    for code, check in sorted(
        w.deterministic["evidence"].items(),
        key=lambda kv_: (kv_[1].get("outcome") == "pass", kv_[0]),
    ):
        outcome = check.get("outcome", "")
        rows.append(
            [
                f"<code>{esc(code)}</code>",
                f"<span class='check {esc(outcome)}'>{esc(outcome)}</span>",
                esc(check.get("note", "")),
                json_block(check.get("facts", {})) if check.get("facts") else "",
            ]
        )
    out.append(table(["check", "outcome", "note", "facts"], rows))
    out.append("</details>")
    return "".join(out)


def gate_result(verdict: str | None, decision: str) -> str:
    """What a replayed gate decision means against the policy verdict."""
    return RESULT_NAMES[result_kind(verdict, decision) or "not_evaluated"]


def _outcome_section(bench: Bench, w: Write) -> str:
    out = ["<h2>6. Backend outcome</h2>"]
    o = w.outcome
    if o is None:
        out.append("<p class='muted'>Not recorded.</p>")
        return "".join(out)
    changed = {True: "yes", False: "no", None: "unknown"}[o["state_changed"]]
    out.append(
        kv(
            [
                (
                    "outcome",
                    f"<span class='outcome {esc(o['outcome'])}'>{esc(o['outcome'])}</span>",
                ),
                ("state changed", changed),
                (
                    "backend error",
                    text_block(o["backend_error"]) if o["backend_error"] else "\u2013",
                ),
            ]
        )
    )
    out.append(
        "<p class='muted'>Recorded after the verdict was committed; it never changes the "
        "verdict.</p>"
    )
    return "".join(out)


def _task_outcome_section(bench: Bench, w: Write) -> str:
    out = ["<h2>7. Final task outcome (of the conversation)</h2>"]
    sim = bench.simulations.get(w.session_id)
    if sim is None:
        out.append("<p class='muted'>The simulation is not in the results files given.</p>")
    else:
        out.append(f"<p>{fmt_reward(sim)} <a href='../{sim_href(sim.id)}'>conversation</a></p>")
    out.append(
        "<p class='muted'>One outcome per simulation, whatever its writes did; it is not a "
        "verdict on this write.</p>"
    )
    return "".join(out)


def match_badge(match: str | None) -> str:
    name = match or "unmatched"
    return f"<span class='badge m-{esc(name)}'>{esc(name)}</span>"


def _benchmark_section(bench: Bench, w: Write) -> str:
    out = [
        "<h3>\u03c4\u00b2 trace comparison: not a safety verdict</h3>",
        "<p class='muted'>Whether the call is in τ²'s reference trace. For τ² analysis only: a "
        "call can match the trace and still break the policy, or miss it and be valid.</p>",
    ]
    truth = bench.ground_truth(w.task_key)
    if truth is None:
        out.append(
            f"<p>{match_badge(w.benchmark_match)} <span class='muted'>No reference trace: task "
            f"{esc(w.task_id)} is not in the results files given.</span></p>"
        )
        return "".join(out)
    e = w.explanation
    if e is not None:
        if e.rule == "5":
            same_tool = any(g.name == w.action for g in truth.actions)
            why = (
                "the tool is in the reference trace, but no unmatched reference call has the "
                "same compared arguments (differences below)."
                if same_tool
                else "the tool is not in the reference trace of a task scored on the final "
                "database (with no reference writes, the trace refuses or transfers)."
            )
        else:
            n = "" if e.gold_index is None else e.gold_index + 1
            why = RULES[e.rule].format(n=n)
        out.append(
            f"<p>{match_badge(e.match)} because {esc(why)} <span class='muted'>(rule {e.rule}"
            " in hatchway/bench/tau2/label.py)</span></p>"
        )
        if w.benchmark_match is not None and w.benchmark_match != e.match:
            out.append(
                f"<p class='warn'>The stored match is {esc(w.benchmark_match)}, but the "
                f"labeler gives {esc(e.match)} on these results.</p>"
            )
    if not truth.actions:
        out.append("<p>The task's reference trace has no assistant actions.</p>")
        return "".join(out)
    rows = []
    for i, g in enumerate(truth.actions):
        cls = "hl" if e is not None and e.gold_index == i else ""
        rows.append(
            [
                f"<span class='{cls}'>{i + 1}</span>",
                f"<code class='{cls}'>{esc(g.name)}</code>",
                f"<code>{esc(canonical_json(g.arguments))}</code>",
            ]
        )
    out.append("<h3>Reference actions</h3>")
    out.append(
        f"<p class='muted'>Scored on the final database: {'yes' if truth.db_scored else 'no'}.</p>"
    )
    out.append(table(["#", "tool", "arguments"], rows))
    for i, g in enumerate(truth.actions):
        if g.name == w.action:
            out.append(f"<h3>Proposed call vs reference action #{i + 1}</h3>")
            out.append(arg_diff(w.args, g))
    return "".join(out)


_MISSING = object()


def arg_diff(args: Mapping[str, Any], gold: GoldAction) -> str:
    keys = sorted({*gold.arguments, *args})
    compared = set(gold.compare_args) if gold.compare_args is not None else set(keys)
    rows = []

    def cell(v: Any) -> str:
        if v is _MISSING:
            return "<span class='muted'>(absent)</span>"
        return f"<code>{esc(canonical_json(v))}</code>"

    for k in keys:
        mine, theirs = args.get(k, _MISSING), gold.arguments.get(k, _MISSING)
        if k not in compared:
            state = "not compared"
        elif mine == theirs:
            state = "same"
        else:
            state = "differs"
        rows.append([f"<code>{esc(k)}</code>", cell(mine), cell(theirs), esc(state)])
    head = "".join(f"<th>{h}</th>" for h in ("argument", "proposed", "reference", ""))
    body = "".join(
        f"<tr class='{'diff' if r[3] == 'differs' else ''}'>"
        + "".join(f"<td>{c}</td>" for c in r)
        + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def answer_cell(question: str, score: Score | None) -> str:
    if score is None or score.question_vector is None:
        return "<span class='muted'>\u2013</span>"
    answer = score.question_vector.get("answers", {}).get(question)
    if answer is None:
        return "<span class='muted'>(no answer)</span>"
    kind = answer.get("type")
    if kind == "yes_no":
        p = answer["p_yes"]
        cls = "yes" if p >= 0.5 else "no"
        return f"<span class='{cls}'>{'yes' if p >= 0.5 else 'no'}</span> p_yes={p:.3f}"
    if kind == "choice":
        probs = answer["probs"]
        top = max(probs, key=probs.get) if probs else None
        return "<br>".join(
            f"{'<b>' if o == top else ''}{esc(o)}: {p:.3f}{'</b>' if o == top else ''}"
            for o, p in probs.items()
        )
    if kind == "score":
        return f"{answer['value']:.3f}"
    return f"<code>{esc(canonical_json(answer))}</code>"


def raw_response_cell(raw: str | None) -> str:
    if raw is None:
        return "<span class='muted'>\u2013</span>"
    try:
        text = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except ValueError:
        text = raw
    return f"<details><summary>{len(raw):,} chars</summary><pre>{esc(text)}</pre></details>"


def _judges_section(bench: Bench, w: Write) -> str:
    out = ["<h2>Judge scores</h2>"]
    key = w.score_key
    if key is None:
        out.append("<p>No rubric: the action is not a known write, so no judge scores it.</p>")
        return "".join(out)
    sharing = [x for x in bench.by_score_key.get(key, []) if x.write_id != w.write_id]
    if sharing:
        links = " ".join(write_chip(x, "../") for x in sharing[:50])
        more = f" and {len(sharing) - 50} more" if len(sharing) > 50 else ""
        out.append(
            f"<p class='note'>Shares one score with {len(sharing)} other "
            f"write{'s' if len(sharing) != 1 else ''} (same state_hash and rubric_hash; billed "
            f"once): {links}{more}</p>"
        )
    scores = bench.scores.get(key, {})
    questions: list[Question] | None = bench.questions(w)
    names: list[tuple[str, str, str]]
    if questions is not None:
        names = [(q.name, q.type.value, q.text or "") for q in questions]
    else:
        seen = {
            n: a.get("type", "")
            for s in scores.values()
            if s.question_vector
            for n, a in s.question_vector.get("answers", {}).items()
        }
        names = [(n, t, "") for n, t in sorted(seen.items())]
        out.append(
            "<p class='warn'>Question text unavailable: the policy file given does not have "
            "this rubric for this action.</p>"
        )
    if not bench.judges:
        out.append("<p class='muted'>No scores in the store yet. The judges will be asked:</p>")
        out.append(
            table(
                ["question", "type", "text"],
                [[f"<code>{esc(n)}</code>", esc(t), esc(x)] for n, t, x in names],
            )
        )
        return "".join(out)

    head = "<th>question</th>" + "".join(
        f"<th>{esc(j)}<br><span class='muted'>{esc(m)}</span></th>" for j, m in bench.judges
    )
    rows = []

    def row(label: str, cell: Callable[[JudgeKey, Score | None], str]) -> None:
        cells = "".join(f"<td>{cell(j, scores.get(j))}</td>" for j in bench.judges)
        rows.append(f"<tr><th>{label}</th>{cells}</tr>")

    def status(j: JudgeKey, s: Score | None) -> str:
        if s is not None:
            return f"<span class='status {esc(s.status)}'>{esc(s.status)}</span>"
        skip = bench.skip_for(key, j)
        if skip is not None:
            return f"<span class='status skipped'>skipped</span> {esc(skip.reason)}"
        return "<span class='muted'>not scored</span>"

    row("status", status)
    for name, qtype, text in names:
        label = (
            f"<code>{esc(name)}</code> <span class='muted'>{esc(qtype)}</span>"
            f"<div class='qtext'>{esc(text)}</div>"
        )
        row(label, lambda _, s, n=name: answer_cell(n, s))
    row("attempts", lambda _, s: esc(s.attempts) if s else "\u2013")
    row("first-attempt latency", lambda _, s: fmt_ms(s.first_attempt_latency_ms) if s else "\u2013")
    row("latency", lambda _, s: fmt_ms(s.latency_ms) if s else "\u2013")
    row("cost", lambda _, s: fmt_usd(s.cost_usd) if s else "\u2013")
    row("error", lambda _, s: text_block(s.error) if s and s.error else "\u2013")
    if bench.has_raw_response:
        row("raw response", lambda _, s: raw_response_cell(s.raw_response) if s else "\u2013")
    out.append(f"<table class='judges'><thead><tr>{head}</tr></thead><tbody>")
    out.append("".join(rows) + "</tbody></table>")
    return "".join(out)


def _state_section(bench: Bench, w: Write) -> str:
    """The exact state text, with the policy section collapsed in place."""
    text = w.state_text
    policy = w.context.get("policy")
    marker = f"## Context: policy\n{policy}" if isinstance(policy, str) else None
    out = [
        "<h2>State text the judges saw</h2>",
        f"<p class='muted'>Exact text, {len(text):,} chars.</p>",
    ]
    if marker and text.count(marker) == 1:
        before, after = text.split(marker)
        out.append(
            f"<pre class='state'>{esc(before)}<details><summary>## Context: policy "
            f"<span class='muted'>({len(policy):,} chars)</span></summary>{esc(policy)}"
            f"</details>{esc(after)}</pre>"
        )
    else:
        out.append(f"<pre class='state'>{esc(text)}</pre>")
    return "".join(out)


def collapsed(title: str, section: Callable[[Bench, Write], str]) -> Callable[[Bench, Write], str]:
    """A section shown collapsed, behind `title`."""

    def render(bench: Bench, w: Write) -> str:
        return f"<details class='box'><summary>{esc(title)}</summary>{section(bench, w)}</details>"

    return render


def _raw_heading(bench: Bench, w: Write) -> str:
    return (
        "<h2>8. Raw evidence and responses</h2>"
        "<p class='muted'>Implementation detail, collapsed: the oracle's checks, every judge "
        "answer and raw model response, the \u03c4\u00b2 trace comparison, the state text the "
        "judges saw and the write's identifiers.</p>"
    )


# Sections of the write page, in order: the summary, then (1) the proposal, (2) the oracle
# verdict, (3) the individual judges, (4) the decision strategies, (5) the configured gateway's
# effective decision, (6) the backend outcome, (7) the final task outcome, and (8) the raw
# evidence and responses, collapsed.
WRITE_SECTIONS: list[Callable[[Bench, Write], str]] = [
    _write_header,
    _summary_section,
    _proposal_section,
    _verdict_section,
    _judge_compare_section,
    _strategy_section,
    _gateway_section,
    _outcome_section,
    _task_outcome_section,
    _raw_heading,
    _evidence_section,
    collapsed("Judge answers and raw model responses", _judges_section),
    collapsed("\u03c4\u00b2 trace comparison (not a safety verdict)", _benchmark_section),
    collapsed("State text the judges saw", _state_section),
    _details_section,
]


def write_page(bench: Bench, w: Write) -> str:
    body = "".join(section(bench, w) for section in WRITE_SECTIONS)
    return page(f"{w.action} · {w.write_id}", body, depth=1)


# --- Simulation page -------------------------------------------------------------------------


def _scenario(bench: Bench, key: TaskKey) -> str:
    task = bench.tasks.get(key)
    if task is None:
        return ""
    scenario = task.get("user_scenario")
    return (
        "<details class='box'><summary>User scenario (what the simulated customer was told)"
        f"</summary>{json_block(scenario)}</details>"
    )


def sim_page(bench: Bench, sim: Simulation) -> str:
    up = "../"
    data = sim.data
    writes = list(bench.by_session.get(sim.id, []))
    reward_info = data.get("reward_info") or {}
    out = [
        f"<h1>Simulation {esc(sim.id)}</h1>",
        kv(
            [
                ("task", task_link(bench, sim.task_key, up)),
                ("trial", esc(sim.trial)),
                ("agent model", esc(sim.agent_model)),
                ("results file", esc(sim.source)),
                ("final task outcome", fmt_reward(sim)),
                ("termination", esc(sim.termination_reason)),
                ("reward breakdown", esc(canonical_json(reward_info.get("reward_breakdown")))),
                ("captured writes", " ".join(write_chip(x, up) for x in writes) or "none"),
                (
                    "agent / user cost",
                    f"{fmt_usd(data.get('agent_cost'))} / {fmt_usd(data.get('user_cost'))}",
                ),
            ]
        ),
        _scenario(bench, sim.task_key),
        "<h2>Conversation</h2><div class='conv'>",
    ]
    pending = iter(writes)
    nxt = next(pending, None)
    for m in data.get("messages") or []:
        role = str(m.get("role"))
        cls = f"msg {esc(role)}" + (" error" if m.get("error") else "")
        who = role
        if role == "tool":
            who = f"tool result ({m.get('requestor', '')})" + (" error" if m.get("error") else "")
        parts = [
            f"<div class='{cls}'><div class='who'>{esc(who)}"
            f" <span class='muted'>#{esc(m.get('turn_idx'))}</span></div>"
        ]
        if m.get("content"):
            parts.append(text_block(str(m["content"])))
        for call in m.get("tool_calls") or []:
            name, args = call.get("name"), call.get("arguments") or {}
            captured = None
            if (
                nxt is not None
                and call.get("requestor", "assistant") == "assistant"
                and role == "assistant"
                and nxt.action == name
                and canonical_json(nxt.args) == canonical_json(args)
            ):
                captured, nxt = nxt, next(pending, None)
            if captured is None:
                parts.append(
                    f"<div class='call'>→ <code>{esc(name)}</code>{json_block(args)}</div>"
                )
            else:
                outcome = (captured.outcome or {}).get("outcome")
                parts.append(
                    f"<div class='call captured v-{esc(captured.verdict or 'none')}' "
                    f"id='w-{esc(captured.write_id)}'>→ <code>{esc(name)}</code> "
                    f"{badge(captured.verdict)}"
                    + (f" <span class='muted'>backend: {esc(outcome)}</span>" if outcome else "")
                    + f" <a href='{up}{write_href(captured.write_id)}'>"
                    f"proposed write {captured.seq}</a>{json_block(args)}</div>"
                )
        parts.append("</div>")
        out.append("".join(parts))
    out.append("</div>")
    rest = ([nxt] if nxt is not None else []) + list(pending)
    if rest:
        out.append(
            "<p class='warn'>Captured writes not found in the conversation: "
            + " ".join(write_chip(x, up) for x in rest)
            + "</p>"
        )
    return page(f"Simulation {sim.id}", "".join(out), depth=1)


# --- Task page -------------------------------------------------------------------------------


def task_page(bench: Bench, key: TaskKey, sims: list[Simulation], writes: list[Write]) -> str:
    up = "../"
    domain, task_id = key
    out = [f"<h1>Task {esc(task_id)} <span class='muted'>{esc(domain)}</span></h1>"]
    passed = sum(s.passed for s in sims)
    verdicts = Counter(w.verdict or "none" for w in writes)
    out.append(
        kv(
            [
                ("simulations", f"{len(sims)} ({passed} with final task outcome pass)"),
                ("proposed writes", esc(len(writes))),
                (
                    "policy verdicts",
                    " ".join(f"{badge(v)} {verdicts[v]}" for v in VERDICTS if verdicts[v]),
                ),
            ]
        )
    )
    task = bench.tasks.get(key)
    if task is not None:
        if task.get("description"):
            out.append(
                f"<details class='box'><summary>Description</summary>"
                f"{json_block(task['description'])}</details>"
            )
        out.append(_scenario(bench, key))
        truth = bench.ground_truth(key)
        if truth is not None and truth.actions:
            out.append("<h2>Reference actions (τ² trace)</h2>")
            out.append(
                table(
                    ["#", "tool", "arguments"],
                    [
                        [
                            str(i + 1),
                            f"<code>{esc(g.name)}</code>",
                            f"<code>{esc(canonical_json(g.arguments))}</code>",
                        ]
                        for i, g in enumerate(truth.actions)
                    ],
                )
            )

    by_action: dict[str, Counter[str]] = {}
    for w in writes:
        by_action.setdefault(w.action, Counter())[w.verdict or "none"] += 1
    if by_action:
        out.append("<h2>Proposed writes by action and policy verdict</h2>")
        out.append(
            table(
                ["action", *(f"{v} ({VERDICT_NAMES[v]})" for v in VERDICTS)],
                [
                    [f"<code>{esc(a)}</code>", *(str(c[v]) for v in VERDICTS)]
                    for a, c in sorted(by_action.items())
                ],
            )
        )

    out.append("<h2>Trials</h2>")
    rows = []
    for s in sorted(sims, key=lambda s: (s.agent_model, s.source, s.trial or 0)):
        ws = bench.by_session.get(s.id, [])
        rows.append(
            [
                esc(s.agent_model),
                esc(s.source),
                esc(s.trial),
                fmt_reward(s),
                esc(s.termination_reason),
                f"<a href='{up}{sim_href(s.id)}'>conversation</a>",
                " ".join(write_chip(x, up) for x in ws) or "<span class='muted'>none</span>",
            ]
        )
    sessions = {s.id for s in sims}
    orphans: dict[str, list[Write]] = {}
    for w in writes:
        if w.session_id not in sessions:
            orphans.setdefault(w.session_id, []).append(w)
    for session_id, ws in orphans.items():
        rows.append(
            [
                esc(ws[0].agent_model),
                "<span class='muted'>store only</span>",
                esc(ws[0].trial),
                "<span class='muted'>\u2013</span>",
                "",
                f"<span class='muted'>{esc(session_id)}</span>",
                " ".join(write_chip(x, up) for x in sorted(ws, key=lambda x: x.seq)),
            ]
        )
    out.append(
        table(
            [
                "agent model",
                "results file",
                "trial",
                "final task outcome",
                "termination",
                "",
                "proposed writes",
            ],
            rows,
        )
    )
    return page(f"Task {domain}/{task_id}", "".join(out), depth=1)


# --- Overview --------------------------------------------------------------------------------


def overview_data(bench: Bench) -> dict[str, Any]:
    """Compact data the overview's script filters and aggregates in the browser."""
    task_keys = sorted(
        {w.task_key for w in bench.writes} | {s.task_key for s in bench.simulations.values()}
    )
    task_index = {k: i for i, k in enumerate(task_keys)}
    score_keys = sorted(bench.by_score_key)
    key_index = {k: i for i, k in enumerate(score_keys)}

    def judge_cell(key: tuple[str, str], j: JudgeKey) -> list[Any] | None:
        s = bench.scores.get(key, {}).get(j)
        if s is not None:
            return [s.status, s.cost_usd, s.first_attempt_latency_ms]
        if bench.skip_for(key, j) is not None:
            return ["skipped", None, None]
        return None

    return {
        "judges": [{"name": j, "model": m} for j, m in bench.judges],
        "tasks": [{"d": d, "id": t, "href": task_href((d, t))} for d, t in task_keys],
        "scoreKeys": [[judge_cell(k, j) for j in bench.judges] for k in score_keys],
        "sims": [
            {
                "id": s.id,
                "d": s.domain,
                "m": s.agent_model,
                "t": task_index[s.task_key],
                "src": s.source,
                "pass": s.passed,
                "rewarded": s.reward is not None,
            }
            for s in bench.simulations.values()
        ],
        "writes": [
            {
                "id": w.write_id,
                "href": write_href(w.write_id),
                "d": w.domain or "",
                "m": w.agent_model or "",
                "t": task_index[w.task_key],
                "tr": w.trial,
                "seq": w.seq,
                "a": w.action,
                "v": w.verdict or "none",
                "o": (w.outcome or {}).get("outcome") or "",
                "bm": w.benchmark_match or "",
                "g": {arm: d["decision"] for arm, d in w.arm_decisions.items()},
                "k": key_index[w.score_key] if w.score_key is not None else -1,
                "src": bench.simulations[w.session_id].source
                if w.session_id in bench.simulations
                else "",
                "sim": sim_href(w.session_id) if w.session_id in bench.simulations else "",
                "ts": w.ts,
            }
            for w in bench.writes
        ],
        "hasSkips": bench.has_skips,
        "arms": sorted(bench.arms),
        "armNames": {arm: strategy_label(bench, arm) for arm in sorted(bench.arms)},
        "oracle": bench.oracle_version,
    }


WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
SCOPE_HEADINGS = {
    "test": "Held-out test only ({n} actions)",
    "all": "All {n} captured actions \u2014 descriptive only; includes training examples",
}
OUTCOME_HEADERS = (
    ("Caught review-required", "caught"),
    ("False allows", "false_allow"),
    ("Safe auto-allows", "safe_auto"),
    ("Over-escalations", "over_escalation"),
)


def count_word(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else f"{n:,}"


def titled_table(headers: Sequence[tuple[str, str | None]], rows: Iterable[Sequence[str]]) -> str:
    """`table`, with an optional tooltip per header."""
    head = "".join(
        f"<th title='{esc(tip)}'>{esc(h)}</th>" if tip else f"<th>{esc(h)}</th>"
        for h, tip in headers
    )
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def outcome_cells(c: Any) -> list[str]:
    return [
        frac(c.caught, c.required),
        frac(c.false_allow, c.required),
        frac(c.safe_auto, c.valid),
        frac(c.over_escalation, c.valid),
    ]


def all_scope(bench: Bench, inner: str) -> str:
    """The all-captured-actions view of a section: descriptive, collapsed under the held-out
    view so the two are never read as one."""
    return (
        "<details class='scope-all'><summary>"
        + esc(SCOPE_HEADINGS["all"].format(n=len(bench.writes)))
        + "</summary>"
        + inner
        + "</details>"
    )


def policy_section(bench: Bench) -> str:
    """1. The answer key: the policy verdicts. Simulations follow as secondary context."""
    n = len(bench.writes)
    counts = Counter(w.verdict or "none" for w in bench.writes)
    rows = [
        [badge(v), str(counts[v]), esc(dict(LEGEND).get(v, "no verdict stored"))]
        for v in ("ALLOW", "ASK", "DENY", "UNKNOWN")
    ]
    if counts["none"]:
        rows.append([badge(None), str(counts["none"]), "no verdict stored"])
    sims = list(bench.simulations.values())
    rewarded = [x for x in sims if x.outcome is not None]
    passes = sum(x.outcome == "PASS" for x in rewarded)
    rejected = sum((w.outcome or {}).get("outcome") == "REJECTED" for w in bench.writes)
    return (
        "<h2 id='policy'>1. What was the correct policy decision?</h2>"
        "<p class='muted'>The policy oracle's verdict on each proposed action, made before it "
        "ran. It is the answer key every judge and strategy below is scored against. UNKNOWN "
        "verdicts are excluded from every rate and counted on their own.</p>"
        f"<div class='block'><h3>{n} proposed business actions</h3>"
        + table(["policy verdict", "actions", "meaning"], rows)
        + "</div>"
        + f"<div class='block secondary'><h3>Secondary context: {len(sims)} simulations</h3>"
        + kv(
            [
                ("final task outcome passes", str(passes)),
                ("final task outcome failures", str(len(rewarded) - passes)),
                ("no final task outcome", str(len(sims) - len(rewarded))),
            ]
        )
        + "<p class='muted'>Per conversation. A passing conversation says nothing about whether "
        f"each of its actions was valid. Backend in shadow mode rejected {rejected} of {n} "
        "proposed actions.</p></div>"
    )


def executive_cards(bench: Bench) -> str:
    """Four cards on the held-out actions: the sample, the best individual judge, the
    configured gate, and whether anything can be concluded."""
    from hatchway.bench.replay import MIN_EVALUATED

    test = in_scope(bench, "test")
    required = sum(w.verdict in INTERVENE for w in test)
    valid = sum(w.verdict == "ALLOW" for w in test)
    unknown = len(test) - required - valid
    cards = [
        (
            "Held-out sample",
            f"<p class='big'>{len(test)} actions</p><p>{required} must not auto-run (ASK or "
            f"DENY) \u00b7 {valid} valid (ALLOW) \u00b7 {unknown} UNKNOWN</p>",
        )
    ]
    singles = single_judge_strategies(bench)
    best = strongest(bench, test, singles)
    if best is not None:
        c = outcome_counts(test, best.arm)
        body = (
            f"<p class='big'>{esc(best.display_name or best.label)}</p>"
            f"<p>caught {frac(c.caught, c.required)} \u00b7 auto-allowed "
            f"{frac(c.safe_auto, c.valid)}</p>"
        )
    else:
        body = "<p class='big'>No single best</p><p>the strongest judges tie</p>"
    cards.append(("Best individual judge", body))
    candidate = configured(bench)
    if candidate is not None:
        c = outcome_counts(test, candidate.arm)
        missed = [
            w
            for w in test
            if candidate.arm in w.arm_decisions
            and result_kind(w.verdict, w.arm_decisions[candidate.arm]["decision"]) == "false_allow"
        ]
        links = ", ".join(
            f"<a href='{write_href(w.write_id)}'>{esc(action_title(w.action, w.args))}</a>"
            for w in missed
        )
        cards.append(
            (
                "Configured gate",
                f"<p class='big'>{esc(candidate.label)}</p>"
                f"<p>caught {frac(c.caught, c.required)} \u00b7 missed "
                f"{frac(c.false_allow, c.required)}"
                + (f" ({links})" if links else "")
                + f" \u00b7 auto-allowed {frac(c.safe_auto, c.valid)}</p>",
            )
        )
    reasons = []
    if diagnostic(bench):
        failed = ((bench.replay_metrics or {}).get("claims") or {}).get("failed_gates")
        reasons.append(
            f"{' and '.join(failed)} gates failed"
            if failed
            else "no claims-gate result"
            if bench.replay_metrics is None
            else "claims gate failed"
        )
    if not any(w.manual is not None for w in bench.writes):
        reasons.append("oracle unaudited")
    evaluated = sum(w.verdict in ESTABLISHED for w in test)
    if evaluated < MIN_EVALUATED:
        reasons.append(f"{evaluated} < {MIN_EVALUATED} held-out actions")
    cards.append(
        (
            "Can we conclude?",
            "<p class='big'>No</p><p>" + esc("; ".join(reasons)) + "</p>"
            if reasons
            else "<p class='big'>Within the claims gate</p>",
        )
    )
    return (
        "<div class='exec'>"
        + "".join(f"<div class='exec-card'><h3>{esc(t)}</h3>{b}</div>" for t, b in cards)
        + "</div>"
    )


def comparison_tables(bench: Bench, writes: Sequence[Write]) -> str:
    """The individual judge and decision strategy tables for one scope."""
    ops = operational_rows(bench)
    tips = [(h, DEFINITIONS[k]) for h, k in OUTCOME_HEADERS]
    rows = []
    for st in single_judge_strategies(bench):
        judge = judge_of(bench, st)
        o = ops.get(judge) if judge else None
        rows.append(
            [
                judge_cell(bench, judge) if judge else esc(st.label),
                *outcome_cells(outcome_counts(writes, st.arm)),
                fmt_cost(o.cost_per_action if o else None),
                fmt_ms(o.p50_ms if o else None),
            ]
        )
    out = ["<h4>Individual judge comparison</h4>"]
    out.append(
        titled_table(
            [("Judge", None), *tips, ("Cost/action", None), ("Median latency", None)], rows
        )
    )
    rows = [
        [
            esc(st.label)
            + f"<div class='muted small'>{esc(strategy_description(bench, arm))}</div>",
            *outcome_cells(outcome_counts(writes, arm)),
        ]
        for arm, st in sorted(bench.strategies.items())
    ]
    out.append("<h4>Decision strategy comparison</h4>")
    out.append(titled_table([("Decision strategy (what it computes)", None), *tips], rows))
    unknown = sum(w.verdict not in ESTABLISHED for w in writes)
    out.append(
        f"<p class='muted'>UNKNOWN or no verdict: {unknown} action"
        f"{'s' if unknown != 1 else ''} in this scope, excluded from these counts.</p>"
    )
    lines = takeaway(bench, writes, blocked=diagnostic(bench), run=run_word(bench))
    if lines:
        out.append("<p class='takeaway'>" + " ".join(esc(x) for x in lines) + "</p>")
    return "".join(out)


def judge_section(bench: Bench) -> str:
    """2. Held-out first: the executive cards, the judges and every strategy; the same tables
    over all captured actions collapsed below."""
    out = ["<h2 id='judges'>2. How did each judge do?</h2>"]
    if not bench.strategies:
        out.append(
            "<p class='muted'>No replay given (build the report with <code>--replay</code>): no "
            "judge decisions to compare.</p>"
        )
        return "".join(out)
    out.append(executive_cards(bench))
    out.append(
        "<p class='muted'>Each judge scores the proposed action from pre-execution evidence. Its "
        "own decision strategy allows the action when its derived gateway score reaches a "
        "threshold fitted on the training split. Counts, not rates: every cell shows its "
        "denominator.</p>"
    )
    test = in_scope(bench, "test")
    out.append(f"<h3>{esc(SCOPE_HEADINGS['test'].format(n=len(test)))}</h3>")
    if diagnostic(bench):
        n = sum(w.verdict in ESTABLISHED for w in test)
        out.append(
            f"<p class='claims-warn'><b>Only {count_word(n)} held-out action"
            f"{'s are' if n != 1 else ' is'} available. These counts diagnose the pipeline; "
            "they do not estimate future performance.</b></p>"
        )
    out.append(comparison_tables(bench, test))
    out.append(all_scope(bench, comparison_tables(bench, in_scope(bench, "all"))))
    out.append(
        "<dl class='defs'>"
        + "".join(f"<dt>{esc(h)}</dt><dd>{esc(DEFINITIONS[k])}</dd>" for h, k in OUTCOME_HEADERS)
        + "<dt>UNKNOWN</dt><dd>Excluded from all four counts and shown separately.</dd></dl>"
    )
    return "".join(out)


FLAG_TEXT = {
    "false_allow": "false allow",
    "over_escalation": "over-escalation",
    "judges_differ": "judges disagree",
    "score_spread": "policy_ok far apart",
}


def card_row(
    bench: Bench,
    w: Write,
    name: str,
    judge: str | None,
    arm: str,
    d: Mapping[str, Any],
    mark: str = "",
) -> str:
    """One row of a disagreement card: the judge's raw answers, the relevant predicate, and the
    strategy's derived score, threshold and decision (reproducible from the row alone)."""
    score = None
    if judge is not None and w.score_key is not None:
        score = next(
            (s for (j, _), s in bench.scores.get(w.score_key, {}).items() if j == judge), None
        )
    digits = shown_digits(bench, arm, score, d)
    f = calc_facts(d, digits)
    override = {"fail_closed": " (fail closed)", "disagreement_veto": " (disagreement veto)"}
    decision = gate_span(d["decision"]) + esc(override.get(f["rule"], "")) + mark
    dash = "<span class='muted'>\u2013</span>"
    cells = [
        esc(name),
        yes_score(score, "policy_ok", digits) if score else dash,
        yes_score(score, "matches_request", digits) if score else dash,
        weakest_cell(score) if score and score.status == "ok" else dash,
        esc(f.get("score", "\u2013")),
        esc(f.get("threshold", "\u2013")),
        decision,
    ]
    return f"<tr class='calc' {calc_attrs(f)}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def disagreement_section(bench: Bench, spread: float) -> str:
    out = ["<h2 id='disagreements'>Where the judges disagreed</h2>"]
    cards = disagreements(bench, spread)
    candidate = configured(bench)
    out.append(
        "<p class='muted'>Actions where the configured candidate false-allowed or "
        "over-escalated, where the individual judges' decisions differ, or where their "
        f"<code>policy_ok</code> answers are more than {spread:g} apart. False allows first. "
        "Each row's decision follows from its derived score and threshold (ALLOW when the "
        "score \u2265 the threshold) unless an override is named.</p>"
    )
    if not cards:
        out.append("<p class='muted'>None.</p>")
        return "".join(out)
    singles = single_judge_strategies(bench)
    head = "".join(
        f"<th>{h}</th>"
        for h in (
            "Judge or strategy",
            "<code>policy_ok</code>",
            "<code>matches_request</code>",
            "Relevant predicate",
            "Derived score",
            "Threshold",
            "Decision",
        )
    )
    for c in cards:
        w = c.write
        verdict = f"{badge(w.verdict)}" + (
            f" \u2014 {esc(reasons_text(w))}" if reasons_text(w) else ""
        )
        rows = [
            card_row(
                bench, w, st.display_name or st.label, st.judge, st.arm, w.arm_decisions[st.arm]
            )
            for st in singles
            if st.arm in w.arm_decisions
        ]
        if candidate is not None and candidate.arm in w.arm_decisions:
            d = w.arm_decisions[candidate.arm]
            effective = effective_decision(w.verdict, d["decision"])
            kind = result_kind(w.verdict, effective)
            mark = (
                f" <b class='result {esc(kind)}'>\u2190 {esc(FLAG_TEXT[kind])}</b>"
                if kind in ("false_allow", "over_escalation")
                else ""
            )
            if effective != d["decision"]:
                mark += f" \u2192 effective {gate_span(effective)} (UNKNOWN verdict)"
            rows.append(
                card_row(bench, w, candidate.label, candidate.judge, candidate.arm, d, mark)
            )
        o = (w.outcome or {}).get("outcome")
        sim = bench.simulations.get(w.session_id)
        context = kv(
            [
                ("Backend", esc(o) if o else "<span class='muted'>not recorded</span>"),
                (
                    "Task",
                    esc(sim.outcome)
                    if sim is not None and sim.outcome
                    else "<span class='muted'>\u2013</span>",
                ),
            ]
        )
        flags = " ".join(f"<span class='flag {esc(f)}'>{esc(FLAG_TEXT[f])}</span>" for f in c.flags)
        out.append(
            f"<div class='card'><h3><a href='{write_href(w.write_id)}'>"
            f"{esc(action_title(w.action, w.args))}</a> {flags}</h3>"
            f"<p class='muted small'>{esc(w.agent_model)} \u00b7 {esc(w.domain)}/"
            f"{esc(w.task_id)} \u00b7 {esc(w.split or 'no split')}</p>"
            f"<p><b>Oracle:</b> {verdict}</p>"
            f"<table class='cardtab'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}"
            "</tbody></table>"
            + context
            + f"<p><a href='{write_href(w.write_id)}'>Open the action page \u2192</a></p></div>"
        )
    return "".join(out)


def action_type_table(bench: Bench, writes: Sequence[Write], columns: Sequence[Strategy]) -> str:
    rows = [
        [
            f"<a href='#action={esc(r['action'])}'>{esc(r['action'])}</a>",
            str(r["actions"]),
            str(r["required"]),
            *(frac(r["caught"][c.arm], r["required"]) for c in columns),
        ]
        for r in by_action_type(bench, writes, [c.arm for c in columns])
    ]
    headers = ["Action type", "Actions", "Required intervention"] + [
        f"{c.display_name or c.label} caught" for c in columns
    ]
    return table(headers, rows)


def action_type_section(bench: Bench) -> str:
    if not bench.strategies:
        return ""
    columns = list(single_judge_strategies(bench))
    candidate = configured(bench)
    if candidate is not None and candidate not in columns:
        columns.append(candidate)
    test = in_scope(bench, "test")
    return (
        "<h2 id='by-action'>By action type</h2>"
        "<p class='muted'>Whether a judge is broadly better or only better at one kind of action. "
        "Click an action type to filter the captured-action table below.</p>"
        f"<h3>{esc(SCOPE_HEADINGS['test'].format(n=len(test)))}</h3>"
        + action_type_table(bench, test, columns)
        + all_scope(bench, action_type_table(bench, in_scope(bench, "all"), columns))
    )


def gate_scope_block(bench: Bench, writes: Sequence[Write], arm: str) -> str:
    """The configured candidate on one scope: the four counts, then the split by verdict."""
    c = outcome_counts(writes, arm)
    rows = []
    for r in by_verdict(writes, arm):
        if r["verdict"] == "UNKNOWN" and not r["actions"]:
            rows.append([badge("UNKNOWN"), "0", "\u2013", "\u2013", "\u2013"])
            continue
        if r["verdict"] == "UNKNOWN":
            allowed = (
                f"{r['allowed']} raw \u00b7 {r['effective_allowed']} effective"
                if r["actions"]
                else "0"
            )
            rows.append(
                [
                    badge("UNKNOWN"),
                    str(r["actions"]),
                    allowed,
                    f"{r['actions'] - r['effective_allowed']} effective",
                    "\u2013",
                ]
            )
            continue
        good_allow = r["verdict"] == "ALLOW"
        rows.append(
            [
                badge(r["verdict"]),
                str(r["actions"]),
                f"{r['allowed']} "
                + (
                    "(safe auto-allows)"
                    if good_allow
                    else "<b class='result false_allow'>(false allows)</b>"
                ),
                f"{r['asked']} " + ("(over-escalations)" if good_allow else "(caught)"),
                frac(r["allowed"] if good_allow else r["asked"], r["actions"]),
            ]
        )
    return (
        "<ul>"
        f"<li>Caught {frac(c.caught, c.required)} review-required actions.</li>"
        f"<li>Missed {frac(c.false_allow, c.required)}.</li>"
        f"<li>Automatically allowed {frac(c.safe_auto, c.valid)} valid actions.</li>"
        f"<li>Unnecessarily escalated {frac(c.over_escalation, c.valid)}.</li></ul>"
        + table(
            [
                "Policy verdict",
                "Actions",
                "Allowed automatically",
                "Asked (escalated)",
                "Right call",
            ],
            rows,
        )
    )


def gateway_section(bench: Bench) -> str:
    """3. The configured candidate, after the judges, and never as the headline."""
    out = ["<h2 id='gateway'>3. What would the configured gateway have done?</h2>"]
    candidate = configured(bench)
    if candidate is None:
        out.append(
            "<p class='muted'>No replay given (build the report with <code>--replay</code>).</p>"
        )
        return "".join(out)
    arm = candidate.arm
    test = in_scope(bench, "test")
    out.append(f"<div class='block'><h3>Current configured candidate: {esc(candidate.label)}</h3>")
    out.append(f"<p class='muted small'>{esc(strategy_description(bench, arm))}</p>")
    out.append(f"<h4>{esc(SCOPE_HEADINGS['test'].format(n=len(test)))}</h4>")
    out.append(gate_scope_block(bench, test, arm))
    out.append(all_scope(bench, gate_scope_block(bench, in_scope(bench, "all"), arm)))
    everything = in_scope(bench, "all")
    best = strongest(bench, everything, list(bench.strategies.values()))
    sentences = []
    if (
        best is not None
        and best.arm != arm
        and outcome_counts(everything, best.arm).rank() < outcome_counts(everything, arm).rank()
    ):
        sample = "smoke sample" if run_word(bench) == "smoke run" else "sample"
        sentences.append(f"{best.label} performed better on this {sample}.")
    if diagnostic(bench):
        sentences.append("No production choice should be made until the held-out sample is larger.")
    if sentences:
        out.append("<p class='takeaway'><b>" + " ".join(esc(x) for x in sentences) + "</b></p>")
    metrics = bench.replay_metrics
    claims = (metrics or {}).get("claims") or {}
    if diagnostic(bench):
        failed = claims.get("failed_gates")
        if metrics is None:
            why = "no claims-gate result (no replay metrics given)."
        elif failed:
            why = f"{' and '.join(failed)} gates failed."
        else:
            why = "claims gate failed."
        out.append(f"<p class='diag'><b>Not a benchmark performance result; {esc(why)}</b></p>")
    replayed = [w for w in bench.writes if arm in w.arm_decisions]
    unestablished = [w for w in replayed if w.verdict not in ESTABLISHED]
    raw_allowed = sum(w.arm_decisions[arm]["decision"] == "ALLOW" for w in unestablished)
    blocked = sum(
        effective_decision(w.verdict, w.arm_decisions[arm]["decision"]) != "ALLOW"
        for w in unestablished
    )
    out.append(
        kv(
            [
                (
                    "UNKNOWN or no verdict (left out of the counts)",
                    f"{len(unestablished)}: raw replay would allow {raw_allowed}; effective "
                    f"runtime ASK for {blocked} of {len(unestablished)}"
                    if unestablished
                    else "0",
                )
            ]
        )
    )
    out.append(
        "<p class='muted'>Computed offline from the stored judge scores; in shadow mode nothing "
        "was blocked.</p></div>"
    )
    return "".join(out)


def operational_section(bench: Bench) -> str:
    if not bench.judges:
        return ""
    ops = operational_rows(bench)
    rows = [
        [
            judge_cell(bench, j),
            str(o.rows),
            str(o.errors),
            str(o.retries),
            fmt_cost(o.total_cost),
            fmt_cost(o.cost_per_action),
            fmt_ms(o.p50_ms),
            fmt_ms(o.p95_ms),
        ]
        for j, o in ops.items()
    ]
    out = [
        "<h2 id='operations'>Operational comparison</h2>",
        "<p class='muted'>Cost and latency, kept apart from safety. Each unique judge invocation "
        "counts once (actions with the same state share one score row); a retry is a score row "
        "with more than one attempt.</p>",
        table(
            [
                "Judge",
                "Score rows",
                "Errors",
                "Retries",
                "Total cost",
                "Cost/action",
                "p50 latency",
                "p95 latency",
            ],
            rows,
        ),
    ]
    if bench.strategies:
        srows = []
        for arm, st in sorted(bench.strategies.items()):
            cost = strategy_cost(bench, arm, ops)
            calls = ", ".join(judge_label(j, bench.judge_names) for j in st.judges) or "\u2013"
            srows.append(
                [
                    esc(st.label),
                    esc(calls),
                    fmt_cost(cost)
                    if cost is not None
                    else "<span class='muted'>not available</span>",
                ]
            )
        out.append("<h3>Decision strategy cost</h3>")
        out.append(
            "<p class='muted'>The sum of the per-action cost of the judges each strategy calls, "
            "from its frozen judge list; \u201cnot available\u201d when that is unknown.</p>"
        )
        out.append(table(["Decision strategy", "Judge calls per action", "Cost/action"], srows))
    return "".join(out)


def reliability_svg(bins: Sequence[Mapping[str, Any]]) -> str:
    """A small reliability curve: mean score (x) against the share that was ALLOW (y)."""
    size, pad = 160, 16
    span = size - 2 * pad

    def xy(x: float, y: float) -> str:
        return f"{pad + x * span:.1f},{size - pad - y * span:.1f}"

    points = " ".join(xy(b["mean_score"], b["frac_allow"]) for b in bins)
    dots = "".join(
        f"<circle cx='{xy(b['mean_score'], b['frac_allow']).split(',')[0]}' "
        f"cy='{xy(b['mean_score'], b['frac_allow']).split(',')[1]}' r='3'/>"
        for b in bins
    )
    return (
        f"<svg class='reliability' viewBox='0 0 {size} {size}' width='{size}' height='{size}' "
        "role='img' aria-label='reliability curve'>"
        f"<rect x='{pad}' y='{pad}' width='{span}' height='{span}' fill='none' "
        "stroke='currentColor' stroke-opacity='.3'/>"
        f"<line x1='{pad}' y1='{size - pad}' x2='{size - pad}' y2='{pad}' stroke='currentColor' "
        "stroke-opacity='.4' stroke-dasharray='3 3'/>"
        f"<polyline points='{points}' fill='none' stroke='currentColor' stroke-width='1.5'/>"
        f"<g fill='currentColor'>{dots}</g></svg>"
    )


def calibration_section(bench: Bench) -> str:
    from hatchway.bench.replay import MIN_EVALUATED

    out = ["<h2 id='calibration'>Calibration</h2>"]
    if not bench.strategies:
        out.append("<p class='muted'>No replay given.</p>")
        return "".join(out)
    cal = calibration(bench, MIN_EVALUATED)
    if not cal["available"]:
        out.append(
            f"<p class='claims-warn'>Calibration unavailable: {cal['n']} held-out verdict-bearing "
            f"actions; minimum required is {cal['min']}.</p>"
        )
        return "".join(out)
    out.append(
        "<p class='muted'>Held-out actions only, with each judge's frozen score: ALLOW = 1, "
        "ASK/DENY = 0, UNKNOWN excluded. A well-calibrated judge follows the dashed line.</p>"
    )
    for arm, r in cal["strategies"].items():
        st = bench.strategies[arm]
        fmt = lambda v: "\u2013" if v is None else f"{v:.3f}"  # noqa: E731
        out.append(
            f"<div class='block'><h3>{esc(st.display_name or st.label)}</h3>"
            + reliability_svg(r["bins"])
            + kv(
                [("actions", str(r["n"])), ("Brier score", fmt(r["brier"])), ("ECE", fmt(r["ece"]))]
            )
            + "</div>"
        )
    return "".join(out)


def claims_box(bench: Bench) -> str:
    """Why these results support no benchmark conclusion (if they do not)."""
    from hatchway.bench.replay import MIN_EVALUATED, MIN_INTERVENTION_PER_ACTION

    reasons: list[str] = []
    n = len(bench.writes)
    if n < MIN_EVALUATED:
        reasons.append(f"Only {n} proposed actions")
    if not any(w.manual is not None for w in bench.writes):
        reasons.append("Deterministic oracle only; unaudited")
    supported = set(bench.supported_actions)
    outside = sum((w.domain or "", w.action) not in supported for w in bench.writes)
    reasons.append(
        f"Only {len(supported)} action types supported"
        + (f" ({outside} proposed actions outside them)" if outside else "")
    )
    metrics = bench.replay_metrics
    if metrics is None:
        reasons.append("No replay given: no replayed gate results")
    else:
        arms = metrics.get("arms") or {}
        thin = [
            name
            for name, a in sorted(arms.items())
            if name != "A"
            and (
                str(a.get("status", "")).startswith("insufficient")
                or (a.get("train") or {}).get("intervention_required", 0)
                < MIN_INTERVENTION_PER_ACTION
            )
        ]
        if thin:
            reasons.append(
                "Insufficient data for fitted thresholds ("
                + ", ".join(strategy_label(bench, a) for a in thin)
                + ")"
            )
        claims = metrics.get("claims") or {}
        reasons += [f"Claims gate: {r}" for r in claims.get("reasons", [])]
    audited = any(w.manual is not None for w in bench.writes)
    gate_blocked = metrics is None or bool((metrics.get("claims") or {}).get("blocked"))
    blocked = gate_blocked or not audited or n < MIN_EVALUATED
    if not blocked:
        return ""
    items = "".join(f"<li>{esc(r)}</li>" for r in reasons)
    return (
        "<div class='box claims'><h2>Results are diagnostic, not benchmark conclusions.</h2>"
        f"<p>Reasons:</p><ul>{items}</ul></div>"
    )


def provenance_box(bench: Bench) -> str:
    p = bench.provenance

    def show(value: Any) -> str:
        if value is None or value == []:
            return "<span class='muted'>not recorded</span>"
        if isinstance(value, list):
            return "<br>".join(f"<code>{esc(v)}</code>" for v in value)
        return f"<code>{esc(value)}</code>"

    rows = [
        ("run commit (capture)", show(p.get("run_commit"))),
        ("report commit (this page)", show(p.get("report_commit"))),
        ("run config", show(p.get("config"))),
        ("run seed", show(p.get("seed"))),
        ("replay seed", show(p.get("replay_seed"))),
        ("replay decision rule", show(p.get("decision_rule"))),
        ("oracle version", show(p.get("oracle_version"))),
        ("agent models", show(p.get("agent_models"))),
        ("user simulator models", show(p.get("user_models"))),
        ("judge models", show(p.get("judge_models"))),
    ]
    if p.get("converted"):
        rows.append(("converted store", f"<b>{esc(p['converted'])}</b>"))
    return "<details class='box' open><summary>Run provenance</summary>" + kv(rows) + "</details>"


def index_page(bench: Bench, spread_threshold: float = SCORE_SPREAD_THRESHOLD) -> str:
    data = json.dumps(overview_data(bench), separators=(",", ":"), ensure_ascii=False)
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    latencies = [
        s.first_attempt_latency_ms
        for by_judge in bench.scores.values()
        for s in by_judge.values()
        if s.first_attempt_latency_ms is not None
    ]
    note = (
        f"{len(bench.writes):,} captured writes, {len(bench.simulations):,} simulations, "
        f"{len(bench.judges)} judges"
        + (
            f", median first-attempt latency {statistics.median(latencies):,.0f} ms"
            if latencies
            else ""
        )
        + ". "
        + ("" if bench.has_raw_response else "No raw_response column. ")
        + ("" if bench.has_skips else "No scoring_skips table. ")
    )
    reviewed = sum(w.manual is not None for w in bench.writes)
    audit = (
        f"Reviewed: {reviewed} of {len(bench.writes)} verdicts adjudicated. "
        if reviewed
        else "Deterministic oracle only, unaudited: no verdict has been reviewed. "
    )
    oracle = (
        f"Policy verdicts from oracle version {bench.oracle_version}. {audit}"
        if bench.oracle_version
        else "No policy verdicts in this store. "
    )
    modes = set(bench.provenance.get("simulation_modes") or ["wrapped"])
    badges = (mode_badge("wrapped") if modes - {"gated"} else "") + (
        mode_badge("gated") if "gated" in modes else ""
    )
    body = f"""
<h1>Benchmark overview</h1>
{badges}
{reading_box(bench)}
<details class='box'><summary>Verdict legend</summary>{legend()}</details>
{policy_section(bench)}
{judge_section(bench)}
{disagreement_section(bench, spread_threshold)}
{action_type_section(bench)}
{gateway_section(bench)}
{operational_section(bench)}
{calibration_section(bench)}
{claims_box(bench)}
{provenance_box(bench)}
<h2 id='explore'>Explore the captured actions</h2>
<p class='muted'>{esc(note)}{esc(oracle)}Simulation counts follow the domain, model and task
filters; verdict and action filter proposed writes only. The gate columns use the selected
decision strategy. Judge cost and latency count each score row once, however many duplicate
writes share it. <a href='review.html'>Verdict review</a>.</p>
<div id='filters' class='filters'></div>
<h2>By domain and agent model</h2><div id='groups'></div>
<h2>Judges</h2><div id='judges'></div>
<h2>Tasks</h2><div id='tasks'></div>
<h2>Proposed writes</h2><div id='writes'></div>
<script type='application/json' id='data'>{data}</script>
<script>{OVERVIEW_JS}</script>
"""
    return page("Overview", body, depth=0)


# --- Verdict review --------------------------------------------------------------------------


def review_page(bench: Bench) -> str:
    """UNKNOWN verdicts awaiting review, and how reviewers agreed with the deterministic
    oracle where they looked (`python -m hatchway.bench.tau2.verdicts --queue/--import`)."""
    out = [
        "<h1>Policy verdict review</h1>",
        f"<p class='muted'>Oracle version <code>{esc(bench.oracle_version)}</code>. Queue and "
        "import reviews with <code>python -m hatchway.bench.tau2.verdicts</code>; an adjudicated "
        "review overrides the deterministic verdict.</p>",
    ]
    pending = [w for w in bench.writes if w.verdict == "UNKNOWN" and w.manual is None]
    out.append(f"<h2>Unknown verdicts awaiting review ({len(pending)})</h2>")
    if pending:
        out.append(
            table(
                ["write", "action", "task", "reasons"],
                [
                    [
                        f"<a href='{write_href(w.write_id)}'>{esc(w.write_id)}</a>",
                        f"<code>{esc(w.action)}</code>",
                        task_link(bench, w.task_key, ""),
                        " ".join(
                            f"<code>{esc(c)}</code>"
                            for c in (w.deterministic or {}).get("reason_codes", [])
                        ),
                    ]
                    for w in pending
                ],
            )
        )
    reviewed = [w for w in bench.writes if w.manual is not None and w.deterministic is not None]
    out.append(f"<h2>Oracle vs reviewer ({len(reviewed)} reviewed)</h2>")
    agreement: dict[str, Counter[str]] = {}
    for w in reviewed:
        agreement.setdefault(w.deterministic["decision"], Counter())[w.manual["decision"]] += 1
    if agreement:
        cols = ["ALLOW", "ASK", "DENY", "UNKNOWN"]
        out.append(
            table(
                ["oracle (rows), reviewer (columns)", *cols, "agreed"],
                [
                    [badge(d), *(str(c[x]) for x in cols), f"{c[d]} / {sum(c.values())}"]
                    for d, c in sorted(agreement.items())
                ],
            )
        )
    else:
        out.append("<p class='muted'>No reviews yet.</p>")
    return page("Verdict review", "".join(out), depth=0)


# --- Assets ----------------------------------------------------------------------------------

CSS = """
:root { --fg:#1d1d1f; --muted:#6e6e73; --bg:#fff; --line:#e3e3e8; --panel:#f6f6f8;
  --ok:#1a7f37; --bad:#c62828; --amb:#b26a00; --hl:#fff4c2; --link:#0b5cad; }
@media (prefers-color-scheme: dark) { :root { --fg:#e8e8ea; --muted:#9a9aa0; --bg:#17171a;
  --line:#33333a; --panel:#212126; --ok:#4cc26b; --bad:#ff6b6b; --amb:#f0a640; --hl:#4a3f12;
  --link:#7ab8ff; } }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.45 system-ui, sans-serif; color:var(--fg); background:var(--bg); }
nav { padding:8px 16px; border-bottom:1px solid var(--line); background:var(--panel); }
nav a { font-weight:600; } .crumb { color:var(--muted); margin-left:12px; }
main { padding:12px 16px 40px; max-width:1400px; }
a { color:var(--link); text-decoration:none; } a:hover { text-decoration:underline; }
h1 { font-size:20px; } h1 code { font-size:inherit; }
h2 { font-size:16px; margin-top:28px; } h3 { font-size:14px; }
pre { white-space:pre-wrap; word-break:break-word; background:var(--panel); padding:8px;
  border-radius:4px; margin:4px 0; max-height:600px; overflow:auto; }
pre.state { max-height:none; } pre details { margin:4px 0; }
code { font:12px ui-monospace, monospace; }
table { border-collapse:collapse; margin:6px 0; }
th, td { border:1px solid var(--line); padding:4px 8px; text-align:left; vertical-align:top; }
thead th { background:var(--panel); }
table.kv th { background:var(--panel); width:160px; }
table.judges td { min-width:180px; }
.qtext { color:var(--muted); max-width:420px; font-weight:normal; }
tr.diff td { background:var(--hl); } .hl { background:var(--hl); font-weight:600; }
.muted { color:var(--muted); } .warn { color:var(--amb); } .note { background:var(--panel);
  padding:6px 8px; }
.badge, .chip { display:inline-block; padding:1px 7px; border-radius:10px; font-size:12px;
  border:1px solid currentColor; margin:1px; }
.mode { display:inline-block; font-weight:700; padding:6px 12px; border-radius:6px;
  margin:4px 8px 8px 0; border:2px solid currentColor; }
.mode.shadow { color:var(--amb); } .mode.gated { color:var(--link); }
.box.reading, .box.claims { border:1px solid var(--line); border-radius:6px; padding:4px 14px;
  background:var(--panel); max-width:900px; }
.box.claims { border-color:var(--amb); }
.diag { color:var(--amb); margin:2px 0 6px; }
.block { display:inline-block; vertical-align:top; margin:0 24px 12px 0; }
.block.secondary { opacity:.85; }
ol.layers { line-height:1.8; } .small { font-size:12px; } h4 { font-size:13px; margin:14px 0 4px; }
.exec { display:flex; flex-wrap:wrap; gap:12px; margin:8px 0 16px; }
.exec-card { border:1px solid var(--line); border-radius:8px; padding:4px 14px 8px; width:250px;
  background:var(--panel); } .exec-card h3 { margin:6px 0 2px; font-size:12px;
  text-transform:uppercase; color:var(--muted); } .exec-card .big { font-size:17px;
  font-weight:700; margin:4px 0; } .exec-card p { margin:4px 0; }
details.scope-all { margin:8px 0 14px; } details.scope-all > summary { cursor:pointer;
  color:var(--muted); }
.claims-warn { color:var(--amb); border-left:3px solid var(--amb); padding-left:8px;
  max-width:900px; }
.takeaway { max-width:900px; font-size:15px; } dl.defs { max-width:900px; }
dl.defs dt { font-weight:700; float:left; clear:left; width:160px; }
dl.defs dd { margin-left:170px; }
.card { border:1px solid var(--line); border-radius:6px; padding:4px 14px 2px; margin:10px 0;
  max-width:900px; } .card h3 { margin:8px 0 2px; }
.flag { font-size:11px; border:1px solid currentColor; border-radius:10px; padding:0 6px;
  margin-left:4px; color:var(--muted); font-weight:600; }
.flag.false_allow { color:var(--bad); } .flag.over_escalation { color:var(--amb); }
svg.reliability { color:var(--fg); margin:4px 16px 4px 0; }
ul.reasons { margin:4px 0; }
ol.steps { font-size:15px; line-height:1.9; background:var(--panel); padding:10px 10px 10px 36px;
  border-radius:6px; max-width:1000px; }
.result { font-weight:700; } .result.caught, .result.safe_auto { color:var(--ok); }
.result.false_allow { color:var(--bad); } .result.over_escalation { color:var(--amb); }
.result.not_evaluated { color:var(--muted); }
.v-ALLOW { color:var(--ok); } .v-DENY { color:var(--bad); } .v-ASK { color:var(--amb); }
.v-UNKNOWN, .v-none { color:var(--muted); } .bname { font-size:11px; opacity:.85; }
.m-MATCH, .m-MISMATCH, .m-AMBIGUOUS, .m-unmatched { color:var(--muted); }
.check.deny, .gate.DENY, .outcome.REJECTED, .outcome.TECHNICAL_ERROR { color:var(--bad);
  font-weight:600; }
.check.ask, .gate.ASK { color:var(--amb); font-weight:600; }
.check.pass, .gate.ALLOW, .outcome.ACCEPTED { color:var(--ok); font-weight:600; }
.check.unknown, .outcome.NOT_EXECUTED { color:var(--muted); font-weight:600; }
.pass, .yes, .status.ok { color:var(--ok); font-weight:600; }
.fail, .no, .status.error { color:var(--bad); font-weight:600; }
.status.skipped { color:var(--amb); font-weight:600; }
.conv { display:flex; flex-direction:column; gap:8px; }
.msg { border:1px solid var(--line); border-radius:6px; padding:6px 10px; max-width:1000px; }
.msg.user { background:var(--panel); } .msg.tool { margin-left:32px; }
.msg.error { border-color:var(--bad); } .who { font-weight:600; font-size:12px; }
.call { margin:4px 0; } .call.captured { border-left:4px solid currentColor;
  padding-left:8px; background:var(--hl); }
.call.captured pre, .call.captured code { color:var(--fg); }
details.box { margin:8px 0; } summary { cursor:pointer; }
.filters { display:flex; flex-wrap:wrap; gap:10px; align-items:end; }
.filters label { display:flex; flex-direction:column; font-size:12px; color:var(--muted); }
.filters select { max-width:260px; }
"""

OVERVIEW_JS = r"""
(function () {
  const D = JSON.parse(document.getElementById('data').textContent);
  const VERDICTS = ['ALLOW', 'ASK', 'DENY', 'UNKNOWN', 'none'];
  const NAMES = {ALLOW: 'policy-valid', ASK: 'needs clarification', DENY: 'policy violation',
    UNKNOWN: 'unknown verdict', none: 'no verdict'};
  const F = ['domain', 'model', 'task', 'verdict', 'action', 'arm'];
  const state = {};
  try {
    new URLSearchParams(location.hash.slice(1)).forEach((v, k) => { state[k] = v; });
  } catch (e) {}
  let showAll = false;

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') e.className = v; else e.setAttribute(k, v);
    }
    for (const k of kids.flat()) {
      if (k == null) continue;
      e.append(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return e;
  }
  function link(href, text) { return href ? el('a', {href}, text) : text; }
  function table(headers, rows) {
    return el('table', {}, el('thead', {}, el('tr', {}, headers.map(h => el('th', {}, h)))),
      el('tbody', {}, rows.map(r => el('tr', {}, r.map(c => el('td', {}, c))))));
  }
  function pct(n, d) { return d ? (100 * n / d).toFixed(1) + '%' : '\u2013'; }
  function quantile(xs, q) {
    if (!xs.length) return null;
    const s = xs.slice().sort((a, b) => a - b);
    const i = (s.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return s[lo] + (s[hi] - s[lo]) * (i - lo);
  }
  function ms(x) { return x == null ? '\u2013' : Math.round(x).toLocaleString() + ' ms'; }
  function taskName(i) { const t = D.tasks[i]; return t.d ? t.d + '/' + t.id : t.id; }

  const options = {
    domain: [...new Set([...D.writes.map(w => w.d), ...D.sims.map(s => s.d)])].sort(),
    model: [...new Set([...D.writes.map(w => w.m), ...D.sims.map(s => s.m)])].sort(),
    task: D.tasks.map((t, i) => i).sort((a, b) => taskName(a).localeCompare(taskName(b))),
    verdict: VERDICTS,
    action: [...new Set(D.writes.map(w => w.a))].sort(),
    arm: D.arms,
  };
  if (!state.arm && D.arms.length) state.arm = D.arms.includes('E') ? 'E' : D.arms[0];
  const box = document.getElementById('filters');
  for (const f of F) {
    if (f === 'arm' && !D.arms.length) continue;
    const all = el('option', {value: ''}, f === 'arm' ? '(none)' : '(all)');
    const sel = el('select', {id: 'f-' + f}, all,
      options[f].map(v => el('option', {value: String(v)},
        f === 'task' ? taskName(v) : f === 'arm' ? (D.armNames[v] || v) : v)));
    sel.value = state[f] || '';
    sel.addEventListener('change', () => { state[f] = sel.value; showAll = false; render(); });
    box.append(el('label', {}, f === 'arm' ? 'decision strategy' : f, sel));
  }
  // Links such as "#action=refuel_data" (the by-action-type table) filter the tables here.
  window.addEventListener('hashchange', () => {
    const next = {};
    try {
      new URLSearchParams(location.hash.slice(1)).forEach((v, k) => { next[k] = v; });
    } catch (e) { return; }
    for (const f of F) {
      if (f === 'arm') continue;
      state[f] = next[f] || '';
      const sel = document.getElementById('f-' + f);
      if (sel) sel.value = state[f];
    }
    showAll = false;
    render();
    document.getElementById('explore').scrollIntoView();
  });

  function simOk(s) {
    return (!state.domain || s.d === state.domain) && (!state.model || s.m === state.model)
      && (!state.task || String(s.t) === state.task);
  }
  function writeOk(w) {
    return (!state.domain || w.d === state.domain) && (!state.model || w.m === state.model)
      && (!state.task || String(w.t) === state.task) && (!state.verdict || w.v === state.verdict)
      && (!state.action || w.a === state.action);
  }

  function render() {
    const h = new URLSearchParams(Object.entries(state).filter(([, v]) => v)).toString();
    try { history.replaceState(null, '', h ? '#' + h : location.pathname); } catch (e) {}
    const sims = D.sims.filter(simOk), writes = D.writes.filter(writeOk);
    const arm = state.arm || '';
    const gate = w => (arm && w.g[arm]) || null;
    const result = w => {
      const d = gate(w);
      if (d == null) return '\u2013';
      const stop = d !== 'ALLOW';
      if (w.v === 'ASK' || w.v === 'DENY') return stop ? 'Caught' : 'False allow';
      if (w.v === 'ALLOW') return stop ? 'Over-escalation' : 'Safe auto-allow';
      return 'Not evaluated (runtime ASK)';
    };

    const groups = new Map();
    const group = (d, m, src) => {
      const k = JSON.stringify([d, m, src]);
      if (!groups.has(k)) groups.set(k, {d, m, src, sims: 0, pass: 0, rewarded: 0, writes: 0,
        verdicts: Object.fromEntries(VERDICTS.map(v => [v, 0]))});
      return groups.get(k);
    };
    for (const s of sims) {
      const g = group(s.d, s.m, s.src);
      g.sims++; if (s.rewarded) g.rewarded++; if (s.pass) g.pass++;
    }
    for (const w of writes) { const g = group(w.d, w.m, w.src); g.writes++; g.verdicts[w.v]++; }
    const grows = [...groups.values()].sort((a, b) =>
      (a.d + a.m + a.src).localeCompare(b.d + b.m + b.src));
    document.getElementById('groups').replaceChildren(table(
      ['domain', 'agent model', 'results file', 'simulations',
       'final task outcome pass rate', 'proposed writes',
       ...VERDICTS.map(v => v + ' (' + NAMES[v] + ')')],
      grows.map(g => [g.d || '\u2013', g.m || '\u2013', g.src || '(store only)', g.sims,
        g.rewarded ? pct(g.pass, g.rewarded) + ' (' + g.pass + '/' + g.rewarded + ')' : '\u2013',
        g.writes, ...VERDICTS.map(v => g.verdicts[v])])));

    const scored = writes.filter(w => w.k >= 0);
    const keys = [...new Set(scored.map(w => w.k))];
    document.getElementById('judges').replaceChildren(D.judges.length ? table(
      ['judge', 'model', 'writes with a rubric', 'ok', 'error', 'skipped', 'not scored',
       'score rows', 'total cost', 'p50 first-attempt latency', 'p95 first-attempt latency'],
      D.judges.map((j, ji) => {
        const c = {ok: 0, error: 0, skipped: 0, none: 0};
        for (const w of scored) { const s = D.scoreKeys[w.k][ji]; c[s ? s[0] : 'none']++; }
        let cost = 0, rows = 0; const lat = [];
        for (const k of keys) {
          const s = D.scoreKeys[k][ji];
          if (!s || s[0] === 'skipped') continue;
          rows++; cost += s[1] || 0; if (s[2] != null) lat.push(s[2]);
        }
        const n = scored.length;
        return [j.name, j.model, n, c.ok + ' (' + pct(c.ok, n) + ')',
          c.error + ' (' + pct(c.error, n) + ')',
          D.hasSkips ? c.skipped + ' (' + pct(c.skipped, n) + ')' : 'n/a',
          c.none + ' (' + pct(c.none, n) + ')', rows, '$' + cost.toFixed(4),
          ms(quantile(lat, 0.5)), ms(quantile(lat, 0.95))];
      })) : el('p', {class: 'muted'}, 'No scores in the store yet.'));

    const tasks = new Map();
    const task = i => {
      if (!tasks.has(i)) tasks.set(i, {i, sims: 0, pass: 0, writes: 0, deny: 0, ask: 0});
      return tasks.get(i);
    };
    for (const s of sims) { const t = task(s.t); t.sims++; if (s.pass) t.pass++; }
    for (const w of writes) {
      const t = task(w.t); t.writes++;
      if (w.v === 'DENY') t.deny++; if (w.v === 'ASK') t.ask++;
    }
    const trows = [...tasks.values()].sort((a, b) => (b.deny + b.ask) - (a.deny + a.ask)
      || (a.pass / (a.sims || 1)) - (b.pass / (b.sims || 1)));
    document.getElementById('tasks').replaceChildren(table(
      ['task', 'simulations', 'final task outcome pass', 'proposed writes', 'policy violations',
       'needing clarification'],
      trows.map(t => [link(D.tasks[t.i].href, taskName(t.i)), t.sims, t.pass + ' (' +
        pct(t.pass, t.sims) + ')', t.writes, t.deny, t.ask])));

    const limit = showAll ? writes.length : Math.min(writes.length, 500);
    const wrows = writes.slice(0, limit).map(w => {
      const js = w.k < 0 ? 'no rubric'
        : D.scoreKeys[w.k].map(s => s ? s[0] : '\u2013').join(' / ');
      return [link(w.href, w.id), taskName(w.t), w.m, w.tr == null ? '\u2013' : w.tr,
        w.sim ? link(w.sim + '#w-' + w.id, 'seq ' + w.seq) : 'seq ' + w.seq, w.a,
        el('span', {class: 'badge v-' + w.v, title: NAMES[w.v]}, w.v),
        gate(w) || '\u2013', result(w), w.o || '\u2013', w.bm || '\u2013', js];
    });
    const parts = [el('p', {class: 'muted'}, 'Showing ' + limit + ' of ' + writes.length +
      ' writes. Judge columns: ' + (D.judges.map(j => j.name).join(' / ') || 'none') + '.'),
      table(['write', 'task', 'agent model', 'trial', 'in conversation', 'action',
        'policy verdict', 'gate decision' + (arm ? ' (' + (D.armNames[arm] || arm) + ')' : ''),
        'result',
        'backend (shadow)', 'τ² trace comparison', 'judges'], wrows)];
    if (limit < writes.length) {
      const b = el('button', {}, 'Show all ' + writes.length);
      b.addEventListener('click', () => { showAll = true; render(); });
      parts.push(b);
    }
    document.getElementById('writes').replaceChildren(...parts);
  }
  render();
})();
"""


# --- Build -----------------------------------------------------------------------------------


def write_report(
    bench: Bench, out: str | Path, *, spread_threshold: float = SCORE_SPREAD_THRESHOLD
) -> Path:
    """Write the report into `out` and return the path of its index page."""
    out = Path(out)
    for sub in ("w", "s", "t"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "report.css").write_text(CSS, encoding="utf-8")
    for w in bench.writes:
        (out / write_href(w.write_id)).write_text(write_page(bench, w), encoding="utf-8")
    for sim in bench.simulations.values():
        (out / sim_href(sim.id)).write_text(sim_page(bench, sim), encoding="utf-8")
    sims_by_task: dict[TaskKey, list[Simulation]] = {}
    for sim in bench.simulations.values():
        sims_by_task.setdefault(sim.task_key, []).append(sim)
    writes_by_task: dict[TaskKey, list[Write]] = {}
    for w in bench.writes:
        writes_by_task.setdefault(w.task_key, []).append(w)
    for key in {*sims_by_task, *writes_by_task}:
        (out / task_href(key)).write_text(
            task_page(bench, key, sims_by_task.get(key, []), writes_by_task.get(key, [])),
            encoding="utf-8",
        )
    (out / "review.html").write_text(review_page(bench), encoding="utf-8")
    index = out / "index.html"
    index.write_text(index_page(bench, spread_threshold), encoding="utf-8")
    return index
