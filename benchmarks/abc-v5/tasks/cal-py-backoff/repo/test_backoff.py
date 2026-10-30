# Shipped tests of the synthetic backoff module (the "upstream" suite).
from backoff import delays


def test_uncapped_schedule():
    assert delays(3, 1, 2, 100) == [1, 2, 4]


def test_zero_attempts():
    assert delays(0) == []
