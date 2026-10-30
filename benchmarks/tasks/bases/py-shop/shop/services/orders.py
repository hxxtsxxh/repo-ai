"""Order lifecycle: place -> pay -> ship, with cancel and refund exits."""

from shop.errors import Conflict, ValidationError
from shop.models.order import CANCELLED, PAID, REFUNDED, SHIPPED, Order, OrderLine
from shop.services.pricing import price_order
from shop.services.shipping import estimate_delivery
from shop.utils.dates import utcnow
from shop.utils.validation import validate_quantity, validate_sku


def _merge_lines(lines):
    """Combine lines for the same SKU, keeping first-seen order."""
    merged = {}
    for line in lines:
        if line.sku in merged:
            merged[line.sku].quantity += line.quantity
        else:
            merged[line.sku] = OrderLine(line.sku, line.quantity, line.unit_price_cents)
    return list(merged.values())


class OrderService:
    def __init__(self, orders, products, inventory, coupons, notifier, clock=utcnow):
        self.orders = orders
        self.products = products
        self.inventory = inventory
        self.coupons = coupons
        self.notifier = notifier
        self.clock = clock

    # -- queries -----------------------------------------------------------
    def get(self, order_id: str) -> Order:
        return self.orders.require(order_id)

    def list_for_user(self, user_id: str) -> list:
        return self.orders.for_user(user_id)

    # -- commands ----------------------------------------------------------
    def place_order(
        self, user_id, items, region="CA", coupon_codes=(), shipping_method="standard"
    ) -> Order:
        if not items:
            raise ValidationError("order must contain at least one item")
        lines = []
        for item in items:
            sku = validate_sku(item.get("sku"))
            quantity = validate_quantity(item.get("quantity", 1))
            product = self.products.require(sku)
            if not product.active:
                raise ValidationError(f"product {sku} is not available")
            lines.append(OrderLine(sku, quantity, product.price_cents))
        order = Order(
            id=self.orders.next_id(),
            user_id=user_id,
            lines=_merge_lines(lines),
            region=region,
            shipping_method=shipping_method,
            coupon_codes=[code.strip().upper() for code in coupon_codes],
            created_at=self.clock(),
        )
        price_order(order, self.coupons)

        reserved = []
        try:
            for line in order.lines:
                self.inventory.reserve(line.sku, line.quantity)
                reserved.append(line)
        except Exception:
            for line in reserved:
                self.inventory.release(line.sku, line.quantity)
            raise

        self.orders.add(order)
        self.notifier.order_placed(order)
        return order

    def _transition(self, order: Order, new_status: str) -> None:
        if not order.can_transition(new_status):
            raise Conflict(f"cannot move order {order.id} from {order.status} to {new_status}")
        order.status = new_status
        self.orders.update(order)

    def mark_paid(self, order_id: str) -> Order:
        order = self.get(order_id)
        self._transition(order, PAID)
        return order

    def mark_refunded(self, order_id: str) -> Order:
        order = self.get(order_id)
        self._transition(order, REFUNDED)
        return order

    def ship(self, order_id: str) -> Order:
        order = self.get(order_id)
        if not order.can_transition(SHIPPED):
            raise Conflict(f"cannot ship order {order.id} in status {order.status}")
        for line in order.lines:
            self.inventory.commit(line.sku, line.quantity)
        self._transition(order, SHIPPED)
        estimate = estimate_delivery(self.clock().date(), order.shipping_method)
        self.notifier.order_shipped(order, estimate=estimate)
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.get(order_id)
        if not order.can_transition(CANCELLED):
            raise Conflict(f"cannot cancel order {order.id} in status {order.status}")
        for line in order.lines:
            self.inventory.release(line.sku, line.quantity)
        self._transition(order, CANCELLED)
        self.notifier.order_cancelled(order)
        return order
