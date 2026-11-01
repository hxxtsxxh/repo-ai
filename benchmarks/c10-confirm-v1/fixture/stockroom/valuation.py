"""Stock valuation at unit cost. All amounts are integer cents."""


def item_value_cents(inventory, sku):
    item = inventory.item(sku)
    return inventory.on_hand(item.sku) * item.unit_cost_cents


def total_value_cents(inventory):
    return sum(item_value_cents(inventory, item.sku) for item in inventory.items())
