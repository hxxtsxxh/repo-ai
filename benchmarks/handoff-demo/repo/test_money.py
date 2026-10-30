from money import format_money


def test_money_pads_cents():
    assert format_money(1205) == "$12.05"


def test_money_zero():
    assert format_money(0) == "$0.00"


def test_money_thousands_separator():
    assert format_money(123456789) == "$1,234,567.89"
