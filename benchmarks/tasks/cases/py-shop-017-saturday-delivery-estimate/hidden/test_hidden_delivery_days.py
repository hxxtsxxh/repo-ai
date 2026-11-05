import unittest
from datetime import date, datetime, timezone

from shop.app import create_app
from shop.services.shipping import estimate_delivery
from shop.utils.dates import add_business_days


class DeliveryEstimateTest(unittest.TestCase):
    def test_business_days_skip_weekends(self):
        self.assertEqual(add_business_days(date(2026, 3, 2), 5), date(2026, 3, 9))
        self.assertEqual(add_business_days(date(2026, 3, 6), 1), date(2026, 3, 9))
        self.assertEqual(add_business_days(date(2026, 3, 7), 1), date(2026, 3, 9))
        self.assertEqual(add_business_days(date(2026, 3, 5), 2), date(2026, 3, 9))

    def test_estimates(self):
        self.assertEqual(estimate_delivery(date(2026, 3, 2), "standard"), date(2026, 3, 9))
        self.assertEqual(estimate_delivery(date(2026, 3, 5), "express"), date(2026, 3, 9))

    def test_shipping_email(self):
        app = create_app(clock=lambda: datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc))
        ctx = app.ctx
        order = ctx.order_service.place_order("usr_1", [{"sku": "HAT-0001"}])
        ctx.payment_service.capture(order.id)
        ctx.order_service.ship(order.id)
        shipped = [m for m in ctx.notifier.outbox if "shipped" in m.subject]
        self.assertIn("Mon, Mar 09 2026", shipped[-1].body)

    def test_regression_within_week(self):
        self.assertEqual(add_business_days(date(2026, 3, 2), 1), date(2026, 3, 3))
        self.assertEqual(add_business_days(date(2026, 3, 2), 0), date(2026, 3, 2))


if __name__ == "__main__":
    unittest.main()
