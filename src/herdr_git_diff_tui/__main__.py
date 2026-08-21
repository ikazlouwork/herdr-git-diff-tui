"""Entry point: `python -m herdr_git_diff_tui`.

Root Textual application wiring the file list + side-by-side diff panel + a
staging/unstaging workflow. See SPEC.md section 4 for the MVP scope.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from . import git
from .diff_parser import parse_unified_diff
from .ui.file_list import FileListPanel
from .ui.side_by_side import SideBySideDiff


class GitDiffApp(App):
    """Root Textual application for the git diff TUI panel."""

    TITLE = "herdr-git-diff-tui"
    CSS = """
    Horizontal#root {
        height: 1fr;
    }
    FileListPanel {
        width: 2fr;
        border-right: solid $panel;
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
        ("t", "toggle_staged", "Toggle staged/unstaged"),
        ("s", "stage", "Stage"),
        ("u", "unstage", "Unstage"),
    ]
    # Tab / Shift+Tab switch focus between the file list and diff panel via
    # Textual's built-in focus_next/focus_previous (Screen-level bindings).

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self.cwd = cwd or str(Path.cwd())
        self.staged = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="root"):
            yield FileListPanel(id="file-list")
            yield SideBySideDiff(id="diff-view")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        self.query_one("#file-list", FileListPanel).focus()

    def action_refresh(self) -> None:
        try:
            raw = git.diff_unified(self.staged, cwd=self.cwd)
        except subprocess.CalledProcessError as exc:
            self.notify(f"git diff failed: {exc.stderr}", severity="error")
            return
        files = parse_unified_diff(raw)
        file_list = self.query_one("#file-list", FileListPanel)
        file_list.set_files(files)
        self._sync_diff_view()
        source = "staged" if self.staged else "working tree"
        self.sub_title = f"{source} — {len(files)} file(s) changed"

    def action_toggle_staged(self) -> None:
        self.staged = not self.staged
        self.action_refresh()

    def action_stage(self) -> None:
        self._stage_or_unstage(staging=True)

    def action_unstage(self) -> None:
        self._stage_or_unstage(staging=False)

    def _stage_or_unstage(self, staging: bool) -> None:
        file_list = self.query_one("#file-list", FileListPanel)
        diff_view = self.query_one("#diff-view", SideBySideDiff)
        file_diff = file_list.selected_file_diff
        if file_diff is None:
            return

        diff_focused = self.focused in (diff_view.before_pane, diff_view.after_pane)
        try:
            if diff_focused and diff_view.current_hunk is not None:
                patch = diff_view.current_hunk.as_patch(file_diff)
                if staging:
                    if self.staged:
                        self.notify("Already viewing staged changes", severity="warning")
                        return
                    git.apply_patch(patch, cached=True, cwd=self.cwd)
                else:
                    if not self.staged:
                        self.notify("Nothing to unstage in working-tree view", severity="warning")
                        return
                    git.apply_patch(patch, cached=True, reverse=True, cwd=self.cwd)
            else:
                if staging:
                    git.stage_file(file_diff.path, cwd=self.cwd)
                else:
                    git.unstage_file(file_diff.path, cwd=self.cwd)
        except subprocess.CalledProcessError as exc:
            self.notify(f"git failed: {exc.stderr}", severity="error")
            return

        self.action_refresh()

    @on(FileListPanel.Highlighted)
    def _on_file_highlighted(self) -> None:
        self._sync_diff_view()

    def _sync_diff_view(self) -> None:
        file_list = self.query_one("#file-list", FileListPanel)
        diff_view = self.query_one("#diff-view", SideBySideDiff)
        diff_view.show_file(file_list.selected_file_diff)

    def on_key(self, event) -> None:
        diff_view = self.query_one("#diff-view", SideBySideDiff)
        if self.focused in (diff_view.before_pane, diff_view.after_pane):
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
