import unittest

from shop.app import create_app
from shop.utils.pagination import clamp_per_page


class PageSizeCapTest(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp_per_page(50), 50)
        self.assertEqual(clamp_per_page(100), 100)
        self.assertEqual(clamp_per_page(500), 100)

    def test_orders_endpoint(self):
        app = create_app()
        headers = app.register_and_login("dash@example.com")
        for _ in range(12):
            app.request("POST", "/orders", headers=headers, body={"items": [{"sku": "STK-0001"}]})
        resp = app.request("GET", "/orders", headers=headers, query={"per_page": "50"})
        self.assertEqual(resp["body"]["per_page"], 50)
        self.assertEqual(len(resp["body"]["items"]), 12)
        self.assertEqual(resp["body"]["pages"], 1)

    def test_regression_defaults(self):
        self.assertEqual(clamp_per_page(None), 20)
        self.assertEqual(clamp_per_page(0), 1)


if __name__ == "__main__":
    unittest.main()
