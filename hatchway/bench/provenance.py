"""Where a benchmark result came from: the code commit that produced it."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_commit() -> str | None:
    """The commit of the checkout this package runs from, or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def git_tree_clean() -> bool | None:
    """True when the checkout has no uncommitted changes to tracked or untracked (not ignored)
    files; None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() == ""


def tau2_commit() -> str | None:
    """The commit of the installed τ² checkout, or None if τ² is missing or not a checkout."""
    try:
        import tau2
    except ImportError:
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(tau2.__file__).parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None
