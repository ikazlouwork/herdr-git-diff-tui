"""Unified diff parsing -> structures (files, hunks, lines).

See SPEC.md section 6. Kept separate from git.py so parsing logic is testable
without invoking git.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiffLine:
    kind: str  # "context" | "add" | "remove"
    text: str
    old_lineno: int | None
    new_lineno: int | None


@dataclass
class Hunk:
    header: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse `git diff` output into a list of FileDiff. Not yet implemented."""
    raise NotImplementedError
