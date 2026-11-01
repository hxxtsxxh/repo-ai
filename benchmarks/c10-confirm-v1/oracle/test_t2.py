from datetime import datetime, timezone

import pytest

from stockroom import InsufficientStockError, Inventory, Item, UnknownSkuError

T0 = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)
T1 = datetime(2024, 3, 2, 9, 30, tzinfo=timezone.utc)


def _inv():
    inv = Inventory()
    inv.add_item(Item("BLT-0001", "Hex bolt M8", 35))
    inv.add_item(Item("NUT-0001", "Hex nut M8", 12))
    inv.add_item(Item("WSH-0001", "Washer M8", 4))
    inv.receive("BLT-0001", 10, T0)
    inv.receive("NUT-0001", 10, T0)
    inv.receive("WSH-0001", 10, T0)
    return inv


def test_t2_baseline_issue_many_issues_every_line():
    inv = _inv()
    inv.issue_many([("BLT-0001", 2), ("NUT-0001", 3)], T1)
    assert inv.on_hand("BLT-0001") == 8
    assert inv.on_hand("NUT-0001") == 7
    assert inv.on_hand("WSH-0001") == 10
    new = list(inv.history())[3:]
    assert [(m.sku, m.delta, m.reason, m.at) for m in new] == [
        ("BLT-0001", -2, "issue", T1),
        ("NUT-0001", -3, "issue", T1),
    ]


def test_t2_convention_failed_batch_changes_nothing():
    inv = _inv()
    before = tuple(inv.history())
    with pytest.raises(InsufficientStockError):
        inv.issue_many([("BLT-0001", 2), ("NUT-0001", 11), ("WSH-0001", 1)], T1)
    assert inv.on_hand("BLT-0001") == 10
    assert inv.on_hand("NUT-0001") == 10
    assert inv.on_hand("WSH-0001") == 10
    assert tuple(inv.history()) == before


def test_t2_convention_first_failing_line_wins():
    inv = _inv()
    with pytest.raises(UnknownSkuError):
        inv.issue_many([("BLT-0001", 1), ("ZZZ-9999", 1), ("NUT-0001", 999)], T1)
    assert inv.on_hand("BLT-0001") == 10


def test_t2_convention_batch_ids():
    inv = _inv()
    assert inv.issue_many([("BLT-0001", 1)], T1) == "BAT-000001"
    assert inv.issue_many([("NUT-0001", 1)], T1) == "BAT-000002"
    other = _inv()
    assert other.issue_many([("WSH-0001", 1)], T1) == "BAT-000001"
