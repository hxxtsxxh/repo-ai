"""The route table. Order matters only for readability; see router.py."""

from shop.api import orders, payments, products, users
from shop.api.responses import json_response


def health(ctx, request):
    return json_response({"status": "ok"})


ROUTES = [
    ("GET /health", health),
    ("POST /auth/login", users.login),
    ("POST /users", users.register),
    ("GET /users/me", users.me),
    ("GET /products", products.list_products),
    ("POST /products", products.create_product),
    ("GET /products/{slug}", products.get_product),
    ("GET /orders", orders.list_orders),
    ("POST /orders", orders.create_order),
    ("GET /orders/{order_id}", orders.get_order),
    ("GET /orders/{order_id}/payments", orders.list_order_payments),
    ("POST /orders/{order_id}/pay", payments.pay_order),
    ("POST /orders/{order_id}/cancel", orders.cancel_order),
    ("POST /orders/{order_id}/ship", orders.ship_order),
    ("POST /payments/{payment_id}/refund", payments.refund_payment),
]
