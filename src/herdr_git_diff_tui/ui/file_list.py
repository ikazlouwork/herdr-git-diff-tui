"""Left column (2/12 grid width): the list of changed files.

See SPEC.md section 4.1.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import ListItem, ListView, Label

from ..diff_parser import FileDiff

_STATUS_STYLE = {
    "A": "bold green",
    "D": "bold red",
    "M": "bold yellow",
}


def status_letter(file_diff: FileDiff) -> str:
    if file_diff.is_new:
        return "A"
    if file_diff.is_deleted:
        return "D"
    return "M"


class FileListItem(ListItem):
    def __init__(self, file_diff: FileDiff) -> None:
        self.file_diff = file_diff
        status = status_letter(file_diff)
        style = _STATUS_STYLE.get(status, "white")
        text = Text(overflow="ellipsis")
        text.append(f"{status} ", style=style)
        text.append(file_diff.path)
        text.append(f"\n  +{file_diff.insertions} ", style="green")
        text.append(f"-{file_diff.deletions}", style="red")
        super().__init__(Label(text))


class FileListPanel(ListView):
    """Shows path, status (M/A/D/R), and +/- line counts per changed file."""

    def set_files(self, files: list[FileDiff]) -> None:
        """Replace the list contents, trying to preserve the current selection by path."""
        previous_path = self.selected_file_diff.path if self.selected_file_diff else None
        self.clear()
        for file_diff in files:
            self.append(FileListItem(file_diff))
        if not files:
            return
        new_index = 0
        if previous_path:
            for i, f in enumerate(files):
                if f.path == previous_path:
                    new_index = i
                    break
        self.index = new_index

    @property
    def selected_file_diff(self) -> FileDiff | None:
        if self.highlighted_child is None:
            return None
        return self.highlighted_child.file_diff  # type: ignore[attr-defined]
