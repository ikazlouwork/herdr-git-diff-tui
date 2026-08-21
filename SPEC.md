---
title: herdr Git Diff TUI — Specification
status: draft
date: 2026-08-21
---

# herdr Git Diff TUI

A plugin for [herdr](https://herdr.dev) — a TUI panel for viewing git diffs with
staging/unstaging support, opened right inside a herdr session via a hotkey.

## 1. Goal and motivation

- Working from herdr with several agents (Claude Code, Codex, etc.) running in different
  panes, there's a need for a fast way to see what an agent changed in the repo, without
  switching to a separate terminal/IDE.
- herdr itself does not provide a diff viewer — only a generic mechanism for panes and
  running arbitrary commands. So we write the viewer ourselves; herdr is just the host.
- UX reference: the diff panel in `lazygit` (file list on one side, diff on the other,
  hunk- and line-level staging).

## 2. Technology stack

| Component      | Choice                                    |
|-----------------|--------------------------------------------|
| Language        | Python 3.11+ (confirmed: 3.14.7 in PATH)   |
| TUI framework    | [Textual](https://textual.textualize.io)  |
| Git access       | wrapper over the `git` CLI via `subprocess` (no libgit2/pygit2 — fewer install-time dependencies) |
| Packaging        | see section 3 |

Why Python/Textual: faster to iterate, a rich ready-made widget stack (lists, diffs,
syntax highlighting already available via `rich`/`pygments`, which Textual depends on).

Deliberate trade-off: unlike a Rust/Go binary, the plugin needs an interpreter and a
virtual environment on the user's machine — addressed in section 3.

## 3. Distribution and launch (key MVP risk)

herdr launches a plugin as an arbitrary command (`command = [...]` in the manifest). Since
Python is not a self-contained binary, behavior must be predictable regardless of what the
user's system `python`/`PATH` currently points to.

Solution:

1. On plugin install (a `build` hook in `herdr-plugin.toml`), create an isolated venv inside
   the plugin directory: `<plugin_dir>/.venv`, and install Textual and other dependencies
   from `requirements.txt`/`pyproject.toml` into it.
2. Entry point — a thin shell/bat script (`bin/herdr-git-diff-tui`) that:
   - locates a system Python (tries `python3`, then `python`, checks version ≥ 3.11);
   - if the plugin's venv is missing or broken — rebuilds it (falls back to the build hook);
   - runs `./.venv/bin/python -m herdr_git_diff_tui` (or `.venv\Scripts\python.exe` on
     Windows), forwarding all argv.
3. No global package installs (`pip install --user ...`) — everything is isolated inside
   the plugin's own folder, so it doesn't conflict with the user's other projects.
4. Cross-platform note: since the user is on Windows (PowerShell/Git Bash), the entry-point
   script must also work on macOS/Linux (for other herdr users) — we ship two wrappers
   (`.sh` and `.ps1`/`.cmd`), or preferably a single dependency-free Python bootstrap script
   that finds/creates the venv itself (preferred — less duplication).

Open question for the MVP: for now we target Windows + the user's current machine;
cross-platform support is best-effort, not a release blocker for v0.1.

## 4. MVP functional scope

### 4.1 Viewing

**Screen layout (12-column grid):**

| Zone                      | Width (of 12) | Content                                    |
|---------------------------|---------------|---------------------------------------------|
| Changed files list        | 2             | path, status (M/A/D/R), +/- line counts    |
| "Before"                  | 5             | file content prior to the change (side A)  |
| "After"                   | 5             | file content after the change (side B)     |

I.e. the primary viewing mode is a **side-by-side diff**, not unified: a narrow navigation
column on the left (2/12) listing files, and on the right two equal-width columns (5/12 +
5/12) showing the original and current version of the selected file, scrolled in sync,
with per-line highlighting of added/removed/changed lines (like the split view in most
IDEs). A unified diff (single column with +/-) as an alternative display mode is not part
of the MVP, but the layout should not preclude adding it later behind a toggle.

- Diff sources:
  - working tree vs index (`git diff`) — unstaged changes;
  - index vs HEAD (`git diff --staged`) — staged changes;
  - an arbitrary commit/range — **out of scope for MVP**, a future extension.
- Diff panel for the selected file: side-by-side "before/after" with +/- line highlighting
  and syntax highlighting in both columns.
- Navigation:
  - file list ↑/↓, Enter/click — select a file;
  - synchronized scrolling of both diff columns (arrows/PgUp/PgDn/mouse) — both sides move
    together so corresponding lines stay aligned;
  - switching focus between the file list and the diff area (Tab).
- Toggling the diff source: a key to switch between working ⇄ staged.
- Manual refresh via a hotkey (`r`) — no auto-watch in the MVP (auto-refresh is a future
  extension).

### 4.2 Staging / unstaging
- Stage/unstage an entire file (`s` — stage, `u` — unstage) from the file list.
- Stage/unstage an individual hunk while positioned in the diff panel with the cursor on
  that hunk (`s`/`u` in the context of the selected hunk → `git apply --cached` of the
  corresponding patch).
- Line-level (partial hunk) staging — **out of scope for MVP** (patch parsing/reassembly
  complexity is high; do this after hunk-level staging is proven out).
- No destructive operations (discard/checkout --) in the MVP — stage/unstage only.

### 4.3 Explicitly out of scope for MVP
- Merge conflicts and resolving them.
- History/log browsing of past commits.
- Line-level partial-hunk staging.
- Auto-refresh on file changes (a file watcher).
- Configuration (colors/keybindings) — reasonable defaults are hardcoded.

## 5. Integration with herdr

- `herdr-plugin.toml` manifest:
  - `[[panes]]` with `placement = "split"` (opens as a split in the current tab; `popup`/
    `zoomed` to be discussed after the first run — split is the easiest to debug).
  - `command` — the entry point from section 3, `cwd` — the current workspace's working
    directory (herdr should pass this via env/context — the exact variable name needs to
    be confirmed against `docs/socket-api` during implementation).
  - default keybinding: `prefix+d` → an action that opens the panel.
- The plugin runs as a standalone TUI process inside the pane (full-screen within the pane),
  rather than via custom graphics/socket streaming — the simplest and most reliable
  integration mode for v0.1.
- Direct use of the herdr socket API is not required for the MVP — all logic (git
  operations) is handled locally by the plugin via `subprocess`. The socket API is left for
  the future (e.g. to hit `pane.read`/notify other agents about staged changes).

## 6. Plugin architecture (draft)

```
herdr-git-diff-tui/
├── herdr-plugin.toml
├── bin/
│   └── bootstrap.py          # locates/creates the venv, launches the app
├── src/
│   └── herdr_git_diff_tui/
│       ├── __init__.py
│       ├── __main__.py        # entry point (textual App)
│       ├── git.py             # wrapper over the git CLI: status, diff, apply --cached
│       ├── diff_parser.py     # unified diff parsing → structures (files, hunks, lines)
│       └── ui/
│           ├── file_list.py       # left column (2/12), changed files list
│           └── side_by_side.py    # right columns (5/12 + 5/12), "before"/"after"
├── requirements.txt           # textual, (optionally) pygments
├── tests/
│   └── ...
└── SPEC.md                    # this file
```

## 7. Open questions (to resolve before/during implementation)

1. How exactly does herdr pass the current workspace's working directory to the plugin
   (an env var? the process's default cwd?) — verify against `docs/socket-api`/`docs/plugins`
   during implementation.
2. `popup` vs `split` vs `zoomed` — which placement is more convenient in actual use;
   decide empirically after the MVP.
3. Do we need support for repositories with submodules — assumed no, for now.
4. Minimum Python version to support (3.11+ proposed, as a reasonable floor for current
   Textual) — confirm.

## 8. MVP Definition of Done

- [ ] The plugin installs and opens via a hotkey in a real herdr session on the user's machine.
- [ ] Shows the list of changed files for working tree and staged, separately.
- [ ] Shows the selected file's diff with +/- and syntax highlighting.
- [ ] Stages/unstages an entire file.
- [ ] Stages/unstages an individual hunk.
- [ ] Manual refresh works and doesn't unnecessarily lose the current selection/scroll
      position.
- [ ] Works against the user's own repository (dogfooding) for at least one working day
      without crashing.
