import unittest

from shop.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app
from shop.errors import ValidationError


class RefundLimitTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.ctx = self.app.ctx
        order = self.ctx.order_service.place_order("usr_1", [{"sku": "BAG-0001"}], region="OR")
        self.order_id = order.id
        self.payment = self.ctx.payment_service.capture(order.id)  # 5099 cents

    def test_second_partial_refund_cannot_overrun(self):
        self.ctx.payment_service.refund(self.payment.id, 3000)
        with self.assertRaises(ValidationError):
            self.ctx.payment_service.refund(self.payment.id, 3000)
        self.assertEqual(self.payment.refunded_cents, 3000)
        self.assertEqual(len(self.ctx.gateway.refunds), 1)

    def test_refund_remaining_exactly(self):
        self.ctx.payment_service.refund(self.payment.id, 3000)
        self.ctx.payment_service.refund(self.payment.id, 2099)
        self.assertEqual(self.payment.status, "refunded")
        self.assertEqual(self.ctx.order_service.get(self.order_id).status, "refunded")

    def test_api_returns_422(self):
        admin = self.app.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        path = f"/payments/{self.payment.id}/refund"
        self.assertEqual(self.app.request("POST", path, headers=admin, body={"amount": "30.00"})["status"], 200)
        resp = self.app.request("POST", path, headers=admin, body={"amount": "30.00"})
        self.assertEqual(resp["status"], 422)

    def test_regression_default_refunds_remaining(self):
        self.ctx.payment_service.refund(self.payment.id, 99)
        self.ctx.payment_service.refund(self.payment.id)
        self.assertEqual(self.payment.refunded_cents, 5099)


if __name__ == "__main__":
    unittest.main()
