import unittest

from shop.app import create_app


class PaymentRetryTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.headers = self.app.register_and_login("retry@example.com")
        self.order_id = self._order()

    def _order(self):
        resp = self.app.request("POST", "/orders", headers=self.headers,
                                body={"items": [{"sku": "HAT-0001"}], "region": "OR"})
        return resp["body"]["id"]

    def pay(self, order_id, key=None, header_name="Idempotency-Key"):
        headers = dict(self.headers)
        if key:
            headers[header_name] = key
        return self.app.request("POST", f"/orders/{order_id}/pay", headers=headers)

    def receipts(self):
        return [m for m in self.app.ctx.notifier.outbox if m.subject.startswith("Payment received")]

    def test_retry_with_same_key_returns_original(self):
        first = self.pay(self.order_id, "key-123")
        second = self.pay(self.order_id, "key-123")
        third = self.pay(self.order_id, "key-123", header_name="idempotency-key")
        self.assertEqual(first["status"], 200)
        self.assertEqual(second["status"], 200)
        self.assertEqual(third["status"], 200)
        self.assertEqual(first["body"]["id"], second["body"]["id"])
        self.assertEqual(first["body"]["id"], third["body"]["id"])
        self.assertEqual(len(self.app.ctx.gateway.charges), 1)
        self.assertEqual(len(self.app.ctx.payments.for_order(self.order_id)), 1)
        self.assertEqual(len(self.receipts()), 1)

    def test_key_reuse_for_other_order_conflicts(self):
        self.assertEqual(self.pay(self.order_id, "key-abc")["status"], 200)
        other = self._order()
        resp = self.pay(other, "key-abc")
        self.assertEqual(resp["status"], 409)
        self.assertEqual(len(self.app.ctx.gateway.charges), 1)

    def test_regression_different_key_after_payment_conflicts(self):
        self.assertEqual(self.pay(self.order_id, "k1")["status"], 200)
        self.assertEqual(self.pay(self.order_id, "k2")["status"], 409)
        self.assertEqual(self.pay(self.order_id)["status"], 409)


if __name__ == "__main__":
    unittest.main()
