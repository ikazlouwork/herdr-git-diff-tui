"""Resolves the "before"/"after" full-ish content of a changed file for a given
diff source (working tree vs index, or index vs HEAD). See SPEC.md section 4.1.
"""

from __future__ import annotations

from . import git
from .diff_parser import FileDiff


def before_content(file_diff: FileDiff, staged: bool, cwd: str | None = None) -> str:
    if staged:
        if file_diff.is_new:
            return ""
        return git.show(f"HEAD:{file_diff.old_path}", cwd=cwd)
    if file_diff.is_new:
        return ""
    return git.show(f":{file_diff.old_path}", cwd=cwd)


def after_content(file_diff: FileDiff, staged: bool, cwd: str | None = None) -> str:
    if file_diff.is_deleted:
        return ""
    if staged:
        return git.show(f":{file_diff.new_path}", cwd=cwd)
    return git.read_working_tree_file(file_diff.new_path, cwd=cwd)
