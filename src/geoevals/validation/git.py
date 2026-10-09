"""Ask git whether a path is tracked, gitignored, or outside any working tree."""

import subprocess
from enum import Enum
from pathlib import Path


class GitPathState(Enum):
    OUTSIDE = "outside"
    """Not inside a git working tree, or git is not available."""
    TRACKED = "tracked"
    IGNORED = "ignored"
    UNIGNORED = "unignored"
    """Inside the working tree, not tracked, and not matched by any ignore rule."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )


def git_path_state(path: Path) -> GitPathState:
    """Classify ``path``, which need not exist yet, against the git working tree that holds it."""
    path = path.resolve()
    start = path.parent
    while not start.is_dir():
        start = start.parent
    try:
        toplevel = _git(start, "rev-parse", "--show-toplevel")
    except FileNotFoundError:  # git is not installed
        return GitPathState.OUTSIDE
    if toplevel.returncode != 0:
        return GitPathState.OUTSIDE
    root = Path(toplevel.stdout.strip()).resolve()
    if not path.is_relative_to(root):
        return GitPathState.OUTSIDE
    relative = path.relative_to(root).as_posix()
    if _git(root, "ls-files", "--error-unmatch", "--", relative).returncode == 0:
        return GitPathState.TRACKED
    if _git(root, "check-ignore", "-q", "--", relative).returncode == 0:
        return GitPathState.IGNORED
    return GitPathState.UNIGNORED
