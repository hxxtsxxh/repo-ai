from datetime import datetime, timedelta, timezone

import pytest

from stockroom import Inventory, Item, StockroomError

D = datetime(2024, 3, 1, tzinfo=timezone.utc)


def _inv():
    inv = Inventory()
    inv.add_item(Item("BLT-0001", "Hex bolt M8", 35))
    inv.add_item(Item("NUT-0001", "Hex nut M8", 12))
    return inv


def test_t6_baseline_filters_by_period():
    inv = _inv()
    inv.receive("BLT-0001", 1, D - timedelta(days=5))
    inv.receive("BLT-0001", 2, D + timedelta(days=1))
    inv.receive("NUT-0001", 3, D + timedelta(days=2))
    inv.receive("BLT-0001", 4, D + timedelta(days=20))
    got = inv.movements_between(D, D + timedelta(days=10))
    assert [(m.sku, m.delta) for m in got] == [("BLT-0001", 2), ("NUT-0001", 3)]
    got = inv.movements_between(D, D + timedelta(days=10), sku="NUT-0001")
    assert [(m.sku, m.delta) for m in got] == [("NUT-0001", 3)]


def test_t6_convention_half_open_period():
    inv = _inv()
    start, end = D, D + timedelta(days=7)
    inv.receive("BLT-0001", 1, start - timedelta(microseconds=1))
    inv.receive("BLT-0001", 2, start)
    inv.receive("BLT-0001", 3, end - timedelta(microseconds=1))
    inv.receive("BLT-0001", 4, end)
    got = inv.movements_between(start, end)
    assert [m.delta for m in got] == [2, 3]


def test_t6_convention_invalid_period():
    from stockroom.errors import InvalidPeriodError

    assert issubclass(InvalidPeriodError, StockroomError)
    assert issubclass(InvalidPeriodError, ValueError)
    inv = _inv()
    with pytest.raises(InvalidPeriodError) as exc:
        inv.movements_between(D, D)
    assert str(exc.value) == "period start must be before end"
    with pytest.raises(InvalidPeriodError) as exc:
        inv.movements_between(D + timedelta(days=1), D)
    assert str(exc.value) == "period start must be before end"


def test_t6_convention_tuple_in_recorded_order():
    inv = _inv()
    inv.receive("BLT-0001", 1, D + timedelta(days=3))
    inv.receive("NUT-0001", 2, D + timedelta(days=1))
    inv.receive("BLT-0001", 3, D + timedelta(days=2))
    got = inv.movements_between(D, D + timedelta(days=10))
    assert isinstance(got, tuple)
    assert [m.delta for m in got] == [1, 2, 3]
