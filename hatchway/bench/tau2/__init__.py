"""τ²-bench capture harness, policy oracle and trace matcher.

`harness` needs the `tau2` package installed at `TAU2_COMMIT` (the `tau2` extra) and the task
data from the same commit (`TAU2_DATA_DIR`, or an editable install of a checkout). `verdicts`
(the policy oracle) never imports `tau2`; `label` (the τ² trace match) runs without it once
ground truth is loaded.
"""

from pathlib import Path

TAU2_REPO = "https://github.com/sierra-research/tau2-bench"
# The last τ²-bench commit that supports Python 3.10/3.11; the next commit (01e812d, τ³-bench
# 1.0.0) requires Python 3.12. Task data for the `base` split matches the published benchmark.
TAU2_COMMIT = "c5b2d228d850c59b749b93cf32c4745d3aa53967"

DEFAULT_POLICY = Path(__file__).with_name("hatchway.yaml")

__all__ = ["DEFAULT_POLICY", "TAU2_COMMIT", "TAU2_REPO"]
