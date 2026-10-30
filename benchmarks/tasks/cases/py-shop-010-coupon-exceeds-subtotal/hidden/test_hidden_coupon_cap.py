import unittest

from shop.app import create_app
from shop.models.order import Order, OrderLine
from shop.services.discounts import FIXED, PERCENT, Coupon, CouponBook
from shop.services.pricing import price_order


class CouponCapTest(unittest.TestCase):
    def test_fixed_coupon_capped(self):
        svc = create_app().ctx.order_service
        order = svc.place_order("usr_1", [{"sku": "STK-0001"}], region="CA", coupon_codes=["SAVE10"])
        self.assertEqual(order.discount_cents, 600)
        self.assertEqual(order.tax_cents, 0)
        self.assertEqual(order.total_cents, 599)

    def test_stacked_coupons_capped(self):
        book = CouponBook([Coupon("A", FIXED, 400), Coupon("B", FIXED, 400), Coupon("C", PERCENT, 50)])
        self.assertEqual(book.total_discount(["A", "B", "C"], 600), 600)
        order = Order(id="o", user_id="u", lines=[OrderLine("STK-0001", 1, 600)], region="OR",
                      coupon_codes=["A", "B"])
        price_order(order, book)
        self.assertEqual(order.total_cents, 599)

    def test_regression_normal_coupons(self):
        book = CouponBook([Coupon("SAVE10", FIXED, 1000), Coupon("PCT10", PERCENT, 10)])
        self.assertEqual(book.total_discount(["SAVE10"], 2500), 1000)
        self.assertEqual(book.total_discount(["PCT10", "SAVE10"], 3000), 1200)


if __name__ == "__main__":
    unittest.main()
