import unittest

from shop.app import create_app
from shop.errors import Conflict, ValidationError


class PaymentServiceTest(unittest.TestCase):
    def setUp(self):
        self.ctx = create_app().ctx
        self.order = self.ctx.order_service.place_order(
            "usr_9", [{"sku": "BAG-0001", "quantity": 1}], region="OR"
        )

    def test_capture_marks_paid(self):
        payment = self.ctx.payment_service.capture(self.order.id)
        self.assertEqual(payment.amount_cents, 4500 + 599)
        self.assertEqual(self.ctx.order_service.get(self.order.id).status, "paid")
        self.assertEqual(len(self.ctx.gateway.charges), 1)

    def test_capture_twice_without_key_conflicts(self):
        self.ctx.payment_service.capture(self.order.id)
        with self.assertRaises(Conflict):
            self.ctx.payment_service.capture(self.order.id)

    def test_full_refund(self):
        payment = self.ctx.payment_service.capture(self.order.id)
        self.ctx.payment_service.refund(payment.id)
        self.assertEqual(payment.status, "refunded")
        self.assertEqual(self.ctx.order_service.get(self.order.id).status, "refunded")

    def test_refund_more_than_captured(self):
        payment = self.ctx.payment_service.capture(self.order.id)
        with self.assertRaises(ValidationError):
            self.ctx.payment_service.refund(payment.id, payment.amount_cents + 1)


if __name__ == "__main__":
    unittest.main()
