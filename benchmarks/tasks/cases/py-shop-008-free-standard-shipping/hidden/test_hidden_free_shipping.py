import unittest
from unittest import mock

from shop import config
from shop.app import create_app
from shop.models.order import Order, OrderLine
from shop.services.pricing import price_order


def _priced(subtotal, method="standard", region="OR"):
    order = Order(id="o", user_id="u", lines=[OrderLine("BAG-0001", 1, subtotal)],
                  region=region, shipping_method=method)
    return price_order(order)


class FreeShippingTest(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(_priced(5000).shipping_cents, 0)
        self.assertEqual(_priced(12000).shipping_cents, 0)
        self.assertEqual(_priced(4999).shipping_cents, 599)
        self.assertEqual(_priced(5000).total_cents, 5000)

    def test_express_never_free(self):
        self.assertEqual(_priced(10000, "express").shipping_cents, 1499)

    def test_configurable(self):
        with mock.patch.object(config, "FREE_SHIPPING_THRESHOLD_CENTS", 10000):
            self.assertEqual(_priced(5000).shipping_cents, 599)
            self.assertEqual(_priced(10000).shipping_cents, 0)

    def test_after_coupons_before_tax(self):
        svc = create_app().ctx.order_service
        free = svc.place_order("usr_1", [{"sku": "BAG-0001"}, {"sku": "STK-0001"}], region="CA")
        self.assertEqual(free.shipping_cents, 0)
        self.assertEqual(free.total_cents, 5100 + free.tax_cents)
        charged = svc.place_order("usr_1", [{"sku": "BAG-0001"}, {"sku": "STK-0001"}],
                                  region="OR", coupon_codes=["SAVE10"])
        self.assertEqual(charged.shipping_cents, 599)
        self.assertEqual(charged.total_cents, 4100 + 599)
        # $49.00 plus 7.25% tax is over $50, but tax must not count toward the threshold
        self.assertEqual(_priced(4900, region="CA").shipping_cents, 599)

    def test_regression_unknown_method(self):
        from shop.errors import ValidationError
        with self.assertRaises(ValidationError):
            _priced(100, "drone")


if __name__ == "__main__":
    unittest.main()
