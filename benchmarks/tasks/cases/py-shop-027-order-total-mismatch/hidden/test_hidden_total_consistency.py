import unittest

from shop.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app


class TotalConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.customer = self.app.register_and_login("ada@example.com")
        resp = self.app.request(
            "POST", "/orders", headers=self.customer,
            body={"items": [{"sku": "HAT-0001", "quantity": 2}], "region": "CA", "coupons": ["pct15"]},
        )
        self.assertEqual(resp["status"], 201)
        self.created = resp["body"]
        self.order_id = resp["body"]["id"]

    def test_checkout_total(self):
        self.assertEqual(self.created["total"]["amount"], "51.57")
        self.assertEqual(self.created["total"]["display"], "$51.57")
        self.assertEqual(self.created["discount"]["amount"], "7.50")

    def test_get_order_total(self):
        resp = self.app.request("GET", f"/orders/{self.order_id}", headers=self.customer)
        self.assertEqual(resp["body"]["total"]["amount"], "51.57")

    def test_confirmation_email_total(self):
        messages = self.app.ctx.notifier.messages_for("ada@example.com")
        placed = [m for m in messages if "received" in m.subject]
        self.assertEqual(len(placed), 1)
        self.assertIn("Total: $51.57", placed[0].body)

    def test_charge_uses_checkout_price_after_catalogue_change(self):
        self.app.ctx.products.get("HAT-0001").price_cents = 2750
        resp = self.app.request("POST", f"/orders/{self.order_id}/pay", headers=self.customer)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["amount"]["amount"], "51.57")
        self.assertEqual(self.app.ctx.gateway.charges[-1][1], 5157)
        paid = [m for m in self.app.ctx.notifier.messages_for("ada@example.com") if "Payment" in m.subject]
        self.assertIn("$51.57", paid[0].body)
        admin = self.app.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        refund = self.app.request("POST", f"/payments/{resp['body']['id']}/refund", headers=admin)
        self.assertEqual(refund["body"]["refunded"]["amount"], "51.57")
        self.assertEqual(self.app.ctx.gateway.refunds[-1][2], 5157)

    def test_regression_no_coupon_order(self):
        resp = self.app.request(
            "POST", "/orders", headers=self.customer,
            body={"items": [{"sku": "TEE-0001"}], "region": "OR"},
        )
        self.assertEqual(resp["body"]["total"]["amount"], "25.98")


if __name__ == "__main__":
    unittest.main()
