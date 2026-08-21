"""Thin wrapper over the `git` CLI via subprocess.

No libgit2/pygit2 dependency — see SPEC.md section 2. Functions here should stay
pure I/O wrappers: run git, return raw/structured text, no UI concerns.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class ChangedFile:
    path: str
    status: str  # M / A / D / R / ...
    insertions: int
    deletions: int


def _run(args: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def diff_unified(staged: bool, cwd: str | None = None) -> str:
    """Return the raw unified diff for working-tree or staged changes."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    return _run(args, cwd=cwd)


def stage_file(path: str, cwd: str | None = None) -> None:
    _run(["add", "--", path], cwd=cwd)


def unstage_file(path: str, cwd: str | None = None) -> None:
    _run(["restore", "--staged", "--", path], cwd=cwd)


def apply_patch(patch_text: str, cached: bool, cwd: str | None = None) -> None:
    """Apply a single-hunk patch, optionally to the index (`--cached`)."""
    args = ["apply"]
    if cached:
        args.append("--cached")
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        input=patch_text,
        text=True,
        check=True,
    )
