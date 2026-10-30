import pytest

from invoicekit.errors import InvoiceError
from invoicekit.lines import invoice_total


def test_simple():
    assert invoice_total([(2, 500)], 10) == 1100


def test_int_cents():
    assert type(invoice_total([(2, 500)], 10)) is int


def test_empty():
    assert invoice_total([], 10) == 0


def test_tax_per_line_small():
    assert invoice_total([(1, 5), (1, 5)], 10) == 10  # 0.5 + 0.5 rounded per line


def test_tax_per_line_half_even():
    assert invoice_total([(1, 105), (1, 105)], 10) == 230  # 10.5 -> 10 per line


def test_negative_qty_invalid():
    with pytest.raises(InvoiceError):
        invoice_total([(-1, 500)], 10)


def test_rate_over_100_invalid():
    with pytest.raises(InvoiceError):
        invoice_total([(1, 500)], 150)
