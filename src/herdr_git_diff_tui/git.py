"""Thin wrapper over the `git` CLI via subprocess.

No libgit2/pygit2 dependency — see SPEC.md section 2. Functions here should stay
pure I/O wrappers: run git, return raw/structured text, no UI concerns.
"""

from __future__ import annotations

import subprocess


def _run(args: list[str], cwd: str | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args, output=result.stdout, stderr=result.stderr
        )
    return result.stdout


def diff_unified(staged: bool, cwd: str | None = None) -> str:
    """Return the raw unified diff for working-tree or staged changes."""
    args = ["diff", "--no-color"]
    if staged:
        args.append("--staged")
    return _run(args, cwd=cwd)


def show(revision_path: str, cwd: str | None = None) -> str:
    """Return the content of `revision_path` (e.g. "HEAD:foo.py" or ":foo.py").

    Returns "" if the object doesn't exist (new/deleted file edge cases).
    """
    try:
        return _run(["show", revision_path], cwd=cwd, check=True)
    except subprocess.CalledProcessError:
        return ""


def read_working_tree_file(path: str, cwd: str | None = None) -> str:
    from pathlib import Path

    base = Path(cwd) if cwd else Path.cwd()
    target = base / path
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError):
        return ""


def stage_file(path: str, cwd: str | None = None) -> None:
    _run(["add", "--", path], cwd=cwd)


def unstage_file(path: str, cwd: str | None = None) -> None:
    _run(["restore", "--staged", "--", path], cwd=cwd)


def apply_patch(
    patch_text: str, cached: bool, reverse: bool = False, cwd: str | None = None
) -> None:
    """Apply a single-hunk patch, optionally to the index (`--cached`).

    Patch bytes are sent as-is (no text-mode newline translation): on Windows,
    `text=True` would rewrite the patch's `\n` line endings to `\r\n` on write,
    which breaks `git apply`'s line-for-line matching against LF-only blobs.
    """
    args = ["apply"]
    if cached:
        args.append("--cached")
    if reverse:
        args.append("--reverse")
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        input=patch_text.encode("utf-8"),
        capture_output=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            args,
            output=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
        )
