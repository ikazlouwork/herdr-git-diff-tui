"""Left column (2/12 grid width): the list of changed files.

Placeholder widget — see SPEC.md section 4.1.
"""

from __future__ import annotations

from textual.widgets import ListView


class FileListPanel(ListView):
    """Shows path, status (M/A/D/R), and +/- line counts per changed file."""
