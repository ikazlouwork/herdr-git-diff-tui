"""Right-hand columns (5/12 + 5/12): "before"/"after" side-by-side diff view.

See SPEC.md section 4.1. Simplification vs. the full spec: rather than rendering
the entire file with a full-file alignment algorithm, each hunk (with git's
default surrounding context lines) is rendered as its own syntax-highlighted
block, separated by a "…" marker where unchanged, un-shown lines were skipped.
This keeps line numbers accurate per hunk without a heavier diff3-style aligner.
"""

from __future__ import annotations

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

from ..diff_parser import FileDiff, Hunk

_ADD_BG = "on dark_green"
_REMOVE_BG = "on dark_red"


def _guess_lexer(path: str) -> str:
    try:
        from pygments.lexers import guess_lexer_for_filename

        return guess_lexer_for_filename(path, "").name.lower()
    except Exception:
        return "text"


def _hunk_block(hunk: Hunk, side: str, path: str) -> Syntax:
    """Render one side ("before"/"after") of a hunk as a Syntax block."""
    lines: list[str] = []
    highlight: set[int] = set()
    start_line = hunk.old_start if side == "before" else hunk.new_start

    for line in hunk.lines:
        if side == "before":
            if line.kind == "add":
                continue
            lines.append(line.text)
            if line.kind == "remove":
                highlight.add(len(lines))
        else:
            if line.kind == "remove":
                continue
            lines.append(line.text)
            if line.kind == "add":
                highlight.add(len(lines))

    code = "\n".join(lines) if lines else " "
    syntax = Syntax(
        code,
        lexer=_guess_lexer(path),
        line_numbers=True,
        start_line=max(start_line, 1),
        word_wrap=False,
    )
    bg = _ADD_BG if side == "after" else _REMOVE_BG
    for lineno in highlight:
        syntax.stylize_range(bg, (lineno, 0), (lineno + 1, 0))
    return syntax


def render_side(file_diff: FileDiff, side: str, current_hunk_index: int, source: str) -> Group:
    # A checkbox per hunk, mirroring VS Code: checked means "this hunk is in
    # the index". Viewing the staged diff -> every hunk here is staged, so it
    # starts checked; toggling it unstages just that hunk. Viewing the
    # unstaged diff -> starts unchecked; toggling stages it.
    checkbox = "☑" if source == "staged" else "☐"
    renderables = []
    for i, hunk in enumerate(file_diff.hunks):
        if i > 0:
            renderables.append(Text("⋯", style="dim"))
        marker_style = "reverse bold" if i == current_hunk_index else "dim"
        header = Text(f"{checkbox} ", style="bold")
        header.append(hunk.header, style=marker_style)
        renderables.append(header)
        renderables.append(_hunk_block(hunk, side, file_diff.path))
    if not renderables:
        renderables.append(Text("(no changes)", style="dim"))
    return Group(*renderables)


class DiffPane(VerticalScroll):
    """A single scrollable half (before or after) of the side-by-side view.

    Only one of the two panes (`before`) is a Tab stop — both sides scroll and
    highlight in lockstep, so exposing both as separate focus targets would
    just make Tab cycle twice through the same logical "diff panel".
    """

    def __init__(self, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.side = side
        self.can_focus = side == "before"
        self._static = Static()
        self.on_scrolled: callable | None = None

    def compose(self):
        yield self._static

    def update_content(
        self, file_diff: FileDiff | None, current_hunk_index: int, source: str
    ) -> None:
        if file_diff is None:
            self._static.update(Text("Select a file", style="dim"))
            return
        self._static.update(render_side(file_diff, self.side, current_hunk_index, source))

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self.on_scrolled is not None:
            self.on_scrolled(self, new_value)


class SideBySideDiff(Horizontal):
    """Two scroll-synced panes: original ("before") and current ("after").

    `source` records which diff is currently displayed ("staged" or
    "unstaged") — it decides which direction the hunk checkbox toggles.
    """

    current_hunk_index: reactive[int] = reactive(0)
    file_diff: reactive[FileDiff | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.before_pane = DiffPane("before", id="before")
        self.after_pane = DiffPane("after", id="after")
        self.before_pane.on_scrolled = self._on_pane_scrolled
        self.after_pane.on_scrolled = self._on_pane_scrolled
        self._syncing = False
        self.source = "unstaged"

    def compose(self):
        yield self.before_pane
        yield self.after_pane

    def show_file(self, file_diff: FileDiff | None, source: str = "unstaged") -> None:
        self.file_diff = file_diff
        self.source = source
        self.current_hunk_index = 0
        self._refresh_panes()

    def _refresh_panes(self) -> None:
        self.before_pane.update_content(self.file_diff, self.current_hunk_index, self.source)
        self.after_pane.update_content(self.file_diff, self.current_hunk_index, self.source)

    @property
    def current_hunk(self) -> Hunk | None:
        if not self.file_diff or not self.file_diff.hunks:
            return None
        return self.file_diff.hunks[self.current_hunk_index]

    def next_hunk(self) -> None:
        if not self.file_diff or not self.file_diff.hunks:
            return
        self.current_hunk_index = min(
            self.current_hunk_index + 1, len(self.file_diff.hunks) - 1
        )
        self._refresh_panes()

    def prev_hunk(self) -> None:
        if not self.file_diff or not self.file_diff.hunks:
            return
        self.current_hunk_index = max(self.current_hunk_index - 1, 0)
        self._refresh_panes()

    def _on_pane_scrolled(self, source: DiffPane, new_value: float) -> None:
        if self._syncing:
            return
        target = self.after_pane if source is self.before_pane else self.before_pane
        self._syncing = True
        try:
            target.scroll_to(y=new_value, animate=False)
        finally:
            self._syncing = False
