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
