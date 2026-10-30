from dataclasses import dataclass
from typing import Optional

CAPTURED = "captured"
PARTIALLY_REFUNDED = "partially_refunded"
FULLY_REFUNDED = "refunded"


@dataclass
class Payment:
    id: str
    order_id: str
    amount_cents: int
    currency: str = "USD"
    status: str = CAPTURED
    refunded_cents: int = 0
    gateway_ref: str = ""
    idempotency_key: Optional[str] = None

    @property
    def refundable_cents(self) -> int:
        return self.amount_cents - self.refunded_cents
