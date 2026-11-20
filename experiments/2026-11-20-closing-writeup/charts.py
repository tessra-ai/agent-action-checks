"""The closing post's charts, drawn from numbers.json only.

    <python with matplotlib> experiments/2026-11-20-closing-writeup/charts.py   # -> charts/*.png

Static PNGs for the blog (light surface, 2x resolution). Palette: the dataviz skill's reference
categorical slots 1-3 (blue, orange, aqua), validated with its script for all pairs in light mode;
aqua is below 3:1 contrast on the surface, so every mark carries a visible text label. Text is in
text colours, never series colours. Every number drawn or printed comes from numbers.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "charts"
SURFACE, TEXT, TEXT2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#a9a8a3"
# texture per category, so the segments are told apart without colour (CVD, print)
HATCH = {"contradiction_in_agreed": "//", "no_agreement_only": "", "both": "xx", "neither": ".."}

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "text.color": TEXT,
        "axes.labelcolor": TEXT2,
        "axes.edgecolor": GRID,
        "xtick.color": TEXT2,
        "ytick.color": TEXT2,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    }
)


def frame(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0)


def save(fig, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def chart_bad_actions(N: dict) -> None:
    """The 91 bad actions by what the two questions (labellers' consensus) say, split by whether
    the backend executed the action or rejected it anyway."""
    cb = N["coverage_bad_by_backend"]
    cats = [
        ("contradiction_in_agreed", "Statement flagged; agreed", ORANGE),
        ("no_agreement_only", "Not agreed; no statement flagged", BLUE),
        ("both", "Statement flagged; not agreed or split", AQUA),
        ("neither", "Nothing flagged", GREY),
    ]
    rows = [("ACCEPTED", "Executed"), ("REJECTED", "Rejected by the backend anyway")]
    fig, ax = plt.subplots(figsize=(8, 2.6))
    for y, (be, _label) in enumerate(rows):
        left = 0
        for key, _name, col in cats:
            v = cb[be].get(key, 0) + (
                cb[be].get("contradiction_agreement_split", 0) if key == "both" else 0
            )
            if v:
                ax.barh(
                    y,
                    v - 0.3,
                    left=left + 0.15,
                    color=col,
                    height=0.55,
                    hatch=HATCH[key],
                    edgecolor=SURFACE,
                    linewidth=0,
                )
                narrow = v <= 2  # too thin for its label: put the count just above the bar
                ax.text(
                    left + v / 2,
                    y - 0.36 if narrow else y,
                    str(v),
                    ha="center",
                    va="center",
                    # 14pt bold is WCAG large text (3:1): white on blue 4.3:1, dark elsewhere >= 6
                    color=SURFACE if col == BLUE and not narrow else TEXT,
                    fontsize=11 if narrow else 14,
                    fontweight="bold",
                )
            left += v
        ax.text(left + 0.8, y, f"{cb[be]['n']} actions", va="center", color=TEXT2, fontsize=9)
    ax.set_yticks(range(len(rows)), [r[1] for r in rows])
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_xlim(0, max(cb[b]["n"] for b, _ in rows) + 9)
    frame(ax)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=c, hatch=HATCH[k], edgecolor=SURFACE, linewidth=0)
        for k, _, c in cats
    ]
    ax.legend(
        handles,
        [n for _, n, _ in cats],
        loc="upper center",
        bbox_to_anchor=(0.45, -0.08),
        ncol=4,
        frameon=False,
        fontsize=8.5,
    )
    ax.set_title(
        f"The {N['data']['bad']} bad actions: what the labellers' consensus flags",
        loc="left",
        fontsize=11,
        color=TEXT,
        pad=16,
    )
    save(fig, "bad_actions_by_question")


def chart_tradeoff(N: dict) -> None:
    """Bad caught against good stopped (out-of-fold cut-offs): Jev alone along its trade-off,
    the labellers' consensus, the cascade, and the three designs with rules."""
    nb, ng = N["data"]["bad"], N["data"]["good"]
    fig, ax = plt.subplots(figsize=(8, 5))
    tr = N["jev_tradeoff"]
    keys = ["cap_2pct", "cap_5pct", "cap_10pct", "cap_20pct"]
    xs = [tr[k]["good_stopped"]["count"] for k in keys]
    ys = [tr[k]["bad_caught"]["count"] for k in keys]
    ax.plot(
        xs,
        ys,
        color=BLUE,
        lw=2,
        marker="o",
        ms=7,
        zorder=3,
        label="Jev alone (cut-offs chosen on the other folds, at most 2/5/10/20% of good stopped)",
    )
    for k, x, y in zip(keys, xs, ys, strict=True):
        ax.annotate(
            f"{k.split('_')[1].replace('pct', '%')} selection cap",
            (x, y),
            xytext=(6, -12),
            textcoords="offset points",
            color=TEXT2,
            fontsize=8,
        )
    pts = [
        (
            "Labellers' consensus alone",
            N["consensus_gate"]["good_stopped"]["count"],
            N["consensus_gate"]["bad_caught"]["count"],
            ORANGE,
            "s",
        ),
        (
            "Cascade (Jev, consensus when unsure)",
            N["cascade"]["selection cap 5%, width 0.2"]["good_stopped"]["count"],
            N["cascade"]["selection cap 5%, width 0.2"]["bad_caught"]["count"],
            ORANGE,
            "D",
        ),
        (
            "A: rules, then the cascade",
            N["designs"]["A: rules -> cascade (width 0.2)"]["good_stopped"]["count"],
            N["designs"]["A: rules -> cascade (width 0.2)"]["bad_caught"]["count"],
            AQUA,
            "o",
        ),
        (
            "B: rules, Jev, then the rubric judge (run 1)",
            N["designs"]["B: rules -> Jev (5% cap) -> judge run 1"]["good_stopped"]["count"],
            N["designs"]["B: rules -> Jev (5% cap) -> judge run 1"]["bad_caught"]["count"],
            AQUA,
            "^",
        ),
        (
            "C: rules, the cascade, then the rubric judge (run 1)",
            N["designs"]["C: rules -> cascade (width 0.2) -> judge run 1"]["good_stopped"]["count"],
            N["designs"]["C: rules -> cascade (width 0.2) -> judge run 1"]["bad_caught"]["count"],
            AQUA,
            "v",
        ),
        (
            "Rules alone (airline only)",
            N["designs"]["rules alone"]["good_stopped"]["count"],
            N["designs"]["rules alone"]["bad_caught"]["count"],
            GREY,
            "P",
        ),
    ]
    for name, x, y, col, m in pts:
        ax.scatter(
            [x],
            [y],
            color=col,
            marker=m,
            s=70,
            zorder=4,
            edgecolors=SURFACE,
            linewidths=2,
            label=name,
        )
        below = name.startswith("B:")  # B sits next to C: put its label underneath
        ax.annotate(
            f"{y} / {x}",
            (x, y),
            xytext=(7, -13) if below else (7, 4),
            textcoords="offset points",
            color=TEXT,
            fontsize=8,
        )
    ax.set_xlabel(f"Good actions stopped (of {ng})")
    ax.set_ylabel(f"Bad actions caught (of {nb})")
    ax.set_xlim(-0.5, max(xs + [p[1] for p in pts]) + 3)
    ax.set_ylim(0, nb + 2)
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    frame(ax)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.13), frameon=False, fontsize=8, ncol=2)
    ax.set_title(
        "Bad caught / good stopped, cut-offs chosen out of fold",
        loc="left",
        fontsize=11,
        color=TEXT,
    )
    save(fig, "tradeoff")


def chart_executed(N: dict) -> None:
    """Each design's catches on the bad actions that actually executed (the backend rejected the
    rest anyway)."""
    cb = N["cut_b_backend_rejected"]
    d = cb["designs_on_executed_bad"]
    rows = [
        ("Labellers' consensus alone", cb["consensus_on_executed_bad"], ORANGE),
        ("A: rules, then the cascade", d["A: rules -> cascade (width 0.2)"], AQUA),
        ("B: rules, Jev, rubric judge (run 1)", d["B: rules -> Jev (5% cap) -> judge run 1"], AQUA),
        (
            "C: rules, cascade, rubric judge (run 1)",
            d["C: rules -> cascade (width 0.2) -> judge run 1"],
            AQUA,
        ),
    ]
    n = cb["executed_bad"]
    fig, ax = plt.subplots(figsize=(8, 2.8))
    for y, (_name, v, col) in enumerate(rows):
        ax.barh(y, n, color=GRID, height=0.5)
        ax.barh(y, v["count"], color=col, height=0.5)
        ax.text(
            v["count"] + 0.6 if v["count"] < n - 4 else v["count"] - 0.6,
            y,
            f"{v['count']} of {n}",
            va="center",
            ha="left" if v["count"] < n - 4 else "right",
            color=TEXT,
            fontsize=9,
        )
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, n)
    ax.set_xticks([])
    frame(ax)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.set_title(
        f"Catches on the {n} bad actions that actually executed",
        loc="left",
        fontsize=11,
        color=TEXT,
    )
    save(fig, "executed_only")


def chart_finetune(N: dict) -> None:
    """Statement and agreement AUC: stock Kev-4B, the fine-tuned Kev-4B (out of fold) and stock
    Jev, against the labellers' consensus. Names sit under the bars in text colour."""
    st, kp = N["stock"], N["kev_pilot"]
    groups = [
        (
            "Statements: false and material?",
            [
                ("Stock\nKev-4B", st["kev4b_statement_auc"], GREY),
                ("Fine-tuned\nKev-4B", kp["statement_auc"], ORANGE),
                ("Stock\nJev", st["jev_statement_auc"], BLUE),
            ],
        ),
        (
            "Agreement: did the customer agree?",
            [
                ("Fine-tuned\nKev-4B", kp["agreement_auc"], ORANGE),
                ("Stock\nJev", st["jev_agreement_auc"], BLUE),
            ],
        ),
    ]
    fig, ax = plt.subplots(figsize=(8, 3.9))
    x, pos, names, centres = 0.0, [], [], []
    for gname, bars in groups:
        start = x
        for name, v, col in bars:
            ax.bar(x, v, color=col, width=0.75)
            ax.text(x, v + 0.015, f"{v:.2f}", ha="center", va="bottom", color=TEXT, fontsize=9)
            pos.append(x)
            names.append(name)
            x += 1
        centres.append(((start + x - 1) / 2, gname))
        x += 0.8
    ax.axhline(0.5, color=TEXT2, lw=1, ls=(0, (3, 3)))
    ax.text(x - 0.9, 0.51, "chance", color=TEXT2, fontsize=8, ha="right", va="bottom")
    ax.set_xticks(pos, names, fontsize=8.5)
    for cx, gname in centres:
        ax.text(
            cx,
            -0.2,
            gname,
            ha="center",
            va="top",
            color=TEXT,
            fontsize=9.5,
            transform=ax.get_xaxis_transform(),
        )
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("AUC against the labellers' consensus")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    frame(ax)
    ax.set_title(
        "The fine-tune moved Kev-4B a long way, and stayed below stock Jev",
        loc="left",
        fontsize=11,
        color=TEXT,
    )
    save(fig, "finetune")


def main() -> None:
    N = json.loads((HERE / "numbers.json").read_text())
    chart_bad_actions(N)
    chart_tradeoff(N)
    chart_executed(N)
    chart_finetune(N)
    print("charts ->", OUT)


if __name__ == "__main__":
    main()
