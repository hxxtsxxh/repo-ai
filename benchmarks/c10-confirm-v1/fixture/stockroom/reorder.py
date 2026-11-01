"""Reorder-point checks."""


def shortfall(inventory, sku):
    """Units needed to bring ``sku`` back above its reorder point.

    Returns 0 when on-hand stock is already above the reorder point.
    """
    item = inventory.item(sku)
    on_hand = inventory.on_hand(item.sku)
    if on_hand > item.reorder_point:
        return 0
    return item.reorder_point - on_hand + 1


def below_reorder_point(inventory):
    """Return the SKUs whose on-hand level is at or below the reorder point."""
    return tuple(
        item.sku
        for item in inventory.items()
        if inventory.on_hand(item.sku) <= item.reorder_point
    )
