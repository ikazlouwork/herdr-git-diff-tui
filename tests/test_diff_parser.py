import pytest

from herdr_git_diff_tui.diff_parser import parse_unified_diff


def test_parse_unified_diff_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        parse_unified_diff("")
