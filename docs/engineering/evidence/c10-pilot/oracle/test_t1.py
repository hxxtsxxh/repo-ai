from decimal import Decimal

import pytest

from invoicekit.errors import InvoiceError
from invoicekit.money import apply_discount


def test_plain():
    assert apply_discount(1000, 10) == 900


def test_int_cents():
    assert type(apply_discount(1000, 10)) is int


def test_half_even_down():
    assert apply_discount(125, 10) == 112  # 112.5


def test_half_even_up():
    assert apply_discount(135, 10) == 122  # 121.5


def test_bounds_inclusive():
    assert apply_discount(1000, 0) == 1000 and apply_discount(1000, 100) == 0


def test_fractional_percent():
    assert apply_discount(1000, Decimal("12.5")) == 875


def test_over_100_invalid():
    with pytest.raises(InvoiceError):
        apply_discount(1000, 101)


def test_negative_invalid():
    with pytest.raises(InvoiceError):
        apply_discount(1000, -1)
