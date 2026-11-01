"""Plain data records."""

from dataclasses import dataclass
from datetime import datetime

from stockroom.skus import normalize_sku


@dataclass(frozen=True)
class Item:
    """A stock-keeping unit.

    ``unit_cost_cents`` is the cost of one unit in integer cents.
    ``reorder_point`` is the on-hand level at or below which the item
    should be reordered.
    """

    sku: str
    name: str
    unit_cost_cents: int
    reorder_point: int = 0

    def __post_init__(self):
        object.__setattr__(self, "sku", normalize_sku(self.sku))
        if not self.name or not self.name.strip():
            raise ValueError("item name must not be empty")
        for field_name in ("unit_cost_cents", "reorder_point"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True)
class Movement:
    """A single change to on-hand stock.

    ``delta`` is signed: positive for stock coming in, negative for out.
    """

    sku: str
    delta: int
    reason: str
    at: datetime
