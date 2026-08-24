---
title: herdr Git Diff TUI — Specification
status: MVP implemented (see section 8) — not yet wired up as a herdr plugin
date: 2026-08-24
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

As implemented, this diverged in a few deliberate ways from the original draft below
(both diff sources always visible instead of a toggle; line-level staging turned out
necessary and shipped after all) — the differences and why are called out inline.

### 4.1 Viewing

**Screen layout:** a narrower left column listing changed files, and on the right two
equal-width columns showing the original ("before") and current ("after") version of the
selected file, scrolled in sync, with per-line highlighting of added/removed lines — a
side-by-side diff, not unified (like the split view in most IDEs). A unified diff (single
column with +/-) as an alternative display mode is not implemented, but the layout
doesn't preclude adding it later behind a toggle.

- Diff sources — **both shown at once**, not toggled: the left column always has two
  live sections, "Staged Changes" (index vs `HEAD`) and "Changes" (working tree vs
  index), VS Code Source Control-style. Staging/unstaging a file is visible as it moving
  between the two sections, rather than the whole view flipping between two modes — this
  is a deliberate change from the toggle originally sketched above, made once staging
  from either side turned out to be common enough that switching context to see it wasn't
  worth the visibility. An arbitrary commit/range as a diff source is still out of scope.
- Diff panel for the selected file: side-by-side "before/after" with +/- line
  highlighting and syntax highlighting (via `pygments`) in both columns. Rather than a
  full-file diff3-style alignment, each hunk (with git's default surrounding context) is
  rendered as its own block, separated by a "⋯" marker — see `ui/side_by_side.py`.
- Navigation — three separate, non-overlapping ways to move, so no single key pair is
  overloaded with several meanings:
  - file lists: `↑`/`↓` move the selection and flow across the Staged/Changes boundary
    directly (reaching the other section never needs `Tab`); `Tab`/`Shift+Tab` moves
    focus between the two sections and into the diff panel.
  - diff panel (`Tab` to focus it — only the "before" side is a tab stop, since both
    sides scroll/highlight in lockstep): changed lines are grouped into "change blocks"
    (checkbox gutter, see 4.2); `↑`/`↓` step a cursor block-to-block across *every* hunk
    in the file as one continuous sequence — no separate hunk-jump key — with the view
    auto-scrolling to keep the cursor visible; `←`/`→` pick the block's old/new side
    (highlighted border, shown only while the panel has focus);
    `PgUp`/`PgDn`/`Home`/`End`/mouse wheel do plain, free scrolling of both sides in sync.
  - a status line above the diff panel always names the active file, hunk position, and
    live `s`/`u` action, independent of keyboard focus — so "what am I looking at, and
    what would `s` do" never depends on remembering where focus is.
- Manual refresh via a hotkey (`r`) — no auto-watch (auto-refresh is a future extension).
  Refresh preserves the selection by position in the merged (Staged, then Changes) list,
  so staging/unstaging a file lands you on whatever slid up to fill the gap rather than
  resetting to the top of a section.

### 4.2 Staging / unstaging
- Stage/unstage an entire file (`s` — stage, `u` — unstage) from the file list.
- Stage/unstage a hunk from the diff panel: `s`/`u` there stage/unstage the current
  hunk as a whole, via `git apply --cached` (optionally `--reverse`) of the hunk
  rendered back into a standalone patch (`Hunk.as_patch`).
- **Line-level (partial-hunk) staging is implemented**, not out of scope as originally
  planned: each added/removed line gets a checkbox (`space` to toggle) in the diff
  panel's gutter; `s`/`u` there stage/unstage exactly the checked lines if any are
  checked, falling back to the whole hunk otherwise. The patch is built with the classic
  `git add -p` trick (see `Hunk.as_patch`'s `selected_indices` param): an unselected
  added line is dropped from the patch entirely, an unselected removed line is turned
  into context — only the two `@@` counts change, not the hunk's position.
- No destructive operations (discard/checkout --) in the MVP — stage/unstage only.

### 4.3 Explicitly out of scope for MVP
- Merge conflicts and resolving them.
- History/log browsing of past commits.
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

## 6. Plugin architecture

```
herdr-git-diff-tui/
├── herdr-plugin.toml
├── bin/
│   └── bootstrap.py          # locates/creates the venv, launches the app
├── src/
│   └── herdr_git_diff_tui/
│       ├── __init__.py
│       ├── __main__.py        # entry point + root Textual App: wires the file
│       │                      #   list, diff panel, and the staging workflow
│       ├── git.py             # wrapper over the git CLI: diff, show, add/restore,
│       │                      #   apply --cached (incl. reversed, for unstaging)
│       ├── diff_parser.py     # unified diff parsing -> FileDiff/Hunk/DiffLine, and
│       │                      #   Hunk.as_patch() (whole-hunk or line-level partial)
│       ├── content.py         # resolves before/after full file content for a FileDiff
│       └── ui/
│           ├── file_list.py       # left column: "Staged Changes" + "Changes" sections
│           └── side_by_side.py    # right columns: "before"/"after", hunk/line cursor,
│                                   #   checkboxes, scroll sync
├── requirements.txt           # textual, pygments
├── tests/
│   └── test_diff_parser.py
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
      Not yet done — herdr integration (section 5) hasn't been wired up; run directly via
      `python -m herdr_git_diff_tui` or `bin/bootstrap.py` for now (see README.md).
- [x] Shows the list of changed files for working tree and staged, separately (both
      sections always visible, VS Code Source Control-style — see 4.1).
- [x] Shows the selected file's diff with +/- and syntax highlighting.
- [x] Stages/unstages an entire file.
- [x] Stages/unstages an individual hunk.
- [x] Stages/unstages individual lines within a hunk — went beyond the original MVP
      scope (4.2 originally called this out of scope); turned out to be needed once
      hunk-level staging was in daily use.
- [x] Manual refresh works and doesn't unnecessarily lose the current selection/scroll
      position (preserved by position in the merged Staged+Changes list, see 4.1).
- [ ] Works against the user's own repository (dogfooding) for at least one working day
      without crashing — in progress; several rounds of real-usage feedback already
      folded back into the navigation/staging/highlighting model above.
