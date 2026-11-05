import unittest

from shop.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app


class CancelEndpointTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.alice = self.app.register_and_login("alice@example.com")
        resp = self.app.request("POST", "/orders", headers=self.alice,
                                body={"items": [{"sku": "TEE-0001", "quantity": 2}]})
        self.order_id = resp["body"]["id"]

    def cancel(self, headers, order_id=None):
        return self.app.request("POST", f"/orders/{order_id or self.order_id}/cancel", headers=headers)

    def test_owner_cancels(self):
        resp = self.cancel(self.alice)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["status"], "cancelled")
        self.assertEqual(resp["body"]["id"], self.order_id)
        self.assertIn("total", resp["body"])
        self.assertEqual(self.app.ctx.inventory.available("TEE-0001"), 20)
        again = self.app.request("GET", f"/orders/{self.order_id}", headers=self.alice)
        self.assertEqual(again["body"]["status"], "cancelled")

    def test_auth_and_ownership(self):
        self.assertEqual(self.cancel({})["status"], 401)
        bob = self.app.register_and_login("bob@example.com")
        self.assertEqual(self.cancel(bob)["status"], 404)
        self.assertEqual(self.cancel(self.alice, "ord_9999")["status"], 404)
        admin = self.app.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        self.assertEqual(self.cancel(admin)["status"], 200)

    def test_conflicts(self):
        self.assertEqual(self.app.request("POST", f"/orders/{self.order_id}/pay", headers=self.alice)["status"], 200)
        admin = self.app.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        self.assertEqual(self.app.request("POST", f"/orders/{self.order_id}/ship", headers=admin)["status"], 200)
        resp = self.cancel(self.alice)
        self.assertEqual(resp["status"], 409)

    def test_regression_get_order(self):
        resp = self.app.request("GET", f"/orders/{self.order_id}", headers=self.alice)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
