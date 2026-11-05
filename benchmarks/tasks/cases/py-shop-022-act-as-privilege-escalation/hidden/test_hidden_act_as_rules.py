import unittest

from shop.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app


class ActAsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        svc = self.app.ctx.user_service
        self.admin_id = self.app.ctx.users.by_email(ADMIN_EMAIL).id
        self.support_id = svc.register("help@shop.invalid", "Helper", "support-pass-1", roles=("support",)).id
        self.ada = self.app.register_and_login("ada@example.com")
        self.ada_id = self.app.ctx.users.by_email("ada@example.com").id
        self.bob = self.app.register_and_login("bob@example.com")
        self.support = self.app.login("help@shop.invalid", "support-pass-1")
        self.admin = self.app.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        resp = self.app.request("POST", "/orders", headers=self.ada, body={"items": [{"sku": "TEE-0001"}]})
        self.order_id = resp["body"]["id"]

    def as_(self, headers, target):
        return {**headers, "X-Act-As": target}

    def test_support_can_act_as_customer(self):
        resp = self.app.request("GET", "/users/me", headers=self.as_(self.support, self.ada_id))
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["email"], "ada@example.com")
        resp = self.app.request("GET", "/orders", headers=self.as_(self.support, self.ada_id))
        self.assertEqual(resp["status"], 200)
        self.assertEqual([o["id"] for o in resp["body"]["items"]], [self.order_id])

    def test_admin_can_act_as_customer(self):
        resp = self.app.request("GET", f"/orders/{self.order_id}", headers=self.as_(self.admin, self.ada_id))
        self.assertEqual(resp["status"], 200)

    def test_customer_cannot_become_admin(self):
        resp = self.app.request("GET", "/users/me", headers=self.as_(self.bob, self.admin_id))
        self.assertEqual(resp["status"], 403)
        resp = self.app.request(
            "POST", "/products", headers=self.as_(self.bob, self.admin_id),
            body={"sku": "CAP-0001", "name": "Cap", "price": "9.50"},
        )
        self.assertEqual(resp["status"], 403)
        self.assertIsNone(self.app.ctx.products.get("CAP-0001"))

    def test_customer_cannot_act_as_other_customer(self):
        resp = self.app.request("GET", f"/orders/{self.order_id}", headers=self.as_(self.bob, self.ada_id))
        self.assertEqual(resp["status"], 403)

    def test_staff_cannot_act_as_staff(self):
        resp = self.app.request("GET", "/users/me", headers=self.as_(self.support, self.admin_id))
        self.assertEqual(resp["status"], 403)
        resp = self.app.request("GET", "/users/me", headers=self.as_(self.admin, self.support_id))
        self.assertEqual(resp["status"], 403)

    def test_without_header_nothing_changes(self):
        self.assertEqual(self.app.request("GET", "/users/me", headers=self.support)["body"]["name"], "Helper")
        resp = self.app.request("GET", f"/orders/{self.order_id}", headers=self.bob)
        self.assertEqual(resp["status"], 404)
        resp = self.app.request("POST", "/products", headers=self.bob,
                                body={"sku": "CAP-0002", "name": "Cap", "price": "9.50"})
        self.assertEqual(resp["status"], 403)


if __name__ == "__main__":
    unittest.main()
