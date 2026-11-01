import pytest

from conftest import T0
from stockroom import (
    DuplicateSkuError,
    InsufficientStockError,
    InvalidQuantityError,
    Item,
    UnknownSkuError,
)


def test_receive_and_issue(inv):
    assert inv.receive("blt-0001", 50, T0) == 50
    assert inv.issue("BLT-0001", 20, T0) == 30
    assert inv.on_hand("BLT-0001") == 30


def test_issue_more_than_on_hand(inv):
    inv.receive("NUT-0001", 3, T0)
    with pytest.raises(InsufficientStockError) as exc:
        inv.issue("NUT-0001", 5, T0)
    assert str(exc.value) == "insufficient stock for NUT-0001: requested 5, on hand 3"
    assert inv.on_hand("NUT-0001") == 3
    assert len(inv.history("NUT-0001")) == 1


def test_unknown_sku(inv):
    with pytest.raises(UnknownSkuError) as exc:
        inv.receive("ZZZ-9999", 1, T0)
    assert str(exc.value) == "unknown SKU: ZZZ-9999"


def test_duplicate_sku(inv):
    with pytest.raises(DuplicateSkuError):
        inv.add_item(Item("blt-0001", "Another bolt", 1))


@pytest.mark.parametrize("qty", [0, -1, 1.5, True, "3"])
def test_bad_quantities(inv, qty):
    with pytest.raises(InvalidQuantityError) as exc:
        inv.receive("BLT-0001", qty, T0)
    assert str(exc.value) == f"quantity must be a positive integer, got {qty!r}"


def test_history_order_and_sign(inv):
    inv.receive("BLT-0001", 5, T0)
    inv.receive("WSH-0001", 7, T0)
    inv.issue("BLT-0001", 2, T0)
    assert [(m.sku, m.delta, m.reason) for m in inv.history()] == [
        ("BLT-0001", 5, "receive"),
        ("WSH-0001", 7, "receive"),
        ("BLT-0001", -2, "issue"),
    ]
    assert [m.delta for m in inv.history("blt-0001")] == [5, -2]


def test_items_sorted_by_sku(inv):
    inv.add_item(Item("AAA-0001", "Anchor", 100))
    assert [i.sku for i in inv.items()] == ["AAA-0001", "BLT-0001", "NUT-0001", "WSH-0001"]
    assert isinstance(inv.items(), tuple)


def test_item_validation():
    with pytest.raises(ValueError):
        Item("BLT-0002", "Bolt", -1)
    with pytest.raises(ValueError):
        Item("BLT-0002", "  ", 1)
