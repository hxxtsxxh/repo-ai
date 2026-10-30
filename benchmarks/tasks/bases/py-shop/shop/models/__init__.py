"""Plain dataclasses; no persistence logic lives here."""

from shop.models.order import Order, OrderLine
from shop.models.payment import Payment
from shop.models.product import Product
from shop.models.user import User

__all__ = ["Order", "OrderLine", "Payment", "Product", "User"]
