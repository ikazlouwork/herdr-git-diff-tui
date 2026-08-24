"""Left column: two always-visible sections, "Staged Changes" and "Changes"
(VS Code's Source Control view). Unlike a single list toggled between staged
and unstaged, both are shown at once — staging/unstaging a file is visible as
it moving from one section to the other, not as the whole view flipping.
See SPEC.md section 4.1/4.2.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView

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
        text.append(f"  +{file_diff.insertions}", style="green")
        text.append(f" -{file_diff.deletions}", style="red")
        super().__init__(Label(text))


class Section(Vertical):
    """One labeled group ("Staged Changes" / "Changes") with its own ListView."""

    def __init__(self, title: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self.header = Label(self._header_text(0), classes="section-header")
        self.list_view = ListView()

    def _header_text(self, count: int) -> str:
        return f"{self.title_text.upper()} ({count})"

    def compose(self) -> ComposeResult:
        yield self.header
        yield self.list_view

    async def set_files(self, files: list[FileDiff]) -> None:
        """Replace the section's contents, preserving selection by path.

        Awaits the underlying `clear`/`append` (both return an awaitable that
        only resolves once the DOM is actually updated) — callers that need
        an accurate `len(list_view.children)` right after this returns (see
        `GitDiffApp._select_merged_index`) depend on that.
        """
        previous_path = self.selected_file_diff.path if self.selected_file_diff else None
        await self.list_view.clear()
        for file_diff in files:
            await self.list_view.append(FileListItem(file_diff))
        self.header.update(self._header_text(len(files)))
        if not files:
            return
        new_index = 0
        if previous_path:
            for i, f in enumerate(files):
                if f.path == previous_path:
                    new_index = i
                    break
        self.list_view.index = new_index

    @property
    def selected_file_diff(self) -> FileDiff | None:
        item = self.list_view.highlighted_child
        return item.file_diff if item is not None else None  # type: ignore[attr-defined]


class ChangesPanel(Vertical):
    """The whole left column: Staged Changes on top, Changes (unstaged) below."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.staged_section = Section("Staged Changes", id="staged-section")
        self.unstaged_section = Section("Changes", id="unstaged-section")

    def compose(self) -> ComposeResult:
        yield self.staged_section
        yield self.unstaged_section

    async def set_files(self, staged: list[FileDiff], unstaged: list[FileDiff]) -> None:
        await self.staged_section.set_files(staged)
        await self.unstaged_section.set_files(unstaged)
