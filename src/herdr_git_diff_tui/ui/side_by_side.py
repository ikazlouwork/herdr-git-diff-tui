"""Right-hand columns (5/12 + 5/12): "before"/"after" side-by-side diff view.

Placeholder widget — see SPEC.md section 4.1 (synchronized scrolling,
per-line highlighting, syntax highlighting on both sides).
"""

from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import Static


class SideBySideDiff(Horizontal):
    """Container with two scroll-synced panes: original ("before") and current ("after")."""

    def compose(self):
        yield Static(id="before")
        yield Static(id="after")
