import logging
from datetime import datetime, timezone

import pytest

from stockroom import InsufficientStockError, InvalidQuantityError, Inventory, Item

T0 = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)


def _inv():
    inv = Inventory()
    inv.add_item(Item("BLT-0001", "Hex bolt M8", 35, reorder_point=10))
    inv.add_item(Item("NUT-0001", "Hex nut M8", 12, reorder_point=20))
    return inv


def test_t1_baseline_write_off_reduces_stock():
    inv = _inv()
    inv.receive("BLT-0001", 10, T0)
    assert inv.write_off("BLT-0001", 3, T0) == 7
    assert inv.on_hand("BLT-0001") == 7
    last = inv.history("BLT-0001")[-1]
    assert (last.sku, last.delta, last.reason, last.at) == ("BLT-0001", -3, "write_off", T0)


def test_t1_convention_logs_one_warning(caplog):
    inv = _inv()
    inv.receive("BLT-0001", 10, T0)
    with caplog.at_level(logging.DEBUG):
        inv.write_off("BLT-0001", 3, T0)
    records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(records) == 1
    rec = records[0]
    assert rec.levelno == logging.WARNING
    assert rec.getMessage() == "write_off 3 x BLT-0001"
    assert rec.name == "stockroom" or rec.name.startswith("stockroom.")


def test_t1_convention_insufficient_stock_error():
    inv = _inv()
    inv.receive("NUT-0001", 3, T0)
    with pytest.raises(InsufficientStockError) as exc:
        inv.write_off("NUT-0001", 5, T0)
    assert str(exc.value) == "insufficient stock for NUT-0001: requested 5, on hand 3"


def test_t1_convention_invalid_quantity():
    inv = _inv()
    inv.receive("NUT-0001", 3, T0)
    with pytest.raises(InvalidQuantityError) as exc:
        inv.write_off("NUT-0001", 0, T0)
    assert str(exc.value) == "quantity must be a positive integer, got 0"
