import unittest

from shop.utils.pagination import paginate


class PaginateTest(unittest.TestCase):
    def test_first_page(self):
        page = paginate(list(range(10)), page=1, per_page=4)
        self.assertEqual(page.items, [0, 1, 2, 3])
        self.assertEqual(page.total, 10)
        self.assertTrue(page.has_next)

    def test_empty(self):
        page = paginate([], page=1, per_page=5)
        self.assertEqual(page.items, [])
        self.assertEqual(page.pages, 0)

    def test_default_size(self):
        page = paginate(list(range(3)))
        self.assertEqual(page.per_page, 20)


if __name__ == "__main__":
    unittest.main()
