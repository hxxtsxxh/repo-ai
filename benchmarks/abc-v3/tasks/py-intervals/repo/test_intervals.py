import pytest
from intervals import merge, subtract, total_length


def test_merge_overlapping():
    assert merge([(5, 8), (1, 3), (2, 4)]) == [(1, 4), (5, 8)]


def test_merge_touching_joins():
    assert merge([(1, 2), (2, 3)]) == [(1, 3)]


def test_merge_drops_empty():
    assert merge([(4, 4), (1, 2)]) == [(1, 2)]


def test_subtract_middle():
    assert subtract([(0, 10)], [(3, 5)]) == [(0, 3), (5, 10)]


def test_subtract_everything():
    assert subtract([(2, 4)], [(0, 10)]) == []


def test_total_length():
    assert total_length([(0, 2), (1, 3), (10, 11)]) == 4


def test_bad_interval():
    with pytest.raises(ValueError):
        merge([(3, 1)])
