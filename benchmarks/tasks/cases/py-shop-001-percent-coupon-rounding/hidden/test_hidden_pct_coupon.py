import unittest

from shop.app import create_app
from shop.utils.money import apply_percent


class PercentCouponRoundingTest(unittest.TestCase):
    def test_rounds_to_nearest_cent(self):
        self.assertEqual(apply_percent(1999, 15), 300)
        self.assertEqual(apply_percent(1250, 15), 188)   # 187.5 -> 188
        self.assertEqual(apply_percent(999, 50), 500)    # 499.5 -> 500
        self.assertEqual(apply_percent(333, 10), 33)     # 33.3 -> 33

    def test_order_uses_rounded_discount(self):
        app = create_app()
        order = app.ctx.order_service.place_order(
            "usr_1", [{"sku": "TEE-0001"}], region="OR", coupon_codes=["pct15"]
        )
        self.assertEqual(order.discount_cents, 300)
        self.assertEqual(order.total_cents, 1999 - 300 + 599)

    def test_regression_exact_values(self):
        self.assertEqual(apply_percent(2000, 15), 300)
        self.assertEqual(apply_percent(0, 15), 0)
        self.assertEqual(apply_percent(1000, 100), 1000)


if __name__ == "__main__":
    unittest.main()
