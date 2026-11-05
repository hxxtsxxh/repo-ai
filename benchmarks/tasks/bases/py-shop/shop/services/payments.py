"""Payment capture and refunds against a (fake) card gateway."""

from shop.errors import Conflict, PaymentError, ValidationError
from shop.models.order import PENDING
from shop.models.payment import FULLY_REFUNDED, PARTIALLY_REFUNDED, Payment


class FakeGateway:
    """Records charges instead of talking to a card processor."""

    def __init__(self, decline_over_cents=None):
        self.charges = []
        self.refunds = []
        self.decline_over_cents = decline_over_cents

    def charge(self, amount_cents: int, currency: str, reference: str) -> str:
        if self.decline_over_cents is not None and amount_cents > self.decline_over_cents:
            raise PaymentError("card declined")
        ref = f"txn_{len(self.charges) + 1:04d}"
        self.charges.append((ref, amount_cents, currency, reference))
        return ref

    def refund(self, gateway_ref: str, amount_cents: int) -> str:
        ref = f"rfd_{len(self.refunds) + 1:04d}"
        self.refunds.append((ref, gateway_ref, amount_cents))
        return ref


class PaymentService:
    def __init__(self, payments, order_service, gateway, notifier):
        self.payments = payments
        self.order_service = order_service
        self.gateway = gateway
        self.notifier = notifier

    def capture(self, order_id: str, idempotency_key=None) -> Payment:
        if idempotency_key:
            existing = self.payments.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.order_id != order_id:
                    raise Conflict("idempotency key already used for another order")
                return existing

        order = self.order_service.get(order_id)
        if order.status != PENDING:
            raise Conflict(f"order {order_id} is not awaiting payment ({order.status})")
        if order.total_cents <= 0:
            raise PaymentError("amount must be positive")

        gateway_ref = self.gateway.charge(order.total_cents, order.currency, order.id)
        payment = Payment(
            id=self.payments.next_id(),
            order_id=order.id,
            amount_cents=order.total_cents,
            currency=order.currency,
            gateway_ref=gateway_ref,
            idempotency_key=idempotency_key,
        )
        self.payments.add(payment)
        self.order_service.mark_paid(order.id)
        self.notifier.payment_received(order, payment)
        return payment

    def refund(self, payment_id: str, amount_cents=None) -> Payment:
        payment = self.payments.require(payment_id)
        remaining = payment.amount_cents - payment.refunded_cents
        if amount_cents is None:
            amount_cents = remaining
        if amount_cents <= 0:
            raise ValidationError("refund amount must be positive")
        if amount_cents > remaining:
            raise ValidationError("refund exceeds the remaining captured amount")

        self.gateway.refund(payment.gateway_ref, amount_cents)
        payment.refunded_cents += amount_cents
        if payment.refunded_cents == payment.amount_cents:
            payment.status = FULLY_REFUNDED
        else:
            payment.status = PARTIALLY_REFUNDED
        self.payments.update(payment)

        order = self.order_service.get(payment.order_id)
        if payment.status == FULLY_REFUNDED:
            self.order_service.mark_refunded(order.id)
        self.notifier.refund_issued(order, amount_cents)
        return payment
