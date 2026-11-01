"""Plain-text stock reports."""

from stockroom.valuation import item_value_cents


def format_cents(cents):
    """Render integer cents as dollars, e.g. 123456 -> "$1,234.56"."""
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rem:02d}"


def stock_lines(inventory):
    """One line per item, sorted by SKU: "SKU  name  on_hand  value"."""
    return tuple(
        f"{item.sku}  {item.name}  {inventory.on_hand(item.sku)}  "
        f"{format_cents(item_value_cents(inventory, item.sku))}"
        for item in inventory.items()
    )
