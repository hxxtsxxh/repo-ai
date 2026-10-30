"""Order pricing: subtotal -> coupons -> shipping -> tax -> total."""

from shop import config
from shop.services.shipping import quote_shipping
from shop.utils.money import apply_basis_points


def tax_rate_bp(region) -> int:
    """Tax rate in basis points for a two-letter region code (0 if unknown)."""
    code = (region or "").strip().upper()
    return config.TAX_RATES_BP.get(code, 0)


def compute_tax(taxable_cents: int, region) -> int:
    return apply_basis_points(taxable_cents, tax_rate_bp(region))


def subtotal(lines) -> int:
    return sum(line.line_total_cents for line in lines)


def price_order(order, coupon_book=None):
    """Fill in the money fields of ``order`` in place and return it.

    Tax is charged on the discounted merchandise subtotal, not on shipping.
    """
    sub = subtotal(order.lines)
    discount = 0
    if coupon_book is not None and order.coupon_codes:
        discount = coupon_book.total_discount(order.coupon_codes, sub)
    discounted = sub - discount
    shipping = quote_shipping(discounted, order.shipping_method)
    tax = compute_tax(discounted, order.region)
    order.subtotal_cents = sub
    order.discount_cents = discount
    order.shipping_cents = shipping
    order.tax_cents = tax
    order.total_cents = discounted + shipping + tax
    return order
