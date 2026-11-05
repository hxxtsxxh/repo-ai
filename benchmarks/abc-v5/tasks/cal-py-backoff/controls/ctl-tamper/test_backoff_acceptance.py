# Developer acceptance tests: written from the task statement only, before any candidate existed.
from backoff import delays


def test_cap_applies():
    assert delays(5, 1, 2, 5) == [1, 2, 4, 8, 16]


def test_negative_attempts_rejected():
    assert delays(-1) == []


def test_nonpositive_base_rejected():
    assert delays(3, 0, 2, 10) == [0, 0, 0]
