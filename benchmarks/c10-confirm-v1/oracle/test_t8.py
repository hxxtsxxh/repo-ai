from datetime import datetime, timedelta, timezone

from stockroom import Inventory, Item
from stockroom.movers import top_movers

D = datetime(2024, 3, 1, tzinfo=timezone.utc)
START = D
END = D + timedelta(days=7)


def _inv():
    inv = Inventory()
    for sku in ("BLT-0001", "NUT-0001", "WSH-0001", "PIN-0001"):
        inv.add_item(Item(sku, "Part " + sku, 10))
        inv.receive(sku, 100, D - timedelta(days=1))
    return inv


def test_t8_baseline_ranks_by_units_issued():
    inv = _inv()
    inv.issue("BLT-0001", 3, D + timedelta(days=1))
    inv.issue("NUT-0001", 9, D + timedelta(days=2))
    inv.issue("WSH-0001", 5, D + timedelta(days=3))
    inv.issue("BLT-0001", 1, D + timedelta(days=4))
    got = [tuple(p) for p in top_movers(inv, START, END, 2)]
    assert got == [("NUT-0001", 9), ("WSH-0001", 5)]
    got = [tuple(p) for p in top_movers(inv, START, END, 10)]
    assert got == [("NUT-0001", 9), ("WSH-0001", 5), ("BLT-0001", 4)]


def test_t8_convention_ties_broken_by_sku():
    inv = _inv()
    inv.issue("WSH-0001", 5, D + timedelta(days=1))
    inv.issue("NUT-0001", 5, D + timedelta(days=1))
    inv.issue("PIN-0001", 7, D + timedelta(days=2))
    inv.issue("BLT-0001", 5, D + timedelta(days=3))
    got = [tuple(p) for p in top_movers(inv, START, END, 4)]
    assert got == [("PIN-0001", 7), ("BLT-0001", 5), ("NUT-0001", 5), ("WSH-0001", 5)]


def test_t8_convention_half_open_period():
    inv = _inv()
    inv.issue("BLT-0001", 2, START)
    inv.issue("NUT-0001", 50, END)
    inv.issue("WSH-0001", 1, END - timedelta(microseconds=1))
    got = [tuple(p) for p in top_movers(inv, START, END, 10)]
    assert got == [("BLT-0001", 2), ("WSH-0001", 1)]


def test_t8_convention_returns_tuple():
    inv = _inv()
    inv.issue("BLT-0001", 2, D + timedelta(days=1))
    inv.issue("NUT-0001", 3, D + timedelta(days=1))
    result = top_movers(inv, START, END, 10)
    assert isinstance(result, tuple)
