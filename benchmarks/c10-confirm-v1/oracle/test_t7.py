from datetime import datetime, timedelta, timezone

from stockroom import Inventory, Item
from stockroom.report import movement_lines

UTC_T = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)


def _inv():
    inv = Inventory()
    inv.add_item(Item("BLT-0001", "Hex bolt M8", 35))
    inv.add_item(Item("NUT-0001", "Hex nut M8", 12))
    return inv


def test_t7_baseline_line_fields():
    inv = _inv()
    inv.receive("BLT-0001", 5, UTC_T)
    inv.receive("NUT-0001", 4, UTC_T + timedelta(hours=1))
    inv.issue("BLT-0001", 2, UTC_T + timedelta(hours=2))
    lines = list(movement_lines(inv))
    assert [line.rsplit(" ", 3)[1:] for line in lines] == [
        ["BLT-0001", "+5", "receive"],
        ["NUT-0001", "+4", "receive"],
        ["BLT-0001", "-2", "issue"],
    ]
    lines = list(movement_lines(inv, sku="BLT-0001"))
    assert [line.rsplit(" ", 3)[1:] for line in lines] == [
        ["BLT-0001", "+5", "receive"],
        ["BLT-0001", "-2", "issue"],
    ]


def test_t7_convention_timestamp_rendering():
    inv = _inv()
    plus_two = timezone(timedelta(hours=2))
    inv.receive("BLT-0001", 5, datetime(2024, 3, 1, 11, 30, 15, 987654, tzinfo=plus_two))
    lines = tuple(movement_lines(inv))
    assert lines[0] == "2024-03-01T09:30:15Z BLT-0001 +5 receive"


