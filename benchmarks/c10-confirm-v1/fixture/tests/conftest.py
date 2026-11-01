from datetime import datetime, timezone

import pytest

from stockroom import Inventory, Item

T0 = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def inv():
    inventory = Inventory()
    inventory.add_item(Item("BLT-0001", "Hex bolt M8", 35, reorder_point=10))
    inventory.add_item(Item("NUT-0001", "Hex nut M8", 12, reorder_point=20))
    inventory.add_item(Item("WSH-0001", "Washer M8", 4))
    return inventory
