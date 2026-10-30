import pytest
from split import split_bill


def test_even_split():
    assert split_bill(100, [1, 1]) == [50, 50]


def test_proportional_split():
    assert split_bill(100, [1, 3]) == [25, 75]


def test_negative_weight_rejected():
    with pytest.raises(ValueError):
        split_bill(100, [1, -1])
