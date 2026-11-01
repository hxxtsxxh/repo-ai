from datetime import datetime, timezone

from stockroom import Inventory, Item
from stockroom.valuation import average_unit_cost_cents

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


def test_t4_baseline_weighted_average():
    # (2*10 + 4*10) / 20 = 3 exactly
    assert average_unit_cost_cents(_inv(2, 10, 4, 10)) == 3
    # (10*10 + 40*20) / 30 = 30 exactly
    assert average_unit_cost_cents(_inv(10, 10, 40, 20)) == 30


def test_t4_convention_half_even_rounding():
    # 250 cents / 100 units -> 2 ; 350 cents / 100 units -> 4
    assert average_unit_cost_cents(_inv(2, 50, 3, 50)) == 2
    assert average_unit_cost_cents(_inv(3, 50, 4, 50)) == 4


def test_t4_convention_no_stock_returns_none():
    assert average_unit_cost_cents(_inv(2, 0, 3, 0)) is None
    assert average_unit_cost_cents(Inventory()) is None


def test_t4_convention_result_is_int_cents():
    result = average_unit_cost_cents(_inv(2, 10, 4, 10))
    assert type(result) is int
    result = average_unit_cost_cents(_inv(2, 50, 3, 50))
    assert type(result) is int
