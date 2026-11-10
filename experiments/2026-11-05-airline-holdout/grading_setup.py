"""Build the blind grading folder, the batches and the grader prompts (no model calls).

    python experiments/2026-11-05-airline-holdout/grading_setup.py <blind dir> <passes>

After `gate.py`. Copies `grading/cases/*.json` and the policy into `<blind dir>` (a folder
outside the repository that holds nothing else), and writes `grading/batches.json` and
`grading/prompts.json`: pass 1 covers every case; passes 2 and 3 cover the union cases again
(the key says which cases get 3 readings), each pass shuffled with the experiment seed, in
batches of 6. The prompt is the first capture's `grading/PROMPT.md`, unchanged, with the
placeholders filled. Graders never see the key. The outputs go to `<blind dir>/out/<batch>.jsonl`
and are copied to `grading/out/` for `analyze.py grades`.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
PROMPT = HERE.parent / "2026-10-28-airline-veto/grading/PROMPT.md"
BATCH = 6


def main(blind: Path, passes: int) -> None:
    key = json.loads((HERE / "grading/key.json").read_text())
    seed = key["seed"]
    cases_dir = blind / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    (blind / "out").mkdir(exist_ok=True)
    for f in (HERE / "grading/cases").glob("*.json"):
        shutil.copy(f, cases_dir / f.name)
    shutil.copy(HERE / "grading/policy.md", blind / "policy.md")
    template = PROMPT.read_text().split("---\n", 1)[1].strip()
    batches, prompts = [], {}
    for p in range(1, passes + 1):
        ids = [c["case"] for c in key["cases"] if p == 1 or c["readings"] >= p]
        rng = random.Random(seed + p)
        rng.shuffle(ids)
        for n in range(0, len(ids), BATCH):
            bid = f"p{p}-b{n // BATCH + 1:02d}"
            chunk = ids[n : n + BATCH]
            batches.append({"id": bid, "cases": chunk})
            prompts[bid] = (
                template.replace("{POLICY}", str(blind / "policy.md"))
                .replace("{CASES}", ", ".join(f"`{cases_dir / (c + '.json')}`" for c in chunk))
                .replace("{OUT}", str(blind / "out" / f"{bid}.jsonl"))
            )
    (HERE / "grading/batches.json").write_text(json.dumps(batches, indent=1) + "\n")
    (HERE / "grading/prompts.json").write_text(json.dumps(prompts, indent=1) + "\n")
    print(f"{len(batches)} batches, {sum(len(b['cases']) for b in batches)} readings")


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 3)
