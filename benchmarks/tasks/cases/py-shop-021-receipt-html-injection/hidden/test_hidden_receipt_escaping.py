import html
import re
import unittest

from shop.app import create_app
from shop.models.product import Product


class ReceiptEscapingTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        ctx = self.app.ctx
        ctx.products.add(Product("PEN-0001", 'Pen" onmouseover="steal()', 300, slug="pen"))
        ctx.products.add(Product("PLT-0001", "Fish & Chips Plate <b>new</b>", 1500, slug="plate"))
        ctx.inventory.set_stock("PEN-0001", 10)
        ctx.inventory.set_stock("PLT-0001", 10)
        ctx.user_service.register(
            "mallory@example.com", "<img src=x onerror=alert(document.domain)>", "mallory-pass-1"
        )
        self.headers = self.app.login("mallory@example.com", "mallory-pass-1")
        resp = self.app.request(
            "POST", "/orders", headers=self.headers,
            body={"items": [{"sku": "PEN-0001"}, {"sku": "PLT-0001"}, {"sku": "TEE-0001"}], "region": "OR"},
        )
        self.assertEqual(resp["status"], 201)
        self.order_id = resp["body"]["id"]

    def receipt(self):
        resp = self.app.request("GET", f"/orders/{self.order_id}/receipt", headers=self.headers)
        self.assertEqual(resp["status"], 200)
        self.assertTrue(resp["headers"]["Content-Type"].startswith("text/html"))
        return resp["body"]

    def test_customer_name_is_text(self):
        body = self.receipt()
        self.assertNotIn("<img", body)
        self.assertIn("&lt;img src=x onerror=alert(document.domain)&gt;", body)

    def test_attribute_values_cannot_break_out(self):
        body = self.receipt()
        self.assertNotIn('" onmouseover="', body)
        titles = re.findall(r'title="([^"]*)"', body)
        self.assertIn('Pen" onmouseover="steal()', [html.unescape(t) for t in titles])

    def test_markup_and_ampersands_in_product_names(self):
        body = self.receipt()
        self.assertNotIn("<b>", body)
        self.assertNotIn("Fish & Chips", body)
        self.assertIn("Fish &amp; Chips Plate &lt;b&gt;new&lt;/b&gt;", body)
        for entity in re.findall(r"&[^\s;<]*;?", body):
            self.assertRegex(entity, r"^&(amp|lt|gt|quot|#x27|#39|apos);$")

    def test_regression_amounts_and_rows(self):
        body = self.receipt()
        self.assertEqual(body.count("<tr><td"), 3)
        self.assertIn("$19.99", body)
        order = self.app.ctx.order_service.get(self.order_id)
        self.assertIn(f"${order.total_cents // 100}.{order.total_cents % 100:02d}", body)

    def test_other_customers_cannot_read_receipt(self):
        other = self.app.register_and_login("eve@example.com")
        resp = self.app.request("GET", f"/orders/{self.order_id}/receipt", headers=other)
        self.assertEqual(resp["status"], 404)


if __name__ == "__main__":
    unittest.main()
