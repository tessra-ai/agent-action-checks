"""Run on the Mac after a fold finishes: prints one compact JSON block to paste back into the chat.

    python3 extract.py rely1-kev-f0

Reads runs/<name>/ as `modal run kev_modal.py::train` downloaded it. Prints only IDs and
probabilities at each checkpoint's fitted temperature, development and calibration (no
conversation text), the fitted temperatures, timing and the training log's
progress lines. Standard library only.
"""

import json
import math
import re
import sys
from pathlib import Path


def p_true(r: dict, temperature: float) -> float:
    """P(true) at the checkpoint's fitted temperature, as kev.metrics.probabilities_at_temperature
    computes it: rows.json holds the raw (T=1) probabilities and logits."""
    keys = r["keys"]
    if temperature == 1:
        return r["p"][keys.index("true")]
    z = r.get("logits") or [math.log(max(x, 1e-12)) for x in r["p"]]
    top = max(z)
    e = [math.exp((v - top) / temperature) for v in z]
    return e[keys.index("true")] / sum(e)


def rows(path: Path, temperature: float) -> list:
    return [
        [r["id"], r["question"], round(p_true(r, temperature), 5)]
        for r in json.loads(path.read_text())
    ]


def main() -> None:
    name = sys.argv[1]
    d = Path("runs") / name
    res = json.loads((d / "result.json").read_text())
    log = (d / "train.log").read_text() if (d / "train.log").exists() else ""
    keep = [x for x in log.splitlines() if re.match(r"(ep\d|replay|dropped|delta|device)", x)]
    out = {
        "name": name,
        "gpu": res.get("gpu"),
        "wall_seconds": res.get("wall_seconds"),
        "temperature": res.get("temperature"),
        "baseline_temperature": (res.get("baseline") or {})
        .get("development", {})
        .get("temperature"),
        "data": {
            k: [v.get("records"), v.get("over_limit")] for k, v in (res.get("data") or {}).items()
        },
        "regression": res.get("regression"),
        "train_log": keep[:3] + keep[-4:],
        "rows": rows(d / "development/rows.json", res["temperature"]),
        "calibration_rows": rows(d / "calibration/rows.json", res["temperature"]),
    }
    base = res.get("baseline")
    if base:
        bt = base["development"]["temperature"]
        out["baseline_rows"] = rows(d / "baseline/development/rows.json", bt)
        out["baseline_calibration_rows"] = rows(d / "baseline/calibration/rows.json", bt)
    text = json.dumps(out, separators=(",", ":"))
    (d / "paste_me.json").write_text(text)
    print(text)
    print(f"\n({len(text):,} characters; also saved to {d / 'paste_me.json'})", file=sys.stderr)


if __name__ == "__main__":
    main()
