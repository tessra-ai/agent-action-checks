from pathlib import Path

from hatchway.bench.tau2 import TAU2_COMMIT

ROOT = Path(__file__).parent.parent


def test_tau2_commit_is_pinned_consistently() -> None:
    assert len(TAU2_COMMIT) == 40
    for name in ("pyproject.toml", ".github/workflows/ci.yml", "SPEC.md", "MILESTONES.md"):
        assert TAU2_COMMIT in (ROOT / name).read_text(encoding="utf-8"), name
