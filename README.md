# herdr-git-diff-tui

A [herdr](https://herdr.dev) plugin: a `lazygit`-style TUI panel for viewing git diffs
with staging/unstaging support, opened right inside a herdr session via a hotkey.

See [SPEC.md](SPEC.md) for the full specification (goals, scope, architecture).

## Status

MVP implemented and functional (side-by-side diff viewer, file/hunk/line staging).
Not yet wired up as an actual herdr plugin/hotkey (see SPEC.md section 5) — for now,
run it directly as below, from inside the git repo you want to view.

## Development

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Running

From inside the git repository whose diff you want to view:

```bash
python -m herdr_git_diff_tui
```

Or via the dependency-free bootstrap script, which locates/creates the plugin's own
`.venv` and installs dependencies for you (this is what herdr will eventually invoke):

```bash
python bin/bootstrap.py
```

### Keybindings

**File lists** ("Staged Changes" / "Changes", both always visible):

| Key       | Action                                                        |
|-----------|-----------------------------------------------------------------|
| `↑`/`↓`   | Move selection; flows across the Staged/Changes boundary too   |
| `Tab`     | Move focus to the next section / into the diff panel            |
| `s` / `u` | Stage / unstage the whole selected file                         |

**Diff panel** (`Tab` to focus it):

| Key            | Action                                                             |
|----------------|---------------------------------------------------------------------|
| `↑`/`↓`        | Move the line-selection cursor over the current hunk's changed lines |
| `PgUp`/`PgDn`/`Home`/`End`/mouse wheel | Free scroll (both sides stay in sync)         |
| `]` / `[`      | Jump to the next / previous hunk                                    |
| `space`        | Check/uncheck the line under the cursor for line-level staging      |
| `s` / `u`      | Stage / unstage the checked lines (or the whole hunk, if none checked) |

**Global:** `r` refresh, `q` quit.

## Tests

```bash
pytest
```
