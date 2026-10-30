import pytest

from invoicekit.errors import InvoiceError
from invoicekit.money import split_amount


def test_remainder_first():
    assert split_amount(100, 3) == [34, 33, 33]


def test_two_leftover_cents():
    assert split_amount(101, 3) == [34, 34, 33]


def test_sum_exact():
    shares = split_amount(1000, 7)
    assert sum(shares) == 1000 and len(shares) == 7


def test_ints():
    assert all(type(s) is int for s in split_amount(1000, 7))


def test_zero():
    assert split_amount(0, 2) == [0, 0]


def test_one_part():
    assert split_amount(5, 1) == [5]


def test_zero_parts_invalid():
    with pytest.raises(InvoiceError):
        split_amount(100, 0)
