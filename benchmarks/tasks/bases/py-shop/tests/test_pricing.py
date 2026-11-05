import unittest

from shop.models.order import Order, OrderLine
from shop.services.discounts import FIXED, PERCENT, Coupon, CouponBook
from shop.services.pricing import compute_tax, price_order, tax_rate_bp
from shop.services.shipping import quote_shipping


def _order(*lines, region="CA", coupons=(), method="standard"):
    return Order(id="ord_x", user_id="usr_x", lines=list(lines), region=region,
                 coupon_codes=list(coupons), shipping_method=method)


class PricingTest(unittest.TestCase):
    def test_tax_rates(self):
        self.assertEqual(tax_rate_bp("CA"), 725)
        self.assertEqual(tax_rate_bp("ZZ"), 0)
        self.assertEqual(compute_tax(1000, "NY"), 40)

    def test_simple_order(self):
        order = price_order(_order(OrderLine("TEE-0001", 1, 1999)))
        self.assertEqual(order.subtotal_cents, 1999)
        self.assertEqual(order.shipping_cents, 599)
        self.assertEqual(order.tax_cents, 145)
        self.assertEqual(order.total_cents, 1999 + 599 + 145)

    def test_fixed_coupon(self):
        book = CouponBook([Coupon("SAVE10", FIXED, 1000)])
        order = price_order(_order(OrderLine("HAT-0001", 1, 2500), region="OR", coupons=["SAVE10"]), book)
        self.assertEqual(order.discount_cents, 1000)
        self.assertEqual(order.total_cents, 1500 + 599)

    def test_percent_after_fixed(self):
        book = CouponBook([Coupon("SAVE10", FIXED, 1000), Coupon("PCT10", PERCENT, 10)])
        order = price_order(
            _order(OrderLine("HAT-0001", 1, 3000), region="OR", coupons=["PCT10", "SAVE10"]), book
        )
        self.assertEqual(order.discount_cents, 1000 + 200)

    def test_express_shipping(self):
        self.assertEqual(quote_shipping(1000, "express"), 1499)


if __name__ == "__main__":
    unittest.main()
