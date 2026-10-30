"""Payment capture through Stripe."""
import stripe

from app.billing.refunds import RefundPolicy


def charge_card(user_id: int, amount_cents: int) -> str:
    """Capture a payment and return the charge id."""
    if amount_cents <= 0:
        raise ValueError("amount must be positive")
    intent = stripe.PaymentIntent.create(amount=amount_cents, currency="usd")
    return intent["id"]


def refund_charge(charge_id: str, policy: RefundPolicy) -> bool:
    return policy.allows(charge_id)
