"""Payment endpoints."""

from shop.api.middleware import current_user, get_header, is_admin, require_admin
from shop.api.responses import json_response
from shop.api.serializers import serialize_payment
from shop.errors import NotFound
from shop.utils.money import to_cents


def pay_order(ctx, request, order_id):
    user = current_user(ctx, request)
    order = ctx.order_service.get(order_id)
    if order.user_id != user["sub"] and not is_admin(user):
        raise NotFound(f"order {order_id} not found")
    key = get_header(request, "Idempotency-Key")
    payment = ctx.payment_service.capture(order_id, idempotency_key=key)
    return json_response(serialize_payment(payment))


def refund_payment(ctx, request, payment_id):
    require_admin(ctx, request)
    body = request.get("body") or {}
    amount = body.get("amount")
    amount_cents = to_cents(amount) if amount is not None else None
    payment = ctx.payment_service.refund(payment_id, amount_cents)
    return json_response(serialize_payment(payment))
