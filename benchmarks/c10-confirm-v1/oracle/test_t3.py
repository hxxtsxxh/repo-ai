import logging
from datetime import datetime, timezone

import pytest

from stockroom import Inventory, Item, UnknownSkuError

T0 = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)
T1 = datetime(2024, 3, 2, 9, 30, tzinfo=timezone.utc)


def _inv():
    inv = Inventory()
    inv.add_item(Item("BLT-0001", "Hex bolt M8", 35))
    inv.add_item(Item("NUT-0001", "Hex nut M8", 12))
    inv.add_item(Item("WSH-0001", "Washer M8", 4))
    inv.receive("BLT-0001", 10, T0)
    inv.receive("NUT-0001", 5, T0)
    return inv


def test_t3_baseline_count_sets_levels():
    inv = _inv()
    inv.record_count({"BLT-0001": 6, "NUT-0001": 5, "WSH-0001": 2}, T1)
    assert inv.on_hand("BLT-0001") == 6
    assert inv.on_hand("NUT-0001") == 5
    assert inv.on_hand("WSH-0001") == 2
    new = sorted((m.sku, m.delta, m.reason) for m in list(inv.history())[2:])
    assert new == [("BLT-0001", -4, "count_adjust"), ("WSH-0001", 2, "count_adjust")]


def test_t3_convention_shrinkage_logs_warning(caplog):
    inv = _inv()
    with caplog.at_level(logging.DEBUG):
        inv.record_count({"BLT-0001": 6, "NUT-0001": 5}, T1)
    records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(records) == 1
    rec = records[0]
    assert rec.levelno == logging.WARNING
    assert rec.getMessage() == "count_adjust 4 x BLT-0001"
    assert rec.name == "stockroom" or rec.name.startswith("stockroom.")


def test_t3_convention_bad_line_changes_nothing():
    inv = _inv()
    before = tuple(inv.history())
    with pytest.raises(UnknownSkuError):
        inv.record_count({"BLT-0001": 6, "ZZZ-9999": 3, "NUT-0001": 1}, T1)
    assert inv.on_hand("BLT-0001") == 10
    assert inv.on_hand("NUT-0001") == 5
    assert tuple(inv.history()) == before


def test_t3_convention_count_ids():
    inv = _inv()
    assert inv.record_count({"BLT-0001": 9}, T1) == "CNT-000001"
    assert inv.record_count({"BLT-0001": 9}, T1) == "CNT-000002"
    assert _inv().record_count({"NUT-0001": 4}, T1) == "CNT-000001"
