"""Shipping quotes and delivery estimates."""

from datetime import date

from shop import config
from shop.errors import ValidationError
from shop.utils.dates import add_business_days

TRANSIT_BUSINESS_DAYS = {"standard": 5, "express": 2}


def quote_shipping(subtotal_cents: int, method: str = "standard") -> int:
    """Shipping charge in cents for an order whose discounted subtotal is given."""
    if method not in config.SHIPPING_RATES_CENTS:
        raise ValidationError(f"unknown shipping method: {method}")
    if method == "standard" and subtotal_cents >= config.FREE_SHIPPING_THRESHOLD_CENTS:
        return 0
    return config.SHIPPING_RATES_CENTS[method]


def estimate_delivery(ship_date: date, method: str = "standard") -> date:
    if method not in TRANSIT_BUSINESS_DAYS:
        raise ValidationError(f"unknown shipping method: {method}")
    return add_business_days(ship_date, TRANSIT_BUSINESS_DAYS[method])
