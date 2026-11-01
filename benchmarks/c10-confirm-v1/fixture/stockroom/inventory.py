"""The Inventory ledger: registered items plus their movement history."""

from stockroom.errors import DuplicateSkuError, InsufficientStockError, UnknownSkuError
from stockroom.models import Item, Movement
from stockroom.quantities import require_positive_quantity
from stockroom.skus import normalize_sku


class Inventory:
    """In-memory stock ledger for one warehouse."""

    def __init__(self):
        self._items = {}
        self._on_hand = {}
        self._movements = []

    def add_item(self, item):
        if not isinstance(item, Item):
            raise TypeError("add_item expects an Item")
        if item.sku in self._items:
            raise DuplicateSkuError(item.sku)
        self._items[item.sku] = item
        self._on_hand[item.sku] = 0
        return item

    def item(self, sku):
        sku = normalize_sku(sku)
        try:
            return self._items[sku]
        except KeyError:
            raise UnknownSkuError(sku) from None

    def items(self):
        """Return every registered Item, sorted by SKU."""
        return tuple(self._items[sku] for sku in sorted(self._items))

    def on_hand(self, sku):
        return self._on_hand[self.item(sku).sku]

    def receive(self, sku, qty, at):
        """Add ``qty`` units of ``sku`` to stock and return the new level."""
        sku = self.item(sku).sku
        qty = require_positive_quantity(qty)
        self._on_hand[sku] += qty
        self._movements.append(Movement(sku, qty, "receive", at))
        return self._on_hand[sku]

    def issue(self, sku, qty, at):
        """Remove ``qty`` units of ``sku`` from stock and return the new level."""
        sku = self.item(sku).sku
        qty = require_positive_quantity(qty)
        current = self._on_hand[sku]
        if qty > current:
            raise InsufficientStockError(sku, qty, current)
        self._on_hand[sku] = current - qty
        self._movements.append(Movement(sku, -qty, "issue", at))
        return self._on_hand[sku]

    def history(self, sku=None):
        """Return movements in the order they were recorded.

        With ``sku`` given, only that item's movements are returned.
        """
        if sku is None:
            return tuple(self._movements)
        sku = self.item(sku).sku
        return tuple(m for m in self._movements if m.sku == sku)
