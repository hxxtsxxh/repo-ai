import unittest

from shop.app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.customer = self.app.register_and_login("ada@example.com")

    def test_health(self):
        self.assertEqual(self.app.request("GET", "/health")["status"], 200)

    def test_list_products(self):
        resp = self.app.request("GET", "/products", query={"per_page": "2"})
        self.assertEqual(resp["status"], 200)
        self.assertEqual(len(resp["body"]["items"]), 2)
        self.assertEqual(resp["body"]["total"], 5)

    def test_product_by_slug(self):
        resp = self.app.request("GET", "/products/logo-tee")
        self.assertEqual(resp["body"]["price"]["display"], "$19.99")
        self.assertEqual(resp["body"]["available"], 20)

    def test_order_flow(self):
        resp = self.app.request(
            "POST", "/orders", headers=self.customer,
            body={"items": [{"sku": "TEE-0001", "quantity": 1}], "region": "OR"},
        )
        self.assertEqual(resp["status"], 201)
        order_id = resp["body"]["id"]
        resp = self.app.request("GET", f"/orders/{order_id}", headers=self.customer)
        self.assertEqual(resp["body"]["total"]["amount"], "25.98")
        resp = self.app.request("POST", f"/orders/{order_id}/pay", headers=self.customer)
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["status"], "captured")

    def test_requires_auth(self):
        resp = self.app.request("GET", "/orders")
        self.assertEqual(resp["status"], 401)

    def test_other_customer_cannot_see_order(self):
        resp = self.app.request(
            "POST", "/orders", headers=self.customer, body={"items": [{"sku": "TEE-0001"}]}
        )
        other = self.app.register_and_login("bob@example.com")
        resp = self.app.request("GET", f"/orders/{resp['body']['id']}", headers=other)
        self.assertEqual(resp["status"], 404)

    def test_admin_creates_product(self):
        admin = self.app.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        resp = self.app.request(
            "POST", "/products", headers=admin,
            body={"sku": "CAP-0001", "name": "Logo Tee", "price": "9.50", "stock": 3},
        )
        self.assertEqual(resp["status"], 201)
        self.assertEqual(resp["body"]["slug"], "logo-tee-2")

    def test_customer_cannot_create_product(self):
        resp = self.app.request(
            "POST", "/products", headers=self.customer,
            body={"sku": "CAP-0001", "name": "Cap", "price": "9.50"},
        )
        self.assertEqual(resp["status"], 403)


if __name__ == "__main__":
    unittest.main()
