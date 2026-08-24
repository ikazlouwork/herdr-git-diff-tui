from herdr_git_diff_tui.diff_parser import parse_unified_diff
from herdr_git_diff_tui.ui.side_by_side import SideBySideDiff, change_blocks

# Three change blocks: a modified line (remove + two adds), a pure deletion,
# and a pure addition.
MIXED_DIFF = """\
diff --git a/foo.py b/foo.py
index e69de29..0cfbf08 100644
--- a/foo.py
+++ b/foo.py
@@ -1,5 +1,6 @@
 line1
-line2
+line2 modified
+line2.5 added
 line3
-line4
 line5
+line6
"""


def _hunk():
    return parse_unified_diff(MIXED_DIFF)[0].hunks[0]


def test_change_blocks_groups_by_contiguous_run():
    blocks = change_blocks(_hunk())
    assert [(b.old, b.new) for b in blocks] == [
        ([1], [2, 3]),
        ([5], []),
        ([], [7]),
    ]


def _diff_view(file_diff):
    """A `SideBySideDiff` with rendering/scrolling stubbed out, so cursor
    logic can be exercised without a mounted Textual app."""
    view = SideBySideDiff()
    view._refresh_panes = lambda: None
    view._ensure_cursor_visible = lambda: None
    view.file_diff = file_diff
    view.current_hunk_index = 0
    view._reset_cursor()
    return view


def test_cursor_defaults_to_old_side_of_first_block():
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    assert view.cursor_flat_index == 0
    assert view.cursor_side == "old"
    assert view._active_indices() == [1]


def test_move_side_switches_to_new_and_back():
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.move_side("right")
    assert view.cursor_side == "new"
    assert view._active_indices() == [2, 3]
    view.move_side("left")
    assert view.cursor_side == "old"


def test_move_side_jumps_to_nearest_block_with_that_side():
    # Block 1 is a pure deletion (no "new" at all) -- `→` there shouldn't
    # just sit still; it should hunt forward for the nearest block that
    # does have a "new" side (block 2, a pure addition) and land there.
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.next_block()  # block 1: pure deletion, only "old" exists
    assert view.cursor_flat_index == 1
    view.move_side("right")
    assert view.cursor_flat_index == 2
    assert view.cursor_side == "new"


def test_move_side_jumps_backward_too():
    # Symmetric case: block 2 is a pure addition (no "old") -- `←` hunts
    # backward for the nearest block with an "old" side (block 1).
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.next_block()
    view.next_block()  # block 2: pure addition, only "new" exists
    assert view.cursor_flat_index == 2
    view.move_side("left")
    assert view.cursor_flat_index == 1
    assert view.cursor_side == "old"


ADDITIONS_ONLY_DIFF = """\
diff --git a/foo.py b/foo.py
new file mode 100644
index 0000000..0cfbf08 100644
--- /dev/null
+++ b/foo.py
@@ -0,0 +1,2 @@
+line1
+line2
"""


def test_move_side_is_a_true_noop_when_no_block_has_that_side_at_all():
    # A brand-new file's hunk is nothing but pure additions -- there is no
    # "old" anywhere to jump to, so `←` must genuinely do nothing.
    view = _diff_view(parse_unified_diff(ADDITIONS_ONLY_DIFF)[0])
    assert view.cursor_side == "new"
    view.move_side("left")
    assert view.cursor_side == "new"
    assert view.cursor_flat_index == 0


def test_next_block_settles_on_the_only_available_side():
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.move_side("right")  # block 0, side "new"
    view.next_block()  # block 1 is pure deletion -> falls back to "old"
    assert view.cursor_flat_index == 1
    assert view.cursor_side == "old"
    view.next_block()  # block 2 is pure addition -> falls back to "new"
    assert view.cursor_flat_index == 2
    assert view.cursor_side == "new"


def test_toggle_current_line_selects_whole_side_as_one_unit():
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.move_side("right")  # block 0, side "new" -> indices [2, 3]
    view.toggle_current_line()
    assert view.selected_lines[0] == {2, 3}
    # Toggling again with the whole group selected clears it, not just one.
    view.toggle_current_line()
    assert view.selected_lines[0] == set()


def test_toggle_current_line_checks_partial_selection_fully_first():
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.move_side("right")
    view.selected_lines[0] = {2}  # only one of the two "new" lines checked
    view.toggle_current_line()
    assert view.selected_lines[0] == {2, 3}  # completes the group, not clears it


TWO_HUNK_DIFF = """\
diff --git a/foo.py b/foo.py
index e69de29..0cfbf08 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 line1
-line2
+line2 modified
 line3
@@ -20,3 +20,3 @@
 line20
-line21
+line21 modified
 line22
"""


def test_next_block_crosses_hunk_boundary_without_a_dedicated_key():
    # No hunk-jump key anymore -- ↑/↓ alone must walk from the last block
    # of one hunk straight into the first block of the next.
    view = _diff_view(parse_unified_diff(TWO_HUNK_DIFF)[0])
    assert view.current_hunk_index == 0
    view.next_block()
    assert view.current_hunk_index == 1
    assert view.cursor_flat_index == 1
    view.prev_block()
    assert view.current_hunk_index == 0
    assert view.cursor_flat_index == 0


def test_staging_indices_defaults_to_current_block_only():
    # Regression: staging with nothing explicitly checked must act on just
    # the block under the cursor, not the whole hunk's other, unrelated
    # blocks (reported as "staging one change transfers both").
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    assert view.staging_indices() == {1, 2, 3}  # block 0 only: old + new
    view.next_block()  # block 1: pure deletion
    assert view.staging_indices() == {5}
    view.next_block()  # block 2: pure addition
    assert view.staging_indices() == {7}


def test_staging_indices_prefers_explicit_checks_over_the_cursor():
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    view.move_side("right")
    view.toggle_current_line()  # checks {2, 3}, cursor still on block 0
    view.next_block()  # move away -- checked lines live in the hunk, not the cursor
    assert view.staging_indices() == {2, 3}


def test_side_highlight_only_shown_while_diff_panel_focused():
    # Regression: the active-side border used to be driven by
    # `before_pane.has_focus`, which Textual's own internal Focus/Blur
    # handlers update with no guaranteed ordering relative to ours -- so it
    # could read stale right when we needed it. `_on_focus_change` is fed
    # straight from the Focus/Blur events instead.
    view = _diff_view(parse_unified_diff(MIXED_DIFF)[0])
    assert "-active-side" not in view.before_pane.classes
    assert "-active-side" not in view.after_pane.classes

    view._on_focus_change(True)
    assert "-active-side" in view.before_pane.classes  # cursor defaults to "old"
    assert "-active-side" not in view.after_pane.classes

    view._on_focus_change(False)
    assert "-active-side" not in view.before_pane.classes
    assert "-active-side" not in view.after_pane.classes

    view.move_side("right")  # cursor state persists across the blur
    view._on_focus_change(True)
    assert "-active-side" not in view.before_pane.classes
    assert "-active-side" in view.after_pane.classes
