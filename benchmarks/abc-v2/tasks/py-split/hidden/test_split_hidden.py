import pytest
from split import split_bill


def test_sum_is_exact_with_ties_to_earlier_index():
    assert split_bill(100, [1, 1, 1]) == [34, 33, 33]


def test_largest_remainder_not_last_share():
    assert split_bill(10, [1, 2, 3]) == [2, 3, 5]


def test_remainder_goes_to_largest_fraction():
    assert split_bill(5, [1, 1, 3]) == [1, 1, 3]
    assert split_bill(7, [3, 1, 1]) == [4, 2, 1]


def test_zero_weight_gets_zero_and_sum_holds():
    out = split_bill(10, [0, 1, 1, 1])
    assert out[0] == 0 and sum(out) == 10 and out == [0, 4, 3, 3]


def test_invalid_inputs():
    for args in ((100, []), (100, [0, 0]), (-1, [1]), (100, [1, -2])):
        with pytest.raises(ValueError):
            split_bill(*args)


def test_zero_total_and_no_mutation():
    w = [1, 2, 3]
    assert split_bill(0, w) == [0, 0, 0]
    assert w == [1, 2, 3]
