"""Entry point: `python -m herdr_git_diff_tui`.

Placeholder App shell — see SPEC.md section 4 for the intended MVP scope
(file list + side-by-side diff + staging).
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class GitDiffApp(App):
    """Root Textual application for the git diff TUI panel."""

    TITLE = "herdr-git-diff-tui"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Not yet implemented — see SPEC.md.", id="placeholder")
        yield Footer()

    def action_refresh(self) -> None:
        pass


def main() -> None:
    GitDiffApp().run()


if __name__ == "__main__":
    main()
