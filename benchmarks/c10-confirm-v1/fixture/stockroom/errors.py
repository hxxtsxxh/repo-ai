"""Exception hierarchy for stockroom."""


class StockroomError(Exception):
    """Base class for every error raised by stockroom."""


class InvalidSkuError(StockroomError, ValueError):
    """Raised when a SKU does not match the AAA-9999 format."""


class InvalidQuantityError(StockroomError, ValueError):
    """Raised when a quantity is not a positive integer."""


class UnknownSkuError(StockroomError, LookupError):
    """Raised when an operation refers to a SKU that is not registered."""

    def __init__(self, sku):
        super().__init__(f"unknown SKU: {sku}")
        self.sku = sku


class DuplicateSkuError(StockroomError):
    """Raised when registering a SKU that already exists."""

    def __init__(self, sku):
        super().__init__(f"duplicate SKU: {sku}")
        self.sku = sku


class InsufficientStockError(StockroomError):
    """Raised when an issue would take on-hand stock below zero."""

    def __init__(self, sku, requested, on_hand):
        super().__init__(
            f"insufficient stock for {sku}: requested {requested}, on hand {on_hand}"
        )
        self.sku = sku
        self.requested = requested
        self.on_hand = on_hand
