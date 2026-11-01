from conftest import T0
from stockroom.reorder import below_reorder_point, shortfall
from stockroom.report import format_cents, stock_lines
from stockroom.valuation import item_value_cents, total_value_cents


def test_below_reorder_point(inv):
    inv.receive("BLT-0001", 10, T0)   # at reorder point -> listed
    inv.receive("NUT-0001", 25, T0)   # above -> not listed
    inv.receive("WSH-0001", 1, T0)    # reorder point 0 -> not listed
    assert below_reorder_point(inv) == ("BLT-0001",)


def test_shortfall(inv):
    inv.receive("NUT-0001", 15, T0)
    assert shortfall(inv, "NUT-0001") == 6
    inv.receive("NUT-0001", 10, T0)
    assert shortfall(inv, "NUT-0001") == 0


def test_valuation(inv):
    inv.receive("BLT-0001", 3, T0)
    inv.receive("NUT-0001", 10, T0)
    assert item_value_cents(inv, "BLT-0001") == 105
    assert total_value_cents(inv) == 225


def test_format_cents():
    assert format_cents(0) == "$0.00"
    assert format_cents(123456) == "$1,234.56"
    assert format_cents(-5) == "-$0.05"


def test_stock_lines(inv):
    inv.receive("BLT-0001", 3, T0)
    assert stock_lines(inv) == (
        "BLT-0001  Hex bolt M8  3  $1.05",
        "NUT-0001  Hex nut M8  0  $0.00",
        "WSH-0001  Washer M8  0  $0.00",
    )
