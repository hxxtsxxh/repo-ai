"""Customer-facing notifications.

Messages are appended to an in-memory outbox; a real deployment would
hand them to a mail relay.
"""

from dataclasses import dataclass

from shop import config
from shop.utils.dates import format_date
from shop.utils.money import format_money


@dataclass
class Message:
    to: str
    subject: str
    body: str
    sender: str = config.NOTIFY_FROM_ADDRESS


class Notifier:
    def __init__(self, users, outbox=None):
        self.users = users
        self.outbox = outbox if outbox is not None else []

    def _address(self, user_id: str) -> str:
        user = self.users.get(user_id)
        return user.email if user else f"{user_id}@unknown.invalid"

    def _send(self, user_id: str, subject: str, body: str) -> Message:
        message = Message(to=self._address(user_id), subject=subject, body=body)
        self.outbox.append(message)
        return message

    def messages_for(self, email: str) -> list:
        return [m for m in self.outbox if m.to == email]

    def order_placed(self, order) -> Message:
        lines = [f"Thanks for your order {order.id}."]
        for line in order.lines:
            lines.append(
                f"  {line.quantity} x {line.sku} @ "
                f"{format_money(line.unit_price_cents, order.currency)}"
            )
        if order.discount_cents:
            lines.append(f"Discount: {format_money(-order.discount_cents, order.currency)}")
        lines.append(f"Total: {format_money(order.total_cents, order.currency)}")
        return self._send(order.user_id, f"Order {order.id} received", "\n".join(lines))

    def payment_received(self, order, payment) -> Message:
        body = (
            f"We received your payment of "
            f"{format_money(payment.amount_cents, payment.currency)} for order {order.id}."
        )
        return self._send(order.user_id, f"Payment received for {order.id}", body)

    def order_shipped(self, order, estimate=None) -> Message:
        body = f"Order {order.id} is on its way."
        if estimate is not None:
            body += f" Estimated delivery: {format_date(estimate)}."
        return self._send(order.user_id, f"Order {order.id} shipped", body)

    def order_cancelled(self, order) -> Message:
        return self._send(
            order.user_id, f"Order {order.id} cancelled", f"Order {order.id} was cancelled."
        )

    def refund_issued(self, order, amount_cents: int) -> Message:
        body = f"Refund for order {order.id}: {format_money(-amount_cents, order.currency)}"
        return self._send(order.user_id, f"Refund for {order.id}", body)
