"""Unified diff parsing -> structures (files, hunks, lines).

See SPEC.md section 6. Kept separate from git.py so parsing logic is testable
without invoking git.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FILE_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@(?P<rest>.*)$"
)


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

    def as_patch(self, file_diff: "FileDiff") -> str:
        """Render this single hunk back into a standalone `git apply`-able patch."""
        lines = [
            f"diff --git a/{file_diff.old_path} b/{file_diff.new_path}",
            f"--- a/{file_diff.old_path}",
            f"+++ b/{file_diff.new_path}",
            self.header,
        ]
        for line in self.lines:
            prefix = {"context": " ", "add": "+", "remove": "-"}[line.kind]
            lines.append(f"{prefix}{line.text}")
        return "\n".join(lines) + "\n"


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    is_new: bool = False
    is_deleted: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path if self.new_path != "/dev/null" else self.old_path

    @property
    def insertions(self) -> int:
        return sum(1 for h in self.hunks for l in h.lines if l.kind == "add")

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for l in h.lines if l.kind == "remove")


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse `git diff` (unified format) output into a list of FileDiff."""
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None
    old_lineno = new_lineno = 0

    for line in text.splitlines():
        file_match = _FILE_HEADER_RE.match(line)
        if file_match:
            current_file = FileDiff(old_path=file_match.group(1), new_path=file_match.group(2))
            current_hunk = None
            files.append(current_file)
            continue

        if current_file is None:
            continue

        if line.startswith("new file mode"):
            current_file.is_new = True
            continue
        if line.startswith("deleted file mode"):
            current_file.is_deleted = True
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("index ") or line.startswith("similarity index") or line.startswith("rename"):
            continue

        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            old_start = int(hunk_match.group("old_start"))
            old_lines = int(hunk_match.group("old_lines") or 1)
            new_start = int(hunk_match.group("new_start"))
            new_lines = int(hunk_match.group("new_lines") or 1)
            current_hunk = Hunk(
                header=line,
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
            )
            current_file.hunks.append(current_hunk)
            old_lineno = old_start
            new_lineno = new_start
            continue

        if current_hunk is None:
            continue

        if line.startswith("+"):
            current_hunk.lines.append(
                DiffLine(kind="add", text=line[1:], old_lineno=None, new_lineno=new_lineno)
            )
            new_lineno += 1
        elif line.startswith("-"):
            current_hunk.lines.append(
                DiffLine(kind="remove", text=line[1:], old_lineno=old_lineno, new_lineno=None)
            )
            old_lineno += 1
        elif line.startswith("\\"):
            # "\ No newline at end of file" — ignore.
            continue
        else:
            current_hunk.lines.append(
                DiffLine(
                    kind="context",
                    text=line[1:] if line.startswith(" ") else line,
                    old_lineno=old_lineno,
                    new_lineno=new_lineno,
                )
            )
            old_lineno += 1
            new_lineno += 1

    return files
