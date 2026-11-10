"""Cross-domain transfer evaluation (the `transfer` section of replay's metrics.json).

Does what the learner fits on one domain (e.g. retail) carry over to another (telecom)? The
rubric questions are shared across domains, so the learner's features are domain-agnostic.

For each ordered pair of domains (source -> target):

Labels are effective policy verdicts (`replay`): ALLOW writes may execute, ASK and DENY writes
require an intervention, UNKNOWN writes are left out.

- **Zero-shot** (arms E and F): fit on every source write with a verdict, evaluate on the target's
  test writes (common support). Per-action thresholds do not exist for the target's actions, so
  only the global threshold is used. Reported next to the same arm fit in-domain on the
  target's training writes (per-action and global thresholds, as in the main replay).
- **Few-shot curve** (arm E, the judge selected by the main replay): add k = 0, 10, 25, 50, 100,
  200 target labels, drawn from the target's training writes with several seeded resamples per
  k. *Transfer* fits on the k target labels pooled with the source labels, the source acting as
  a prior: each source write is weighted so that all of them together count as
  `PRIOR_LABELS` (100) labels, or less if there are fewer (the learner's IPS weights carry
  this). *Scratch* fits on the k target labels alone; with no labels, or a single label class,
  it cannot rank writes and asks for everything.

The curve's headline number is the target test ask rate at 95% intervention-required recall
with the threshold placed on the target test set itself: it compares how well each model ranks
the target's writes, without the noise of fitting a threshold on 10 labels. Ask rates and
recall with thresholds fit on the training labels (as an operator would deploy them) are
reported alongside. Each is the mean over resamples, with standard deviation, minimum and
maximum.

A direction without verdicts on both sides (or without intervention-required target test
writes) is reported as "insufficient data".
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from hatchway.bench.learner import ece, fit_threshold
from hatchway.bench.replay import (
    INTERVENE,
    LABELED,
    TWO_JUDGES,
    Row,
    evaluate,
    fit_arm,
)

FEW_SHOT_K = (0, 10, 25, 50, 100, 200)
RESAMPLES = 5
PRIOR_LABELS = 100.0
METHOD = (
    "pooled fit: source labels weighted to count as PRIOR_LABELS target labels in total, "
    "plus the k target labels at weight 1"
)


def ask_at_catch(scores: Sequence[float], rows: Sequence[Row], target: float) -> float | None:
    """Ask rate over `rows` with the threshold placed on these rows to catch `target` of the
    intervention-required ones. None without such rows."""
    labeled = [i for i, r in enumerate(rows) if r.verdict in LABELED]
    t = fit_threshold(
        [scores[i] for i in labeled],
        [rows[i].ok for i in labeled],
        [1.0] * len(labeled),
        target,
    )
    if t is None:
        return None
    return sum(s < t for s in scores) / len(scores)


def _spread(values: Sequence[float | None]) -> dict[str, float | None]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
    mean = math.fsum(vals) / len(vals)
    std = math.sqrt(math.fsum((v - mean) ** 2 for v in vals) / len(vals))
    return {"mean": mean, "std": std, "min": min(vals), "max": max(vals), "n": len(vals)}


def _score(
    arm: str,
    judges: tuple[str, ...],
    rows: Sequence[Row],
    evaluation: Sequence[Row],
    model_ids: Mapping[str, str],
    seed: int,
    target: float,
    *,
    global_only: bool,
) -> dict[str, Any]:
    fit = fit_arm(arm, judges, rows, seed, target)
    out: dict[str, Any] = {"status": fit.reason or "ok", "train_labels": len(fit.examples)}
    if fit.model is None:
        return out
    frozen = fit.freeze(target, model_ids)
    if global_only:
        frozen.action_thresholds = {}
    m = evaluate(frozen, evaluation, end_to_end=False)["overall"]
    labeled = [r for r in evaluation if r.verdict in LABELED]
    p = [frozen.p_ok(r.action, r.vectors) for r in labeled]
    out.update(
        intervention_required_recall=m["intervention_required_recall"],
        safe_auto_rate=m["safe_auto_rate"],
        ask_rate=m["ask_rate"],
        ece=ece(p, [r.ok for r in labeled]),
        global_threshold=frozen.global_threshold,
    )
    return out


def _few_shot(
    judge: str,
    source: Sequence[Row],
    pool: Sequence[Row],
    evaluation: Sequence[Row],
    model_ids: Mapping[str, str],
    *,
    direction: str,
    seed: int,
    target: float,
    ks: Sequence[int],
    resamples: int,
    prior_labels: float,
) -> dict[str, Any]:
    src = [r for r in source if r.verdict in LABELED and judge in r.vectors]
    pool = [r for r in pool if r.verdict in LABELED and judge in r.vectors]
    weight = min(1.0, prior_labels / len(src)) if src else 0.0
    prior = [replace(r, weight=r.weight * weight) for r in src]
    result: dict[str, Any] = {
        "status": "ok",
        "judge": judge,
        "k": list(ks),
        "source_weight": weight,
    }
    for name in ("transfer", "scratch"):
        result[name] = {"ask_at_target": [], "fitted_recall": [], "fitted_ask_rate": []}
    for k in ks:
        runs: dict[str, dict[str, list[float | None]]] = {
            n: {"ask": [], "catch": [], "fitted_ask": []} for n in ("transfer", "scratch")
        }
        if k <= len(pool):
            for r in range(1 if k in (0, len(pool)) else resamples):
                sample = random.Random(f"{seed}:{direction}:{k}:{r}").sample(list(pool), k)
                for name, rows in (("transfer", prior + sample), ("scratch", sample)):
                    fit = fit_arm("E", (judge,), rows, seed, target)
                    if fit.model is None:  # no labels: nothing to rank with, ask everything
                        runs[name]["ask"].append(1.0)
                        runs[name]["catch"].append(1.0)
                        runs[name]["fitted_ask"].append(1.0)
                        continue
                    frozen = fit.freeze(target, model_ids)
                    scores = [frozen.p_ok(x.action, x.vectors) for x in evaluation]
                    runs[name]["ask"].append(ask_at_catch(scores, evaluation, target))
                    m = evaluate(frozen, evaluation, end_to_end=False)["overall"]
                    runs[name]["catch"].append(m["intervention_required_recall"])
                    runs[name]["fitted_ask"].append(m["ask_rate"])
        for name, run in runs.items():
            result[name]["ask_at_target"].append(_spread(run["ask"]))
            result[name]["fitted_recall"].append(_spread(run["catch"]))
            result[name]["fitted_ask_rate"].append(_spread(run["fitted_ask"]))
    return result


def transfer_eval(
    train: Sequence[Row],
    test: Sequence[Row],
    test_common: Sequence[Row],
    model_ids: Mapping[str, str],
    *,
    seed: int,
    target: float,
    e_judge: str | None,
    ks: Sequence[int] = FEW_SHOT_K,
    resamples: int = RESAMPLES,
    prior_labels: float = PRIOR_LABELS,
) -> dict[str, Any]:
    domains = sorted({r.domain for r in [*train, *test] if r.domain and r.verdict in LABELED})
    out: dict[str, Any] = {
        "method": METHOD,
        "prior_labels": prior_labels,
        "resamples": resamples,
        "k": list(ks),
        "set": "common_support",
        "domains": domains,
        "directions": {},
    }
    if len(domains) < 2:
        out["status"] = "insufficient data: needs writes with verdicts from two domains"
        return out
    out["status"] = "ok"
    arms: dict[str, tuple[str, ...]] = {}
    if e_judge is not None:
        arms["E"] = (e_judge,)
    if all(j in model_ids for j in TWO_JUDGES):
        arms["F"] = TWO_JUDGES
    for src in domains:
        for tgt in domains:
            if src == tgt:
                continue
            direction = f"{src}->{tgt}"
            source = [r for r in [*train, *test] if r.domain == src]
            pool = [r for r in train if r.domain == tgt]
            evaluation = [r for r in test_common if r.domain == tgt]
            entry: dict[str, Any] = {
                "source_labels": sum(r.verdict in LABELED for r in source),
                "target_train_labels": sum(r.verdict in LABELED for r in pool),
                "target_test_writes": len(evaluation),
                "target_test_intervention_required": sum(
                    r.verdict in INTERVENE for r in evaluation
                ),
            }
            if not entry["target_test_intervention_required"] or not entry["source_labels"]:
                entry["status"] = (
                    "insufficient data: needs source verdicts and intervention-required target "
                    "test writes"
                )
                out["directions"][direction] = entry
                continue
            entry["status"] = "ok"
            entry["zero_shot"] = {
                arm: {
                    "in_domain": _score(
                        arm, js, pool, evaluation, model_ids, seed, target, global_only=False
                    ),
                    "zero_shot": _score(
                        arm, js, source, evaluation, model_ids, seed, target, global_only=True
                    ),
                }
                for arm, js in arms.items()
            }
            if e_judge is None:
                entry["few_shot"] = {"status": "insufficient data: arm E could not be fit"}
            else:
                entry["few_shot"] = _few_shot(
                    e_judge,
                    source,
                    pool,
                    evaluation,
                    model_ids,
                    direction=direction,
                    seed=seed,
                    target=target,
                    ks=ks,
                    resamples=resamples,
                    prior_labels=prior_labels,
                )
            out["directions"][direction] = entry
    return out


# Categorical slots 1-2 of the dataviz reference palette: one color per direction; transfer is
# solid, scratch dashed.
_DIRECTION_COLORS = ("#2a78d6", "#eb6834")


def plot_transfer(transfer: Mapping[str, Any], path: Path) -> None:
    from hatchway.bench.replay import _axes, _finish

    title = "Few-shot transfer: ask rate at 95% catch (target test)"
    fig, ax = _axes(title, "target-domain labels", "ask rate")
    plotted = False
    directions = [
        (d, e)
        for d, e in transfer.get("directions", {}).items()
        if e.get("few_shot", {}).get("status") == "ok"
    ]
    for (direction, entry), color in zip(directions, _DIRECTION_COLORS * 4, strict=False):
        fs = entry["few_shot"]
        for name, style in (("transfer", "-"), ("scratch", "--")):
            pts = [
                (k, s["mean"], s["std"])
                for k, s in zip(fs["k"], fs[name]["ask_at_target"], strict=True)
                if s["mean"] is not None
            ]
            if not pts:
                continue
            ks, means, stds = zip(*pts, strict=True)
            label = f"{direction} {'with' if name == 'transfer' else 'without'} prior"
            ax.errorbar(ks, means, yerr=stds, color=color, linestyle="none", capsize=3)
            ax.plot(
                ks,
                means,
                color=color,
                linestyle=style,
                linewidth=2,
                marker="o",
                markersize=5,
                label=label,
            )
            plotted = True
    ax.set_ylim(0, 1.02)
    _finish(fig, ax, path, plotted)
