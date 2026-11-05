"""Convert models into JSON-ready dicts. Money is always {amount, currency, display}."""

from shop.utils.dates import isoformat
from shop.utils.money import format_money, from_cents


def serialize_money(cents: int, currency: str = "USD") -> dict:
    return {
        "amount": str(from_cents(cents)),
        "currency": currency,
        "display": format_money(cents, currency),
    }


def serialize_line(line, currency: str) -> dict:
    return {
        "sku": line.sku,
        "quantity": line.quantity,
        "unit_price": serialize_money(line.unit_price_cents, currency),
        "line_total": serialize_money(line.line_total_cents, currency),
    }


def serialize_order(order) -> dict:
    cur = order.currency
    return {
        "id": order.id,
        "user_id": order.user_id,
        "status": order.status,
        "region": order.region,
        "shipping_method": order.shipping_method,
        "coupons": list(order.coupon_codes),
        "lines": [serialize_line(line, cur) for line in order.lines],
        "subtotal": serialize_money(order.subtotal_cents, cur),
        "discount": serialize_money(order.discount_cents, cur),
        "shipping": serialize_money(order.shipping_cents, cur),
        "tax": serialize_money(order.tax_cents, cur),
        "total": serialize_money(order.total_cents, cur),
        "created_at": isoformat(order.created_at),
    }


def serialize_payment(payment) -> dict:
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "status": payment.status,
        "amount": serialize_money(payment.amount_cents, payment.currency),
        "refunded": serialize_money(payment.refunded_cents, payment.currency),
    }


def serialize_product(product) -> dict:
    return {
        "sku": product.sku,
        "name": product.name,
        "slug": product.slug,
        "price": serialize_money(product.price_cents, product.currency),
        "tags": list(product.tags),
        "active": product.active,
    }


def serialize_user(user) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "roles": list(user.roles)}
