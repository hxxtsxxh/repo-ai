import unittest

from shop.app import create_app
from shop.utils.slugify import slugify, unique_slug


class AccentSlugTest(unittest.TestCase):
    def test_transliterates(self):
        self.assertEqual(slugify("Crème Brûlée Mug"), "creme-brulee-mug")
        self.assertEqual(slugify("Ñandú Über Café"), "nandu-uber-cafe")
        self.assertEqual(unique_slug("Café", {"cafe"}), "cafe-2")

    def test_product_page(self):
        app = create_app()
        resp = app.request("GET", "/products/creme-brulee-mug")
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["body"]["sku"], "MUG-0001")

    def test_regression_ascii(self):
        self.assertEqual(slugify("  Hello, World!  "), "hello-world")
        self.assertEqual(slugify("x" * 80), "x" * 60)


if __name__ == "__main__":
    unittest.main()
