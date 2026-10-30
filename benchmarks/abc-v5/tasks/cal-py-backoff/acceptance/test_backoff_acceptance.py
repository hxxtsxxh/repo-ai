# Developer acceptance tests: written from the task statement only, before any candidate existed.
import pytest

from backoff import delays


def test_cap_applies():
    assert delays(5, 1, 2, 5) == [1, 2, 4, 5, 5]


def test_negative_attempts_rejected():
    with pytest.raises(ValueError):
        delays(-1)


def test_nonpositive_base_rejected():
    with pytest.raises(ValueError):
        delays(3, 0, 2, 10)
