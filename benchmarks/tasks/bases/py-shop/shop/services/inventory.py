"""Stock tracking.

``on_hand`` is physical stock; ``reserved`` is stock promised to orders
that have not shipped yet. Available stock is the difference.
"""

from shop import config
from shop.errors import OutOfStock, ValidationError


class InventoryService:
    def __init__(self):
        self._on_hand = {}
        self._reserved = {}

    def set_stock(self, sku: str, quantity: int) -> None:
        if quantity < 0:
            raise ValidationError("stock cannot be negative")
        self._on_hand[sku] = quantity

    def on_hand(self, sku: str) -> int:
        return self._on_hand.get(sku, 0)

    def reserved(self, sku: str) -> int:
        return self._reserved.get(sku, 0)

    def available(self, sku: str) -> int:
        return self.on_hand(sku) - self.reserved(sku)

    def reserve(self, sku: str, quantity: int) -> None:
        if self.available(sku) < quantity:
            raise OutOfStock(
                f"only {self.available(sku)} of {sku} available, {quantity} requested"
            )
        self._reserved[sku] = self.reserved(sku) + quantity

    def release(self, sku: str, quantity: int) -> None:
        self._reserved[sku] = max(0, self.reserved(sku) - quantity)

    def commit(self, sku: str, quantity: int) -> None:
        """Turn a reservation into a shipment: stock physically leaves."""
        self._reserved[sku] = max(0, self.reserved(sku) - quantity)
        self._on_hand[sku] = max(0, self.on_hand(sku) - quantity)

    def low_stock(self, threshold=None) -> list:
        limit = config.LOW_STOCK_THRESHOLD if threshold is None else threshold
        return sorted(sku for sku in self._on_hand if self.available(sku) <= limit)
