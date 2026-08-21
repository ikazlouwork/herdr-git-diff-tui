# herdr-git-diff-tui

A [herdr](https://herdr.dev) plugin: a `lazygit`-style TUI panel for viewing git diffs
with staging/unstaging support, opened right inside a herdr session via a hotkey.

See [SPEC.md](SPEC.md) for the full specification (goals, scope, architecture).

## Status

Draft / pre-MVP. Not yet functional.

## Development

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

Run the app (once implemented):

```bash
python -m herdr_git_diff_tui
```
