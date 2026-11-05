import unittest

from shop.app import create_app
from shop.services.pricing import compute_tax, tax_rate_bp


class RegionTaxTest(unittest.TestCase):
    def test_region_codes_normalised(self):
        self.assertEqual(tax_rate_bp("ny"), 400)
        self.assertEqual(tax_rate_bp(" NY"), 400)
        self.assertEqual(tax_rate_bp("Ca "), 725)
        self.assertEqual(compute_tax(1999, "ny"), 80)

    def test_api_order_lowercase_region(self):
        app = create_app()
        headers = app.register_and_login("mo@example.com")
        resp = app.request("POST", "/orders", headers=headers,
                           body={"items": [{"sku": "TEE-0001"}], "region": "ny"})
        self.assertEqual(resp["status"], 201)
        self.assertEqual(resp["body"]["tax"]["amount"], "0.80")

    def test_regression_unknown_and_missing(self):
        self.assertEqual(tax_rate_bp("ZZ"), 0)
        self.assertEqual(tax_rate_bp(None), 0)
        self.assertEqual(tax_rate_bp("OR"), 0)


if __name__ == "__main__":
    unittest.main()
