"""Entry point: `python -m herdr_git_diff_tui`.

Root Textual application wiring the file list + side-by-side diff panel + a
staging/unstaging workflow. See SPEC.md section 4 for the MVP scope.

Staging UX (VS Code Source Control-style, see SPEC.md section 4.2): the left
column always shows both "Staged Changes" and "Changes" sections at once —
staging/unstaging a file moves it between the two live, rather than the whole
view flipping between two modes. Hunks are staged/unstaged individually via a
checkbox next to the hunk header in the diff panel (space bar).
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
    .section-header {
        color: $text-muted;
        text-style: bold;
        padding: 1 1 0 1;
    }
    SideBySideDiff {
        width: 10fr;
    }
    DiffPane {
        width: 1fr;
    }
    DiffPane#before {
        border-right: solid $panel;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("s", "stage", "Stage"),
        ("u", "unstage", "Unstage"),
        ("space", "toggle_hunk", "Stage/unstage hunk"),
    ]
    # Tab / Shift+Tab switch focus between the two file-list sections and the
    # diff panel via Textual's built-in focus_next/focus_previous.

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self.cwd = cwd or str(Path.cwd())
        # Which section last had a highlighted item — the source of truth for
        # "what am I looking at", independent of whatever currently has
        # keyboard focus (so it still holds once focus moves into the diff
        # panel, and doesn't go stale mid-refresh; see _active_selection).
        self._active_section = "unstaged"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="root"):
            yield ChangesPanel(id="changes")
            yield SideBySideDiff(id="diff-view")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        panel = self.query_one(ChangesPanel)
        if panel.unstaged_section.selected_file_diff is not None:
            self._active_section = "unstaged"
            panel.unstaged_section.list_view.focus()
        else:
            self._active_section = "staged"
            panel.staged_section.list_view.focus()
        self._sync_diff_view()

    def action_refresh(self) -> None:
        try:
            staged_raw = git.diff_unified(True, cwd=self.cwd)
            unstaged_raw = git.diff_unified(False, cwd=self.cwd)
        except subprocess.CalledProcessError as exc:
            self.notify(f"git diff failed: {exc.stderr}", severity="error")
            return
        staged_files = parse_unified_diff(staged_raw)
        unstaged_files = parse_unified_diff(unstaged_raw)
        panel = self.query_one(ChangesPanel)
        panel.set_files(staged_files, unstaged_files)
        self._sync_diff_view()
        self.sub_title = f"{len(staged_files)} staged, {len(unstaged_files)} changed"

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

    def action_stage(self) -> None:
        file_diff, source = self._active_selection()
        if file_diff is None:
            return
        if source == "staged":
            self.notify("Already staged", severity="warning")
            return
        self._run_git(lambda: git.stage_file(file_diff.path, cwd=self.cwd))

    def action_unstage(self) -> None:
        file_diff, source = self._active_selection()
        if file_diff is None:
            return
        if source == "unstaged":
            self.notify("Not staged yet", severity="warning")
            return
        self._run_git(lambda: git.unstage_file(file_diff.path, cwd=self.cwd))

    def action_toggle_hunk(self) -> None:
        diff_view = self.query_one(SideBySideDiff)
        if self.focused is not diff_view.before_pane or diff_view.current_hunk is None:
            return
        file_diff, source = self._active_selection()
        if file_diff is None:
            return
        patch = diff_view.current_hunk.as_patch(file_diff)
        if source == "unstaged":
            self._run_git(lambda: git.apply_patch(patch, cached=True, cwd=self.cwd))
        else:
            self._run_git(
                lambda: git.apply_patch(patch, cached=True, reverse=True, cwd=self.cwd)
            )

    def _run_git(self, action) -> None:
        try:
            action()
        except subprocess.CalledProcessError as exc:
            self.notify(f"git failed: {exc.stderr}", severity="error")
            return
        self.action_refresh()

    @on(ListView.Highlighted)
    def _on_file_highlighted(self, event: ListView.Highlighted) -> None:
        panel = self.query_one(ChangesPanel)
        if event.list_view is panel.staged_section.list_view:
            self._active_section = "staged"
        elif event.list_view is panel.unstaged_section.list_view:
            self._active_section = "unstaged"
        self._sync_diff_view()

    def _sync_diff_view(self) -> None:
        file_diff, source = self._active_selection()
        diff_view = self.query_one(SideBySideDiff)
        diff_view.show_file(file_diff, source)

    def on_key(self, event) -> None:
        diff_view = self.query_one(SideBySideDiff)
        if self.focused is diff_view.before_pane:
            if event.key == "down":
                diff_view.next_hunk()
                event.stop()
            elif event.key == "up":
                diff_view.prev_hunk()
                event.stop()


def main() -> None:
    GitDiffApp().run()


if __name__ == "__main__":
    main()
