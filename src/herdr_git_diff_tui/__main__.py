"""Entry point: `python -m herdr_git_diff_tui`.

Root Textual application wiring the file list + side-by-side diff panel + a
staging/unstaging workflow. See SPEC.md section 4 for the MVP scope.

Staging UX (VS Code Source Control-style, see SPEC.md section 4.2): the left
column always shows both "Staged Changes" and "Changes" sections at once —
staging/unstaging a file moves it between the two live, rather than the whole
view flipping between two modes.

`s`/`u` are contextual rather than being split across separate keys: with
focus in a file list they stage/unstage the whole selected file; with focus
in the diff panel they stage/unstage exactly the checked lines (checkboxes
toggled with `space`) if any are checked, or just the current change block
under the cursor otherwise — never the rest of the hunk, which may hold
other, unrelated blocks the cursor isn't pointing at (see
`SideBySideDiff.staging_indices`). The cursor itself moves with `↑`/`↓`
across every hunk's blocks as one continuous sequence — there's no separate
hunk-jump key. The diff panel's own status line always names which action
is live, so the active file/block and its available action stay visible
regardless of which widget currently has keyboard focus.

After any stage/unstage, selection lands on whatever file is now at the same
position in the merged (Staged Changes, then Changes) list — i.e. "the file
that slid up to fill the gap" — rather than resetting to the top of a
section (see `_merged_index_of_active`/`_select_merged_index`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, ListView

from . import git
from .diff_parser import FileDiff, parse_unified_diff
from .ui.file_list import ChangesPanel
from .ui.side_by_side import SideBySideDiff


class GitDiffApp(App):
    """Root Textual application for the git diff TUI panel."""

    TITLE = "herdr-git-diff-tui"
    CSS = """
    Horizontal#root {
        height: 1fr;
    }
    ChangesPanel {
        width: 3fr;
        border-right: solid $panel;
    }
    Section {
        height: auto;
    }
    Section ListView {
        height: auto;
        max-height: 14;
    }
    /* Muted: "remembered position" in a section that isn't the active one.
       Underline is a color-independent signal (unlike a translucent tint,
       which can render as indistinguishable from the background in some
       terminal themes) — Section.active overrides this to a solid,
       unmissable highlight for the file actually being acted on/shown in
       the diff panel, so there's always a clearly visible "you are here". */
    Section ListView > ListItem.-highlight {
        text-style: underline;
    }
    Section.active ListView > ListItem.-highlight {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    .section-header {
        color: $text-muted;
        text-style: bold;
        padding: 1 1 0 1;
    }
    SideBySideDiff {
        width: 10fr;
    }
    SideBySideDiff > #diff-status {
        height: 1;
        padding: 0 1;
        background: $panel;
        text-style: bold;
    }
    SideBySideDiff > Horizontal#panes {
        height: 1fr;
    }
    DiffPane {
        width: 1fr;
        border: solid $panel;
    }
    /* Which side (old/new) `←`/`→` currently points at — see
       `SideBySideDiff._update_side_highlight`. Only shown while the diff
       panel actually has focus: the block/side cursor itself persists
       even after Tab moves focus away (so it's still there when you tab
       back), but the highlight shouldn't linger on screen the whole time
       as if the panel were still being steered. */
    DiffPane.-active-side {
        border: heavy $accent;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("s", "stage", "Stage"),
        ("u", "unstage", "Unstage"),
        ("space", "toggle_line", "Select line"),
    ]
    # Tab / Shift+Tab switch focus between the two file-list sections and the
    # diff panel via Textual's built-in focus_next/focus_previous; in the
    # file lists, ↑/↓ also flow across the Staged/Changes boundary directly
    # (see `on_key`), so you never need Tab just to reach the other section.
    # Tab is how you get into the diff panel; once there, ↑/↓ step the
    # block cursor across *every* hunk's changes as one continuous sequence
    # (see `DiffPane`/`SideBySideDiff` in ui/side_by_side.py) — there's no
    # separate hunk-jump key — `←`/`→` pick the block's old/new side, and
    # PgUp/PgDn/Home/End/mouse wheel still do plain free scrolling.

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self.cwd = cwd or str(Path.cwd())
        # Which section last had a highlighted item — the source of truth for
        # "what am I looking at", independent of whatever currently has
        # keyboard focus (so it still holds once focus moves into the diff
        # panel, and doesn't go stale mid-refresh; see _active_selection).
        self._active_section = "unstaged"
        # True while `action_refresh` is rebuilding both sections' ListViews.
        # The *inactive* section's own by-path selection preservation (see
        # `Section.set_files`) can change its `.index`, which fires a
        # `ListView.Highlighted` — without this guard, that would be treated
        # like a real user navigation and clobber `_active_section` right
        # before `_select_merged_index` gets to set the authoritative one.
        self._programmatic_refresh = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="root"):
            yield ChangesPanel(id="changes")
            yield SideBySideDiff(id="diff-view")
        yield Footer()

    async def on_mount(self) -> None:
        await self.action_refresh()
        panel = self.query_one(ChangesPanel)
        if panel.unstaged_section.selected_file_diff is not None:
            self._active_section = "unstaged"
            panel.unstaged_section.list_view.focus()
        else:
            self._active_section = "staged"
            panel.staged_section.list_view.focus()
        self._update_active_section_classes()
        self._sync_diff_view()

    async def action_refresh(self) -> None:
        # Where the currently active file sits in the merged (staged, then
        # unstaged) list, captured against the *old* panel contents, before
        # anything is rebuilt below.
        merged_index = self._merged_index_of_active()
        try:
            staged_raw = git.diff_unified(True, cwd=self.cwd)
            unstaged_raw = git.diff_unified(False, cwd=self.cwd)
        except subprocess.CalledProcessError as exc:
            self.notify(f"git diff failed: {exc.stderr}", severity="error")
            return
        staged_files = parse_unified_diff(staged_raw)
        unstaged_files = parse_unified_diff(unstaged_raw)
        panel = self.query_one(ChangesPanel)
        self._programmatic_refresh = True
        try:
            # Awaited: `Section.set_files` only resolves once the DOM
            # mount/removal it triggers has actually completed, so
            # `_select_merged_index` right after sees final, accurate
            # `len(list_view.children)` counts (see `Section.set_files`).
            await panel.set_files(staged_files, unstaged_files)
            self._select_merged_index(merged_index)
        finally:
            self._programmatic_refresh = False
        self._sync_diff_view()
        self.sub_title = f"{len(staged_files)} staged, {len(unstaged_files)} changed"

    def _merged_index_of_active(self) -> int | None:
        """Position of the currently active file in the merged (staged,
        then unstaged) list, as displayed right now — i.e. before a refresh
        rebuilds either section."""
        file_diff, source = self._active_selection()
        if file_diff is None:
            return None
        panel = self.query_one(ChangesPanel)
        if source == "staged":
            return panel.staged_section.list_view.index
        n_staged = len(panel.staged_section.list_view.children)
        return n_staged + (panel.unstaged_section.list_view.index or 0)

    def _select_merged_index(self, merged_index: int | None) -> None:
        """Select whatever file now sits at `merged_index` in the merged
        list — after removing an item, this is exactly "the file that slid
        up to fill the gap", staged or unstaged, whichever it lands on.
        """
        if merged_index is None:
            return
        panel = self.query_one(ChangesPanel)
        staged_lv = panel.staged_section.list_view
        unstaged_lv = panel.unstaged_section.list_view
        total = len(staged_lv.children) + len(unstaged_lv.children)
        if total == 0:
            return
        index = min(merged_index, total - 1)
        was_in_file_list = self.focused in (staged_lv, unstaged_lv)
        if index < len(staged_lv.children):
            staged_lv.index = index
            self._active_section = "staged"
            if was_in_file_list:
                staged_lv.focus()
        else:
            unstaged_lv.index = index - len(staged_lv.children)
            self._active_section = "unstaged"
            if was_in_file_list:
                unstaged_lv.focus()
        self._update_active_section_classes()

    def _update_active_section_classes(self) -> None:
        """Mark whichever section is `_active_section` with the "active"
        class so the CSS can highlight only its selection brightly — the
        other section's remembered highlight stays muted, so it never reads
        as "there's a cursor here too".
        """
        panel = self.query_one(ChangesPanel)
        panel.staged_section.set_class(self._active_section == "staged", "active")
        panel.unstaged_section.set_class(self._active_section == "unstaged", "active")

    def _active_selection(self) -> tuple[FileDiff | None, str]:
        """The file currently "in view", and whether it's the staged or
        unstaged side — driven by `self._active_section`, not by whatever
        currently has keyboard focus (focus moves into the diff panel, which
        isn't itself a section; and this must stay correct through a
        post-action refresh, before any new Highlighted event has fired).
        """
        panel = self.query_one(ChangesPanel)
        section = (
            panel.staged_section if self._active_section == "staged" else panel.unstaged_section
        )
        file_diff = section.selected_file_diff
        if file_diff is not None:
            return file_diff, self._active_section
        # The active section is now empty (e.g. its last file just got fully
        # staged/unstaged) — fall back to whichever section still has one.
        other = panel.unstaged_section if self._active_section == "staged" else panel.staged_section
        other_source = "unstaged" if self._active_section == "staged" else "staged"
        return other.selected_file_diff, other_source

    async def action_stage(self) -> None:
        if self._diff_panel_focused():
            await self._stage_current_hunk(stage=True)
            return
        file_diff, source = self._active_selection()
        if file_diff is None:
            return
        if source == "staged":
            self.notify("Already staged", severity="warning")
            return
        await self._run_git(lambda: git.stage_file(file_diff.path, cwd=self.cwd))

    async def action_unstage(self) -> None:
        if self._diff_panel_focused():
            await self._stage_current_hunk(stage=False)
            return
        file_diff, source = self._active_selection()
        if file_diff is None:
            return
        if source == "unstaged":
            self.notify("Not staged yet", severity="warning")
            return
        await self._run_git(lambda: git.unstage_file(file_diff.path, cwd=self.cwd))

    def action_toggle_line(self) -> None:
        self.query_one(SideBySideDiff).toggle_current_line()

    def _diff_panel_focused(self) -> bool:
        return self.focused is self.query_one(SideBySideDiff).before_pane

    async def _stage_current_hunk(self, stage: bool) -> None:
        diff_view = self.query_one(SideBySideDiff)
        hunk = diff_view.current_hunk
        if hunk is None:
            return
        file_diff, source = self._active_selection()
        if file_diff is None:
            return
        if stage and source == "staged":
            self.notify("Already staged", severity="warning")
            return
        if not stage and source == "unstaged":
            self.notify("Not staged yet", severity="warning")
            return
        # Checked lines if any are checked; otherwise just the current
        # change block under the cursor (both its sides) — never the rest
        # of the hunk, which may hold other, unrelated blocks the cursor
        # isn't pointing at (see `SideBySideDiff.staging_indices`).
        selected = diff_view.staging_indices()
        patch = hunk.as_patch(file_diff, selected_indices=selected)
        await self._run_git(
            lambda: git.apply_patch(patch, cached=True, reverse=not stage, cwd=self.cwd)
        )

    async def _run_git(self, action) -> None:
        try:
            action()
        except subprocess.CalledProcessError as exc:
            self.notify(f"git failed: {exc.stderr}", severity="error")
            return
        await self.action_refresh()

    @on(ListView.Highlighted)
    def _on_file_highlighted(self, event: ListView.Highlighted) -> None:
        if self._programmatic_refresh:
            # A stale event from the *inactive* section's own by-path
            # preservation during `action_refresh` — `_select_merged_index`
            # already decided the authoritative active section/file.
            return
        panel = self.query_one(ChangesPanel)
        if event.list_view is panel.staged_section.list_view:
            self._active_section = "staged"
        elif event.list_view is panel.unstaged_section.list_view:
            self._active_section = "unstaged"
        self._update_active_section_classes()
        self._sync_diff_view()

    def _sync_diff_view(self) -> None:
        file_diff, source = self._active_selection()
        diff_view = self.query_one(SideBySideDiff)
        diff_view.show_file(file_diff, source)

    def on_key(self, event) -> None:
        """Let ↑/↓ flow across the Staged/Changes boundary, so reaching a
        file in the other section never requires Tab — pressing Down at the
        bottom of "Staged Changes" moves into the top of "Changes", and Up at
        the top of "Changes" moves into the bottom of "Staged Changes" (and
        vice-versa isn't needed the other way since each list already
        handles interior movement on its own).
        """
        if event.key not in ("up", "down"):
            return
        panel = self.query_one(ChangesPanel)
        staged_lv = panel.staged_section.list_view
        unstaged_lv = panel.unstaged_section.list_view
        if self.focused is staged_lv:
            at_bottom = staged_lv.index is not None and staged_lv.index >= len(staged_lv.children) - 1
            if event.key == "down" and at_bottom and unstaged_lv.children:
                event.stop()
                self._move_file_focus(unstaged_lv, 0, "unstaged")
        elif self.focused is unstaged_lv:
            at_top = unstaged_lv.index == 0
            if event.key == "up" and at_top and staged_lv.children:
                event.stop()
                self._move_file_focus(staged_lv, len(staged_lv.children) - 1, "staged")

    def _move_file_focus(self, list_view: ListView, index: int, section: str) -> None:
        """Move focus (and the logical "active section") to `list_view`.

        Setting `.index` alone doesn't reliably fire `ListView.Highlighted`
        (e.g. it's a no-op if the target list already happens to be
        highlighting that same index) — so `_active_section`/the diff view
        are updated explicitly here rather than relying on that event.
        """
        list_view.focus()
        list_view.index = index
        self._active_section = section
        self._update_active_section_classes()
        self._sync_diff_view()


def main() -> None:
    GitDiffApp().run()


if __name__ == "__main__":
    main()
