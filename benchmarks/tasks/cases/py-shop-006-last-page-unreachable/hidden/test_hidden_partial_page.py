import unittest

from shop.app import create_app
from shop.utils.pagination import paginate


class PartialLastPageTest(unittest.TestCase):
    def test_partial_last_page(self):
        page = paginate(list(range(25)), page=3, per_page=10)
        self.assertEqual(page.pages, 3)
        self.assertEqual(page.items, [20, 21, 22, 23, 24])
        self.assertFalse(page.has_next)
        self.assertTrue(paginate(list(range(25)), page=2, per_page=10).has_next)

    def test_regression_exact_multiple(self):
        page = paginate(list(range(20)), page=2, per_page=10)
        self.assertEqual(page.pages, 2)
        self.assertEqual(page.items, list(range(10, 20)))
        self.assertEqual(paginate(list(range(20)), page=3, per_page=10).items, [])
        self.assertEqual(paginate([], page=1, per_page=10).pages, 0)

    def test_products_endpoint(self):
        app = create_app()
        resp = app.request("GET", "/products", query={"per_page": "2", "page": "3"})
        self.assertEqual(resp["body"]["pages"], 3)
        self.assertEqual(len(resp["body"]["items"]), 1)


if __name__ == "__main__":
    unittest.main()
