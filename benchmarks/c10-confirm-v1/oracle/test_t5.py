from datetime import datetime, timezone
from decimal import Decimal

from stockroom import Inventory, Item
from stockroom.valuation import value_share_percent

T0 = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)


def _inv(cost_a, qty_a, cost_b, qty_b):
    inv = Inventory()
    inv.add_item(Item("AAA-0001", "Item A", cost_a))
    inv.add_item(Item("BBB-0001", "Item B", cost_b))
    if qty_a:
        inv.receive("AAA-0001", qty_a, T0)
    if qty_b:
        inv.receive("BBB-0001", qty_b, T0)
    return inv


def test_t5_baseline_share_of_value():
    inv = _inv(10, 3, 30, 3)  # A = 30, B = 90, total 120
    assert value_share_percent(inv, "AAA-0001") == 25
    assert value_share_percent(inv, "BBB-0001") == 75


def test_t5_convention_percentage_format():
    inv = _inv(1, 1, 15, 1)  # A = 1 of 16 -> 6.25 %
    share = value_share_percent(inv, "AAA-0001")
    assert isinstance(share, Decimal)
    assert str(share) == "6.3"
    whole = _inv(5, 2, 7, 0)  # A holds all the value
    full = value_share_percent(whole, "AAA-0001")
    assert isinstance(full, Decimal)
    assert str(full) == "100.0"


def test_t5_convention_zero_total_returns_none():
    inv = _inv(10, 0, 30, 0)
    assert value_share_percent(inv, "AAA-0001") is None
