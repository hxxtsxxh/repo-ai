import pytest

from invoicekit.errors import InvoiceError
from invoicekit.lines import line_total
from invoicekit.money import format_amount, parse_amount


def test_parse_amount():
    assert parse_amount("12.34") == 1234


def test_parse_rejects_text():
    with pytest.raises(InvoiceError):
        parse_amount("twelve")


def test_format_amount():
    assert format_amount(1234, "usd") == "USD 12.34"


def test_line_total():
    assert line_total(3, 250) == 750
