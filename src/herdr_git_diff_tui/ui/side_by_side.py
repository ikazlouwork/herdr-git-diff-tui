"""Right-hand columns (5/12 + 5/12): "before"/"after" side-by-side diff view.

See SPEC.md section 4.1. Simplification vs. the full spec: rather than rendering
the entire file with a full-file alignment algorithm, each hunk (with git's
default surrounding context lines) is rendered as its own syntax-highlighted
block, separated by a "…" marker where unchanged, un-shown lines were skipped.
This keeps line numbers accurate per hunk without a heavier diff3-style aligner.

Navigation model: `Tab` is how you get into this panel in the first place;
once it has focus, changed lines are grouped into contiguous "change
blocks" (a run of removed lines, a run of added lines, or a modified line's
remove-run-then-add-run pair — see `change_blocks`), and the cursor moves
across two independent axes: `↑`/`↓` step from block to block — across
*every* hunk in the file, treated as one continuous sequence, so there's no
separate hunk-jump key (see `SideBySideDiff._all_blocks`/`next_block`) —
and `←`/`→` pick which side of the *current* block is active — old/"before"
or new/"after" (see `DiffPane.action_cursor_left/_right`). If the current
block doesn't have that side at all (a pure addition has no "old", a pure
deletion has no "new"), `←`/`→` jump on to the nearest block in that same
direction that does, rather than sitting still — see
`SideBySideDiff.move_side`/`_jump_to_nearest_side`. `PgUp`/`PgDn`/`Home`/
`End`/mouse wheel are still plain, free scrolling (inherited from
`VerticalScroll` — untouched).

Line-level staging: each added/removed line gets a checkbox (☐/☑, toggled
with `space`) in a gutter to the left of its syntax-highlighted text, plus a
`›` cursor marker on every line of whichever (block, side) `↑`/`↓`/`←`/`→`
currently points at. `space` toggles that whole side of the block as one
unit (all its lines together, not line-by-line) — see
`SideBySideDiff.toggle_current_line`. `s`/`u` stage/unstage exactly the
checked lines in the current hunk if any are checked, or the current block
(both its sides — the whole edit at the cursor, not the rest of the hunk)
otherwise — see `SideBySideDiff.staging_indices`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    hunk: Hunk, side: str, path: str, selected: set[int], cursor_indices: frozenset[int]
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
        cursor_ch = "›" if orig_index in cursor_indices else " "
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
    cursor_indices: frozenset[int],
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
        cursor = cursor_indices if is_current else frozenset()
        renderables.append(_hunk_block(hunk, side, file_diff.path, selected, cursor))
    if not renderables:
        renderables.append(Text("(no changes)", style="dim"))
    return Group(*renderables)


@dataclass
class ChangeBlock:
    """One contiguous run of non-context lines: the unit `↑`/`↓` moves
    across. `old`/`new` are indices into `hunk.lines` for this block's
    removed/added lines respectively — either can be empty (a pure
    addition has no `old`, a pure deletion has no `new`), but never both.
    """

    old: list[int] = field(default_factory=list)
    new: list[int] = field(default_factory=list)

    def side(self, which: str) -> list[int]:
        return self.old if which == "old" else self.new

    def has_side(self, which: str) -> bool:
        return bool(self.side(which))


def change_blocks(hunk: Hunk) -> list[ChangeBlock]:
    """Group `hunk.lines` into `ChangeBlock`s, in order.

    A block is exactly what a single real edit at that position in the
    hunk looks like in unified diff form: zero or more consecutive
    "remove" lines immediately followed by zero or more consecutive "add"
    lines, bounded by context (or the ends of the hunk) on both sides.
    """
    blocks: list[ChangeBlock] = []
    current = ChangeBlock()
    for i, line in enumerate(hunk.lines):
        if line.kind == "context":
            if current.old or current.new:
                blocks.append(current)
                current = ChangeBlock()
            continue
        if line.kind == "remove":
            current.old.append(i)
        else:  # "add"
            current.new.append(i)
    if current.old or current.new:
        blocks.append(current)
    return blocks


class DiffPane(VerticalScroll):
    """A single scrollable half (before or after) of the side-by-side view.

    Only one of the two panes (`before`) is a Tab stop — both sides scroll and
    highlight in lockstep, so exposing both as separate focus targets would
    just make Tab cycle twice through the same logical "diff panel".
    """

    # Shadows VerticalScroll's own "up"/"down" (-> scroll_up/scroll_down):
    # while the diff panel has focus, plain arrows drive the block/side
    # cursor instead of raw-scrolling — Tab is how you get into this pane in
    # the first place, so arrows are free to mean "move within it" rather
    # than "scroll it". PgUp/PgDn/Home/End are left alone (still inherited)
    # as an escape hatch for free scrolling.
    BINDINGS = [
        ("up", "cursor_up", "Prev change"),
        ("down", "cursor_down", "Next change"),
        ("left", "cursor_left", "Old side"),
        ("right", "cursor_right", "New side"),
    ]

    def __init__(self, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.side = side
        self.can_focus = side == "before"
        self._static = Static()
        self.on_scrolled: callable | None = None
        self.on_cursor_move: callable | None = None  # ("up" | "down") -> None
        self.on_side_move: callable | None = None  # ("left" | "right") -> None
        self.on_focus_change: callable | None = None  # (bool) -> None

    def compose(self):
        yield self._static

    def on_focus(self) -> None:
        if self.on_focus_change is not None:
            self.on_focus_change(True)

    def on_blur(self) -> None:
        if self.on_focus_change is not None:
            self.on_focus_change(False)

    def action_cursor_up(self) -> None:
        if self.on_cursor_move is not None:
            self.on_cursor_move("up")

    def action_cursor_down(self) -> None:
        if self.on_cursor_move is not None:
            self.on_cursor_move("down")

    def action_cursor_left(self) -> None:
        if self.on_side_move is not None:
            self.on_side_move("left")

    def action_cursor_right(self) -> None:
        if self.on_side_move is not None:
            self.on_side_move("right")

    def update_content(
        self,
        file_diff: FileDiff | None,
        current_hunk_index: int,
        selected_by_hunk: dict[int, set[int]],
        cursor_indices: frozenset[int],
    ) -> None:
        if file_diff is None:
            self._static.update(Text("Select a file", style="dim"))
            return
        self._static.update(
            render_side(file_diff, self.side, current_hunk_index, selected_by_hunk, cursor_indices)
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
        self.before_pane.on_side_move = self._on_side_move
        self.before_pane.on_focus_change = self._on_focus_change
        self._syncing = False
        self.source = "unstaged"
        # hunk index -> set of `hunk.lines` indices checked for line-level
        # staging. Cleared whenever a different file is shown (indices are
        # only meaningful against that file's own parsed hunks).
        self.selected_lines: dict[int, set[int]] = {}
        # Index into `_all_blocks()` — every hunk's change blocks, flattened
        # into one continuous sequence, so ↑/↓ crosses hunk boundaries on
        # their own and there's no separate hunk-jump key. Paired with which
        # of the block's sides ("old"/"new") ←/→ currently points at.
        self.cursor_flat_index: int | None = None
        self.cursor_side: str = "old"
        # Tracks focus directly from the Focus/Blur events themselves (via
        # `on_focus_change`) rather than reading `before_pane.has_focus`:
        # that flag is updated by Textual's own internal `_on_focus`/
        # `_on_blur` handlers, whose ordering relative to *our* handler
        # (same event, different method) isn't guaranteed, so it can still
        # read stale at the moment we'd check it.
        self._diff_panel_focused = False

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
        cursor = frozenset(self._active_indices())
        self.before_pane.update_content(
            self.file_diff, self.current_hunk_index, self.selected_lines, cursor
        )
        self.after_pane.update_content(
            self.file_diff, self.current_hunk_index, self.selected_lines, cursor
        )
        self._update_side_highlight()
        self.status.update(self._status_text())

    def _on_focus_change(self, focused: bool) -> None:
        self._diff_panel_focused = focused
        self._update_side_highlight()

    def _update_side_highlight(self) -> None:
        """Border-highlight whichever pane `←`/`→` currently points at (see
        the `.-active-side` CSS in `GitDiffApp`) — but only while the diff
        panel actually has focus. The block/side cursor itself persists
        even after `Tab` moves focus away (so it's still there when you tab
        back), but the highlight shouldn't linger on screen the whole time
        as if it were always "active" — it's only meaningful while you're
        actually the one steering `←`/`→` right now.
        """
        active = self._diff_panel_focused and self.cursor_flat_index is not None
        self.before_pane.set_class(active and self.cursor_side == "old", "-active-side")
        self.after_pane.set_class(active and self.cursor_side == "new", "-active-side")

    def _status_text(self) -> str:
        if self.file_diff is None:
            return "Select a file"
        total = len(self.file_diff.hunks)
        hunk_part = f"Hunk {self.current_hunk_index + 1}/{total}" if total else "no hunks"
        key = "s" if self.source == "unstaged" else "u"
        verb = "stage" if self.source == "unstaged" else "unstage"
        selected = self.selected_lines.get(self.current_hunk_index, set())
        side_hint = f"[{self.cursor_side}]" if self.cursor_flat_index is not None else ""
        if selected:
            action_hint = f"{key}: {verb} {len(selected)} line(s)  ·  space: toggle  ↑↓ change  ←→ old/new {side_hint}"
        else:
            action_hint = f"{key}: {verb} change  ·  space: select side  ↑↓ change  ←→ old/new {side_hint}"
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

    # -- block/side cursor and checkboxes ------------------------------------

    def _all_blocks(self) -> list[tuple[int, ChangeBlock]]:
        """Every hunk's change blocks, flattened into one (hunk_index,
        block) sequence in file order — the single list `↑`/`↓` walks, so
        the cursor crosses hunk boundaries on its own without a dedicated
        hunk-jump key.
        """
        if not self.file_diff:
            return []
        return [
            (h, block)
            for h, hunk in enumerate(self.file_diff.hunks)
            for block in change_blocks(hunk)
        ]

    def _current_block(self) -> ChangeBlock | None:
        blocks = self._all_blocks()
        if self.cursor_flat_index is None or self.cursor_flat_index >= len(blocks):
            return None
        return blocks[self.cursor_flat_index][1]

    def _active_indices(self) -> list[int]:
        """`hunk.lines` indices of the (block, side) the cursor points at —
        what gets the `›` marker and what `space` toggles as one unit.
        """
        block = self._current_block()
        if block is None:
            return []
        return block.side(self.cursor_side)

    def staging_indices(self) -> set[int] | None:
        """What `s`/`u` should act on in the current hunk: exactly the
        checked lines if any are checked, otherwise the *current block's*
        own lines (both sides — the whole edit under the cursor) — never
        the rest of the hunk, which may hold other, unrelated blocks the
        cursor isn't pointing at.
        """
        checked = self.selected_lines.get(self.current_hunk_index)
        if checked:
            return checked
        block = self._current_block()
        if block is None:
            return None
        return set(block.old) | set(block.new)

    def _reset_cursor(self) -> None:
        blocks = self._all_blocks()
        self.cursor_flat_index = 0 if blocks else None
        self.current_hunk_index = blocks[0][0] if blocks else 0
        self.cursor_side = self._default_side(blocks[0][1]) if blocks else "old"

    @staticmethod
    def _default_side(block: ChangeBlock) -> str:
        return "old" if block.has_side("old") else "new"

    def next_block(self) -> None:
        blocks = self._all_blocks()
        if not blocks or self.cursor_flat_index is None:
            return
        self.cursor_flat_index = min(self.cursor_flat_index + 1, len(blocks) - 1)
        hunk_index, block = blocks[self.cursor_flat_index]
        self.current_hunk_index = hunk_index
        self._settle_side(block)
        self._refresh_panes()
        self._ensure_cursor_visible()

    def prev_block(self) -> None:
        blocks = self._all_blocks()
        if not blocks or self.cursor_flat_index is None:
            return
        self.cursor_flat_index = max(self.cursor_flat_index - 1, 0)
        hunk_index, block = blocks[self.cursor_flat_index]
        self.current_hunk_index = hunk_index
        self._settle_side(block)
        self._refresh_panes()
        self._ensure_cursor_visible()

    def _settle_side(self, block: ChangeBlock) -> None:
        """Keep the current side across a block change if it still exists
        there, otherwise fall back to whichever side the block does have.
        """
        if not block.has_side(self.cursor_side):
            self.cursor_side = self._default_side(block)

    def _on_cursor_move(self, direction: str) -> None:
        if direction == "up":
            self.prev_block()
        else:
            self.next_block()

    def move_side(self, direction: str) -> None:
        """`←`/`→` -> "old"/"new". If the current block has no line on that
        side (e.g. `←` on a pure addition, which has no "old" at all), this
        isn't a no-op: it hunts in that same direction for the nearest
        block that *does* have it and jumps the cursor there instead — so
        `←` from a pure addition lands you on the nearest earlier old-side
        line rather than just sitting still with nothing to show for it.
        """
        block = self._current_block()
        if block is None:
            return
        target = "old" if direction == "left" else "new"
        if block.has_side(target):
            self.cursor_side = target
            self._refresh_panes()
            self._ensure_cursor_visible()
            return
        self._jump_to_nearest_side(direction, target)

    def _jump_to_nearest_side(self, direction: str, target: str) -> None:
        blocks = self._all_blocks()
        if self.cursor_flat_index is None:
            return
        step = -1 if direction == "left" else 1
        i = self.cursor_flat_index + step
        while 0 <= i < len(blocks):
            hunk_index, block = blocks[i]
            if block.has_side(target):
                self.cursor_flat_index = i
                self.current_hunk_index = hunk_index
                self.cursor_side = target
                self._refresh_panes()
                self._ensure_cursor_visible()
                return
            i += step
        # No block anywhere in that direction has the side we're after --
        # a genuine no-op (e.g. the very first block in the file is a pure
        # addition and there's no earlier "old" to jump back to).

    def _on_side_move(self, direction: str) -> None:
        self.move_side(direction)

    def toggle_current_line(self) -> None:
        indices = self._active_indices()
        if not indices:
            return
        selected = self.selected_lines.setdefault(self.current_hunk_index, set())
        # All-or-nothing for the whole side of the block, as one unit: if
        # any line in it is still unchecked, checking it checks the rest;
        # only once the whole group is checked does toggling uncheck it.
        if all(i in selected for i in indices):
            selected.difference_update(indices)
        else:
            selected.update(indices)
        self._refresh_panes()

    def _row_for_line(self, side: str) -> int | None:
        """Absolute row of the cursor group's first line in `side`'s
        rendered content, or `None` if that line doesn't exist on this side
        (e.g. an "add" line has no row on the "before" side)."""
        hunk = self.current_hunk
        indices = self._active_indices()
        if hunk is None or not indices:
            return None
        cursor_index = indices[0]
        line = hunk.lines[cursor_index]
        skip_kind = "add" if side == "before" else "remove"
        if line.kind == skip_kind:
            return None
        base = hunk_row_offsets(self.file_diff, side)[self.current_hunk_index] + 1
        visible_before = sum(1 for l in hunk.lines[:cursor_index] if l.kind != skip_kind)
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
