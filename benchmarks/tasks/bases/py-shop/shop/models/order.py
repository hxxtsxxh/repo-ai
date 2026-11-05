from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

PENDING = "pending"
PAID = "paid"
SHIPPED = "shipped"
CANCELLED = "cancelled"
REFUNDED = "refunded"

# Allowed status transitions: current status -> statuses it may move to.
TRANSITIONS = {
    PENDING: {PAID, CANCELLED},
    PAID: {SHIPPED, CANCELLED, REFUNDED},
    SHIPPED: {REFUNDED},
    CANCELLED: set(),
    REFUNDED: set(),
}


@dataclass
class OrderLine:
    sku: str
    quantity: int
    unit_price_cents: int

    @property
    def line_total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass
class Order:
    id: str
    user_id: str
    lines: list = field(default_factory=list)
    status: str = PENDING
    currency: str = "USD"
    region: str = "CA"
    shipping_method: str = "standard"
    coupon_codes: list = field(default_factory=list)
    subtotal_cents: int = 0
    discount_cents: int = 0
    tax_cents: int = 0
    shipping_cents: int = 0
    total_cents: int = 0
    created_at: Optional[datetime] = None

    def can_transition(self, new_status: str) -> bool:
        return new_status in TRANSITIONS.get(self.status, set())

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)
