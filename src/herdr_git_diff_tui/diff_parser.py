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
    # Set when this line is immediately followed by git's "\ No newline at
    # end of file" marker in the source diff — i.e. this line, as it appears
    # in the version(s) it belongs to, is the true last line of that file.
    no_newline: bool = False


@dataclass
class Hunk:
    header: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine] = field(default_factory=list)

    def as_patch(self, file_diff: "FileDiff", selected_indices: set[int] | None = None) -> str:
        r"""Render this hunk back into a standalone `git apply`-able patch.

        `selected_indices` (indices into `self.lines`) picks out individual
        added/removed lines to include, for line-level (partial-hunk)
        staging — `None` means "the whole hunk", as before. This is the
        standard trick behind e.g. `git add -p`'s manual line selection: an
        unselected "add" line is simply dropped (it was never added), while
        an unselected "remove" line is turned into context (it isn't being
        removed after all, so the base still has it). Only the two `@@`
        counts change; `old_start`/`new_start` (the position) don't.

        `DiffLine.no_newline` (set by the parser from a "\ No newline at end
        of file" marker) needs care when reconstructing a partial hunk: a
        "-" line's marker describes the *old* blob only, and a "+" line's
        marker the *new* blob only, so either can be re-emitted whenever
        that line itself makes it into the output — nothing of that same
        side can follow it, since git only ever flags a line that's truly
        the last one of its side. A context line's marker describes *both*
        blobs at once, though, so it's only valid to re-emit if nothing at
        all still follows in the output — which is also where an unselected
        "remove" (now emitted as context) needs the same "nothing follows"
        check: dropping a later selected "add" line would otherwise leave a
        no-longer-terminal line incorrectly marked as newline-less.
        """
        out_lines: list[str] = []
        old_count = 0
        new_count = 0

        def _is_output(idx: int, l: "DiffLine") -> bool:
            return l.kind != "add" or selected_indices is None or idx in selected_indices

        def _nothing_follows(i: int) -> bool:
            return not any(_is_output(j, l) for j, l in enumerate(self.lines) if j > i)

        for i, line in enumerate(self.lines):
            if line.kind == "context":
                out_lines.append(f" {line.text}")
                old_count += 1
                new_count += 1
                if line.no_newline and _nothing_follows(i):
                    out_lines.append("\\ No newline at end of file")
            elif line.kind == "add":
                if selected_indices is None or i in selected_indices:
                    out_lines.append(f"+{line.text}")
                    new_count += 1
                    if line.no_newline:
                        out_lines.append("\\ No newline at end of file")
                # else: omit — this addition isn't part of the selection.
            elif line.kind == "remove":
                if selected_indices is None or i in selected_indices:
                    out_lines.append(f"-{line.text}")
                    old_count += 1
                    if line.no_newline:
                        out_lines.append("\\ No newline at end of file")
                elif line.no_newline and not _nothing_follows(i):
                    # Not selected for removal, so the base still has this
                    # text — but the base's copy has no trailing newline,
                    # and a later selected "add" line still follows it in
                    # the output. A plain context line can't express that
                    # newline-status change (context means identical bytes
                    # on both sides), so fall back to an identical
                    # remove+add pair: same text, but the "+" copy is no
                    # longer flagged newline-less since content now follows
                    # it.
                    out_lines.append(f"-{line.text}")
                    out_lines.append("\\ No newline at end of file")
                    out_lines.append(f"+{line.text}")
                    old_count += 1
                    new_count += 1
                else:
                    # Not selected for removal -> the base still has it.
                    out_lines.append(f" {line.text}")
                    old_count += 1
                    new_count += 1
                    if line.no_newline:
                        out_lines.append("\\ No newline at end of file")
                    if line.no_newline and _nothing_follows(i):
                        out_lines.append("\\ No newline at end of file")
        header = f"@@ -{self.old_start},{old_count} +{self.new_start},{new_count} @@"
        lines = [
            f"diff --git a/{file_diff.old_path} b/{file_diff.new_path}",
            f"--- a/{file_diff.old_path}",
            f"+++ b/{file_diff.new_path}",
            header,
            *out_lines,
        ]
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
            # "\ No newline at end of file" — refers to the line just
            # emitted above, not a line of its own; record it there so
            # `Hunk.as_patch` can re-emit it when reconstructing a
            # (possibly partial) patch. See as_patch's docstring.
            if current_hunk.lines:
                current_hunk.lines[-1].no_newline = True
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
