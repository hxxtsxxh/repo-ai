from textutil import wrap_words


def test_wraps_greedily():
    assert wrap_words("the quick brown fox", 9) == ["the quick", "brown fox"]


def test_long_word_alone_unbroken():
    assert wrap_words("a extraordinarily b", 5) == ["a", "extraordinarily", "b"]


def test_whitespace_collapses_and_empty():
    assert wrap_words("a   b", 10) == ["a b"]
    assert wrap_words("   ", 10) == []
