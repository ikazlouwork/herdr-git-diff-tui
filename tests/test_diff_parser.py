from herdr_git_diff_tui.diff_parser import parse_unified_diff

SIMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
index e69de29..0cfbf08 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 line1
-line2
+line2 modified
+line2.5 added
 line3
"""

NEW_FILE_DIFF = """\
diff --git a/new.py b/new.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+hello
+world
"""

DELETED_FILE_DIFF = """\
diff --git a/gone.py b/gone.py
deleted file mode 100644
index e69de29..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-hello
-world
"""

# The base file's last line ("last") has no trailing newline; the change
# appends a new line after it, which is git's real representation whenever
# a no-newline-terminated last line stops being the last line.
NO_TRAILING_NEWLINE_DIFF = """\
diff --git a/eof.py b/eof.py
index e69de29..0cfbf08 100644
--- a/eof.py
+++ b/eof.py
@@ -1,2 +1,3 @@
 first
-last
\\ No newline at end of file
+last
+appended
\\ No newline at end of file
"""


def test_parse_empty_diff_returns_no_files():
    assert parse_unified_diff("") == []


def test_parse_simple_modification():
    files = parse_unified_diff(SIMPLE_DIFF)
    assert len(files) == 1
    file_diff = files[0]
    assert file_diff.path == "foo.py"
    assert not file_diff.is_new
    assert not file_diff.is_deleted
    assert len(file_diff.hunks) == 1

    hunk = file_diff.hunks[0]
    assert hunk.old_start == 1
    assert hunk.new_start == 1
    kinds = [line.kind for line in hunk.lines]
    assert kinds == ["context", "remove", "add", "add", "context"]
    assert file_diff.insertions == 2
    assert file_diff.deletions == 1


def test_parse_new_file():
    files = parse_unified_diff(NEW_FILE_DIFF)
    assert len(files) == 1
    assert files[0].is_new
    assert files[0].path == "new.py"
    assert files[0].insertions == 2
    assert files[0].deletions == 0


def test_parse_deleted_file():
    files = parse_unified_diff(DELETED_FILE_DIFF)
    assert len(files) == 1
    assert files[0].is_deleted
    assert files[0].deletions == 2


def test_hunk_as_patch_roundtrips_applyable_patch():
    files = parse_unified_diff(SIMPLE_DIFF)
    patch = files[0].hunks[0].as_patch(files[0])
    assert patch.startswith("diff --git a/foo.py b/foo.py")
    assert "@@ -1,3 +1,4 @@" in patch
    assert "+line2 modified" in patch
    assert "-line2" in patch


def test_hunk_as_patch_partial_selection_drops_unselected_add():
    # kinds: 0 context, 1 remove, 2 add ("line2 modified"), 3 add ("line2.5
    # added"), 4 context. Select only the unselected-remove's *other* add
    # line (index 3) -- the unselected add (index 2) must be omitted
    # entirely, and the unselected remove must become context (line2 stays).
    files = parse_unified_diff(SIMPLE_DIFF)
    hunk = files[0].hunks[0]
    patch = hunk.as_patch(files[0], selected_indices={3})
    lines = patch.splitlines()
    assert "@@ -1,3 +1,4 @@" in patch
    assert " line2" in lines  # unselected remove -> kept as context
    assert "-line2" not in patch
    assert "+line2.5 added" in patch
    assert "+line2 modified" not in patch


def test_hunk_as_patch_partial_selection_keeps_selected_remove():
    files = parse_unified_diff(SIMPLE_DIFF)
    hunk = files[0].hunks[0]
    patch = hunk.as_patch(files[0], selected_indices={1})
    assert "-line2" in patch
    assert "+line2 modified" not in patch
    assert "+line2.5 added" not in patch


def test_parse_records_no_newline_marker_on_preceding_line():
    files = parse_unified_diff(NO_TRAILING_NEWLINE_DIFF)
    hunk = files[0].hunks[0]
    # kinds: 0 context ("first"), 1 remove ("last"), 2 add ("last"), 3 add
    # ("appended"). Both the removed and the re-added "last" lack a
    # trailing newline in their respective blobs; only the final "appended"
    # line is genuinely EOF in the new blob.
    assert [line.no_newline for line in hunk.lines] == [False, True, False, True]


def test_hunk_as_patch_whole_hunk_preserves_no_newline_markers():
    # Regression: selecting the whole hunk (the common case) must re-emit
    # both "\ No newline at end of file" markers untouched.
    files = parse_unified_diff(NO_TRAILING_NEWLINE_DIFF)
    hunk = files[0].hunks[0]
    patch = hunk.as_patch(files[0])
    assert patch.count("\\ No newline at end of file") == 2


def test_hunk_as_patch_partial_selection_at_eof_avoids_stale_context_marker():
    # Regression for the reported bug: selecting only the "appended" add
    # line (not the "last" remove/add pair) would naively drop the
    # unselected remove into a plain context line. But a genuinely
    # selected line ("appended") still follows it in the reconstructed
    # output, so that "last" line is no longer the true end of file on
    # either side -- a plain context line can't express "unchanged text,
    # but the base's trailing-newline-less copy needs one now that more
    # follows". as_patch must fall back to an explicit remove+add pair for
    # it instead of tagging stale context with a marker git would reject
    # as not matching the base file's real bytes (see as_patch's
    # docstring).
    files = parse_unified_diff(NO_TRAILING_NEWLINE_DIFF)
    hunk = files[0].hunks[0]
    appended_index = next(
        i for i, line in enumerate(hunk.lines) if line.text == "appended"
    )
    patch = hunk.as_patch(files[0], selected_indices={appended_index})
    lines = patch.splitlines()
    assert " last" not in lines  # not left as a stale, wrongly-marked context line
    remove_pos = lines.index("-last")
    assert lines[remove_pos + 1] == "\\ No newline at end of file"
    assert lines[remove_pos + 2] == "+last"
    # The re-added "appended" line is the real EOF now, and must carry it.
    assert lines[-1] == "\\ No newline at end of file"
    assert lines[-2] == "+appended"
