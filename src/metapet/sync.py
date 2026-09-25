"""Optional git backup of the data home, to whatever remote the user configures."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path


class SyncError(RuntimeError):
    pass


def _git(home: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(home), *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise SyncError("git is not installed") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(f"git {' '.join(args)} failed: {detail}")
    return result


def is_repo(home: Path) -> bool:
    return (home / ".git").exists()


def init_repo(home: Path, remote: str | None = None) -> None:
    if not is_repo(home):
        _git(home, "init", "-q", "-b", "main")
    if remote:
        existing = _git(home, "remote").stdout.split()
        _git(home, "remote", "set-url" if "origin" in existing else "add", "origin", remote)


def sync(home: Path, message: str | None = None) -> list[str]:
    """Commit local changes, then pull --rebase and push if a remote exists."""
    if not is_repo(home):
        raise SyncError(f"{home} is not a git repository; run `pet init --git [--remote URL]`")
    steps: list[str] = []

    _git(home, "add", "-A")
    if _git(home, "diff", "--cached", "--quiet", check=False).returncode != 0:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        _git(home, "commit", "-q", "-m", message or f"ideas: sync {stamp}")
        steps.append("committed local changes")
    else:
        steps.append("nothing new to commit")

    if "origin" not in _git(home, "remote").stdout.split():
        steps.append("no remote configured; skipped pull/push")
        return steps
    if _git(home, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        steps.append("no commits yet; skipped pull/push")
        return steps

    branch = _git(home, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if _git(home, "ls-remote", "--heads", "origin", branch).stdout.strip():
        _git(home, "pull", "-q", "--rebase", "origin", branch)
        steps.append(f"pulled origin/{branch}")
    _git(home, "push", "-q", "-u", "origin", branch)
    steps.append(f"pushed to origin/{branch}")
    return steps
