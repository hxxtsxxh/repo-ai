from table import render_table


def test_aligned_no_trailing_space():
    assert render_table([["a", "bbb"], ["cc", "d"]]) == "a  | bbb\ncc | d"


def test_ragged_rows():
    assert render_table([["a", "b", "c"], ["d"]]) == "a | b | c\nd"


def test_empty():
    assert render_table([]) == ""
