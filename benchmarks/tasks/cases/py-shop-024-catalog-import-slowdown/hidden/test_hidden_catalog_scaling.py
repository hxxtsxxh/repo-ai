import unittest

from shop.app import create_app
from shop.errors import Conflict, ValidationError
from shop.services.catalog import import_products


class CountingItems(dict):
    """Counts every stored product handed out by a full scan of the repository."""

    visits = 0

    def values(self):
        for value in super().values():
            self.visits += 1
            yield value

    def items(self):
        for pair in super().items():
            self.visits += 1
            yield pair

    def __iter__(self):
        for key in super().__iter__():
            self.visits += 1
            yield key


def _rows(n, names=40, prefix="IMP"):
    return [
        {"sku": f"{prefix}-{i:04d}", "name": f"Import Item {i % names}", "price": "1.00", "stock": 2}
        for i in range(n)
    ]


class CatalogImportTest(unittest.TestCase):
    def setUp(self):
        self.ctx = create_app().ctx

    def test_repository_is_not_rescanned_per_row(self):
        items = CountingItems(self.ctx.products._items)
        self.ctx.products._items = items
        rows = _rows(3000)
        created = import_products(self.ctx, rows)
        self.assertEqual(len(created), 3000)
        self.assertLess(items.visits, 10 * len(rows), "import scans the whole catalog for every row")

    def test_slugs_unchanged(self):
        created = import_products(self.ctx, _rows(200))
        self.assertEqual(created[0].slug, "import-item-0")
        self.assertEqual(created[40].slug, "import-item-0-2")
        self.assertEqual(created[80].slug, "import-item-0-3")
        self.assertEqual(created[199].slug, "import-item-39-5")
        self.assertEqual(len({p.slug for p in self.ctx.products.list()}), len(self.ctx.products))

    def test_clash_with_existing_catalog(self):
        created = import_products(self.ctx, [
            {"sku": "TEE-0002", "name": "Logo Tee", "price": "21.00"},
            {"sku": "TEE-0003", "name": "Logo Tee", "price": "22.00", "tags": ["apparel"]},
        ])
        self.assertEqual([p.slug for p in created], ["logo-tee-2", "logo-tee-3"])
        self.assertEqual(created[1].tags, ["apparel"])
        self.assertEqual(self.ctx.inventory.on_hand("TEE-0002"), 0)
        self.assertIs(self.ctx.products.by_slug("logo-tee-3"), created[1])

    def test_errors_unchanged(self):
        with self.assertRaises(Conflict):
            import_products(self.ctx, [{"sku": "TEE-0001", "name": "Again", "price": "1.00"}])
        with self.assertRaises(ValidationError) as cm:
            import_products(self.ctx, [{"sku": "NEW-0001", "name": "", "price": "1.00"}])
        self.assertIn("row 1", str(cm.exception))
        with self.assertRaises(ValidationError) as cm:
            import_products(self.ctx, [{"sku": "NEW-0002", "name": "Ok", "price": "1.00"},
                                       {"sku": "bad", "name": "Bad", "price": "1.00"}])
        self.assertIn("row 2", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
