"""Right-hand columns (5/12 + 5/12): "before"/"after" side-by-side diff view.

See SPEC.md section 4.1. Simplification vs. the full spec: rather than rendering
the entire file with a full-file alignment algorithm, each hunk (with git's
default surrounding context lines) is rendered as its own syntax-highlighted
block, separated by a "…" marker where unchanged, un-shown lines were skipped.
This keeps line numbers accurate per hunk without a heavier diff3-style aligner.

Navigation model: `Tab` is how you get into this panel in the first place;
once it has focus, `↑`/`↓` step a line-selection cursor through the current
hunk's changed lines (see `DiffPane.action_cursor_up/_down`), `]`/`[` jump
hunk-to-hunk, and `PgUp`/`PgDn`/`Home`/`End`/mouse wheel are still plain,
free scrolling (inherited from `VerticalScroll` — untouched). Three
independent, non-overlapping ways to move, instead of overloading one pair
of keys with several meanings.

Line-level staging: each added/removed line gets a checkbox (☐/☑, toggled
with `space`) in a gutter to the left of its syntax-highlighted text, plus a
`›` cursor marker for whichever line `↑`/`↓` currently points at. `s`/`u`
stage/unstage exactly the checked lines in the current hunk if any are
checked, or the whole hunk otherwise (see `SideBySideDiff.selected_lines`).
"""

from __future__ import annotations

from rich.console import Group
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

from ..diff_parser import FileDiff, Hunk
from .file_list import status_letter

_ADD_BG = "on dark_green"
_ADD_BG_SELECTED = "on green"
_REMOVE_BG = "on dark_red"
_REMOVE_BG_SELECTED = "on red"


def _guess_lexer(path: str) -> str:
    try:
        from pygments.lexers import guess_lexer_for_filename

        return guess_lexer_for_filename(path, "").name.lower()
    except Exception:
        return "text"


def _side_rows(hunk: Hunk, side: str) -> list[tuple[int, "DiffLine"]]:  # noqa: F821
    """(index into hunk.lines, line) for every line visible on this side."""
    skip_kind = "add" if side == "before" else "remove"
    return [(i, line) for i, line in enumerate(hunk.lines) if line.kind != skip_kind]


def _hunk_block(
    hunk: Hunk, side: str, path: str, selected: set[int], cursor_index: int | None
) -> Table:
    """Render one side ("before"/"after") of a hunk: a checkbox/cursor gutter
    next to a syntax-highlighted code block, kept in row-for-row sync (both
    have exactly one row per line — `word_wrap=False` guarantees the Syntax
    side never soft-wraps, so nothing shifts the two columns out of step).
    """
    rows = _side_rows(hunk, side)
    start_line = hunk.old_start if side == "before" else hunk.new_start

    code = "\n".join(line.text for _, line in rows) if rows else " "
    syntax = Syntax(
        code,
        lexer=_guess_lexer(path),
        line_numbers=True,
        start_line=max(start_line, 1),
        word_wrap=False,
    )

    marks: list[str] = []
    for row_num, (orig_index, line) in enumerate(rows, start=1):
        if line.kind == "context":
            marks.append("  ")
            continue
        is_selected = orig_index in selected
        if line.kind == "remove":
            bg = _REMOVE_BG_SELECTED if is_selected else _REMOVE_BG
        else:
            bg = _ADD_BG_SELECTED if is_selected else _ADD_BG
        syntax.stylize_range(bg, (row_num, 0), (row_num + 1, 0))
        cursor_ch = "›" if orig_index == cursor_index else " "
        box_ch = "☑" if is_selected else "☐"
        marks.append(f"{cursor_ch}{box_ch}")
    gutter = Text("\n".join(marks) if marks else " ")

    table = Table.grid(padding=0)
    table.add_column(width=2)
    table.add_column(ratio=1)
    table.add_row(gutter, syntax)
    return table


def hunk_row_offsets(file_diff: FileDiff, side: str) -> list[int]:
    """Row (0-indexed) where each hunk's header line starts in `render_side`'s
    output, for the given side. Before/after can differ per hunk (a hunk that
    only adds lines renders 0 body rows on the "before" side), so this is
    computed separately per side rather than assuming a shared row count.
    """
    offsets = []
    row = 0
    for i, hunk in enumerate(file_diff.hunks):
        if i > 0:
            row += 1  # the "⋯" separator between hunks
        offsets.append(row)
        row += 1  # the hunk header line itself
        row += len(_side_rows(hunk, side))
    return offsets


def render_side(
    file_diff: FileDiff,
    side: str,
    current_hunk_index: int,
    selected_by_hunk: dict[int, set[int]],
    cursor_line_index: int | None,
) -> Group:
    renderables = []
    for i, hunk in enumerate(file_diff.hunks):
        if i > 0:
            renderables.append(Text("⋯", style="dim"))
        is_current = i == current_hunk_index
        header = Text("▶ " if is_current else "  ", style="bold reverse" if is_current else "")
        header.append(hunk.header, style="bold reverse" if is_current else "dim")
        renderables.append(header)
        selected = selected_by_hunk.get(i, set())
        cursor = cursor_line_index if is_current else None
        renderables.append(_hunk_block(hunk, side, file_diff.path, selected, cursor))
    if not renderables:
        renderables.append(Text("(no changes)", style="dim"))
    return Group(*renderables)


def changed_line_indices(hunk: Hunk) -> list[int]:
    """Indices (into `hunk.lines`) of every added/removed line, in order —
    the set of positions the line-selection cursor (`j`/`k`) can land on.
    """
    return [i for i, line in enumerate(hunk.lines) if line.kind != "context"]


class DiffPane(VerticalScroll):
    """A single scrollable half (before or after) of the side-by-side view.

    Only one of the two panes (`before`) is a Tab stop — both sides scroll and
    highlight in lockstep, so exposing both as separate focus targets would
    just make Tab cycle twice through the same logical "diff panel".
    """

    # Shadows VerticalScroll's own "up"/"down" (-> scroll_up/scroll_down):
    # while the diff panel has focus, plain arrows step the line-selection
    # cursor through changed lines instead of raw-scrolling — Tab is how you
    # get into this pane in the first place, so arrows are free to mean
    # "move within it" rather than "scroll it". PgUp/PgDn/Home/End are left
    # alone (still inherited) as an escape hatch for free scrolling.
    BINDINGS = [
        ("up", "cursor_up", "Prev line"),
        ("down", "cursor_down", "Next line"),
    ]

    def __init__(self, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.side = side
        self.can_focus = side == "before"
        self._static = Static()
        self.on_scrolled: callable | None = None
        self.on_cursor_move: callable | None = None  # ("up" | "down") -> None

    def compose(self):
        yield self._static

    def action_cursor_up(self) -> None:
        if self.on_cursor_move is not None:
            self.on_cursor_move("up")

    def action_cursor_down(self) -> None:
        if self.on_cursor_move is not None:
            self.on_cursor_move("down")

    def update_content(
        self,
        file_diff: FileDiff | None,
        current_hunk_index: int,
        selected_by_hunk: dict[int, set[int]],
        cursor_line_index: int | None,
    ) -> None:
        if file_diff is None:
            self._static.update(Text("Select a file", style="dim"))
            return
        self._static.update(
            render_side(file_diff, self.side, current_hunk_index, selected_by_hunk, cursor_line_index)
        )

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self.on_scrolled is not None:
            self.on_scrolled(self, new_value)


class SideBySideDiff(Vertical):
    """A status line always showing what's selected, plus two scroll-synced
    panes: original ("before") and current ("after").

    `source` records which diff is currently displayed ("staged" or
    "unstaged") — it decides which direction hunk/line staging goes, and is
    reflected in the status line's hint text so the available action always
    matches what's on screen, regardless of keyboard focus.
    """

    current_hunk_index: reactive[int] = reactive(0)
    file_diff: reactive[FileDiff | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = Static(self._status_text(), id="diff-status")
        self.before_pane = DiffPane("before", id="before")
        self.after_pane = DiffPane("after", id="after")
        self.before_pane.on_scrolled = self._on_pane_scrolled
        self.after_pane.on_scrolled = self._on_pane_scrolled
        self.before_pane.on_cursor_move = self._on_cursor_move
        self._syncing = False
        self.source = "unstaged"
        # hunk index -> set of `hunk.lines` indices checked for line-level
        # staging. Cleared whenever a different file is shown (indices are
        # only meaningful against that file's own parsed hunks).
        self.selected_lines: dict[int, set[int]] = {}
        self.cursor_line_index: int | None = None

    def compose(self):
        yield self.status
        with Horizontal(id="panes"):
            yield self.before_pane
            yield self.after_pane

    def show_file(self, file_diff: FileDiff | None, source: str = "unstaged") -> None:
        self.file_diff = file_diff
        self.source = source
        self.current_hunk_index = 0
        self.selected_lines = {}
        self._reset_cursor()
        self._refresh_panes()
        self._syncing = True
        try:
            self.before_pane.scroll_to(y=0, animate=False, immediate=True)
            self.after_pane.scroll_to(y=0, animate=False, immediate=True)
        finally:
            self._syncing = False

    def _refresh_panes(self) -> None:
        self.before_pane.update_content(
            self.file_diff, self.current_hunk_index, self.selected_lines, self.cursor_line_index
        )
        self.after_pane.update_content(
            self.file_diff, self.current_hunk_index, self.selected_lines, self.cursor_line_index
        )
        self.status.update(self._status_text())

    def _status_text(self) -> str:
        if self.file_diff is None:
            return "Select a file"
        total = len(self.file_diff.hunks)
        hunk_part = f"Hunk {self.current_hunk_index + 1}/{total}" if total else "no hunks"
        key = "s" if self.source == "unstaged" else "u"
        verb = "stage" if self.source == "unstaged" else "unstage"
        selected = self.selected_lines.get(self.current_hunk_index, set())
        if selected:
            action_hint = f"{key}: {verb} {len(selected)} line(s)  ·  space: toggle  j/k: move"
        else:
            action_hint = f"{key}: {verb} hunk  ·  space: select line  j/k: move"
        return (
            f"{status_letter(self.file_diff)} {self.file_diff.path}   "
            f"+{self.file_diff.insertions} -{self.file_diff.deletions}   "
            f"[{self.source}]   {hunk_part}   {action_hint}"
        )

    @property
    def current_hunk(self) -> Hunk | None:
        if not self.file_diff or not self.file_diff.hunks:
            return None
        return self.file_diff.hunks[self.current_hunk_index]

    # -- hunk navigation ---------------------------------------------------

    def next_hunk(self) -> None:
        if not self.file_diff or not self.file_diff.hunks:
            return
        self.current_hunk_index = min(
            self.current_hunk_index + 1, len(self.file_diff.hunks) - 1
        )
        self._reset_cursor()
        self._refresh_panes()
        self._scroll_to_current_hunk()

    def prev_hunk(self) -> None:
        if not self.file_diff or not self.file_diff.hunks:
            return
        self.current_hunk_index = max(self.current_hunk_index - 1, 0)
        self._reset_cursor()
        self._refresh_panes()
        self._scroll_to_current_hunk()

    def _scroll_to_current_hunk(self) -> None:
        """Bring the current hunk's header to the top of both panes.

        Before/after offsets are computed independently (see
        `hunk_row_offsets`) since a hunk that's pure additions/deletions has a
        different row count on each side — scrolling both panes to the *same*
        absolute row would desync them right at the hunk you're jumping to.
        """
        if not self.file_diff or not self.file_diff.hunks:
            return
        before_offsets = hunk_row_offsets(self.file_diff, "before")
        after_offsets = hunk_row_offsets(self.file_diff, "after")
        idx = self.current_hunk_index
        self._syncing = True
        try:
            self.before_pane.scroll_to(y=before_offsets[idx], animate=False, immediate=True)
            self.after_pane.scroll_to(y=after_offsets[idx], animate=False, immediate=True)
        finally:
            self._syncing = False

    # -- line-selection cursor and checkboxes -------------------------------

    def _reset_cursor(self) -> None:
        hunk = self.current_hunk
        changed = changed_line_indices(hunk) if hunk else []
        self.cursor_line_index = changed[0] if changed else None

    def next_line(self) -> None:
        hunk = self.current_hunk
        if hunk is None or self.cursor_line_index is None:
            return
        changed = changed_line_indices(hunk)
        pos = changed.index(self.cursor_line_index)
        self.cursor_line_index = changed[min(pos + 1, len(changed) - 1)]
        self._refresh_panes()
        self._ensure_cursor_visible()

    def prev_line(self) -> None:
        hunk = self.current_hunk
        if hunk is None or self.cursor_line_index is None:
            return
        changed = changed_line_indices(hunk)
        pos = changed.index(self.cursor_line_index)
        self.cursor_line_index = changed[max(pos - 1, 0)]
        self._refresh_panes()
        self._ensure_cursor_visible()

    def _on_cursor_move(self, direction: str) -> None:
        if direction == "up":
            self.prev_line()
        else:
            self.next_line()

    def toggle_current_line(self) -> None:
        if self.cursor_line_index is None:
            return
        selected = self.selected_lines.setdefault(self.current_hunk_index, set())
        if self.cursor_line_index in selected:
            selected.discard(self.cursor_line_index)
        else:
            selected.add(self.cursor_line_index)
        self._refresh_panes()

    def _row_for_line(self, side: str) -> int | None:
        """Absolute row of the cursor line in `side`'s rendered content, or
        `None` if that line doesn't exist on this side (e.g. an "add" line
        has no row on the "before" side)."""
        hunk = self.current_hunk
        if hunk is None or self.cursor_line_index is None:
            return None
        line = hunk.lines[self.cursor_line_index]
        skip_kind = "add" if side == "before" else "remove"
        if line.kind == skip_kind:
            return None
        base = hunk_row_offsets(self.file_diff, side)[self.current_hunk_index] + 1
        visible_before = sum(
            1 for l in hunk.lines[: self.cursor_line_index] if l.kind != skip_kind
        )
        return base + visible_before

    def _ensure_cursor_visible(self) -> None:
        self._syncing = True
        try:
            for pane, side in ((self.before_pane, "before"), (self.after_pane, "after")):
                row = self._row_for_line(side)
                if row is None:
                    continue
                top = pane.scroll_y
                bottom = top + max(pane.size.height - 1, 0)
                if row < top:
                    pane.scroll_to(y=row, animate=False, immediate=True)
                elif row > bottom:
                    pane.scroll_to(
                        y=row - max(pane.size.height - 1, 0), animate=False, immediate=True
                    )
        finally:
            self._syncing = False

    def _on_pane_scrolled(self, source: DiffPane, new_value: float) -> None:
        if self._syncing:
            return
        target = self.after_pane if source is self.before_pane else self.before_pane
        self._syncing = True
        try:
            target.scroll_to(y=new_value, animate=False, immediate=True)
        finally:
            self._syncing = False
